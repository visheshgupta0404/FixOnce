"""Demo shop: a small, honest SIMULATION of a checkout service that can break.

It exists so FixOnce has something real to watch and fix during the demo.
Every chaos button is labelled as a simulation in the UI (requirement A5).

Scenarios
  db_pool      A nightly export job holds most DB connections. Checkout times out.
               Correct fix: pause_batch_job.
               raise_pool_size / scale_up hit the DB connection cap -> worse.
               restart_service causes a reconnect storm -> worse for a while.
  bad_deploy   Version v1.7 ships a bug. Correct fix: rollback_last_deploy.
  memory_leak  Memory grows until requests fail. Correct fix: restart_service.
"""
import os
import random
import time

from fastapi import FastAPI, HTTPException

STORM_SECONDS = float(os.getenv("STORM_SECONDS", "20"))

app = FastAPI(title="FixOnce demo shop (simulation)")

SAFE_ACTIONS = ["pause_batch_job", "raise_pool_size", "scale_up", "rollback_last_deploy", "restart_service"]


def _fresh_state() -> dict:
    return {
        "service": "checkout",
        "version": "v1.6",
        "previous_version": "v1.5",
        "pool_size": 20,
        "replicas": 2,
        "batch_job_running": False,
        "bad_deploy": False,
        "leak_started": None,
        "storm_until": 0.0,
        "overloaded": False,
        "sale_mode": False,
        "logs": [],
    }


STATE = _fresh_state()


def _log(level: str, msg: str) -> None:
    STATE["logs"].append({"t": round(time.time(), 1), "level": level, "msg": msg})
    STATE["logs"] = STATE["logs"][-60:]


def error_rate() -> float:
    s = STATE
    now = time.time()
    rate = 0.003
    if s["batch_job_running"]:
        rate = 0.45 if s["overloaded"] else 0.22
    if s["bad_deploy"]:
        rate = max(rate, 0.30)
    if s["leak_started"]:
        rate = max(rate, min(0.6, 0.05 + (now - s["leak_started"]) * 0.01))
    if now < s["storm_until"]:
        rate = max(rate, 0.6)
    return round(rate, 3)


def _emit_symptom_logs() -> None:
    s = STATE
    if s["batch_job_running"]:
        _log("INFO", "export-job nightly_orders_export running, batch 41/90")
        if s["overloaded"]:
            _log("ERROR", "psycopg OperationalError: FATAL: sorry, too many clients already")
        _log("WARN", f"sqlalchemy.pool QueuePool limit of size {s['pool_size']} overflow 0 reached, connection timed out, timeout 30.00")
        _log("ERROR", "checkout POST /api/checkout 503 upstream db timeout")
    if s["bad_deploy"]:
        _log("ERROR", f"checkout {s['version']} TypeError: cannot read 'currency' of undefined in cart.total")
    if s["leak_started"]:
        _log("WARN", "checkout worker rss=1.8GB, gc pause 900ms")
        _log("ERROR", "checkout worker killed: OOMKilled")
    if time.time() < s["storm_until"]:
        _log("ERROR", "db: connection storm, 400 new connections in 5s")


@app.get("/health")
def health():
    return {"ok": True, "simulation": True}


@app.get("/metrics")
def metrics():
    _emit_symptom_logs()
    rate = error_rate()
    return {
        "service": STATE["service"],
        "version": STATE["version"],
        "error_rate": rate,
        "p95_latency_ms": int(180 + rate * 4000 + random.randint(0, 40)),
        "pool_size": STATE["pool_size"],
        "replicas": STATE["replicas"],
        "sale_mode": STATE["sale_mode"],
        "simulation": True,
    }


@app.get("/logs")
def logs(limit: int = 20):
    return {"service": STATE["service"], "lines": STATE["logs"][-limit:], "simulation": True}


@app.get("/deploys")
def deploys():
    return {"service": STATE["service"], "current": STATE["version"], "previous": STATE["previous_version"]}


@app.post("/chaos/{kind}")
def chaos(kind: str):
    if kind == "db_pool":
        STATE["batch_job_running"] = True
        _log("INFO", "export-job nightly_orders_export started")
    elif kind == "bad_deploy":
        STATE["previous_version"], STATE["version"] = STATE["version"], "v1.7"
        STATE["bad_deploy"] = True
        _log("INFO", "deploy checkout v1.7 finished")
    elif kind == "memory_leak":
        STATE["leak_started"] = time.time()
    elif kind == "sale_on":
        STATE["sale_mode"] = True
    elif kind == "sale_off":
        STATE["sale_mode"] = False
    else:
        raise HTTPException(404, f"unknown chaos kind {kind}")
    return {"ok": True, "kind": kind, "simulation": True}


@app.post("/actions/{name}")
def action(name: str):
    if name not in SAFE_ACTIONS:
        raise HTTPException(400, f"{name} is not on the safe list")
    s = STATE
    if name == "pause_batch_job":
        s["batch_job_running"] = False
        s["overloaded"] = False
        result = "export job paused"
    elif name == "raise_pool_size":
        s["pool_size"] = 50
        if s["batch_job_running"]:
            s["overloaded"] = True  # DB max_connections hit
        result = "pool size 20 -> 50"
    elif name == "scale_up":
        s["replicas"] += 2
        if s["batch_job_running"]:
            s["overloaded"] = True
        result = f"replicas -> {s['replicas']}"
    elif name == "rollback_last_deploy":
        s["version"], s["previous_version"] = s["previous_version"], s["version"]
        s["bad_deploy"] = False
        result = f"rolled back to {s['version']}"
    else:  # restart_service
        s["leak_started"] = None
        if s["batch_job_running"]:
            s["storm_until"] = time.time() + STORM_SECONDS
        result = "service restarted"
    _log("INFO", f"action {name}: {result}")
    return {"ok": True, "action": name, "result": result}


@app.post("/reset")
def reset():
    STATE.clear()
    STATE.update(_fresh_state())
    return {"ok": True}
