"""HTTP client for the demo shop (metrics, logs, deploys, safe actions, chaos)."""
from __future__ import annotations

import httpx

from .config import settings


class ShopClient:
    def __init__(self, base_url: str | None = None, transport: httpx.AsyncBaseTransport | None = None):
        self.base_url = base_url or settings.shop_url
        self.transport = transport  # tests pass an ASGI transport

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

    async def chaos(self, kind: str) -> dict:
        return await self._post(f"/chaos/{kind}")

    async def reset(self) -> dict:
        return await self._post("/reset")


shop = ShopClient()
