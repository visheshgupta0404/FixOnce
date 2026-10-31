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
STATE = {"memories": [], "conversations": {}, "conv_owner": {}, "artifacts": {}, "sse": False, "add_returns_ids": True,
         "calls": []}


def reset(sse=False, add_returns_ids=True):
    STATE.update({"memories": [], "conversations": {}, "conv_owner": {}, "artifacts": {}, "sse": sse,
                  "add_returns_ids": add_returns_ids, "calls": []})


def _tok(s):
    return {w for w in re.findall(r"[a-z0-9_]+", s.lower()) if len(w) > 2}


def _search(query, limit=10, promoted=False):
    """Like real Meko, promoted memories leave mem0 search and show up in the knowledge base."""
    q = _tok(query)
    out = []
    for m in STATE["memories"]:
        score = len(q & _tok(m["memory"])) / max(1, len(q))
        if score > 0 and m["promoted"] == promoted:
            out.append({**m, "score": round(score, 3), "raw_similarity_score": round(score * 0.9, 3)})
    return sorted(out, key=lambda m: m["score"], reverse=True)[:limit]


def _kb_chunk(m):
    return {"id": uuid.uuid4().hex, "chunk_text": m["memory"], "document_id": uuid.uuid4().hex,
            "metadata_filters": {"source": "memory", "agent_id": m["agent_id"], "memory_id": m["id"]},
            "distance": round(1 - m["score"], 3), "match_type": "hybrid", "rerank_score": m["score"]}


def _tool(name, a):
    STATE["calls"].append(name)
    # Real Meko rules: every tool but conversation_create needs a conversation_id,
    # and metadata is a JSON string, not an object.
    if name != "conversation_create" and not a.get("conversation_id"):
        raise ValueError("conversation_id: Missing required argument")
    if a.get("metadata") is not None and not isinstance(a["metadata"], str):
        raise ValueError("metadata: Input should be a valid string")
    if name == "memory_add":
        m = {"id": uuid.uuid4().hex, "memory": a["text"], "metadata": json.loads(a.get("metadata") or "{}"),
             "agent_id": a.get("agent_id"), "promoted": False}
        STATE["memories"].append(m)
        return {"results": [{"id": m["id"], "memory": m["memory"], "event": "ADD"}]} if STATE["add_returns_ids"] \
            else {"status": "queued"}
    if name == "memory_search":
        return {"results": _search(a["query"], a.get("limit", 10))}
    if name == "context_search":
        return {"results": {"knowledge_base": [], "memory": _search(a["query"], a.get("limit", 10)),
                            "conversation": {"hits": [], "thread": []}},
                "match_quality": "mid"}
    if name == "knowledgebase_search":
        chunks = [_kb_chunk(m) for m in _search(a["query"], a.get("limit", 10), promoted=True)]
        return {"results": chunks, "count": len(chunks)}
    if name == "memory_promote":
        for m in STATE["memories"]:
            if m["id"] in a["memory_ids"]:
                m["promoted"] = True
        return {"promoted": len(a["memory_ids"])}
    if name == "memory_get_by_id":
        m = next((m for m in STATE["memories"] if m["id"] == a["memory_id"] and not m["promoted"]), None)
        return {"error": "not_found", "detail": f"No memory found with id {a['memory_id']}."} if m is None \
            else {"id": m["id"], "memory": m["memory"], "agent_id": m["agent_id"]}
    if name in ("memory_delete_by_id", "memory_update"):
        m = next((m for m in STATE["memories"] if m["id"] == a["memory_id"]), None)
        if m is not None and m["promoted"]:  # real Meko: promotion is one-way, the memory left mem0
            raise RuntimeError(f"Error calling tool '{name}': Object of type UUID is not JSON serializable")
        if m is None or m["agent_id"] != a.get("agent_id"):
            raise PermissionError("agent_id must match the writer")
        if name == "memory_update":
            m["memory"] = a["text"]
        else:
            STATE["memories"].remove(m)
        return {"ok": True}
    if name == "memory_get_all":
        promoted = bool(a.get("promoted"))
        rows = [{"id": m["id"], "data": m["memory"], "agent_id": m["agent_id"]}
                for m in STATE["memories"] if m["promoted"] == promoted]
        return {"promoted_memories" if promoted else "memories": rows[-20:], "total": len(rows)}
    if name == "conversation_create":
        cid = uuid.uuid4().hex
        STATE["conversations"][cid] = []
        STATE["conv_owner"][cid] = a.get("agent_id")
        return {"id": cid, "agent_id": a.get("agent_id"), "title": a.get("title")}
    if name == "conversation_add_message":
        owner = STATE["conv_owner"].get(a["conversation_id"])
        if owner is not None and owner != a.get("agent_id"):  # real Meko: a normal result, not isError
            return {"error": "agent_id_mismatch",
                    "detail": f"Conversation {a['conversation_id']} belongs to agent '{owner}'"}
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
            "context_search", "knowledgebase_search", "memory_add", "memory_search", "memory_promote",
            "memory_get_by_id", "memory_delete_by_id",
            "memory_update", "memory_get_all", "conversation_create", "conversation_add_message", "artifact_put")]}})
    if method == "tools/call":
        p = msg["params"]
        try:
            text = json.dumps(_tool(p["name"], p.get("arguments", {})))
            # Real Meko sends the same JSON twice: as text, and wrapped as {"result": "<json text>"}.
            result = {"content": [{"type": "text", "text": text}], "structuredContent": {"result": text},
                      "isError": False}
        except Exception as e:
            result = {"content": [{"type": "text", "text": str(e)}], "isError": True}
        return _reply({"jsonrpc": "2.0", "id": rid, "result": result})
    return _reply({"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": "method not found"}})
