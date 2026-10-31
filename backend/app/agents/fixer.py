"""Fixer agent: picks ONE action from the safe list. Never something that already failed,
never something a team rule forbids."""
from __future__ import annotations

from ..llm import llm, obj
from ..models import ACTION_LABELS, SAFE_ACTIONS, Incident, RecallResult
from ..rules import blocking_rule

SCHEMA = obj({
    "action": {"type": "string", "enum": SAFE_ACTIONS},
    "reason": {"type": "string", "description": "Two short sentences in plain words for a junior engineer."},
    "used_memory_ids": {"type": "array", "items": {"type": "string"}},
})

# What a reasonable engineer with NO team memory would try first, by symptom.
TEXTBOOK = {
    "db": ["raise_pool_size", "restart_service", "scale_up", "pause_batch_job", "rollback_last_deploy"],
    "deploy": ["rollback_last_deploy", "restart_service", "scale_up"],
    "memory": ["restart_service", "scale_up", "rollback_last_deploy"],
    "other": ["restart_service", "scale_up", "rollback_last_deploy"],
}


def _kind(signature: str) -> str:
    s = signature.lower()
    if "db" in s or "connection" in s:
        return "db"
    if "deploy" in s:
        return "deploy"
    if "memory" in s or "oom" in s:
        return "memory"
    return "other"


def candidates(recall: RecallResult | None, failed_here: list[str]) -> list[str]:
    out = [a for a in SAFE_ACTIONS if a not in failed_here]
    if recall and recall.failed:
        trimmed = [a for a in out if a not in recall.failed]
        out = trimmed or out
    return out


def _rule_based(incident: Incident, recall: RecallResult | None, cands: list[str]) -> dict:
    if recall and recall.match:
        for a in recall.worked:
            if a in cands:
                ids = [i.id for i in recall.items[:3] if i.id]
                note = " It was learned on an older version, so watch closely." if recall.stale else ""
                return {"action": a, "reason": f"Team memory says {ACTION_LABELS[a].lower()} fixed this before"
                        + (f", and {' and '.join(ACTION_LABELS[x].lower() for x in recall.failed)} made it worse." if recall.failed else ".") + note,
                        "used_memory_ids": ids}
    for a in TEXTBOOK[_kind(incident.signature)]:
        if a in cands:
            return {"action": a, "reason": f"No team memory to go on. The usual first step for this symptom is: {ACTION_LABELS[a].lower()}.",
                    "used_memory_ids": []}
    return {"action": cands[0], "reason": "Trying the next safe option.", "used_memory_ids": []}


async def propose(incident: Incident, recall: RecallResult | None, metrics: dict, logs: list[dict],
                  failed_here: list[str]) -> dict:
    """Returns {action, reason, used_memory_ids, blocked_reason} or {action: None, ...} to escalate."""
    blocked_notes, unblocked = [], []
    for a in [x for x in SAFE_ACTIONS if x not in failed_here]:
        rule = blocking_rule(a, incident.service, metrics)
        if rule:
            # only worth telling the human if it was a real option (memory or textbook pick)
            if (recall and a in recall.worked) or a == TEXTBOOK[_kind(incident.signature)][0]:
                blocked_notes.append(f"{ACTION_LABELS[a]} is blocked: {rule['text']}")
        else:
            unblocked.append(a)
    allowed = [a for a in candidates(recall, failed_here) if a in unblocked]
    if not allowed:
        return {"action": None, "reason": "Every safe option is blocked or already failed. Escalating.",
                "used_memory_ids": [], "blocked_reason": " ".join(blocked_notes)}

    if recall and recall.items:
        mem = "\n".join(f"- [{i.id}] (score {i.score}) {i.text}" for i in recall.items[:6])
        memory_block = f"Context recalled from team memory (Meko), verbatim:\n{mem}\n"
    elif recall and not recall.meko_enabled:
        memory_block = "Team memory is switched off. You have no history for this service.\n"
    else:
        memory_block = "Team memory returned nothing for this incident.\n"
    lines = "\n".join(f"{l['level']} {l['msg']}" for l in logs[-12:])
    options = "\n".join(f"- {a}: {ACTION_LABELS[a]}" for a in allowed)
    prompt = (
        "You are the fixer agent for an on-call team. Choose exactly ONE action from the allowed list.\n"
        "If team memory says an action fixed this before, prefer it. Never choose an action memory says made things worse.\n"
        f"Incident: {incident.summary}\nSignature: {incident.signature}\n"
        f"Metrics: error_rate={metrics.get('error_rate')}, version={metrics.get('version')}\n"
        f"Recent logs:\n{lines}\n{memory_block}"
        f"Already tried in this incident and failed: {', '.join(failed_here) or 'nothing'}\n"
        f"Allowed actions:\n{options}\n"
    )
    out = await llm.json("fixer", prompt, SCHEMA, lambda: _rule_based(incident, recall, allowed))
    if out.get("action") not in allowed:
        out = _rule_based(incident, recall, allowed)
    out["blocked_reason"] = " ".join(blocked_notes)
    return out
