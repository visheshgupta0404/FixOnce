"""Demo shop: a small, honest SIMULATION of a checkout service that can break.

It exists so FixOnce has something real to watch and fix during the demo.
Every chaos button is labelled as a simulation in the UI (requirement A5), and every
response from this service carries "simulation": true.

Scenarios
  db_pool      A nightly export job holds most DB connections. Checkout times out.
               Correct fix: pause_batch_job.
               raise_pool_size / scale_up hit the DB connection cap -> worse.
               restart_service causes a reconnect storm -> worse for a while.
  bad_deploy   Version v1.7 ships a bug. Correct fix: rollback_last_deploy.
  memory_leak  Memory grows until requests fail. Correct fix: restart_service.

Traffic is simulated by the clock, not by how often /metrics is polled: each call to
/metrics or /logs "replays" the requests since the last call and logs a sample of them.
"""
import os
import random
import time
import uuid

from fastapi import FastAPI, HTTPException

STORM_SECONDS = float(os.getenv("STORM_SECONDS", "20"))
REQUESTS_PER_S = 40          # simulated checkout traffic
SAMPLE_LINES_PER_S = 1.5     # how many access log lines per second we keep
SYMPTOM_EVERY_S = 2.0        # a given symptom line is logged at most this often
EXPORT_BATCHES = 90
EXPORT_POD = "orders-export-28841720-k7x2p"

app = FastAPI(title="FixOnce demo shop (simulation)")

SAFE_ACTIONS = ["pause_batch_job", "raise_pool_size", "scale_up", "rollback_last_deploy", "restart_service"]
ROUTES = [("POST", "/api/checkout", 140), ("GET", "/api/cart", 35), ("GET", "/api/products", 25),
          ("POST", "/api/cart/items", 45)]


def _pods(n: int) -> list[str]:
    return [f"checkout-7d9f6-{random.choice('bcdfghjkmnpqrstvwxz')}{random.randint(10, 99)}{c}" for c in "abcdefgh"[:n]]


def _fresh_state() -> dict:
    now = time.time()
    return {
        "service": "checkout",
        "version": "v1.6",
        "previous_version": "v1.5",
        "pool_size": 20,
        "replicas": 2,
        "pods": _pods(2),
        "batch_job_running": False,
        "batch_started": None,
        "bad_deploy": False,
        "leak_started": None,
        "storm_until": 0.0,
        "overloaded": False,
        "sale_mode": False,
        "last_tick": now,
        "last_symptom": {},
        "requests_total": 0,
        "errors_total": 0,
        "logs": [],
    }


STATE = _fresh_state()


def _log(level: str, msg: str, pod: str | None = None) -> None:
    pod = pod or random.choice(STATE["pods"])
    STATE["logs"].append({"t": round(time.time(), 1), "level": level, "pod": pod, "msg": msg})
    STATE["logs"] = STATE["logs"][-80:]


def _symptom(key: str, level: str, msg: str, pod: str | None = None) -> None:
    """Log a symptom line, but not more often than SYMPTOM_EVERY_S, so polling does not spam."""
    now = time.time()
    if now - STATE["last_symptom"].get(key, 0) >= SYMPTOM_EVERY_S:
        STATE["last_symptom"][key] = now
        _log(level, msg, pod)


def _base_rate() -> float:
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
    return rate


def error_rate() -> float:
    """The scenario's error rate with a little noise, as a real 1-minute window would have.
    The noise leans up so a scenario that is just over the alert threshold stays over it."""
    return round(_base_rate() * random.uniform(0.96, 1.1), 3)


def _rss_mb() -> int:
    if not STATE["leak_started"]:
        return 410 + random.randint(0, 30)
    return min(1990, int(1150 + (time.time() - STATE["leak_started"]) * 30))  # OOM at ~2GiB


def _failure(route: str) -> tuple[int, int, str]:
    """Status, latency and reason for a failed request in the current scenario."""
    s = STATE
    if time.time() < s["storm_until"]:
        return 503, random.randint(2000, 5000), "db connect refused during reconnect storm"
    if s["batch_job_running"]:
        return 503, 30000 + random.randint(0, 40), "upstream db timeout waiting for a pool connection"
    if s["bad_deploy"] and route == "/api/checkout":
        return 500, random.randint(8, 20), "TypeError in cart.total"
    if s["leak_started"]:
        return 502, random.randint(900, 2500), "worker restarted mid-request"
    return 500, random.randint(10, 40), "internal error"


def _latency_ms(base: int) -> int:
    s = STATE
    ms = base * random.uniform(0.7, 1.6)
    if s["batch_job_running"]:
        ms += random.randint(800, 4000)  # waiting in the pool queue
    if s["leak_started"]:
        ms += min(2000, (time.time() - s["leak_started"]) * 25)  # gc pauses
    return int(ms)


def _tick() -> None:
    """Replay simulated traffic since the last call: counters, a sample of access logs, symptoms."""
    s = STATE
    now = time.time()
    elapsed = min(30.0, now - s["last_tick"])
    s["last_tick"] = now
    rate = _base_rate()
    n = int(elapsed * REQUESTS_PER_S)
    s["requests_total"] += n
    s["errors_total"] += int(n * rate)

    for _ in range(min(6, int(elapsed * SAMPLE_LINES_PER_S + random.random()))):
        method, route, base = random.choice(ROUTES)
        req = uuid.uuid4().hex[:8]
        if random.random() < rate:
            status, ms, why = _failure(route)
            _log("ERROR", f"{method} {route} {status} {ms}ms req={req} {why}")
        else:
            _log("INFO", f"{method} {route} 200 {_latency_ms(base)}ms req={req}")

    if s["batch_job_running"]:
        batch = min(EXPORT_BATCHES, 41 + int((now - s["batch_started"]) / 6))
        _symptom("export", "INFO", f"export-job nightly_orders_export running, batch {batch}/{EXPORT_BATCHES}, "
                                   f"holding 16 DB connections", EXPORT_POD)
        _symptom("pool", "WARN", f"sqlalchemy.pool QueuePool limit of size {s['pool_size']} overflow 0 reached, "
                                 "connection timed out, timeout 30.00")
        if s["overloaded"]:
            _symptom("toomany", "ERROR", "psycopg OperationalError: FATAL: sorry, too many clients already "
                                         "(postgres max_connections=100)")
        _symptom("503", "ERROR", "checkout POST /api/checkout 503 upstream db timeout")
    if s["bad_deploy"]:
        _symptom("typeerror", "ERROR", f"checkout {s['version']} TypeError: cannot read 'currency' of undefined "
                                       "in cart.total (cart.py:88)")
    if s["leak_started"]:
        rss = _rss_mb()
        _symptom("rss", "WARN", f"checkout worker rss={rss / 1000:.1f}GB, gc pause {random.randint(600, 1200)}ms")
        if rss > 1500:
            _symptom("oom", "ERROR", "checkout worker killed: OOMKilled (limit 2GiB), restarting")
    if now < s["storm_until"]:
        _symptom("storm", "ERROR", f"db: connection storm, {random.randint(350, 450)} new connections in 5s")


@app.get("/health")
def health():
    return {"ok": True, "simulation": True}


@app.get("/metrics")
def metrics():
    _tick()
    rate = error_rate()
    s = STATE
    if s["batch_job_running"] and rate > 0.05:
        p95 = 30000 + random.randint(0, 60)          # the slowest 5% wait out the 30s pool timeout
    elif time.time() < s["storm_until"]:
        p95 = random.randint(4000, 5200)
    elif s["leak_started"]:
        p95 = int(260 + min(2400, (time.time() - s["leak_started"]) * 30) + random.randint(0, 60))
    else:
        p95 = 210 + random.randint(0, 50)            # a bad deploy fails fast
    return {
        "service": s["service"],
        "version": s["version"],
        "error_rate": rate,
        "p95_latency_ms": p95,
        "requests_per_min": int(REQUESTS_PER_S * 60 * random.uniform(0.95, 1.05)),
        "pool_size": s["pool_size"],
        "db_connections_in_use": min(100, s["pool_size"] * s["replicas"] // 2
                                     + (16 if s["batch_job_running"] else 0)
                                     + (60 if s["overloaded"] else 0)),
        "replicas": s["replicas"],
        "memory_rss_mb": _rss_mb(),
        "sale_mode": s["sale_mode"],
        "simulation": True,
    }


@app.get("/logs")
def logs(limit: int = 20):
    _tick()
    return {"service": STATE["service"], "lines": STATE["logs"][-limit:], "simulation": True}


@app.get("/deploys")
def deploys():
    return {"service": STATE["service"], "current": STATE["version"], "previous": STATE["previous_version"],
            "simulation": True}


@app.post("/chaos/{kind}")
def chaos(kind: str):
    s = STATE
    if kind == "db_pool":
        s["batch_job_running"] = True
        s["batch_started"] = time.time()
        _log("INFO", "export-job nightly_orders_export started (90 batches, 16 workers)", EXPORT_POD)
    elif kind == "bad_deploy":
        s["previous_version"], s["version"] = s["version"], "v1.7"
        s["bad_deploy"] = True
        s["pods"] = _pods(s["replicas"])
        _log("INFO", f"deploy checkout v1.7 finished: {s['replicas']}/{s['replicas']} pods ready")
    elif kind == "memory_leak":
        s["leak_started"] = time.time()
    elif kind == "sale_on":
        s["sale_mode"] = True
        _log("INFO", "flash sale started: traffic expected x3")
    elif kind == "sale_off":
        s["sale_mode"] = False
        _log("INFO", "flash sale ended")
    else:
        raise HTTPException(404, f"unknown chaos kind {kind} (simulation)")
    return {"ok": True, "kind": kind, "simulation": True,
            "note": "Simulated failure in the demo shop. No real system was touched."}


@app.post("/actions/{name}")
def action(name: str):
    if name not in SAFE_ACTIONS:
        raise HTTPException(400, f"{name} is not on the safe list")
    s = STATE
    if name == "pause_batch_job":
        s["batch_job_running"] = False
        s["overloaded"] = False
        result = "export job paused"
        _log("INFO", "export-job nightly_orders_export paused, 16 DB connections released", EXPORT_POD)
    elif name == "raise_pool_size":
        old = s["pool_size"]
        s["pool_size"] = 50
        if s["batch_job_running"]:
            s["overloaded"] = True  # DB max_connections hit
        result = f"pool size {old} -> 50"
        _log("INFO", f"config checkout DB_POOL_SIZE {old} -> 50, rolling reload")
    elif name == "scale_up":
        s["replicas"] += 2
        s["pods"] = s["pods"] + _pods(2)
        if s["batch_job_running"]:
            s["overloaded"] = True
        result = f"replicas -> {s['replicas']}"
        _log("INFO", f"scaled checkout to {s['replicas']} replicas, each opening {s['pool_size']} DB connections")
    elif name == "rollback_last_deploy":
        s["version"], s["previous_version"] = s["previous_version"], s["version"]
        s["bad_deploy"] = False
        s["pods"] = _pods(s["replicas"])
        result = f"rolled back to {s['version']}"
        _log("INFO", f"rollback checkout to {s['version']}: {s['replicas']}/{s['replicas']} pods ready")
    else:  # restart_service
        s["leak_started"] = None
        s["pods"] = _pods(s["replicas"])
        if s["batch_job_running"]:
            s["storm_until"] = time.time() + STORM_SECONDS
        result = "service restarted"
        _log("INFO", f"rolling restart checkout: {s['replicas']}/{s['replicas']} pods ready")
    _log("INFO", f"action {name}: {result}")
    return {"ok": True, "action": name, "result": result, "simulation": True}


@app.post("/reset")
def reset():
    STATE.clear()
    STATE.update(_fresh_state())
    return {"ok": True, "simulation": True}
