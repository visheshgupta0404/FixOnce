"""The REAL Meko code path (MCP client + RealMeko parsing) against a mock Meko server.
Proves the protocol handling and the OFF vs ON flow before anyone plugs in a real key."""
import asyncio
import os

os.environ.update({"MEKO_MODE": "fake", "LLM_MODE": "fake", "CHECK_SECONDS": "0.3",
                   "STORM_SECONDS": "5", "WATCH_INTERVAL_SECONDS": "0"})

import httpx  # noqa: E402
import pytest  # noqa: E402

import shop.app as shop_app  # noqa: E402
from app import orchestrator as orch_mod  # noqa: E402
from app.memory import memory  # noqa: E402
from app.memory.backends import RealMeko  # noqa: E402
from app.seed import seed  # noqa: E402
from app.shop_client import shop  # noqa: E402
from app.store import store  # noqa: E402
from tests import mock_meko  # noqa: E402

shop.transport = httpx.ASGITransport(app=shop_app.app)
shop.base_url = "http://shop"


def use_mock(sse=False, add_returns_ids=True):
    mock_meko.reset(sse=sse, add_returns_ids=add_returns_ids)
    memory.backend = RealMeko("http://meko/mcp", "mko_tkn_test", "dp-ops",
                              transport=httpx.ASGITransport(app=mock_meko.app))
    memory.log.clear()
    memory.pending_writes.clear()
    store.clear()
    orch_mod.orchestrator.armed = True
    asyncio.run(shop.reset())
    asyncio.run(seed())


async def run_incident(meko_on: bool):
    memory.enabled = meko_on
    await shop.reset()
    store.clear()
    orch_mod.orchestrator.armed = True
    await shop.chaos("db_pool")
    inc = await orch_mod.orchestrator.watch_once()
    while inc.status == "waiting_human":
        await orch_mod.orchestrator.decide(inc.id, "apply")
    return inc


@pytest.mark.parametrize("sse", [False, True])
def test_off_vs_on_through_real_meko_path(sse):
    use_mock(sse=sse)
    off = asyncio.run(run_incident(False))
    on = asyncio.run(run_incident(True))
    assert off.status == "escalated" and off.attempts[0].action == "raise_pool_size"
    assert on.status == "resolved" and [a.action for a in on.attempts] == ["pause_batch_job"]
    assert on.recall.items and all(i.id for i in on.recall.items)   # real ids from Meko
    assert on.lesson_ids                                              # lesson stored with a real id
    assert "context_search" in mock_meko.STATE["calls"]


def test_promote_correct_forget_use_real_ids_and_writer_agent():
    use_mock()
    inc = asyncio.run(run_incident(True))
    lid = inc.lesson_ids[0]
    asyncio.run(orch_mod.orchestrator.promote(lid, "on-call"))
    assert next(m for m in mock_meko.STATE["memories"] if m["id"] == lid)["promoted"]
    asyncio.run(orch_mod.orchestrator.correct(lid, "Corrected lesson text"))
    assert next(m for m in mock_meko.STATE["memories"] if m["id"] == lid)["memory"] == "Corrected lesson text"
    asyncio.run(orch_mod.orchestrator.forget(lid))
    assert all(m["id"] != lid for m in mock_meko.STATE["memories"])
    assert all(e["ok"] for e in memory.log if e["op"] in ("promote", "correct", "forget"))


def test_memory_add_without_ids_finds_the_real_id():
    use_mock(add_returns_ids=False)
    inc = asyncio.run(run_incident(True))
    real_ids = {m["id"] for m in mock_meko.STATE["memories"]}
    assert inc.lesson_ids and set(inc.lesson_ids) <= real_ids


def test_meko_down_keeps_incident_moving_and_queues_writes():
    use_mock()
    memory.backend.client.api_key = "x"
    memory.backend.client.transport = httpx.MockTransport(lambda r: httpx.Response(503, text="down"))
    memory.backend.client.session_id = None
    inc = asyncio.run(run_incident(True))
    assert inc.recall.error                      # recall failed, logged
    assert inc.status in ("resolved", "escalated")
    assert memory.pending_writes                 # lesson queued for later
