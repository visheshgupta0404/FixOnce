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
        "text": ("[seeded demo history] Lesson for checkout (v1.6), on 2026-09-14: when checkout returns 503s because DB "
                 "connections run out and requests time out waiting for a connection. Root cause: the nightly "
                 "orders export job holds most DB connections. The fix that worked was pause_batch_job "
                 "(pause the export job), errors back to normal in about a minute. These made it worse or "
                 "failed: raise_pool_size (DB hit its connection cap), restart_service (reconnect storm)."),
        "meta": {"kind": "lesson", "service": "checkout", "version": "v1.6", "seeded": True, "date": "2026-09-14",
                 "worked": ["pause_batch_job"], "failed": ["raise_pool_size", "restart_service"]},
    },
    {
        # The same outage again: with it, the first Meko ON run says "This is the 3rd time".
        "text": ("[seeded demo history] Lesson for checkout (v1.6), on 2026-10-02: when checkout returns 503s because "
                 "DB connections run out and requests time out waiting for a connection. Root cause: the nightly "
                 "orders export job holds most DB connections. The fix that worked was pause_batch_job (pause the "
                 "export job) again; nobody moved the export off the checkout database after last time. These made "
                 "it worse or failed: scale_up (every new replica opened more DB connections)."),
        "meta": {"kind": "lesson", "service": "checkout", "version": "v1.6", "seeded": True, "date": "2026-10-02",
                 "worked": ["pause_batch_job"], "failed": ["scale_up"]},
    },
    {
        "text": ("[seeded demo history] Lesson for checkout (v1.4), on 2026-08-21: when checkout errors right after a new deploy "
                 "with a TypeError in cart total, the fix that worked was rollback_last_deploy (roll back to the "
                 "previous version). These made it worse or failed: restart_service (same bug came back)."),
        "meta": {"kind": "lesson", "service": "checkout", "version": "v1.4", "seeded": True, "date": "2026-08-21",
                 "worked": ["rollback_last_deploy"], "failed": ["restart_service"]},
    },
    {
        "text": ("[seeded demo history] Lesson for checkout (v1.6), on 2026-09-28: when checkout workers run out of memory and get "
                 "OOMKilled, the fix that worked was restart_service (restart the service) as a stopgap. "
                 "These made it worse or failed: scale_up (every new replica leaked too)."),
        "meta": {"kind": "lesson", "service": "checkout", "version": "v1.6", "seeded": True, "date": "2026-09-28",
                 "worked": ["restart_service"], "failed": ["scale_up"]},
    },
]


async def seed(promote: bool = True, only: str | None = None) -> list[str]:
    """Write the seeded history into Meko and promote it. `only="2026-10-02"` writes just the lessons of
    that date (for a datapack seeded before they existed: promoted lessons are locked, so never re-seed)."""
    was = memory.enabled
    memory.enabled = True
    ids: list[str] = []
    try:
        for lesson in SEED_LESSONS:
            if only and lesson["meta"].get("date") != only:
                continue
            stored = await memory.save_lesson(lesson["text"], lesson["meta"], None, agent="scribe")
            ids += [s.id for s in stored if s.id]
        for rule in ([] if only else RULES):
            stored = await memory.save_lesson(rule["text"], {"kind": "rule", **rule}, None, agent="scribe")
            ids += [s.id for s in stored if s.id]
        if promote and ids:
            await memory.promote(ids, None)
    finally:
        memory.enabled = was
    return ids


if __name__ == "__main__":
    import sys
    only = sys.argv[sys.argv.index("--only") + 1] if "--only" in sys.argv else None
    print("seeded memory ids:", asyncio.run(seed(only=only)))
