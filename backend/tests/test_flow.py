"""End-to-end: the same incident with Meko OFF, then ON, gives clearly different results (A1).
Runs fully offline: fake Meko, rule-based LLM, the demo shop in-process."""
import asyncio
import os

os.environ.update({"MEKO_MODE": "fake", "LLM_MODE": "fake", "CHECK_SECONDS": "0.3",
                   "STORM_SECONDS": "5", "WATCH_INTERVAL_SECONDS": "0"})

import httpx  # noqa: E402
import pytest  # noqa: E402

import fixonce.demo.shop as shop_app  # noqa: E402
from fixonce import orchestrator as orch_mod  # noqa: E402
from fixonce.agents.recall import actions_in  # noqa: E402
from fixonce.memory import memory  # noqa: E402
from fixonce.memory.backends import FakeMeko  # noqa: E402
from fixonce.seed import seed  # noqa: E402
from fixonce.target import HttpTarget, target  # noqa: E402
from fixonce.store import store  # noqa: E402

shop = target.use(HttpTarget("http://shop", transport=httpx.ASGITransport(app=shop_app.app), simulation=True))


@pytest.fixture(autouse=True)
def fresh():
    memory.backend = FakeMeko()
    memory.log.clear()
    store.clear()
    orch_mod.orchestrator.armed = True
    asyncio.run(shop.reset())
    asyncio.run(seed())
    yield


async def _run_db_pool_incident(meko_on: bool):
    memory.enabled = meko_on
    await shop.chaos("db_pool")
    inc = await orch_mod.orchestrator.watch_once()
    assert inc is not None
    while inc.status == "waiting_human":
        await orch_mod.orchestrator.decide(inc.id, "apply")
    return inc


def test_meko_off_repeats_the_mistake():
    inc = asyncio.run(_run_db_pool_incident(meko_on=False))
    tried = [a.action for a in inc.attempts]
    assert tried[0] == "raise_pool_size"           # textbook guess, no memory
    assert inc.attempts[0].result == "failed"
    assert inc.status == "escalated"
    assert inc.stored == []                          # nothing saved while OFF


def test_meko_on_fixes_it_first_time():
    inc = asyncio.run(_run_db_pool_incident(meko_on=True))
    assert inc.recall.match
    assert "pause_batch_job" in inc.recall.worked
    assert "raise_pool_size" in inc.recall.failed
    assert [a.action for a in inc.attempts] == ["pause_batch_job"]
    assert inc.status == "resolved"
    assert inc.lesson_ids                            # new lesson stored in Meko


def test_rule_blocks_restart_during_sale():
    async def go():
        memory.enabled = True
        await shop.chaos("sale_on")
        await shop.chaos("memory_leak")
        await asyncio.sleep(0.5)
        return await orch_mod.orchestrator.watch_once()
    inc = asyncio.run(go())
    assert inc.proposed_action != "restart_service"
    assert "never restart" in inc.blocked_reason.lower()


def test_actions_parsed_from_plain_text():
    worked, failed = actions_in("The fix that worked was pausing the export job. Raising the pool made it worse.")
    assert worked == ["pause_batch_job"] and failed == ["raise_pool_size"]


def test_forget_removes_lesson():
    inc = asyncio.run(_run_db_pool_incident(meko_on=True))
    lesson = inc.lesson_ids[0]
    asyncio.run(orch_mod.orchestrator.forget(lesson))
    assert all(i["id"] != lesson for i in memory.backend.items)
