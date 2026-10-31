# Decisions to promote to `fixonce-build`

Vedansh: ask your Claude Code (connected to Meko) to save and promote each line below as
"[Vedansh] decided: ...". Teammates promote their own decisions the same way as they work.

1. Project name is FixOnce; tagline "Every incident, fixed only once".
2. Track A of the Meko challenge; theme label Cloud; submit by 10 AM, 1 Nov.
3. Repo layout: shop/ (simulation), backend/app (FastAPI, agents, memory), web/ (UI).
4. backend/app/models.py is the shared contract; change only together.
5. Safe actions are exactly: pause_batch_job, raise_pool_size, scale_up, rollback_last_deploy, restart_service.
6. Chaos kinds: db_pool, bad_deploy, memory_leak, plus sale_on / sale_off.
7. db_pool scenario: the right fix is pause_batch_job; raise_pool_size, scale_up and restart_service make it worse.
8. All Meko calls go through backend/app/memory/service.py; agents never call Meko directly.
9. Meko is reached with a small JSON-RPC client (memory/mcp_client.py), not the mcp SDK, to avoid version drift.
10. Lessons are written by agent_id "scribe", so only "scribe" can update or delete them (Meko rule).
11. Product datapack and fixonce-build are never mixed.
12. MEKO_ENABLED / POST /settings/meko is the ON/OFF switch for requirement A1.
13. GET /incidents/{id}/context returns exactly what Meko returned and stored (A4, A5).
14. Offline dev uses FakeMeko + rule-based LLM; the demo always uses real Meko and Gemini.
15. Gemini model via GEMINI_MODEL env; structured JSON output with a schema.
16. tests/mock_meko.py mimics Meko's MCP server; the real Meko path must stay green against it (JSON and SSE).
