"""The demo shop: each scenario still reads the same to triage, the same fix still clears it
(the seeded lessons depend on both), and every response says it is a simulation."""
import time

from fastapi.testclient import TestClient

import fixonce.demo.shop as shop_app
from fixonce.agents.triage import _rule_based

client = TestClient(shop_app.app)
SCENARIOS = {  # chaos kind -> (words in the triage signature, the right fix)
    "db_pool": ("DB connections run out", "pause_batch_job"),
    "bad_deploy": ("new deploy", "rollback_last_deploy"),
    "memory_leak": ("run out of memory", "restart_service"),
}


def test_each_scenario_triages_and_heals_with_its_fix():
    for kind, (words, fix) in SCENARIOS.items():
        client.post("/reset")
        assert client.post(f"/chaos/{kind}").json()["simulation"] is True
        time.sleep(0.5)  # the leak starts right at the 5% threshold and climbs from there
        m = client.get("/metrics").json()
        assert m["simulation"] is True and m["error_rate"] > 0.05, kind
        logs = client.get("/logs").json()["lines"]
        assert words in _rule_based(logs, m, client.get("/deploys").json())["signature"], kind
        assert client.post(f"/actions/{fix}").json()["simulation"] is True
        assert client.get("/metrics").json()["error_rate"] < 0.05, kind


def test_healthy_shop_logs_traffic_without_symptoms():
    client.post("/reset")
    shop_app.STATE["last_tick"] -= 10  # ten simulated seconds of traffic
    lines = client.get("/logs").json()["lines"]
    assert len(lines) >= 5 and not any(line["level"] == "WARN" for line in lines)
    assert _rule_based(lines, client.get("/metrics").json(), {})["signature"].endswith("unknown reason")


def test_inprocess_shop_client_for_one_container_deploys():
    import asyncio
    from fixonce.target import HttpTarget
    c = HttpTarget(base_url="inprocess")
    assert asyncio.run(c.metrics())["simulation"] is True
