"""The REAL Meko code path (MCP client + RealMeko parsing) against a mock Meko server.
Proves the protocol handling and the OFF vs ON flow before anyone plugs in a real key."""
import asyncio
import json
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
    assert any(i.source == "knowledge_base" for i in on.recall.items)  # seeded lessons are promoted
    traces = mock_meko.STATE["conversations"][on.conversation_id]       # decision traces reached Meko
    assert {json.loads(t["metadata"])["decided_by"] for t in traces} >= {"triage", "recall", "fixer"}
    assert all(e["ok"] for e in memory.log if e["op"] == "decision_trace")


def test_correct_forget_promote_use_real_ids_and_writer_agent():
    use_mock()
    inc = asyncio.run(run_incident(True))
    lid = inc.lesson_ids[0]
    assert asyncio.run(orch_mod.orchestrator.correct(lid, "Corrected lesson text")) == {"corrected": lid}
    assert next(m for m in mock_meko.STATE["memories"] if m["id"] == lid)["memory"] == "Corrected lesson text"
    assert inc.stored[0].text == "Corrected lesson text"            # the panel shows the new text
    asyncio.run(orch_mod.orchestrator.promote(lid, "on-call"))
    assert next(m for m in mock_meko.STATE["memories"] if m["id"] == lid)["promoted"]
    assert inc.stored[0].promoted is True                             # the panel can lock it
    assert all(e["ok"] for e in memory.log if e["op"] in ("promote", "correct"))
    other = asyncio.run(memory.save_lesson("Unpromoted lesson to forget", {}, None))[0].id
    assert asyncio.run(orch_mod.orchestrator.forget(other)) == {"forgotten": other}
    assert all(m["id"] != other for m in mock_meko.STATE["memories"])


def test_promoted_lesson_is_locked_and_says_so():
    """Real Meko: promotion is one-way. Correct/Forget must say no plainly, not fake success or queue."""
    use_mock()
    inc = asyncio.run(run_incident(True))
    lid = inc.lesson_ids[0]
    asyncio.run(orch_mod.orchestrator.promote(lid, "on-call"))
    assert asyncio.run(orch_mod.orchestrator.correct(lid, "new text"))["corrected"] is None
    assert "promoted" in asyncio.run(orch_mod.orchestrator.forget(lid))["error"]
    assert any(m["id"] == lid for m in mock_meko.STATE["memories"])
    assert not memory.pending_writes
    assert [e["ok"] for e in memory.log if e["op"] in ("correct", "forget")] == [False, False]


def test_memory_add_without_ids_finds_the_real_id():
    use_mock(add_returns_ids=False)
    inc = asyncio.run(run_incident(True))
    real_ids = {m["id"] for m in mock_meko.STATE["memories"]}
    assert inc.lesson_ids and set(inc.lesson_ids) <= real_ids


def test_reset_right_after_resolved_still_saves_the_lesson():
    """A demo reset cancels the running fix. Once the fix is checked, its lesson must still reach Meko."""
    use_mock()
    real = httpx.ASGITransport(app=mock_meko.app)

    async def slow_meko(request):
        if b'"memory_add"' in request.content:
            await asyncio.sleep(0.5)
        return await real.handle_async_request(request)

    memory.backend.client.transport = httpx.MockTransport(slow_meko)

    async def go():
        memory.enabled = True
        await shop.chaos("db_pool")
        inc = await orch_mod.orchestrator.watch_once()
        task = asyncio.create_task(orch_mod.orchestrator.decide(inc.id, "apply"))
        while inc.status != "resolved":
            await asyncio.sleep(0.05)
        task.cancel()  # what POST /api/demo/reset does to a running fix
        await asyncio.gather(task, return_exceptions=True)
        await asyncio.gather(*orch_mod.orchestrator._learning)
        return inc

    inc = asyncio.run(go())
    assert inc.lesson_ids and set(inc.lesson_ids) <= {m["id"] for m in mock_meko.STATE["memories"]}


def test_one_dropped_connection_is_retried():
    use_mock()
    real = httpx.ASGITransport(app=mock_meko.app)
    drops = []

    async def flaky(request):
        if not drops:  # the first request never reaches Meko
            drops.append(1)
            raise httpx.ConnectError("network blip", request=request)
        return await real.handle_async_request(request)

    memory.backend.client.transport = httpx.MockTransport(flaky)
    items = asyncio.run(memory.backend.search("checkout DB connections run out", "recall"))
    assert drops and items


def test_meko_down_keeps_incident_moving_and_queues_writes():
    use_mock()
    memory.backend.client.api_key = "x"
    memory.backend.client.transport = httpx.MockTransport(lambda r: httpx.Response(503, text="down"))
    memory.backend.client.session_id = None
    inc = asyncio.run(run_incident(True))
    assert inc.recall.error                      # recall failed, logged
    assert inc.status in ("resolved", "escalated")
    assert memory.pending_writes                 # lesson queued for later
