"""A small stand-in for Meko's remote MCP server, used ONLY by tests.

It speaks the same protocol (JSON-RPC over streamable HTTP, session header, SSE or JSON replies)
and implements the tools FixOnce calls, with mem0-style result shapes. It also enforces two real
Meko rules: a Bearer key is required, and only the agent that wrote a memory may delete or edit it.
"""
import json
import re
import uuid

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

app = FastAPI()
STATE = {"memories": [], "conversations": {}, "artifacts": {}, "sse": False, "add_returns_ids": True,
         "calls": []}


def reset(sse=False, add_returns_ids=True):
    STATE.update({"memories": [], "conversations": {}, "artifacts": {}, "sse": sse,
                  "add_returns_ids": add_returns_ids, "calls": []})


def _tok(s):
    return {w for w in re.findall(r"[a-z0-9_]+", s.lower()) if len(w) > 2}


def _search(query, limit=10):
    q = _tok(query)
    out = []
    for m in STATE["memories"]:
        score = len(q & _tok(m["memory"])) / max(1, len(q))
        if score > 0:
            out.append({**m, "score": round(score, 3), "raw_similarity_score": round(score * 0.9, 3)})
    return sorted(out, key=lambda m: m["score"], reverse=True)[:limit]


def _tool(name, a):
    STATE["calls"].append(name)
    if name == "memory_add":
        m = {"id": uuid.uuid4().hex, "memory": a["text"], "metadata": a.get("metadata") or {},
             "agent_id": a.get("agent_id"), "promoted": False}
        STATE["memories"].append(m)
        return {"results": [{"id": m["id"], "memory": m["memory"], "event": "ADD"}]} if STATE["add_returns_ids"] \
            else {"status": "queued"}
    if name == "memory_search":
        return {"results": _search(a["query"], a.get("limit", 10))}
    if name == "context_search":
        return {"memory": {"status": "ok", "results": _search(a["query"], a.get("limit", 10))},
                "knowledge_base": {"status": "empty", "results": []},
                "conversation": {"status": "empty", "results": []}}
    if name == "memory_promote":
        for m in STATE["memories"]:
            if m["id"] in a["memory_ids"]:
                m["promoted"] = True
        return {"promoted": len(a["memory_ids"])}
    if name in ("memory_delete_by_id", "memory_update"):
        m = next((m for m in STATE["memories"] if m["id"] == a["memory_id"]), None)
        if m is None or m["agent_id"] != a.get("agent_id"):
            raise PermissionError("agent_id must match the writer")
        if name == "memory_update":
            m["memory"] = a["text"]
        else:
            STATE["memories"].remove(m)
        return {"ok": True}
    if name == "memory_get_all":
        rows = [m for m in STATE["memories"] if a.get("promoted") is None or m["promoted"] == a["promoted"]]
        return {"results": rows[-20:], "total": len(rows)}
    if name == "conversation_create":
        cid = uuid.uuid4().hex
        STATE["conversations"][cid] = []
        return {"conversation_id": cid}
    if name == "conversation_add_message":
        STATE["conversations"].setdefault(a["conversation_id"], []).append(a)
        return {"ok": True}
    if name == "artifact_put":
        h = uuid.uuid4().hex
        STATE["artifacts"][h] = a["content_base64"]
        return {"content_hash": h}
    raise KeyError(f"unknown tool {name}")


def _reply(body: dict, headers: dict | None = None) -> Response:
    if STATE["sse"]:
        text = f"event: message\ndata: {json.dumps(body)}\n\n"
        return Response(text, media_type="text/event-stream", headers=headers)
    return JSONResponse(body, headers=headers)


@app.post("/mcp")
async def mcp(request: Request):
    if not request.headers.get("authorization", "").startswith("Bearer "):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    msg = await request.json()
    method, rid = msg.get("method"), msg.get("id")
    if method == "initialize":
        return _reply({"jsonrpc": "2.0", "id": rid, "result": {"protocolVersion": "2025-03-26",
                       "capabilities": {"tools": {}}, "serverInfo": {"name": "mock-meko"}}},
                      {"mcp-session-id": "sess-1"})
    if request.headers.get("mcp-session-id") != "sess-1":
        return JSONResponse({"error": "no session"}, status_code=400)
    if method == "notifications/initialized":
        return Response(status_code=202)
    if method == "tools/list":
        return _reply({"jsonrpc": "2.0", "id": rid, "result": {"tools": [{"name": n} for n in (
            "context_search", "memory_add", "memory_search", "memory_promote", "memory_delete_by_id",
            "memory_update", "memory_get_all", "conversation_create", "conversation_add_message", "artifact_put")]}})
    if method == "tools/call":
        p = msg["params"]
        try:
            out = _tool(p["name"], p.get("arguments", {}))
            result = {"content": [{"type": "text", "text": json.dumps(out)}], "isError": False}
        except Exception as e:
            result = {"content": [{"type": "text", "text": str(e)}], "isError": True}
        return _reply({"jsonrpc": "2.0", "id": rid, "result": result})
    return _reply({"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": "method not found"}})
