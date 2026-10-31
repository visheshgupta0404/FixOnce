"""Alerts for every incident step: a Telegram message straight from this process (TELEGRAM_BOT_TOKEN),
and/or a JSON webhook (FIXONCE_WEBHOOK_URL) for Slack, email or a pager.

Telegram is outgoing only (Bot API sendMessage), so it works behind a company firewall. With no
TELEGRAM_CHAT_ID, FixOnce messages the last chat that pressed Start on the bot.

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
    rec = r.recurrence if r and r.meko_enabled else None
    if rec and rec.count >= 2:
        nth = rec.count + 1
        line = f"🔁 This is the {nth}{'th' if 11 <= nth % 100 <= 13 else {1: 'st', 2: 'nd', 3: 'rd'}.get(nth % 10, 'th')} time."
        if rec.root_cause:
            line += f" Root cause: {rec.root_cause}"
        line += " Follow-up still open." if rec.followup else f" Permanent fix: {rec.permanent_fix}"
        lines.append(line)
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
        "recurrence": r.recurrence.model_dump() if r and r.recurrence else None,
        "url": settings.public_url, "text": message(event, inc),
    }


TELEGRAM_API = "https://api.telegram.org"


class Notifier:
    def __init__(self):
        self.calls: list[dict] = []   # shown in GET /api/egress
        self.transport: httpx.AsyncBaseTransport | None = None  # tests pass a mock
        self._tasks: set[asyncio.Task] = set()
        self._chat_id: str | None = None  # found with getUpdates when TELEGRAM_CHAT_ID is empty

    def emit(self, event: str, inc: Incident) -> None:
        """Fire and forget: the incident flow never waits on Telegram or the webhook."""
        body = payload(event, inc)
        if settings.telegram_bot_token:
            self._spawn(self._telegram(event, body["text"]))
        if settings.webhook_url:
            self._spawn(self._send(event, body))

    def _spawn(self, coro) -> None:
        task = asyncio.ensure_future(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    def _record(self, to: str, event: str, chars: int, ok: bool, note: str) -> None:
        self.calls.append({"t": time.time(), "to": to, "op": event, "chars": chars, "ok": ok, "note": note})
        self.calls = self.calls[-300:]

    async def _telegram(self, event: str, text: str) -> None:
        token = settings.telegram_bot_token
        ok, note = False, ""
        try:
            async with httpx.AsyncClient(base_url=f"{TELEGRAM_API}/bot{token}", timeout=10, transport=self.transport) as c:
                chat = settings.telegram_chat_id or self._chat_id
                if not chat:
                    r = await c.get("/getUpdates")
                    chats = [u[k]["chat"]["id"] for u in r.json().get("result", []) for k in ("message", "my_chat_member")
                             if isinstance(u.get(k), dict) and "chat" in u[k]]
                    chat = self._chat_id = str(chats[-1]) if chats else None
                if not chat:
                    note = "no chat yet: open the bot in Telegram and press Start"
                else:
                    r = await c.post("/sendMessage", json={"chat_id": chat, "text": text,
                                                           "disable_web_page_preview": True})
                    ok, note = r.status_code < 400, f"HTTP {r.status_code}"
        except Exception as e:  # Telegram being down must not touch the incident
            note = (str(e).replace(token, "<token>")[:120]) or type(e).__name__  # never log the bot token
        if not ok:
            log.warning("telegram %s failed: %s", event, note)
        self._record("telegram", event, len(text), ok, note)

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
        self._record("webhook", event, len(raw), ok, note)

    async def drain(self) -> None:
        """Wait for webhooks in flight (tests, shutdown)."""
        if self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)


notifier = Notifier()
