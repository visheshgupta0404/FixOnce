"""The service FixOnce watches and fixes: the "target".

FixOnce needs four things from a service, so it can run inside any company's own infrastructure:
- an HTTP service (any language) that serves GET /metrics, GET /logs?limit=N, GET /deploys and
  POST /actions/{name}: use HttpTarget(url), or
- a Python object with the same four async methods (see Target), passed to fixonce.configure().

The demo shop is one HTTP target (SHOP_URL / TARGET_URL; "inprocess" runs it inside this process).
Log lines are redacted (redact.py) before any agent sees them, so they never reach the LLM or Meko raw.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

import httpx

from .config import settings
from .redact import redact_logs


@runtime_checkable
class Target(Protocol):
    async def metrics(self) -> dict:
        """{"service": str, "version": str, "error_rate": 0..1, ...anything else you want the agents to see}"""

    async def logs(self, limit: int = 20) -> list[dict]:
        """Newest last: [{"level": "ERROR", "msg": "..."}]"""

    async def deploys(self) -> dict:
        """{"current": "v1.7", "previous": "v1.6"}"""

    async def run_action(self, name: str) -> dict:
        """Run one safe action by name (only names from the action catalog are ever passed)."""


class HttpTarget:
    """Any service that serves the four endpoints above. The demo shop adds /chaos and /reset."""

    def __init__(self, base_url: str | None = None, transport: httpx.AsyncBaseTransport | None = None,
                 simulation: bool | None = None):
        self.base_url = base_url or settings.target_url
        self.transport = transport  # tests pass an ASGI transport
        self.simulation = settings.demo if simulation is None else simulation
        if self.base_url == "inprocess":  # one-container deploys and `fixonce demo`: the shop runs in this process
            from .demo.shop import app as shop_app
            self.base_url, self.transport = "http://shop", httpx.ASGITransport(app=shop_app)

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(base_url=self.base_url, transport=self.transport, timeout=10)

    async def _get(self, path: str) -> dict:
        async with self._client() as c:
            r = await c.get(path)
            r.raise_for_status()
            return r.json()

    async def _post(self, path: str) -> dict:
        async with self._client() as c:
            r = await c.post(path)
            r.raise_for_status()
            return r.json()

    async def metrics(self) -> dict:
        return await self._get("/metrics")

    async def logs(self, limit: int = 20) -> list[dict]:
        return (await self._get(f"/logs?limit={limit}"))["lines"]

    async def deploys(self) -> dict:
        return await self._get("/deploys")

    async def run_action(self, name: str) -> dict:
        return await self._post(f"/actions/{name}")

    # demo shop only (labelled simulation)
    async def chaos(self, kind: str) -> dict:
        return await self._post(f"/chaos/{kind}")

    async def reset(self) -> dict:
        return await self._post("/reset")


class CurrentTarget:
    """The one target this process watches. `use()` swaps it (CLI, embedding apps, tests).
    Every read of logs goes through redaction here, whatever the target is."""

    def __init__(self):
        self._t: object | None = None

    def use(self, t: object) -> object:
        self._t = t
        return t

    @property
    def current(self) -> object:
        if self._t is None:
            self._t = HttpTarget()
        return self._t

    @property
    def simulation(self) -> bool:
        return bool(getattr(self.current, "simulation", False))

    def supports(self, name: str) -> bool:
        return callable(getattr(self.current, name, None))

    async def logs(self, limit: int = 20) -> list[dict]:
        lines = await self.current.logs(limit)
        return redact_logs(lines) if settings.redact else lines

    def __getattr__(self, name: str):
        return getattr(self.current, name)


target = CurrentTarget()
