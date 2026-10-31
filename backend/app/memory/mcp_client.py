"""Tiny MCP client for Meko's remote MCP server (streamable HTTP, JSON-RPC 2.0).

We talk JSON-RPC directly instead of using the `mcp` SDK, because the SDK's API changed
between major versions and three laptops would end up on three versions.

Usage:
    client = MekoMCP(url, api_key)
    tools = await client.list_tools()
    result = await client.call("memory_search", {"query": "...", "datapack_id": "..."})
"""
from __future__ import annotations

import itertools
import json
from typing import Any

import httpx

PROTOCOL_VERSION = "2025-03-26"


class MekoError(RuntimeError):
    pass


class MekoMCP:
    def __init__(self, url: str, api_key: str, timeout: float = 30.0,
                 transport: httpx.AsyncBaseTransport | None = None):
        if not api_key:
            raise MekoError("MEKO_API_KEY is empty")
        self.transport = transport  # tests pass a mock Meko server here
        self.url = url
        self.api_key = api_key
        self.timeout = timeout
        self.session_id: str | None = None
        self.protocol_version = PROTOCOL_VERSION
        self._ids = itertools.count(1)

    def _headers(self) -> dict:
        h = {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        }
        if self.session_id:
            h["Mcp-Session-Id"] = self.session_id
            h["MCP-Protocol-Version"] = self.protocol_version
        return h

    @staticmethod
    def _parse(resp: httpx.Response, want_id: int | None) -> Any:
        ctype = resp.headers.get("content-type", "")
        if "text/event-stream" in ctype:
            for line in resp.text.splitlines():
                if not line.startswith("data:"):
                    continue
                try:
                    msg = json.loads(line[5:].strip())
                except json.JSONDecodeError:
                    continue
                if want_id is None or msg.get("id") == want_id:
                    return msg
            raise MekoError("no JSON-RPC response found in event stream")
        if not resp.content:
            return {}
        return resp.json()

    async def _rpc(self, method: str, params: dict | None = None, notify: bool = False) -> Any:
        body: dict = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            body["params"] = params
        rid = None
        if not notify:
            rid = next(self._ids)
            body["id"] = rid
        async with httpx.AsyncClient(timeout=self.timeout, transport=self.transport) as http:
            resp = await http.post(self.url, headers=self._headers(), json=body)
        if resp.status_code == 404 and self.session_id and method != "initialize":
            # session expired: start again once
            self.session_id = None
            await self.initialize()
            return await self._rpc(method, params, notify)
        if resp.status_code >= 400:
            raise MekoError(f"{method}: HTTP {resp.status_code} {resp.text[:300]}")
        if method == "initialize":
            self.session_id = resp.headers.get("mcp-session-id") or self.session_id
        if notify:
            return None
        msg = self._parse(resp, rid)
        if "error" in msg:
            raise MekoError(f"{method}: {msg['error']}")
        return msg.get("result", {})

    async def initialize(self) -> dict:
        result = await self._rpc(
            "initialize",
            {"protocolVersion": PROTOCOL_VERSION, "capabilities": {},
             "clientInfo": {"name": "fixonce", "version": "0.1"}},
        )
        self.protocol_version = result.get("protocolVersion", PROTOCOL_VERSION)
        await self._rpc("notifications/initialized", notify=True)
        return result

    async def _ensure(self) -> None:
        if not self.session_id:
            await self.initialize()

    async def list_tools(self) -> list[dict]:
        await self._ensure()
        return (await self._rpc("tools/list", {})).get("tools", [])

    async def call(self, tool: str, arguments: dict) -> Any:
        """Call a Meko tool and return its payload (structured content or parsed JSON text)."""
        await self._ensure()
        args = {k: v for k, v in arguments.items() if v is not None}
        result = await self._rpc("tools/call", {"name": tool, "arguments": args})
        if result.get("isError"):
            raise MekoError(f"{tool}: {_text_of(result)[:300]}")
        if result.get("structuredContent") is not None:
            return result["structuredContent"]
        text = _text_of(result)
        try:
            return json.loads(text)
        except (json.JSONDecodeError, TypeError):
            return text


def _text_of(result: dict) -> str:
    parts = [c.get("text", "") for c in result.get("content", []) if c.get("type") == "text"]
    return "\n".join(parts)
