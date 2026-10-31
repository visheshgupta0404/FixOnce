"""Example: plugging FixOnce into your own service with a Python adapter (no HTTP needed).

    pip install "fixonce[gemini] @ git+https://github.com/visheshgupta0404/FixOnce.git#subdirectory=backend"
    fixonce serve --target examples.payments_target:Payments      # run from the repo root

This "payments" service is a tiny SIMULATION so the example runs anywhere: its payout queue gets
stuck 20 seconds after start (and again a minute after every fix). In your company, each method
would call your real metrics, log store, deploy tool and runbook automation instead.
"""
from __future__ import annotations

import random
import time


class Payments:
    # The only actions FixOnce may ever propose for this service, in plain words for the on-call.
    actions = {
        "drain_queue": "Drain the stuck payout queue",
        "flush_rates_cache": "Flush the currency rates cache",
        "restart_workers": "Restart the payout workers",
    }
    # Team rule: never restart payout workers during the bank settlement window.
    rules = [{"id": "no-restart-in-settlement", "action": "restart_workers", "service": "payments",
              "when": "settlement_window",
              "text": "Team rule: never restart payout workers during the bank settlement window."}]
    simulation = True  # shown as a simulation on the page; set False for a real service

    def __init__(self):
        self.stuck_at = time.time() + 20

    def _stuck(self) -> bool:
        return time.time() >= self.stuck_at

    async def metrics(self) -> dict:
        return {"service": "payments", "version": "v3.2", "error_rate": 0.32 if self._stuck() else 0.01,
                "settlement_window": False}

    async def logs(self, limit: int = 20) -> list[dict]:
        if not self._stuck():
            return [{"level": "INFO", "msg": "payout batch settled"}]
        n = random.randint(1000, 9999)
        return [{"level": "ERROR",
                 "msg": f"payout {n} timed out waiting on queue payouts-high (depth 18000) for "
                        f"user{n}@bank.example from 10.8.{n % 250}.7 Bearer tok_{n}abc"}] * min(limit, 5)

    async def deploys(self) -> dict:
        return {"current": "v3.2", "previous": "v3.1"}

    async def run_action(self, name: str) -> dict:
        if name == "drain_queue":
            self.stuck_at = time.time() + 60
        return {"ok": True, "action": name}
