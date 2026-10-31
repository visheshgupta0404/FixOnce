"""Runs one incident through the agents:
watch -> triage -> recall (Meko) -> fixer -> human taps -> fix + check -> scribe learns (Meko).
"""
from __future__ import annotations

import asyncio
import logging
import time

from .agents import fixer, recall as recall_agent, scribe, triage as triage_agent
from .config import settings
from .llm import LLMError
from .memory import memory
from .models import ACTION_LABELS, Attempt, Incident, MemoryItem
from .notify import notifier
from .store import store
from .target import target

log = logging.getLogger("fixonce")


class Orchestrator:
    def __init__(self):
        self.armed = True
        self._watch_task: asyncio.Task | None = None
        self._learning: set[asyncio.Task] = set()  # lessons being saved (held so they are not GC'd)

    async def _learn(self, inc: Incident) -> None:
        """Save the lesson. The fix has finished by now, so the lesson is real: a demo reset that
        cancels this fix (it drops half-checked fixes) must not cut the save off halfway."""
        task = asyncio.ensure_future(scribe.learn(inc))
        self._learning.add(task)
        task.add_done_callback(self._learning.discard)
        await asyncio.shield(task)

    # ---- opening and analysing -------------------------------------------------
    async def open_incident(self, metrics: dict) -> Incident:
        inc = Incident(service=metrics.get("service", "checkout"), version=metrics.get("version", ""),
                       meko_enabled=memory.enabled, simulation=target.simulation)
        inc.log("watcher", f"Error rate {round(metrics.get('error_rate', 0) * 100)}%: opened incident")
        store.save(inc)
        inc.conversation_id = await memory.start_conversation(f"Incident {inc.id} on {inc.service}")
        await self.analyse(inc, metrics)
        return inc

    async def analyse(self, inc: Incident, metrics: dict | None = None) -> None:
        inc.status = "investigating"
        metrics = metrics or await target.metrics()
        logs = await target.logs(20)
        deploys = await target.deploys()
        try:
            t = await triage_agent.triage(inc, metrics, logs, deploys)
        except LLMError as e:
            return self._escalate(inc, f"Triage failed: {e}")
        inc.signature, inc.summary = t["signature"], t["summary"]
        inc.log("triage", inc.summary)
        await memory.log_decision(inc.conversation_id, "triage", "metrics + logs", inc.signature,
                                  "Grouped the alerts into one incident and named its pattern.")

        inc.recall = await recall_agent.recall(inc, metrics.get("version", ""))
        r = inc.recall
        if not r.meko_enabled:
            inc.log("recall", "Meko is OFF: no team memory")
        elif r.error:
            inc.log("recall", f"Meko unreachable ({r.error}); investigating without memory")
        elif r.match:
            inc.log("recall", f"Seen before (confidence {r.confidence}). Worked: {', '.join(r.worked)}."
                    + (f" Made it worse: {', '.join(r.failed)}." if r.failed else "")
                    + (f" Learned on {r.learned_on_version}, now {inc.version}: may be outdated." if r.stale else ""))
        else:
            inc.log("recall", f"No strong match in memory (confidence {r.confidence}); slow path")
        await memory.log_decision(inc.conversation_id, "recall", inc.signature,
                                  f"match={r.match} worked={r.worked} failed={r.failed}",
                                  "Asked Meko before any reasoning.")
        await self._propose(inc, metrics, logs)

    async def _propose(self, inc: Incident, metrics: dict, logs: list[dict]) -> None:
        failed_here = [a.action for a in inc.attempts if a.result == "failed"]
        try:
            p = await fixer.propose(inc, inc.recall, metrics, logs, failed_here)
        except LLMError as e:
            return self._escalate(inc, f"Fixer failed: {e}")
        inc.blocked_reason = p.get("blocked_reason", "")
        if inc.blocked_reason:
            inc.log("fixer", inc.blocked_reason)
        if not p["action"]:
            return self._escalate(inc, p["reason"])
        inc.proposed_action, inc.proposal_reason = p["action"], p["reason"]
        inc.status = "waiting_human"
        inc.log("fixer", f"Proposes: {ACTION_LABELS[p['action']]}. {p['reason']}")
        await memory.log_decision(inc.conversation_id, "fixer", inc.signature, p["action"], p["reason"],
                                  [f"used memory {m}" for m in p.get("used_memory_ids", [])])
        notifier.emit("incident.proposed", inc)

    # ---- human decisions ---------------------------------------------------------
    async def decide(self, incident_id: str, choice: str, by: str = "on-call") -> dict:
        inc = store.get(incident_id)
        if inc is None:
            raise KeyError(incident_id)
        if choice == "why":
            return {"reason": inc.proposal_reason, "blocked": inc.blocked_reason,
                    "recall": inc.recall.model_dump() if inc.recall else None}
        if choice == "escalate":
            self._escalate(inc, f"{by} escalated to a senior")
            await self._learn(inc)
            return {"status": inc.status}
        if inc.status != "waiting_human" or not inc.proposed_action:
            return {"status": inc.status, "note": "nothing to apply right now"}
        await self.apply(inc, by)
        return {"status": inc.status}

    async def apply(self, inc: Incident, by: str) -> None:
        action = inc.proposed_action
        attempt = Attempt(action=action, approved_by=by)
        inc.attempts.append(attempt)
        inc.status = "fixing"
        inc.log(by, f"Approved: {ACTION_LABELS[action]}")
        await target.run_action(action)
        ok, rate = await self._check()
        attempt.result = "worked" if ok else "failed"
        attempt.note = f"error rate after {settings.check_seconds:.0f}s: {round(rate * 100)}%"
        inc.log("watcher", f"{ACTION_LABELS[action]} {'worked' if ok else 'did NOT work'} ({attempt.note})")
        await memory.log_decision(inc.conversation_id, "fixer", action, attempt.result, attempt.note)
        if ok:
            inc.status, inc.resolved_at = "resolved", time.time()
            inc.log("system", f"Resolved in {inc.time_to_fix_s}s")
            notifier.emit("incident.resolved", inc)
            await self._learn(inc)
            return
        if len(inc.attempts) >= settings.max_fix_attempts:
            self._escalate(inc, f"{len(inc.attempts)} fixes failed")
            await self._learn(inc)
            return
        await self._propose(inc, await target.metrics(), await target.logs(20))

    async def _check(self) -> tuple[bool, float]:
        deadline = time.time() + settings.check_seconds
        rate = 1.0
        while True:
            m = await target.metrics()
            rate = m["error_rate"]
            if time.time() >= deadline:
                return rate < settings.error_threshold, rate
            await asyncio.sleep(min(1.0, settings.check_seconds))

    def _escalate(self, inc: Incident, why: str) -> None:
        inc.status = "escalated"
        inc.proposed_action = None
        inc.log("system", f"Escalated: {why}")
        notifier.emit("incident.escalated", inc)

    # ---- lessons (visible context, A4) -------------------------------------------
    @staticmethod
    def _lesson(lesson_id: str) -> tuple[Incident | None, MemoryItem | None]:
        inc = next((i for i in store.all() if lesson_id in i.lesson_ids), None)
        item = next((s for s in inc.stored if s.id == lesson_id), None) if inc else None
        return inc, item

    async def promote(self, lesson_id: str, by: str) -> dict:
        inc, item = self._lesson(lesson_id)
        result = await memory.promote([lesson_id], inc.conversation_id if inc else None)
        if result is None:
            return {"promoted": None, "error": "Meko did not confirm the promotion (OFF or unreachable)."}
        if item:
            item.promoted = True  # Meko promotion is one-way: the lesson is now locked
        if inc:
            inc.log(by, "Confirmed the fix held: lesson promoted to shared team knowledge")
        return {"promoted": lesson_id}

    async def forget(self, lesson_id: str) -> dict:
        result = await memory.forget(lesson_id)
        if isinstance(result, dict) and result.get("ok") is False:
            return {"forgotten": None, "error": result["error"]}
        if result is None:
            return {"forgotten": None, "error": "Meko did not confirm: it is OFF, or unreachable and the change is queued."}
        inc, item = self._lesson(lesson_id)
        if inc and item:
            inc.stored.remove(item)
            inc.lesson_ids.remove(lesson_id)
            inc.log("on-call", "Forgot the lesson in Meko")
        return {"forgotten": lesson_id}

    async def correct(self, lesson_id: str, text: str) -> dict:
        result = await memory.correct(lesson_id, text)
        if isinstance(result, dict) and result.get("ok") is False:
            return {"corrected": None, "error": result["error"]}
        if result is None:
            return {"corrected": None, "error": "Meko did not confirm: it is OFF, or unreachable and the change is queued."}
        inc, item = self._lesson(lesson_id)
        if item:
            item.text = text
            inc.log("on-call", "Corrected the lesson in Meko")
        return {"corrected": lesson_id}

    # ---- watcher -----------------------------------------------------------------
    async def watch_once(self) -> Incident | None:
        m = await target.metrics()
        high = m["error_rate"] > settings.error_threshold
        if not high:
            self.armed = True
            if memory.pending_writes:
                await memory.flush_pending()
            return None
        if self.armed and store.active(m["service"]) is None:
            self.armed = False
            return await self.open_incident(m)
        return None

    async def watch_forever(self) -> None:
        while True:
            try:
                await self.watch_once()
            except Exception as e:  # target down etc. Keep watching.
                log.warning("watcher: %s", e)
            await asyncio.sleep(settings.watch_interval_s)

    def start(self) -> None:
        if self._watch_task is None:
            self._watch_task = asyncio.create_task(self.watch_forever())


orchestrator = Orchestrator()
