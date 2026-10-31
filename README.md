# FixOnce

**Every incident, fixed only once.** An on-call teammate that remembers.

When a service breaks at 3 AM, FixOnce tells the engineer on call, in plain words, what happened last
time, what fixed it, what made it worse, and offers the safe fix as one tap. Every incident becomes a
lesson in [Meko](https://mekodata.ai), so the next one is faster. Switch Meko off and FixOnce goes
back to guessing: that difference is the product.

Built at hackCBS 9.0 for the Meko challenge (Track A).

**FixOnce is a pip package, not a hosted service.** Companies install it and run it inside their own
infrastructure, next to the service it watches. There is no FixOnce server: incident data goes only
to the Meko datapack and the LLM key the company configures itself, and log lines are redacted first.
See [Use it in your company](#use-it-in-your-company-pip-package).

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
docker compose exec backend python -m fixonce.seed   # seeded demo history, written into Meko (once per datapack)
```

Open http://localhost:8000. With no keys in `.env`, it runs offline with a fake memory and a
rule-based model (for development only; the demo uses real Meko and Gemini). `GET /api/status`
says which one is running.

On a slow network the first build can take 15+ minutes; if pip times out, run
`docker compose up --build -d` again and it resumes from the wheels it already downloaded.

Only port 8000 is published. The demo shop listens on 127.0.0.1:8001 for debugging.

Without Docker, from the package: `pip install "./backend[gemini]"`, then `fixonce demo` (page, agents and
the demo shop in one process; it reads `.env` from the current folder).

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
4. Look at the orange card: **This is the 3rd time**. FixOnce counts the past incidents of this kind in
   Meko, names the root cause from those lessons, and suggests the permanent fix. Tap **Create follow-up**:
   it is stored in Meko, listed under Open follow-ups, and the next repeat says it is still not done.
   "Every incident, fixed only once" means the quick fix stops being a habit.
5. Scroll to **What left this machine**: every request that went to Meko and to Gemini, and the
   customer emails and IPs masked in the logs before anything was sent. Nothing else leaves.

## How Meko is used (and why)

| Meko use | In FixOnce | Why |
| --- | --- | --- |
| Recall before reasoning | The Recall agent calls `context_search` and `knowledgebase_search` before the LLM sees the incident | The past fix and the failed steps are in front of the agent from the first step |
| Extracted memories | The Scribe saves each incident as a lesson with `memory_add`; the on-call can correct or forget it | The next on-call needs the lesson, not the raw logs |
| Promotion to shared knowledge | After a human confirms the fix held, `memory_promote`. Promotion is one-way in Meko, so a promoted lesson is shown as locked | Only verified fixes become team knowledge |
| Sharing across agents and users | Four agents and every teammate's agents read promoted lessons | The morning shift gets the night shift's lessons |
| Documents | Postmortems saved with `artifact_put`; decision traces with `conversation_add_message` | Every choice can be explained later |
| Patterns across incidents | Recall counts the past lessons of the same kind (private and promoted) and reads the root cause from them; a follow-up for the permanent fix is a Meko memory that recall finds on the next repeat | A repeat should push the team to fix the cause, not just apply the quick fix faster |

Everything shown as memory in the UI came back from a real Meko call (see "Every Meko call").
The chaos buttons and the shop are a labelled simulation. No personal data is stored.

## Use it in your company (pip package)

Most companies will not send production incidents to a third-party app. So FixOnce ships as a
package that runs on their own machines; nothing goes through us.

```bash
pip install "fixonce[gemini] @ git+https://github.com/visheshgupta0404/FixOnce.git#subdirectory=backend"
fixonce serve --target http://payments.internal:9000      # any service with 4 small endpoints
fixonce serve --target mycompany.fixonce_target:Payments   # ...or a Python adapter object
```

Or embed it in your own Python app:

```python
import fixonce

class Payments:                      # four async methods over your own service
    actions = {"drain_queue": "Drain the stuck payout queue", "flush_cache": "Flush the rates cache"}
    async def metrics(self): ...     # {"service", "version", "error_rate"}
    async def logs(self, limit=20): ...   # [{"level", "msg"}]
    async def deploys(self): ...     # {"current", "previous"}
    async def run_action(self, name): ... # only names from `actions` are ever passed

app = fixonce.create_app(target=Payments())   # FastAPI app: API + on-call page; run with uvicorn
```

| Data | Where it goes |
| --- | --- |
| Metrics, logs, deploys | Read in your process. Emails, IPs, secrets, card and phone numbers are masked before any agent sees them (`FIXONCE_REDACT`, on by default) |
| Lessons, postmortems, decision traces | Your own Meko datapack, with your own key (`MEKO_API_KEY`, `MEKO_DATAPACK_ID`). Switch Meko off and nothing is stored |
| Prompts | Your own Gemini key, or none: without `GEMINI_API_KEY` the agents use built-in rules and nothing goes to an LLM |
| Anything else | Nowhere. The package has no telemetry and no FixOnce server |

The agents only ever propose an action from your `actions` list, and a human taps Apply before it runs.
The page's **What left this machine** panel lists every request to Meko and the LLM as it happens.
A complete adapter to copy: [examples/payments_target.py](examples/payments_target.py)
(`fixonce serve --target examples.payments_target:Payments` from the repo root).
Alerts: set `FIXONCE_WEBHOOK_URL` and every incident step is posted as JSON, with a ready-to-send
message, to n8n, Slack or WhatsApp ([docs/n8n-whatsapp.md](docs/n8n-whatsapp.md)).
Details, the HTTP contract and every setting: [docs/package.md](docs/package.md).

## Architecture

All code is one Python package, `backend/fixonce` (`pip install ./backend`):

- `fixonce/target.py`: the service being watched (HTTP or Python adapter); `redact.py` masks logs
- `fixonce/agents/`: four agents (triage, recall, fixer, scribe); `memory/`: Meko over MCP; Gemini in `llm.py`
- `fixonce/main.py` + `fixonce/web/index.html`: API and the page the on-call engineer uses
- `fixonce/demo/shop.py`: the demo shop simulation that can break three ways
- `fixonce/cli.py`: the `fixonce` command (`demo`, `serve`, `seed`, `check`)

## Slides and team

- Slides: _add link_
- Team: Vedansh Mathur, Vishal Verma, Vishesh Gupta

## Tests

```bash
cd backend && pip install -e ".[dev]" && python -m pytest -q
```
