# Decisions to promote to `fixonce-build`

Vedansh: ask your Claude Code (connected to Meko) to save and promote each line below as
"[Vedansh] decided: ...". Teammates promote their own decisions the same way as they work.

1. Project name is FixOnce; tagline "Every incident, fixed only once".
2. Track A of the Meko challenge; theme label Cloud; submit by 10 AM, 1 Nov.
3. Repo layout: one pip package backend/fixonce (agents, memory, API, page in web/, demo shop in demo/); shop/ holds only its Dockerfile.
4. backend/fixonce/models.py is the shared contract; change only together.
5. Safe actions are exactly: pause_batch_job, raise_pool_size, scale_up, rollback_last_deploy, restart_service.
6. Chaos kinds: db_pool, bad_deploy, memory_leak, plus sale_on / sale_off.
7. db_pool scenario: the right fix is pause_batch_job; raise_pool_size, scale_up and restart_service make it worse.
8. All Meko calls go through backend/fixonce/memory/service.py; agents never call Meko directly.
9. Meko is reached with a small JSON-RPC client (memory/mcp_client.py), not the mcp SDK, to avoid version drift.
10. Lessons are written by agent_id "scribe", so only "scribe" can update or delete them (Meko rule).
11. Product datapack and fixonce-build are never mixed.
12. MEKO_ENABLED / POST /settings/meko is the ON/OFF switch for requirement A1.
13. GET /incidents/{id}/context returns exactly what Meko returned and stored (A4, A5).
14. Offline dev uses FakeMeko + rule-based LLM; the demo always uses real Meko and Gemini.
15. Gemini model via GEMINI_MODEL env; structured JSON output with a schema.
16. tests/mock_meko.py mimics Meko's MCP server; the real Meko path must stay green against it (JSON and SSE).
17. FixOnce ships as a pip package (`fixonce`) that companies run in their own infra; there is no FixOnce server.
18. The watched service is a "target": 4 HTTP endpoints (/metrics, /logs, /deploys, /actions/{name}) or a Python object with the same async methods (target.py).
19. A target brings its own action catalog via fixonce.configure(actions=...); the fixer only proposes names from it. The 5 demo actions are the default.
20. Logs are redacted in-process (emails, IPs, secrets, card and phone numbers) before agents, the LLM or Meko see them; FIXONCE_REDACT=true by default.
21. Commands: fixonce demo | serve --target | seed | check. TARGET_URL replaces SHOP_URL (both read). FIXONCE_DEMO=false for real targets (no chaos, no seeded history).
