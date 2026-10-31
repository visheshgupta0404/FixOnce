# FixOnce: team protocol for coding agents

FixOnce is an on-call teammate that remembers. When a service breaks, it shows the on-call engineer
what happened last time, what worked, what made it worse, and offers a safe fix as one tap.
Built for the Meko challenge, Track A, at hackCBS 9.0. Deadline: submit by 10 AM, 1 Nov.

## Meko build datapack: `fixonce-build` (Check T)
- Before every task: recall from `fixonce-build` (contract, decisions, conventions).
- After every task: save a 2-3 line summary to `fixonce-build`, starting with your name.
- Promote every decision the others must follow (API shape, names, env vars, datapack names)
  as "[Name] decided: ...". Only promoted rows reach the rest of the team.
- Never store keys, tokens or personal data in `fixonce-build`.
- Never read or write the product datapack from here. The product never reads `fixonce-build`.

## What judges check (Meko brief, Track A)
- A1: the same flow with Meko ON vs OFF gives clearly different results (`POST /settings/meko`).
- A2: at least 3 Meko uses with a reason each (recall before reasoning, extracted memories,
  promotion to shared knowledge, sharing across agents and users, documents).
- A4: the UI shows what was recalled and stored, with Correct and Forget.
- A5: nothing shown as memory unless Meko returned it; the chaos buttons are labelled simulation.
- Setup in 5 commands or fewer (see README). Demo of 5 minutes max.

## Code map
- `shop/app.py`: demo shop SIMULATION with chaos scenarios (Teammate B owns)
- `backend/app/models.py`: the shared contract. Change only together, then promote the change
- `backend/app/memory/`: the ONE door to Meko (`service.py`), MCP client, real + fake backends (Vedansh)
- `backend/app/agents/`: triage, recall, fixer, scribe (Vedansh)
- `backend/app/orchestrator.py`: incident flow + watcher (Vedansh)
- `backend/app/main.py`: API endpoints from the contract (Teammate B owns)
- `backend/app/store.py`: incident store, in-memory; may move to YugabyteDB (Teammate B)
- `web/index.html`: the page judges see (Teammate C owns)

## Rules
- Python 3.11+, FastAPI, small files, plain words in anything a user sees.
- Run `cd backend && python -m pytest -q` before every push. Keep the tests green.
- Branches: `feat/agents` (Vedansh), `feat/platform` (B), `feat/experience` (C). Merge at 6 PM, 1 AM, 3 AM.
