"""LLM access. Gemini in the real demo; a deterministic rule-based stand-in for tests/offline.

Every agent calls `llm.json(task, prompt, schema, fallback)`:
- gemini mode: asks Gemini for JSON matching `schema`, checks the keys, retries once, then raises.
- fake mode:   returns `fallback()` (plain Python rules), so the whole flow runs with no keys.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any, Callable

from .config import settings


class LLMError(RuntimeError):
    pass


class LLM:
    def __init__(self, mode: str | None = None):
        self.mode = mode or settings.llm_mode
        self._client = None

    def _gemini(self):
        if self._client is None:
            from google import genai
            self._client = genai.Client(api_key=settings.gemini_api_key)
        return self._client

    async def json(self, task: str, prompt: str, schema: dict, fallback: Callable[[], dict]) -> dict:
        if self.mode != "gemini":
            return fallback()
        last_err: Exception | None = None
        for _ in range(2):  # one retry
            try:
                out = await asyncio.to_thread(self._call_gemini, prompt, schema)
                missing = [k for k in schema.get("required", []) if k not in out]
                if missing:
                    raise LLMError(f"{task}: missing keys {missing}")
                return out
            except Exception as e:
                last_err = e
        raise LLMError(f"{task}: Gemini failed twice: {last_err}")

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
        if self.mode != "gemini":
            return fallback()
        try:
            resp = await asyncio.to_thread(
                self._gemini().models.generate_content, model=settings.gemini_model, contents=prompt)
            return resp.text.strip()
        except Exception:
            return fallback()


llm = LLM()


def obj(properties: dict[str, Any], required: list[str] | None = None) -> dict:
    """Small helper to write JSON schemas for Gemini structured output."""
    return {"type": "object", "properties": properties, "required": required or list(properties)}
