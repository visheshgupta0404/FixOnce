"""Mask personal data and secrets in log lines before any agent sees them.

The agents send log lines to the LLM and write lessons into Meko, so this runs first, inside the
company's own process. On by default; FIXONCE_REDACT=false turns it off.
"""
from __future__ import annotations

import re
from collections import Counter

# (pattern, replacement, kind counted on the page)
PATTERNS = [
    (re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"), "<email>", "email"),
    (re.compile(r"(?i)\b(bearer|token|api[_-]?key|apikey|password|passwd|secret|authorization)\b(\s*[:=]\s*|\s+)[^\s,;]+"),
     r"\1\2<secret>", "secret"),
    (re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"), "<ip>", "ip"),
    (re.compile(r"\b(?:\d{4}[ -]){3}\d{1,7}\b"), "<card>", "card"),         # 4-4-4-4 style card numbers
    (re.compile(r"\+?\b\d{2,3}[ -]?\d{5}[ -]?\d{5}\b"), "<phone>", "phone"),  # +91 98765 43210 style
]

# what was masked so far, shown on the page ("What left this machine")
stats: dict = {"lines": 0, "masked": Counter(), "last": None}


def redact(text: str) -> str:
    for pattern, repl, kind in PATTERNS:
        text, n = pattern.subn(repl, text)
        stats["masked"][kind] += n
    return text


def redact_logs(lines: list[dict]) -> list[dict]:
    out = []
    for line in lines:
        msg = str(line.get("msg", ""))
        clean = redact(msg)
        stats["lines"] += 1
        if clean != msg:
            stats["last"] = clean
        out.append({**line, "msg": clean})
    return out
