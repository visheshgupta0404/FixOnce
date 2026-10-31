"""Triage agent: turns raw metrics + logs into a reusable incident signature."""
from __future__ import annotations

from ..llm import llm, obj
from ..models import Incident

SCHEMA = obj({
    "signature": {"type": "string", "description": "One plain-English line describing the failure pattern, reusable to match future incidents. No ids, times or numbers that change."},
    "summary": {"type": "string", "description": "One or two short sentences for a junior engineer on call."},
})


def _rule_based(logs: list[dict], metrics: dict, deploys: dict) -> dict:
    text = " ".join(line["msg"] for line in logs).lower()
    svc = metrics.get("service", "service")
    pct = round(metrics.get("error_rate", 0) * 100)
    if "queuepool" in text or "db timeout" in text or "too many clients" in text:
        sig = f"{svc} returns 503s because DB connections run out and requests time out waiting for a connection"
    elif "typeerror" in text or "deploy" in text and "error" in text:
        sig = f"{svc} errors right after a new deploy: TypeError in cart total"
    elif "oomkilled" in text or "rss=" in text:
        sig = f"{svc} workers run out of memory and get OOMKilled, errors climb over time"
    else:
        sig = f"{svc} error rate is high for an unknown reason"
    return {"signature": sig, "summary": f"{svc} is failing for about {pct}% of requests. {sig[0].upper() + sig[1:]}."}


async def triage(incident: Incident, metrics: dict, logs: list[dict], deploys: dict) -> dict:
    lines = "\n".join(f"{l['level']} {l['msg']}" for l in logs[-15:])
    prompt = (
        "You are the triage agent for an on-call team. Describe this incident.\n"
        f"Service: {incident.service}\nVersion: {metrics.get('version')}\n"
        f"Metrics: error_rate={metrics.get('error_rate')}, p95_latency_ms={metrics.get('p95_latency_ms')}\n"
        f"Deploys: current={deploys.get('current')}, previous={deploys.get('previous')}\n"
        f"Recent logs:\n{lines}\n"
    )
    return await llm.json("triage", prompt, SCHEMA, lambda: _rule_based(logs, metrics, deploys))
