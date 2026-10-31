"""API: "apply" returns at once and the fix is checked in the background."""
import asyncio
import os
import time

os.environ.update({"MEKO_MODE": "fake", "LLM_MODE": "fake", "CHECK_SECONDS": "0.3",
                   "STORM_SECONDS": "5", "WATCH_INTERVAL_SECONDS": "0"})

import httpx  # noqa: E402

import shop.app as shop_app  # noqa: E402
from app import main  # noqa: E402
from app.memory import memory  # noqa: E402
from app.memory.backends import FakeMeko  # noqa: E402
from app.orchestrator import orchestrator  # noqa: E402
from app.seed import seed  # noqa: E402
from app.shop_client import shop  # noqa: E402
from app.store import store  # noqa: E402

shop.transport = httpx.ASGITransport(app=shop_app.app)
shop.base_url = "http://shop"


async def _open_incident():
    memory.backend = FakeMeko()
    memory.enabled = True
    store.clear()
    orchestrator.armed = True
    await shop.reset()
    await seed()
    await shop.chaos("db_pool")
    return await orchestrator.watch_once()


def test_apply_returns_at_once_and_fixes_in_background():
    async def go():
        inc = await _open_incident()
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://api") as c:
            t0 = time.monotonic()
            r = await c.post(f"/incidents/{inc.id}/decision", json={"choice": "apply"})
            assert time.monotonic() - t0 < 0.2
            assert r.json() == {"status": "fixing"}
            again = await c.post(f"/incidents/{inc.id}/decision", json={"choice": "apply"})
            assert again.json() == {"status": "fixing"}      # no second fix while one runs
            await main.fixing[inc.id]
            assert (await c.get(f"/incidents/{inc.id}")).json()["status"] == "resolved"
            assert inc.id not in main.fixing
            why = await c.post(f"/incidents/{inc.id}/decision", json={"choice": "why"})
            assert "reason" in why.json()                      # "why" stays synchronous
            missing = await c.post("/incidents/nope/decision", json={"choice": "apply"})
            assert missing.status_code == 404
    asyncio.run(go())


def test_reset_lets_a_resolved_fix_finish_saving_its_lesson():
    async def go():
        inc = await _open_incident()
        add = memory.backend.add

        async def slow_add(*a, **kw):                        # real Meko takes seconds to store
            await asyncio.sleep(0.3)
            return await add(*a, **kw)
        memory.backend.add = slow_add
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://api") as c:
            await c.post(f"/incidents/{inc.id}/decision", json={"choice": "apply"})
            while inc.status != "resolved":                  # resolved is set before the lesson is saved
                await asyncio.sleep(0.01)
            await c.post("/api/demo/reset")
            assert inc.lesson_ids                            # the reset waited for the lesson
    asyncio.run(go())
