"""FixOnce backend API. Endpoints follow the shared contract in the war-plan doc."""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

from .agents import scribe
from .config import settings
from .llm import llm
from .memory import memory
from .models import Ask, CorrectLesson, Decision, MekoSetting, PromoteLesson
from .orchestrator import orchestrator
from .seed import seed
from .shop_client import shop
from .store import store

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("fixonce.api")
WEB_DIR = Path(__file__).resolve().parents[2] / "web"


@asynccontextmanager
async def lifespan(app: FastAPI):
    if memory.mode == "fake-meko":
        await seed()  # offline mode only; for real Meko run `python -m app.seed` once
    if settings.watch_interval_s > 0:
        orchestrator.start()
    yield


app = FastAPI(title="FixOnce", lifespan=lifespan)


@app.get("/")
def index():
    page = WEB_DIR / "index.html"
    if page.exists():
        return FileResponse(page)
    return {"ok": True, "note": "web/index.html not found"}


@app.get("/api/status")
def status():
    return {"meko_enabled": memory.enabled, "meko_backend": memory.mode, "llm": llm.mode,
            "pending_writes": len(memory.pending_writes), "simulation": True}


# ---- demo shop passthrough (labelled simulation) ----
@app.post("/chaos/{kind}")
async def chaos(kind: str):
    return await shop.chaos(kind)


@app.get("/metrics")
async def metrics():
    return await shop.metrics()


@app.post("/api/demo/reset")
async def demo_reset():
    """Reset the shop and incidents between demo runs. Memory in Meko is kept."""
    await shop.reset()
    store.clear()
    orchestrator.armed = True
    return {"ok": True}


# ---- incidents ----
@app.get("/incidents")
def incidents():
    return [i.model_dump() | {"time_to_fix_s": i.time_to_fix_s} for i in store.all()]


@app.get("/incidents/{incident_id}")
def incident(incident_id: str):
    inc = store.get(incident_id)
    if not inc:
        raise HTTPException(404, "no such incident")
    return inc.model_dump() | {"time_to_fix_s": inc.time_to_fix_s}


@app.get("/incidents/{incident_id}/context")
def incident_context(incident_id: str):
    """Exactly what Meko returned for this incident and what we stored (A4, A5)."""
    inc = store.get(incident_id)
    if not inc:
        raise HTTPException(404, "no such incident")
    return {
        "meko_enabled": inc.meko_enabled,
        "recalled": [i.model_dump() for i in (inc.recall.items if inc.recall else [])],
        "stored": [i.model_dump() for i in inc.stored],
        "worked": inc.recall.worked if inc.recall else [],
        "failed": inc.recall.failed if inc.recall else [],
        "stale": inc.recall.stale if inc.recall else False,
        "learned_on_version": inc.recall.learned_on_version if inc.recall else None,
    }


fixing: dict[str, asyncio.Task] = {}  # incident id -> running apply (held so it is not GC'd)


def _apply_done(incident_id: str, task: asyncio.Task) -> None:
    fixing.pop(incident_id, None)
    if not task.cancelled() and task.exception():
        log.error("apply for %s failed", incident_id, exc_info=task.exception())


@app.post("/incidents/{incident_id}/decision")
async def decision(incident_id: str, body: Decision):
    """"apply" returns at once and checks the fix in the background; the page polls the incident."""
    inc = store.get(incident_id)
    if not inc:
        raise HTTPException(404, "no such incident")
    if body.choice != "apply":
        return await orchestrator.decide(incident_id, body.choice, body.by)
    if incident_id in fixing:
        return {"status": "fixing"}
    if inc.status != "waiting_human" or not inc.proposed_action:
        return {"status": inc.status, "note": "nothing to apply right now"}
    task = asyncio.create_task(orchestrator.decide(incident_id, "apply", body.by))
    fixing[incident_id] = task
    task.add_done_callback(lambda t: _apply_done(incident_id, t))
    return {"status": "fixing"}


# ---- Meko switch and lessons ----
@app.post("/settings/meko")
def set_meko(body: MekoSetting):
    memory.enabled = body.enabled
    return {"meko_enabled": memory.enabled}


@app.get("/lessons")
async def lessons(promoted: bool | None = None):
    return [i.model_dump() for i in await memory.recent(promoted)]


@app.post("/lessons/{lesson_id}/promote")
async def promote(lesson_id: str, body: PromoteLesson):
    return await orchestrator.promote(lesson_id, body.confirmed_by)


@app.post("/lessons/{lesson_id}/correct")
async def correct(lesson_id: str, body: CorrectLesson):
    return await orchestrator.correct(lesson_id, body.text)


@app.delete("/lessons/{lesson_id}")
async def forget(lesson_id: str):
    return await orchestrator.forget(lesson_id)


@app.get("/api/meko/log")
def meko_log(limit: int = 50):
    """Every Meko call this server made, newest last."""
    return memory.log[-limit:]


@app.post("/ask")
async def ask(body: Ask):
    return await scribe.answer(body.question, store.all())
