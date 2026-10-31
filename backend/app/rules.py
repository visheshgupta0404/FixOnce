"""Team rules = guardrails. The source of truth is this list; the seed script also writes
each rule into Meko and promotes it, so every agent and teammate can recall it."""
from __future__ import annotations

RULES = [
    {
        "id": "rule-no-restart-during-sale",
        "text": "Team rule: never restart the checkout service while a sale is running. Escalate to a senior instead.",
        "action": "restart_service",
        "service": "checkout",
        "when": "sale_mode",
    },
]


def blocking_rule(action: str, service: str, metrics: dict) -> dict | None:
    for rule in RULES:
        if rule["action"] != action or rule["service"] != service:
            continue
        if rule["when"] == "always" or metrics.get(rule["when"]):
            return rule
    return None
