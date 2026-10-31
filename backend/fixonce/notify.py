"""Outgoing webhook: every incident step is POSTed as JSON to FIXONCE_WEBHOOK_URL, so n8n, Slack,
WhatsApp, email or a pager can plug in without FixOnce knowing their tokens.

Events: incident.proposed (a fix is waiting for a human), incident.resolved, incident.escalated.
Each payload carries `text`, a ready-to-send message in plain words. With FIXONCE_WEBHOOK_SECRET set,
the body is signed: header X-FixOnce-Signature = "sha256=" + HMAC-SHA256(secret, body).
Sending never blocks or breaks the incident flow; every request shows in GET /api/egress.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import time

import httpx

from .config import settings
from .models import ACTION_LABELS, Incident

log = logging.getLogger("fixonce.notify")


def _label(action: str | None) -> str:
    return ACTION_LABELS.get(action or "", action or "")


def message(event: str, inc: Incident) -> str:
    r = inc.recall
    if event == "incident.resolved":
        fix = next((a.action for a in inc.attempts if a.result == "worked"), None)
        return (f"✅ {inc.service} fixed in {inc.time_to_fix_s}s with: {_label(fix)}. "
                + ("The lesson is saved to team memory." if inc.meko_enabled else "Team memory was OFF, so nothing was learned."))
    if event == "incident.escalated":
        tried = ", ".join(_label(a.action) for a in inc.attempts) or "nothing"
        return f"⚠️ {inc.service} handed to a senior. Tried: {tried}. {inc.timeline[-1]['what'] if inc.timeline else ''}".strip()
    lines = [f"🔴 {inc.service} is failing. {inc.summary}"]
    if r and not r.meko_enabled:
        lines.append("No team memory (Meko OFF): this suggestion is a guess.")
    elif r and r.match:
        seen = f"Seen before (team memory): {', '.join(_label(a) for a in r.worked)} fixed it."
        if r.failed:
            seen += f" Made it worse: {', '.join(_label(a) for a in r.failed)}."
        lines.append(seen)
    else:
        lines.append("New to us: no matching lesson in team memory.")
    tried = [a for a in inc.attempts if a.result == "failed"]
    if tried:
        lines.append(f"Already tried: {', '.join(_label(a.action) for a in tried)}.")
    lines.append(f"Suggested: {_label(inc.proposed_action)}. Open FixOnce to approve: {settings.public_url}")
    return "\n".join(lines)


def payload(event: str, inc: Incident) -> dict:
    r = inc.recall
    return {
        "event": event, "at": time.time(), "incident_id": inc.id, "service": inc.service,
        "version": inc.version, "status": inc.status, "summary": inc.summary, "meko_enabled": inc.meko_enabled,
        "seen_before": bool(r and r.match), "confidence": r.confidence if r else 0.0,
        "worked_before": [_label(a) for a in (r.worked if r else [])],
        "made_it_worse": [_label(a) for a in (r.failed if r else [])],
        "proposed_action": inc.proposed_action, "proposed_label": _label(inc.proposed_action),
        "reason": inc.proposal_reason, "attempts": [{"action": a.action, "result": a.result} for a in inc.attempts],
        "time_to_fix_s": inc.time_to_fix_s, "simulation": inc.simulation,
        "url": settings.public_url, "text": message(event, inc),
    }


class Notifier:
    def __init__(self):
        self.calls: list[dict] = []   # shown in GET /api/egress
        self.transport: httpx.AsyncBaseTransport | None = None  # tests pass a mock
        self._tasks: set[asyncio.Task] = set()

    def emit(self, event: str, inc: Incident) -> None:
        """Fire and forget: the incident flow never waits on the webhook."""
        if not settings.webhook_url:
            return
        task = asyncio.ensure_future(self._send(event, payload(event, inc)))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _send(self, event: str, body: dict) -> None:
        raw = json.dumps(body).encode()
        headers = {"Content-Type": "application/json", "User-Agent": "fixonce"}
        if settings.webhook_secret:
            sig = hmac.new(settings.webhook_secret.encode(), raw, hashlib.sha256).hexdigest()
            headers["X-FixOnce-Signature"] = f"sha256={sig}"
        ok, note = False, ""
        try:
            async with httpx.AsyncClient(timeout=5, transport=self.transport) as c:
                r = await c.post(settings.webhook_url, content=raw, headers=headers)
            ok, note = r.status_code < 400, f"HTTP {r.status_code}"
        except Exception as e:  # the receiver being down must not touch the incident
            note = str(e)[:120] or type(e).__name__
            log.warning("webhook %s failed: %s", event, note)
        self.calls.append({"t": time.time(), "to": "webhook", "op": event, "chars": len(raw), "ok": ok, "note": note})
        self.calls = self.calls[-300:]

    async def drain(self) -> None:
        """Wait for webhooks in flight (tests, shutdown)."""
        if self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)


notifier = Notifier()
