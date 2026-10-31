# FixOnce

**Every incident, fixed only once.** An on-call teammate that remembers.

When a service breaks at 3 AM, FixOnce tells the engineer on call, in plain words, what happened last
time, what fixed it, what made it worse, and offers the safe fix as one tap. Every incident becomes a
lesson in [Meko](https://mekodata.ai), so the next one is faster. Switch Meko off and FixOnce goes
back to guessing: that difference is the product.

Built at hackCBS 9.0 for the Meko challenge (Track A).

## Problem

Most outages are repeats. The fix exists, but it lives in someone's head or an old chat thread,
and the junior on call starts from zero. Worse, nobody writes down what made things worse, so the
same wrong step gets tried again.

## Run it (5 commands)

Needs only Git and Docker (Docker Desktop running on Windows/macOS). Works the same in bash and PowerShell.

```bash
git clone https://github.com/visheshgupta0404/FixOnce.git
cd FixOnce
cp .env.example .env          # add MEKO_API_KEY, MEKO_DATAPACK_ID, GEMINI_API_KEY
docker compose up --build -d
docker compose exec backend python -m app.seed   # seeded demo history, written into Meko (once per datapack)
```

Open http://localhost:8000. With no keys in `.env`, it runs offline with a fake memory and a
rule-based model (for development only; the demo uses real Meko and Gemini). `GET /api/status`
says which one is running.

On a slow network the first build can take 15+ minutes; if pip times out, run
`docker compose up --build -d` again and it resumes from the wheels it already downloaded.

Only port 8000 is published. The demo shop listens on 127.0.0.1:8001 for debugging.

Between demo runs: `scripts/demo_reset.sh` (shop healthy, incidents cleared, Meko OFF; lessons in
Meko are kept). `scripts/demo_smoke.sh` runs the Meko OFF vs ON flow through the API and prints PASS.
Both take `FIXONCE_URL=<url>` to point at the hosted copy.

Free hosting (Render): New > Blueprint > this repo, enter the three keys when asked. `render.yaml`
uses the one-container `Dockerfile` at the root (the shop runs inside the backend process).
Free instances sleep after 15 idle minutes, so point a free uptime monitor at `/api/status`.

## Try it

1. Turn Meko **OFF**, press **Break: DB connections**, tap Apply. The agent raises the pool size,
   which makes things worse, then gives up after three tries.
2. Press **Reset demo**, turn Meko **ON**, break it again. FixOnce recalls the past incident,
   avoids the steps that made it worse, and pauses the export job. Fixed first time.
3. In the recall panel, see exactly what Meko returned and stored. Correct or forget the new lesson,
   then promote it: it joins the shared team knowledge panel and is locked from then on.

## How Meko is used (and why)

| Meko use | In FixOnce | Why |
| --- | --- | --- |
| Recall before reasoning | The Recall agent calls `context_search` and `knowledgebase_search` before the LLM sees the incident | The past fix and the failed steps are in front of the agent from the first step |
| Extracted memories | The Scribe saves each incident as a lesson with `memory_add`; the on-call can correct or forget it | The next on-call needs the lesson, not the raw logs |
| Promotion to shared knowledge | After a human confirms the fix held, `memory_promote`. Promotion is one-way in Meko, so a promoted lesson is shown as locked | Only verified fixes become team knowledge |
| Sharing across agents and users | Four agents and every teammate's agents read promoted lessons | The morning shift gets the night shift's lessons |
| Documents | Postmortems saved with `artifact_put`; decision traces with `conversation_add_message` | Every choice can be explained later |

Everything shown as memory in the UI came back from a real Meko call (see "Every Meko call").
The chaos buttons and the shop are a labelled simulation. No personal data is stored.

## Architecture

- `shop/`: demo shop simulation that can break three ways
- `backend/`: FastAPI + four agents (triage, recall, fixer, scribe) + Meko over MCP + Gemini
- `web/`: the page the on-call engineer uses

## Slides and team

- Slides: _add link_
- Team: Vedansh Mathur, Vishal Verma, Vishesh Gupta

## Tests

```bash
cd backend && pip install -r requirements.txt && python -m pytest -q
```
