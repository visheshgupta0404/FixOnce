"""Scribe agent: turns a finished incident into a lesson in Meko (extracted memory),
writes the postmortem document, and answers handoff questions."""
from __future__ import annotations

import time

from ..llm import llm
from ..memory import memory
from ..models import ACTION_LABELS, Incident


def lesson_text(inc: Incident) -> str:
    worked = [a.action for a in inc.attempts if a.result == "worked"]
    failed = [a.action for a in inc.attempts if a.result == "failed"]
    parts = [f"Lesson for {inc.service} ({inc.version}): when {inc.signature}"]
    if worked:
        parts.append(f"The fix that worked was {worked[0]} ({ACTION_LABELS[worked[0]].lower()})")
    if failed:
        parts.append(f"These made it worse or failed: {', '.join(failed)}")
    if not worked:
        parts.append("No safe action fixed it; it was escalated to a senior")
    return ". ".join(parts) + "."


async def learn(inc: Incident) -> None:
    text = lesson_text(inc)
    meta = {
        "kind": "lesson",
        "service": inc.service,
        "version": inc.version,
        "signature": inc.signature,
        "incident_id": inc.id,
        "worked": [a.action for a in inc.attempts if a.result == "worked"],
        "failed": [a.action for a in inc.attempts if a.result == "failed"],
    }
    stored = await memory.save_lesson(text, meta, inc.conversation_id, agent="scribe")
    inc.stored.extend(stored)
    inc.lesson_ids.extend(i.id for i in stored if i.id)
    await memory.put_document(f"postmortem-{inc.id}.md", postmortem(inc), inc.conversation_id)
    inc.log("scribe", "Saved the lesson to Meko" if stored else "Lesson not saved (Meko is OFF or unreachable)")


def postmortem(inc: Incident) -> str:
    rows = "\n".join(f"- {time.strftime('%H:%M:%S', time.localtime(a.at))} {a.action}: {a.result} {a.note}"
                     for a in inc.attempts)
    return (f"# Postmortem {inc.id} ({inc.service} {inc.version})\n\n"
            f"Simulation: {inc.simulation}\n\n## What happened\n{inc.summary}\n\n"
            f"## Attempts\n{rows or '- none'}\n\n## Time to fix\n{inc.time_to_fix_s} s\n\n"
            f"## Lesson\n{lesson_text(inc)}\n")


async def answer(question: str, incidents: list[Incident]) -> dict:
    items, _ = await memory.recall(question, agent="scribe")
    recent = [i for i in incidents if time.time() - i.opened_at < 24 * 3600]
    facts = "\n".join(
        f"- {i.service}: {i.summary} Status {i.status}. Tried: "
        f"{', '.join(f'{a.action} ({a.result})' for a in i.attempts) or 'nothing yet'}." for i in recent)
    mem = "\n".join(f"- {m.text}" for m in items[:5])

    def fallback() -> str:
        if not recent:
            return "No incidents in the last 24 hours."
        return f"{len(recent)} incident(s) in the last 24 hours:\n{facts}"

    prompt = (f"An engineer starting their shift asks: {question}\n"
              f"Incidents from our system:\n{facts or 'none'}\n"
              f"Team memory (Meko) returned:\n{mem or 'nothing'}\n"
              "Answer in at most 4 short lines, plain words. Only use the facts above.")
    text = await llm.text(prompt, fallback)
    return {"answer": text, "recalled": [m.model_dump() for m in items]}
