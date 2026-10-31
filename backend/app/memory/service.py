"""The ONE door to Meko. Every agent goes through `memory`, never through the backend directly.

- `enabled` is the Meko ON/OFF switch for the demo (requirement A1). OFF means: recall returns
  nothing and nothing is stored. The agents run on the LLM alone.
- `log` records every Meko call (tool, agent, what went in, what came back). The web page shows it,
  so judges can see that every piece of context came from a real call (A4, A5).
- If Meko is unreachable, reads return nothing and writes are queued, then flushed later.
"""
from __future__ import annotations

import time
from typing import Any

from ..config import settings
from ..models import MemoryItem
from .backends import FakeMeko, RealMeko


class MemoryService:
    def __init__(self, backend=None):
        if backend is None:
            if settings.meko_mode == "real":
                backend = RealMeko(settings.meko_url, settings.meko_api_key, settings.meko_datapack_id)
            else:
                backend = FakeMeko()
        self.backend = backend
        self.enabled = settings.meko_enabled_at_start
        self.log: list[dict] = []
        self.pending_writes: list[tuple[str, tuple, dict]] = []

    @property
    def mode(self) -> str:
        return self.backend.name

    def _record(self, op: str, agent: str, sent: Any, got: Any = None, ok: bool = True, note: str = "") -> None:
        self.log.append({"t": time.time(), "op": op, "agent": agent, "sent": sent, "got": got,
                         "ok": ok, "note": note, "backend": self.mode})
        self.log = self.log[-300:]

    async def _write(self, op: str, agent: str, fn_name: str, *args, **kwargs):
        sent = {"args": list(args), **kwargs}
        if not self.enabled:
            self._record(op, agent, sent, note="skipped: Meko is OFF")
            return None
        try:
            result = await getattr(self.backend, fn_name)(*args, **kwargs)
            self._record(op, agent, sent, _brief(result))
            return result
        except Exception as e:  # Meko down: queue it, keep the incident moving
            self.pending_writes.append((fn_name, args, kwargs))
            self._record(op, agent, sent, ok=False, note=f"queued, Meko error: {e}")
            return None

    async def flush_pending(self) -> int:
        done, keep = 0, []
        for fn_name, args, kwargs in self.pending_writes:
            try:
                await getattr(self.backend, fn_name)(*args, **kwargs)
                done += 1
            except Exception:
                keep.append((fn_name, args, kwargs))
        self.pending_writes = keep
        return done

    # ---- reads -------------------------------------------------------------
    async def recall(self, query: str, agent: str = "recall") -> tuple[list[MemoryItem], str | None]:
        """Returns (items exactly as Meko returned them, error or None)."""
        if not self.enabled:
            self._record("recall", agent, {"query": query}, [], note="skipped: Meko is OFF")
            return [], None
        try:
            items = await self.backend.search(query, agent_id=agent)
            self._record("recall", agent, {"query": query}, [i.model_dump() for i in items])
            return items, None
        except Exception as e:
            self._record("recall", agent, {"query": query}, ok=False, note=f"Meko error: {e}")
            return [], str(e)

    async def recent(self, promoted: bool | None = None, agent: str = "web") -> list[MemoryItem]:
        if not self.enabled:
            return []
        try:
            return await self.backend.recent(None, promoted)
        except Exception as e:
            self._record("recent", agent, {"promoted": promoted}, ok=False, note=str(e))
            return []

    # ---- writes ------------------------------------------------------------
    async def save_lesson(self, text: str, metadata: dict, conversation_id: str | None,
                          agent: str = "scribe") -> list[MemoryItem]:
        result = await self._write("save_lesson", agent, "add", text, agent_id=agent,
                                   metadata=metadata, conversation_id=conversation_id)
        return result or []

    async def promote(self, memory_ids: list[str], conversation_id: str | None, agent: str = "scribe"):
        return await self._write("promote", agent, "promote", memory_ids, agent_id=agent,
                                 conversation_id=conversation_id)

    async def forget(self, memory_id: str, agent: str = "scribe"):
        # Meko only lets the agent that wrote a memory delete it: lessons are written as "scribe".
        return await self._write("forget", agent, "delete", memory_id, agent_id=agent)

    async def correct(self, memory_id: str, text: str, agent: str = "scribe"):
        return await self._write("correct", agent, "update", memory_id, text, agent_id=agent)

    async def start_conversation(self, title: str, agent: str = "orchestrator") -> str | None:
        return await self._write("conversation_create", agent, "conversation", title, agent_id=agent)

    async def log_decision(self, conversation_id: str | None, agent: str, input: str, output: str,
                           reasoning: str, plan: list[str] | None = None):
        """Decision trace: why an agent did what it did (stored with the conversation)."""
        if not conversation_id:
            return None
        return await self._write("decision_trace", agent, "message", conversation_id, agent_id=agent,
                                 input=input, output=output, reasoning=reasoning, plan=plan or [])

    async def put_document(self, filename: str, text: str, conversation_id: str | None, agent: str = "scribe"):
        return await self._write("artifact_put", agent, "artifact", filename, text, agent_id=agent,
                                 conversation_id=conversation_id)


def _brief(result: Any) -> Any:
    if isinstance(result, list):
        return [r.model_dump() if hasattr(r, "model_dump") else r for r in result]
    return result


memory = MemoryService()
