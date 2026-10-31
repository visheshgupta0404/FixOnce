"""Seeded demo history, written INTO Meko through the same calls the product uses (A5).
Every seeded lesson says it is seeded demo history, so nothing pretends to be real.

Run once against the real product datapack:   fixonce seed   (or: python -m fixonce.seed)
The fake backend seeds itself on startup.
"""
from __future__ import annotations

import asyncio

from .memory import memory
from .rules import RULES

SEED_LESSONS = [
    {
        "text": ("[seeded demo history] Lesson for checkout (v1.6): when checkout returns 503s because DB "
                 "connections run out and requests time out waiting for a connection. Root cause: the nightly "
                 "orders export job holds most DB connections. The fix that worked was pause_batch_job "
                 "(pause the export job), errors back to normal in about a minute. These made it worse or "
                 "failed: raise_pool_size (DB hit its connection cap), restart_service (reconnect storm)."),
        "meta": {"kind": "lesson", "service": "checkout", "version": "v1.6", "seeded": True,
                 "worked": ["pause_batch_job"], "failed": ["raise_pool_size", "restart_service"]},
    },
    {
        "text": ("[seeded demo history] Lesson for checkout (v1.4): when checkout errors right after a new deploy "
                 "with a TypeError in cart total, the fix that worked was rollback_last_deploy (roll back to the "
                 "previous version). These made it worse or failed: restart_service (same bug came back)."),
        "meta": {"kind": "lesson", "service": "checkout", "version": "v1.4", "seeded": True,
                 "worked": ["rollback_last_deploy"], "failed": ["restart_service"]},
    },
    {
        "text": ("[seeded demo history] Lesson for checkout (v1.6): when checkout workers run out of memory and get "
                 "OOMKilled, the fix that worked was restart_service (restart the service) as a stopgap. "
                 "These made it worse or failed: scale_up (every new replica leaked too)."),
        "meta": {"kind": "lesson", "service": "checkout", "version": "v1.6", "seeded": True,
                 "worked": ["restart_service"], "failed": ["scale_up"]},
    },
]


async def seed(promote: bool = True) -> list[str]:
    was = memory.enabled
    memory.enabled = True
    ids: list[str] = []
    try:
        for lesson in SEED_LESSONS:
            stored = await memory.save_lesson(lesson["text"], lesson["meta"], None, agent="scribe")
            ids += [s.id for s in stored if s.id]
        for rule in RULES:
            stored = await memory.save_lesson(rule["text"], {"kind": "rule", **rule}, None, agent="scribe")
            ids += [s.id for s in stored if s.id]
        if promote and ids:
            await memory.promote(ids, None)
    finally:
        memory.enabled = was
    return ids


if __name__ == "__main__":
    print("seeded memory ids:", asyncio.run(seed()))
