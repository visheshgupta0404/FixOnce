"""Incident store. In-memory for now.

Teammate B: swap this for YugabyteDB (YSQL, port 5433) by keeping the same four methods.
"""
from __future__ import annotations

from .models import Incident


class IncidentStore:
    def __init__(self):
        self._items: dict[str, Incident] = {}

    def save(self, inc: Incident) -> Incident:
        self._items[inc.id] = inc
        return inc

    def get(self, incident_id: str) -> Incident | None:
        return self._items.get(incident_id)

    def all(self) -> list[Incident]:
        return sorted(self._items.values(), key=lambda i: i.opened_at, reverse=True)

    def active(self, service: str) -> Incident | None:
        for inc in self.all():
            if inc.service == service and inc.status not in ("resolved", "escalated"):
                return inc
        return None

    def clear(self) -> None:
        self._items.clear()


store = IncidentStore()
