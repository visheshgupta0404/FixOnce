""""This keeps coming back": repeats are counted from Meko, the root cause comes from the lessons, and a
follow-up for the permanent fix is stored in Meko and reminded next time. Meko OFF shows none of it (A1)."""
import asyncio
import os

os.environ.update({"MEKO_MODE": "fake", "LLM_MODE": "fake", "CHECK_SECONDS": "0.3",
                   "STORM_SECONDS": "5", "WATCH_INTERVAL_SECONDS": "0"})

import httpx  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import fixonce.demo.shop as shop_app  # noqa: E402
from fixonce import main  # noqa: E402
from fixonce.memory import memory  # noqa: E402
from fixonce.memory.backends import FakeMeko  # noqa: E402
from fixonce.notify import message  # noqa: E402
from fixonce.orchestrator import orchestrator  # noqa: E402
from fixonce.seed import seed  # noqa: E402
from fixonce.store import store  # noqa: E402
from fixonce.target import HttpTarget, target  # noqa: E402

shop = target.use(HttpTarget("http://shop", transport=httpx.ASGITransport(app=shop_app.app), simulation=True))
client = TestClient(main.app)


@pytest.fixture(autouse=True)
def fresh():
    memory.backend = FakeMeko()
    memory.enabled = True
    store.clear()
    orchestrator.armed = True
    asyncio.run(seed())
    yield
    memory.enabled = True


async def _db_pool(meko_on: bool = True):
    memory.enabled = meko_on
    await shop.reset()
    orchestrator.armed = True
    await shop.chaos("db_pool")
    inc = await orchestrator.watch_once()
    while inc.status == "waiting_human":
        await orchestrator.decide(inc.id, "apply")
    return inc


def test_third_time_names_the_root_cause_and_a_permanent_fix():
    inc = asyncio.run(_db_pool())
    rec = inc.recall.recurrence
    assert rec.count == 2 and rec.dates == ["2026-09-14", "2026-10-02"]
    assert "export job holds most DB connections" in rec.root_cause
    assert rec.permanent_fix and rec.followup is None
    assert [a.action for a in inc.attempts] == ["pause_batch_job"] and inc.status == "resolved"
    lesson = next(s for s in inc.stored if s.id in inc.lesson_ids)
    assert "This was occurrence #3" in lesson.text and lesson.metadata["occurrence"] == 3
    assert "Root cause (from earlier lessons)" in lesson.text
    assert "This is the 3rd time" in message("incident.proposed", inc)


def test_meko_off_knows_nothing_about_repeats():
    inc = asyncio.run(_db_pool(meko_on=False))
    assert inc.recall.recurrence is None
    r = client.post(f"/incidents/{inc.id}/followup", json={"by": "on-call"}).json()
    assert r["followup_id"] is None and "Meko is OFF" in r["error"]


def test_follow_up_is_stored_reminded_not_counted_and_closed():
    first = asyncio.run(_db_pool())
    r = client.post(f"/incidents/{first.id}/followup", json={"by": "on-call"}).json()
    assert r["followup_id"] and r["text"].startswith("Follow-up for checkout:") and "3rd repeat" in r["text"]
    listed = client.get("/followups").json()
    assert [f["id"] for f in listed] == [r["followup_id"]] and listed[0]["service"] == "checkout"

    second = asyncio.run(_db_pool())
    rec = second.recall.recurrence
    assert rec.count == 3                                  # 2 seeded + tonight's lesson; the follow-up is not counted
    assert rec.followup and rec.followup["id"] == r["followup_id"]
    assert "Follow-up still open" in message("incident.proposed", second)
    assert client.post(f"/incidents/{second.id}/followup", json={}).json()["note"] == "already open"

    assert client.delete(f"/lessons/{r['followup_id']}").json()["forgotten"] == r["followup_id"]
    assert client.get("/followups").json() == []


def test_a_new_incident_has_no_follow_up_to_open():
    asyncio.run(shop.reset())
    memory.backend = FakeMeko()                             # empty memory: nothing has repeated
    inc = asyncio.run(_db_pool())
    assert inc.recall.recurrence is None
    assert client.post(f"/incidents/{inc.id}/followup", json={}).json()["followup_id"] is None
