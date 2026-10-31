"""Outgoing webhook (n8n / Slack / WhatsApp): plain-words messages for each step, signed, never blocking."""
import asyncio
import hashlib
import hmac
import json
import os

os.environ.update({"MEKO_MODE": "fake", "LLM_MODE": "fake", "CHECK_SECONDS": "0.3",
                   "STORM_SECONDS": "5", "WATCH_INTERVAL_SECONDS": "0"})

import httpx  # noqa: E402
import pytest  # noqa: E402

import fixonce.demo.shop as shop_app  # noqa: E402
from fixonce.config import settings  # noqa: E402
from fixonce.memory import memory  # noqa: E402
from fixonce.memory.backends import FakeMeko  # noqa: E402
from fixonce.notify import notifier  # noqa: E402
from fixonce.orchestrator import orchestrator  # noqa: E402
from fixonce.seed import seed  # noqa: E402
from fixonce.store import store  # noqa: E402
from fixonce.target import HttpTarget, target  # noqa: E402

shop = target.use(HttpTarget("http://shop", transport=httpx.ASGITransport(app=shop_app.app), simulation=True))
sent: list[httpx.Request] = []


@pytest.fixture(autouse=True)
def hook():
    sent.clear()
    settings.webhook_url, settings.webhook_secret = "https://hooks.example/fixonce", "s3cret"
    notifier.transport = httpx.MockTransport(lambda req: sent.append(req) or httpx.Response(200))
    notifier.calls.clear()
    memory.backend = FakeMeko()
    store.clear()
    orchestrator.armed = True
    yield
    settings.webhook_url, settings.webhook_secret = "", ""
    notifier.transport = None
    memory.enabled = True


async def _run(meko_on: bool):
    await shop.reset()
    await seed()
    memory.enabled = meko_on
    await shop.chaos("db_pool")
    inc = await orchestrator.watch_once()
    while inc.status == "waiting_human":
        await orchestrator.decide(inc.id, "apply")
    await notifier.drain()
    return [json.loads(r.content) for r in sent]


def test_meko_on_sends_seen_before_then_fixed():
    events = asyncio.run(_run(True))
    assert [e["event"] for e in events] == ["incident.proposed", "incident.resolved"]
    assert events[0]["seen_before"] and "Seen before (team memory)" in events[0]["text"]
    assert "Raise the DB connection pool size" in events[0]["made_it_worse"]
    assert events[1]["text"].startswith("✅ checkout fixed in")
    sig = hmac.new(b"s3cret", sent[0].content, hashlib.sha256).hexdigest()
    assert sent[0].headers["X-FixOnce-Signature"] == f"sha256={sig}"
    assert [c["op"] for c in notifier.calls] == ["incident.proposed", "incident.resolved"]


def test_meko_off_says_it_is_guessing_then_escalates():
    events = asyncio.run(_run(False))
    assert events[0]["text"].count("guess") == 1
    assert events[-1]["event"] == "incident.escalated"
    assert len([e for e in events if e["event"] == "incident.proposed"]) == 3


def test_a_dead_receiver_does_not_break_the_incident():
    def down(req):
        raise httpx.ConnectError("refused")
    notifier.transport = httpx.MockTransport(down)
    asyncio.run(_run(True))
    assert store.all()[0].status == "resolved"
    assert notifier.calls and not notifier.calls[0]["ok"]
