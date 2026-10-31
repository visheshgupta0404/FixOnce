"""LLM access. Gemini in the real demo; a deterministic rule-based stand-in for tests/offline.

Every agent calls `llm.json(task, prompt, schema, fallback)`:
- gemini mode: asks Gemini for JSON matching `schema`, checks the keys, retries once. If Gemini is
  down or too slow (each call has a timeout), it uses `fallback()` so the demo keeps going, counts it
  in `fallbacks` (shown by /api/status), and skips Gemini for a minute instead of waiting again.
  Set LLM_FALLBACK=false to raise instead.
- fake mode:   returns `fallback()` (plain Python rules), so the whole flow runs with no keys.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from typing import Any, Callable

from .config import settings

log = logging.getLogger("fixonce.llm")
TIMEOUT_S = float(os.getenv("GEMINI_TIMEOUT_SECONDS", "15"))
COOLDOWN_S = float(os.getenv("GEMINI_COOLDOWN_SECONDS", "60"))
USE_FALLBACK = os.getenv("LLM_FALLBACK", "true").strip().lower() in {"1", "true", "yes", "on"}


class LLMError(RuntimeError):
    pass


class LLM:
    def __init__(self, mode: str | None = None):
        self.mode = mode or settings.llm_mode
        self._client = None
        self.fallbacks = 0              # times the rule-based stand-in answered because Gemini failed
        self.last_error: str | None = None
        self._down_until = 0.0
        self.calls: list[dict] = []     # every request sent to Gemini (shown as "What left this machine")

    def _sent(self, task: str, prompt: str, ok: bool, note: str = "") -> None:
        self.calls.append({"t": time.time(), "to": "gemini", "op": task, "model": settings.gemini_model,
                           "chars": len(prompt), "ok": ok, "note": note})
        self.calls = self.calls[-300:]

    def _gemini(self):
        if self._client is None:
            from google import genai
            self._client = genai.Client(api_key=settings.gemini_api_key)
        return self._client

    async def json(self, task: str, prompt: str, schema: dict, fallback: Callable[[], dict]) -> dict:
        if self.mode != "gemini":
            return fallback()
        last_err: Exception | None = None
        if time.time() < self._down_until:
            last_err = LLMError(f"skipped, Gemini failed in the last {COOLDOWN_S:.0f}s")
        else:
            for _ in range(2):  # one retry
                try:
                    out = await asyncio.wait_for(asyncio.to_thread(self._call_gemini, prompt, schema), TIMEOUT_S)
                    missing = [k for k in schema.get("required", []) if k not in out]
                    if missing:
                        raise LLMError(f"{task}: missing keys {missing}")
                    self._sent(task, prompt, True)
                    return out
                except Exception as e:
                    last_err = e if str(e) else LLMError(f"no answer in {TIMEOUT_S:.0f}s")
                    self._sent(task, prompt, False, str(last_err)[:120])
            self._down_until = time.time() + COOLDOWN_S
        return self._fallback(task, last_err, fallback)

    def _fallback(self, task: str, err: Exception | None, fallback: Callable[[], Any]) -> Any:
        self.last_error = f"{task}: {str(err)[:200]}"
        if not USE_FALLBACK:
            raise LLMError(f"{task}: Gemini failed twice: {err}")
        self.fallbacks += 1
        log.warning("Gemini unavailable, rule-based stand-in answered %s (%s)", task, self.last_error)
        return fallback()

    def _call_gemini(self, prompt: str, schema: dict) -> dict:
        from google.genai import types
        resp = self._gemini().models.generate_content(
            model=settings.gemini_model,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=schema,
                temperature=0.2,
            ),
        )
        return json.loads(resp.text)

    async def text(self, prompt: str, fallback: Callable[[], str]) -> str:
        if self.mode != "gemini" or time.time() < self._down_until:
            return fallback()
        try:
            resp = await asyncio.wait_for(asyncio.to_thread(
                self._gemini().models.generate_content, model=settings.gemini_model, contents=prompt), TIMEOUT_S)
            self._sent("text", prompt, True)
            return resp.text.strip()
        except Exception as e:
            self._sent("text", prompt, False, str(e)[:120] or "timeout")
            self._down_until = time.time() + COOLDOWN_S
            self.last_error = f"text: {str(e)[:200] or 'timeout'}"
            self.fallbacks += 1
            return fallback()


llm = LLM()


def obj(properties: dict[str, Any], required: list[str] | None = None) -> dict:
    """Small helper to write JSON schemas for Gemini structured output."""
    return {"type": "object", "properties": properties, "required": required or list(properties)}
