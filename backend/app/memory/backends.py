"""Two interchangeable memory backends with the same methods.

RealMeko  -> Meko over MCP (tool names from docs.mekodata.ai/reference/mcp-server)
FakeMeko  -> in-memory stand-in for tests and offline work. NEVER use it in the demo:
             requirement A5 says nothing may be shown as context that Meko did not return.
"""
from __future__ import annotations

import asyncio
import base64
import re
import time
import uuid
from typing import Any

from ..models import MemoryItem
from .mcp_client import MekoMCP

TEXT_KEYS = ("memory", "text", "content", "chunk", "snippet", "data", "message", "summary")
ID_KEYS = ("id", "memory_id", "document_id", "message_id")
SCORE_KEYS = ("score", "raw_similarity_score", "similarity", "relevance")


def _walk_items(payload: Any, source: str) -> list[MemoryItem]:
    """Find memory-like dicts anywhere in a Meko response. Meko documents few return
    shapes, so this is deliberately tolerant."""
    found: list[MemoryItem] = []

    def visit(node: Any, src: str) -> None:
        if isinstance(node, dict):
            text = next((node[k] for k in TEXT_KEYS if isinstance(node.get(k), str) and node.get(k).strip()), None)
            if text is not None and any(k in node for k in ID_KEYS + SCORE_KEYS):
                score = next((node[k] for k in SCORE_KEYS if isinstance(node.get(k), (int, float))), None)
                mid = next((str(node[k]) for k in ID_KEYS if node.get(k) is not None), None)
                meta = node.get("metadata") if isinstance(node.get("metadata"), dict) else {}
                found.append(MemoryItem(id=mid, text=text, score=score, source=src,
                                        promoted=node.get("promoted"), metadata=meta))
                return
            for key, value in node.items():
                child_src = key if key in ("memory", "knowledge_base", "conversation") and isinstance(value, (list, dict)) else src
                visit(value, child_src)
        elif isinstance(node, list):
            for v in node:
                visit(v, src)

    visit(payload, source)
    return found


def _overlap(a: str, b: str) -> float:
    ta, tb = set(re.findall(r"[a-z0-9_]+", a.lower())), set(re.findall(r"[a-z0-9_]+", b.lower()))
    return len(ta & tb) / max(1, min(len(ta), len(tb)))


class RealMeko:
    name = "meko"

    def __init__(self, url: str, api_key: str, datapack_id: str, transport=None):
        self.client = MekoMCP(url, api_key, transport=transport)
        self.datapack_id = datapack_id or None

    def _dp(self, **kw) -> dict:
        kw["datapack_id"] = self.datapack_id
        return kw

    async def search(self, query: str, agent_id: str, limit: int = 8) -> list[MemoryItem]:
        payload = await self.client.call("context_search", self._dp(query=query, agent_id=agent_id, limit=limit))
        items = _walk_items(payload, "memory")
        if not items:  # fall back to plain memory search
            payload = await self.client.call("memory_search", self._dp(query=query, agent_id=agent_id, limit=limit))
            items = _walk_items(payload, "memory")
        return items

    async def add(self, text: str, agent_id: str, metadata: dict, conversation_id: str | None) -> list[MemoryItem]:
        payload = await self.client.call("memory_add", self._dp(
            text=text, agent_id=agent_id, metadata=metadata, conversation_id=conversation_id))
        items = [i for i in _walk_items(payload, "stored") if i.id]
        if not items:
            # Meko may extract memories asynchronously and return no ids. Look the new memory up,
            # so Correct / Forget / Promote have a real id. Never invent one.
            await asyncio.sleep(1.0)
            found = _walk_items(await self.client.call("memory_search", self._dp(
                query=text[:300], agent_id=agent_id, limit=3)), "stored")
            items = [i for i in found if i.id and _overlap(i.text, text) >= 0.5]
        for i in items:
            i.source = "stored"
        return items or [MemoryItem(text=text, source="stored", metadata=metadata,
                                    promoted=None)]

    async def promote(self, memory_ids: list[str], agent_id: str, conversation_id: str | None) -> Any:
        return await self.client.call("memory_promote", self._dp(
            memory_ids=memory_ids, agent_id=agent_id, conversation_id=conversation_id))

    async def delete(self, memory_id: str, agent_id: str) -> Any:
        return await self.client.call("memory_delete_by_id", self._dp(memory_id=memory_id, agent_id=agent_id))

    async def update(self, memory_id: str, text: str, agent_id: str) -> Any:
        return await self.client.call("memory_update", self._dp(memory_id=memory_id, text=text, agent_id=agent_id))

    async def recent(self, agent_id: str | None, promoted: bool | None) -> list[MemoryItem]:
        payload = await self.client.call("memory_get_all", self._dp(agent_id=agent_id, promoted=promoted))
        return _walk_items(payload, "memory")

    async def conversation(self, title: str, agent_id: str) -> str | None:
        payload = await self.client.call("conversation_create", self._dp(title=title, agent_id=agent_id))
        if isinstance(payload, dict):
            for k in ("conversation_id", "id"):
                if payload.get(k):
                    return str(payload[k])
            for v in payload.values():
                if isinstance(v, dict) and (v.get("conversation_id") or v.get("id")):
                    return str(v.get("conversation_id") or v.get("id"))
        return None

    async def message(self, conversation_id: str, agent_id: str, input: str, output: str,
                      reasoning: str, plan: list[str]) -> Any:
        return await self.client.call("conversation_add_message", self._dp(
            conversation_id=conversation_id, agent_id=agent_id, input=input, output=output,
            reasoning=reasoning, plan=plan))

    async def artifact(self, filename: str, text: str, agent_id: str, conversation_id: str | None) -> str:
        payload = await self.client.call("artifact_put", self._dp(
            filename=filename, content_base64=base64.b64encode(text.encode()).decode(),
            content_type="text/markdown", agent_id=agent_id, conversation_id=conversation_id))
        if isinstance(payload, dict):
            return str(payload.get("content_hash") or payload.get("hash") or payload)
        return str(payload)


class FakeMeko:
    """Same interface, kept in a Python list. Scores by word overlap."""
    name = "fake-meko"

    def __init__(self):
        self.items: list[dict] = []
        self.messages: list[dict] = []
        self.artifacts: dict[str, str] = {}

    @staticmethod
    def _tokens(s: str) -> set[str]:
        return {w for w in re.findall(r"[a-z0-9_]+", s.lower()) if len(w) > 2}

    async def search(self, query: str, agent_id: str, limit: int = 8) -> list[MemoryItem]:
        q = self._tokens(query)
        scored = []
        for it in self.items:
            t = self._tokens(it["text"])
            if not q or not t:
                continue
            score = len(q & t) / len(q)
            if score > 0:
                scored.append((score, it))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [MemoryItem(id=it["id"], text=it["text"], score=round(s, 3), source="memory",
                           promoted=it["promoted"], metadata=it["metadata"]) for s, it in scored[:limit]]

    async def add(self, text: str, agent_id: str, metadata: dict, conversation_id: str | None) -> list[MemoryItem]:
        it = {"id": f"mem-{uuid.uuid4().hex[:8]}", "text": text, "agent_id": agent_id,
              "metadata": dict(metadata), "promoted": False, "t": time.time()}
        self.items.append(it)
        return [MemoryItem(id=it["id"], text=text, source="stored", promoted=False, metadata=it["metadata"])]

    async def promote(self, memory_ids: list[str], agent_id: str, conversation_id: str | None) -> Any:
        for it in self.items:
            if it["id"] in memory_ids:
                it["promoted"] = True
        return {"promoted": memory_ids}

    async def delete(self, memory_id: str, agent_id: str) -> Any:
        self.items = [it for it in self.items if it["id"] != memory_id]
        return {"deleted": memory_id}

    async def update(self, memory_id: str, text: str, agent_id: str) -> Any:
        for it in self.items:
            if it["id"] == memory_id:
                it["text"] = text
        return {"updated": memory_id}

    async def recent(self, agent_id: str | None, promoted: bool | None) -> list[MemoryItem]:
        rows = [it for it in self.items if promoted is None or it["promoted"] == promoted]
        rows = sorted(rows, key=lambda it: it["t"], reverse=True)[:20]
        return [MemoryItem(id=it["id"], text=it["text"], source="memory", promoted=it["promoted"],
                           metadata=it["metadata"]) for it in rows]

    async def conversation(self, title: str, agent_id: str) -> str | None:
        return f"conv-{uuid.uuid4().hex[:8]}"

    async def message(self, conversation_id, agent_id, input, output, reasoning, plan) -> Any:
        self.messages.append({"conversation_id": conversation_id, "agent_id": agent_id, "input": input,
                              "output": output, "reasoning": reasoning, "plan": plan, "t": time.time()})
        return {"ok": True}

    async def artifact(self, filename: str, text: str, agent_id: str, conversation_id: str | None) -> str:
        h = f"sha-{uuid.uuid4().hex[:12]}"
        self.artifacts[h] = text
        return h
