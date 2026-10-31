""""This keeps coming back": counts how often team memory has seen this incident before, names the root
cause from those lessons, suggests the permanent fix, and finds a follow-up that is already open.

Everything shown comes from what Meko returned, except the permanent fix, which is labelled as a suggestion.
"""
from __future__ import annotations

import re

from ..llm import llm, obj
from ..models import Incident, MemoryItem, Recurrence
from .fixer import _kind

DATE = re.compile(r"\b(20\d\d-\d\d-\d\d)\b")
ROOT_CAUSE = re.compile(r"Root cause[^:]*:\s*([^.]+\.)", re.I)
WHEN = re.compile(r"when (.+?)(?:\.|$)", re.I)

SCHEMA = obj({"permanent_fix": {"type": "string",
                                "description": "One plain sentence: the change that stops this incident coming back."}})

# Used when Gemini is not available. A suggestion, never shown as memory.
PERMANENT_FIX = {
    "db": "Stop batch jobs from sharing the service's database connections: move them to a read replica, "
          "cap their connections, or run them outside peak hours.",
    "deploy": "Add a test for this failure and ship behind a canary, so a bad deploy is stopped before full rollout.",
    "memory": "Find and fix the leak with a heap profile of the workers, and alert on memory before pods get OOMKilled.",
    "other": "Write down the root cause and fix it in code or config, so the quick fix is not needed again.",
}


def is_followup(it: MemoryItem) -> bool:
    return (it.metadata or {}).get("kind") == "followup" or it.text.startswith("Follow-up for ")


def is_lesson(it: MemoryItem) -> bool:
    kind = (it.metadata or {}).get("kind")
    if it.source == "conversation" or kind in ("rule", "followup"):
        return False
    return kind == "lesson" or "Lesson for " in it.text


def _words(s: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", s.lower()) if len(w) > 2}


def same_incident(incident: Incident, it: MemoryItem) -> bool:
    """Same service, and the same kind of failure (or mostly the same words)."""
    meta = it.metadata or {}
    if meta.get("service", incident.service) != incident.service or incident.service not in it.text:
        return False
    sig = meta.get("signature") or ((WHEN.search(it.text) or [None, it.text])[1])
    kind = _kind(incident.signature)
    if kind != "other" and _kind(sig) == kind:
        return True
    a, b = _words(incident.signature), _words(sig)
    return bool(a and b) and len(a & b) / min(len(a), len(b)) >= 0.6


def _date(it: MemoryItem) -> str:
    meta = it.metadata or {}
    return meta.get("date") or meta.get("opened_at") or (DATE.findall(it.text) or [""])[0]


def followup_row(it: MemoryItem) -> dict:
    """A follow-up as the API returns it. Live Meko's memory_get_all can drop metadata, so the text
    ("Follow-up for <service>: ... Opened <date> after ... repeat of: <signature>.") is the fallback."""
    meta = it.metadata or {}
    svc = re.match(r"Follow-up for ([^:]+):", it.text)
    sig = re.search(r"repeat of: (.+?)\.?$", it.text)
    return {"id": it.id, "text": it.text, "service": meta.get("service") or (svc.group(1) if svc else None),
            "signature": meta.get("signature") or (sig.group(1) if sig else None), "opened_at": _date(it) or None}


async def _permanent_fix(incident: Incident, root_cause: str, lessons: list[str]) -> str:
    fallback = {"permanent_fix": PERMANENT_FIX[_kind(incident.signature)]}
    prompt = ("This incident keeps coming back. Suggest the ONE permanent fix that stops it recurring, in one plain "
              "sentence for an engineer (not the quick fix).\n"
              f"Incident: {incident.signature}\nRoot cause from team memory: {root_cause or 'not recorded'}\n"
              "Past lessons:\n" + "\n".join(f"- {t}" for t in lessons[:4]))
    out = await llm.json("permanent_fix", prompt, SCHEMA, lambda: fallback)
    return str(out.get("permanent_fix") or fallback["permanent_fix"]).strip()


async def recurrence(incident: Incident, items: list[MemoryItem]) -> Recurrence | None:
    """None when nothing matched. Root cause and permanent fix only once it has repeated (count >= 2)."""
    lessons = [it for it in items if is_lesson(it) and same_incident(incident, it)]
    followups = [it for it in items if is_followup(it) and same_incident(incident, it)]
    if not lessons and not followups:
        return None
    dates = sorted((_date(it) for it in lessons), key=lambda d: d or "0")  # unknown dates first ("earlier")
    rec = Recurrence(count=len(lessons), dates=dates)
    if followups:
        f = followups[0]
        rec.followup = {"id": f.id, "text": f.text, "opened_at": _date(f)}
    if rec.count >= 2:
        rec.root_cause = next((m.group(1).strip() for it in lessons if (m := ROOT_CAUSE.search(it.text))), "")
        rec.permanent_fix = await _permanent_fix(incident, rec.root_cause, [it.text for it in lessons])
    return rec
