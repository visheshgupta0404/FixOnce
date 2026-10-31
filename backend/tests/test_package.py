"""FixOnce as a package: a company plugs in its own service and actions, and logs are redacted
before any agent, the LLM or Meko sees them."""
import asyncio
import os

os.environ.update({"MEKO_MODE": "fake", "LLM_MODE": "fake", "CHECK_SECONDS": "0.3",
                   "STORM_SECONDS": "5", "WATCH_INTERVAL_SECONDS": "0"})

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import fixonce  # noqa: E402
from fixonce import cli  # noqa: E402
from fixonce.memory import memory  # noqa: E402
from fixonce.memory.backends import FakeMeko  # noqa: E402
from fixonce.models import ACTION_LABELS, SAFE_ACTIONS  # noqa: E402
from fixonce.orchestrator import orchestrator  # noqa: E402
from fixonce.redact import redact  # noqa: E402
from fixonce.rules import RULES  # noqa: E402
from fixonce.store import store  # noqa: E402
from fixonce.target import Target, target  # noqa: E402


class PaymentsTarget:
    """What a company writes: four async methods over its own service. No HTTP needed."""
    actions = {"drain_queue": "Drain the stuck payout queue", "flush_cache": "Flush the rates cache"}
    simulation = False

    def __init__(self):
        self.ran: list[str] = []
        self.broken = True

    async def metrics(self):
        return {"service": "payments", "version": "v3.2", "error_rate": 0.4 if self.broken else 0.0}

    async def logs(self, limit=20):
        return [{"level": "ERROR", "msg": "payout failed for asha@example.com from 10.2.3.4 token=sk_live_abc123"}]

    async def deploys(self):
        return {"current": "v3.2", "previous": "v3.1"}

    async def run_action(self, name):
        self.ran.append(name)
        if name == "drain_queue":
            self.broken = False
        return {"ok": True}


@pytest.fixture
def payments():
    saved = (target._t, dict(ACTION_LABELS), list(SAFE_ACTIONS), list(RULES))
    memory.backend = FakeMeko()
    memory.enabled = False
    store.clear()
    orchestrator.armed = True
    t = PaymentsTarget()
    fixonce.configure(target=t, rules=[])
    yield t
    target._t = saved[0]
    ACTION_LABELS.clear()
    ACTION_LABELS.update(saved[1])
    SAFE_ACTIONS[:] = saved[2]
    RULES[:] = saved[3]
    memory.enabled = True


def test_own_target_and_actions_run_end_to_end(payments):
    assert isinstance(payments, Target)
    assert SAFE_ACTIONS == ["drain_queue", "flush_cache"]  # the target's catalog replaced the demo one

    async def run():
        inc = await orchestrator.watch_once()
        assert inc is not None and inc.service == "payments" and inc.simulation is False
        while inc.status == "waiting_human":
            assert inc.proposed_action in payments.actions  # never an action outside the catalog
            await orchestrator.decide(inc.id, "apply")
        return inc

    inc = asyncio.run(run())
    assert payments.ran[-1] == "drain_queue"
    assert inc.status == "resolved"


def test_logs_are_redacted_before_agents_see_them(payments):
    msg = asyncio.run(target.logs(5))[0]["msg"]
    assert "asha@example.com" not in msg and "10.2.3.4" not in msg and "sk_live_abc123" not in msg
    assert msg == "payout failed for <email> from <ip> token=<secret>"


def test_redact_keeps_the_words_triage_needs():
    line = "GET /checkout 503 2400ms req=9f2c QueuePool limit reached, db timeout; card 4111 1111 1111 1111"
    out = redact(line)
    assert "QueuePool" in out and "db timeout" in out and "503 2400ms" in out
    assert "4111" not in out


def test_app_without_the_demo_has_no_chaos_buttons(payments):
    client = TestClient(fixonce.create_app())
    st = client.get("/api/status").json()
    assert st["simulation"] is False
    assert st["actions"] == PaymentsTarget.actions
    assert client.post("/chaos/db_pool").status_code == 404
    assert "<title>" in client.get("/").text  # the page ships inside the package


def test_cli_loads_a_target_by_module_path():
    t = cli.load_target("tests.test_package:PaymentsTarget")
    assert isinstance(t, PaymentsTarget)


def test_egress_lists_only_meko_and_llm_and_shows_masking(payments):
    client = TestClient(fixonce.create_app())
    asyncio.run(target.logs(5))
    e = client.get("/api/egress").json()
    assert [d["name"] for d in e["destinations"]] == ["Meko", "Gemini"]
    assert all(d["host"] is None for d in e["destinations"])  # offline: nothing leaves at all
    assert e["redaction"]["masked"]["email"] >= 1 and "<email>" in e["redaction"]["last"]
