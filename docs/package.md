# FixOnce as a package

## Why a package

Our mentor at hackCBS liked the idea but pointed out that most companies are not comfortable
sending production incidents (logs, metrics, what broke and how) to a third-party app. So FixOnce
ships as a pip package. A company installs it and runs it inside its own infrastructure, next to the
service it watches. There is no FixOnce server and no telemetry. Data leaves the process only for:

1. **Their own Meko datapack**, with their own key. This is the memory. With Meko switched off,
   nothing is stored anywhere.
2. **Their own LLM key** (Gemini), if they set one. Without a key, the four agents use built-in
   rules and nothing goes to an LLM.

Before either of those, log lines are redacted in-process: emails, IPs, secrets (`token=`,
`password=`, `Bearer ...`), card and phone numbers. `FIXONCE_REDACT=false` turns this off.

The page proves it live: the **What left this machine** panel (`GET /api/egress`) lists every
request sent to Meko and to the LLM (task, size, result), how many emails, IPs and secrets were
masked, and the last masked log line. With no keys it says "nothing sent" for both.

Meko itself is a hosted service. A company that cannot use any external store can run FixOnce with
Meko off; it still triages and proposes a safe fix, but it does not learn. That trade-off is the
product's point, and the page shows which mode is running.

## Install

```bash
pip install "fixonce[gemini] @ git+https://github.com/visheshgupta0404/FixOnce.git#subdirectory=backend"
# or from a clone:  pip install "./backend[gemini]"
```

The `[gemini]` extra installs the Gemini client. Leave it out if you will not use an LLM.

## Three ways to run it

| Command | What it does |
| --- | --- |
| `fixonce demo` | Page, agents and the demo shop simulation in one process (what judges see) |
| `fixonce serve --target http://svc:9000` | Watch your own HTTP service |
| `fixonce serve --target pkg.module:Obj` | Watch through a Python adapter (a class is created with no arguments) |
| `fixonce seed` | Write the seeded demo history into your Meko datapack (demo only, once) |
| `fixonce check` | Call every Meko tool FixOnce uses against your datapack, and print the result |

Every command reads settings from the environment, or from `.env` in the current folder
(`--env-file` to change it). `fixonce serve` sets `FIXONCE_DEMO=false`. That hides the chaos buttons
and does not seed demo lessons.

From Python, `fixonce.create_app(target=..., actions=..., rules=...)` returns the FastAPI app (API
and page). Run it with any ASGI server. `fixonce.configure(...)` takes the same arguments without
building the app.

## The target contract

### HTTP

The service, or a small sidecar in front of it, serves:

| Endpoint | Returns |
| --- | --- |
| `GET /metrics` | `{"service": "payments", "version": "v3.2", "error_rate": 0.0-1.0, ...}` |
| `GET /logs?limit=N` | `{"lines": [{"level": "ERROR", "msg": "..."}]}`, newest last |
| `GET /deploys` | `{"current": "v3.2", "previous": "v3.1"}` |
| `POST /actions/{name}` | runs one safe action; any JSON back |

This works from any language. A Node or Go service exposes these four routes and runs
`fixonce serve` beside it. That is why we did not build a separate npm package: the agents are
Python, and the HTTP contract is the cross-language interface.

### Python

Pass any object with the same four async methods: `metrics()`, `logs(limit)`, `deploys()`,
`run_action(name)`. It may also carry:
- `actions`: `{name: plain-words label}`. This is the catalog. The fixer only ever proposes a name
  from it, and a human taps Apply before `run_action` is called.
- `rules`: team rules that block an action, e.g.
  `{"id": "no-restart-in-sale", "text": "...", "action": "restart_service", "service": "checkout", "when": "sale_mode"}`.
  A rule blocks when `metrics()[when]` is truthy, or always when `when == "always"`.
- `simulation`: `True` only for a demo target.

A complete example to copy is `examples/payments_target.py`: a payments service with its own three
actions and a settlement-window rule. Run it with `fixonce serve --target examples.payments_target:Payments`
from the repo root. The tests use a similar `PaymentsTarget` (`backend/tests/test_package.py`).

## Settings

| Variable | Default | Meaning |
| --- | --- | --- |
| `MEKO_API_KEY`, `MEKO_DATAPACK_ID` | empty | Your Meko key and the product datapack. Empty key = offline stand-in (dev only) |
| `MEKO_ENABLED` | `true` | Start with memory on (the page has the switch) |
| `GEMINI_API_KEY`, `GEMINI_MODEL` | empty, `gemini-3.8-flash` | LLM. Empty key = built-in rules, nothing sent |
| `TARGET_URL` (or `SHOP_URL`) | `http://localhost:8001` | HTTP target; `inprocess` = the demo shop inside this process |
| `FIXONCE_DEMO` | `true` (`false` under `serve`) | Demo simulation: chaos buttons, seeded history offline |
| `FIXONCE_REDACT` | `true` | Mask personal data and secrets in logs before agents see them |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | empty | Telegram alerts for every incident step, sent from this process. See `docs/telegram.md` |
| `FIXONCE_WEBHOOK_URL`, `FIXONCE_WEBHOOK_SECRET` | empty | POST every incident step as JSON (signed when a secret is set) to Slack, email or a pager |
| `FIXONCE_PUBLIC_URL` | `http://localhost:8000` | The link put in alerts |
| `ERROR_THRESHOLD`, `WATCH_INTERVAL_SECONDS`, `CHECK_SECONDS`, `MAX_FIX_ATTEMPTS` | `0.05`, `3`, `8`, `3` | When to open an incident, how often to look, how long to check a fix, and how many tries before escalating |

## Not done yet

- Not on PyPI yet; install from Git. The name `fixonce` still has to be claimed on PyPI.
- Incidents are kept in memory per process (`store.py`); lessons live in Meko, so a restart loses
  only open incidents.
- One target per process. Run one `fixonce serve` per service.
