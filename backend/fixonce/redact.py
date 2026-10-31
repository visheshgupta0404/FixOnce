"""Mask personal data and secrets in log lines before any agent sees them.

The agents send log lines to the LLM and write lessons into Meko, so this runs first, inside the
company's own process. On by default; FIXONCE_REDACT=false turns it off.
"""
from __future__ import annotations

import re

PATTERNS = [
    (re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"), "<email>"),
    (re.compile(r"(?i)\b(bearer|token|api[_-]?key|apikey|password|passwd|secret|authorization)\b(\s*[:=]\s*|\s+)[^\s,;]+"),
     r"\1\2<secret>"),
    (re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"), "<ip>"),
    (re.compile(r"\b(?:\d{4}[ -]){3}\d{1,7}\b"), "<card>"),       # 4-4-4-4 style card numbers
    (re.compile(r"\+?\b\d{2,3}[ -]?\d{5}[ -]?\d{5}\b"), "<phone>"),  # +91 98765 43210 style
]


def redact(text: str) -> str:
    for pattern, repl in PATTERNS:
        text = pattern.sub(repl, text)
    return text


def redact_logs(lines: list[dict]) -> list[dict]:
    return [{**line, "msg": redact(str(line.get("msg", "")))} for line in lines]
