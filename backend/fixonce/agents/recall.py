"""Recall agent: asks Meko BEFORE any reasoning (requirement A2: recall before reasoning)."""
from __future__ import annotations

import re

from ..config import settings
from ..memory import memory
from ..models import SAFE_ACTIONS, Incident, MemoryItem, RecallResult
from .recurrence import is_followup, recurrence

SYNONYMS = {
    "pause_batch_job": ["pause_batch_job", "pause the batch", "pausing the batch", "paused the batch",
                        "pause the export", "pausing the export", "paused the export", "stop the export",
                        "stopping the export", "export job paused"],
    "raise_pool_size": ["raise_pool_size", "raise the pool", "raising the pool", "raised the pool",
                        "increase the pool", "increasing the pool", "bigger pool"],
    "scale_up": ["scale_up", "scale up", "scaling up", "scaled up", "more replicas", "adding replicas"],
    "rollback_last_deploy": ["rollback_last_deploy", "roll back", "rolled back", "rolling back", "rollback"],
    "restart_service": ["restart_service", "restart", "restarting", "restarted"],
}
BAD = ("worse", "failed", "did not", "didn't", "no effect", "never", "avoid", "do not", "don't")
GOOD = ("fixed", "worked", "resolved", "solved", "recovered", "fix that")
MAX_TRACES = 3
VERSION = re.compile(r"\bv\d+\.\d+(?:\.\d+)?\b")


def actions_in(text: str) -> tuple[list[str], list[str]]:
    """Read which safe actions a memory says worked or failed (used when Meko returns no metadata)."""
    worked, failed = [], []
    for clause in re.split(r"[.;\n]", text.lower()):
        found = [a for a in SAFE_ACTIONS if any(w in clause for w in SYNONYMS.get(a, [a]))]
        if not found:
            continue
        target = failed if any(b in clause for b in BAD) else worked if any(g in clause for g in GOOD) else None
        if target is not None:
            target.extend(a for a in found if a not in target)
    return worked, failed


def _confidence(items: list[MemoryItem]) -> float:
    if not items or items[0].score is None:
        return 0.0
    s = float(items[0].score)
    return max(0.0, min(1.0, s if s <= 1 else s / 10))


async def recall(incident: Incident, current_version: str) -> RecallResult:
    query = f"{incident.service}: {incident.signature}"
    items, err = await memory.recall(query, agent="recall")
    # Past decision traces come back from context_search too (one per agent per incident). Keep the first
    # MAX_TRACES so the panel shows the lessons, not a wall of traces; lessons are never dropped.
    traces = [it for it in items if it.source == "conversation"]
    items = [it for it in items if it.source != "conversation" or it in traces[:MAX_TRACES]]
    result = RecallResult(meko_enabled=memory.enabled, items=items, error=err)
    if not items:
        return result
    result.confidence = round(_confidence(items), 2)
    floor = result.confidence * 0.85  # only lessons about THIS kind of incident
    for it in items:
        if it.score is not None and float(it.score if it.score <= 1 else it.score / 10) < floor:
            continue
        if it.source == "conversation":
            # Decision traces of past incidents ("match=True worked=[...] failed=[...]") come back from
            # context_search too. They are shown in the panel, but they are not lessons: parsing them
            # as text marks every action named on the line as failed, including the fix that worked.
            continue
        if is_followup(it):  # an open follow-up is a reminder, not a fix that worked or failed
            continue
        meta = it.metadata or {}
        w = meta.get("worked") or []
        f = meta.get("failed") or []
        if not (w or f):
            w, f = actions_in(it.text)
        result.worked += [a for a in w if a in SAFE_ACTIONS and a not in result.worked]
        result.failed += [a for a in f if a in SAFE_ACTIONS and a not in result.failed]
        if result.learned_on_version is None:
            v = meta.get("version") or (VERSION.findall(it.text) or [None])[0]
            result.learned_on_version = v
    result.worked = [a for a in result.worked if a not in result.failed]
    result.stale = bool(result.learned_on_version and current_version and result.learned_on_version != current_version)
    result.match = result.confidence >= settings.fast_path_confidence and bool(result.worked)
    # Counted on every recalled item, not only those above the relevance floor: a lesson saved tonight
    # (mem0) scores lower than a promoted one (knowledge base), but it is still the same incident.
    result.recurrence = await recurrence(incident, items)
    return result
