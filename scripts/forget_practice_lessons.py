#!/usr/bin/env python3
"""List, then forget, the lessons left in Meko by practice runs, so the demo starts from the seeded history.

Keeps: promoted lessons (locked in Meko anyway), "[seeded demo history]" lessons and team rules.
Forgets (with --yes only): every other unpromoted memory, through FixOnce's own Forget (DELETE /lessons/{id}).
Forgetting is permanent. Run it yourself, with FixOnce running and Meko ON:

    python3 scripts/forget_practice_lessons.py              # dry run: shows what would go
    python3 scripts/forget_practice_lessons.py --yes        # forgets them
    FIXONCE_URL=https://... python3 scripts/forget_practice_lessons.py
"""
import json
import os
import sys
import urllib.request

URL = os.getenv("FIXONCE_URL", "http://localhost:8000").rstrip("/")


def call(method: str, path: str):
    req = urllib.request.Request(URL + path, method=method)
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read() or "null")


def keep(m: dict) -> bool:
    text = m.get("text", "")
    return bool(m.get("promoted")) or text.startswith("[seeded demo history]") or text.startswith("Team rule")


lessons = call("GET", "/lessons")
drop = [m for m in lessons if not keep(m)]
print(f"{len(lessons)} memories in Meko; {len(drop)} from practice runs:")
for m in drop:
    print(f"  {m['id']}  {m['text'][:110]}")
if "--yes" not in sys.argv:
    print("\nDry run. Add --yes to forget them (permanent).")
    sys.exit(0)
for m in drop:
    r = call("DELETE", f"/lessons/{m['id']}")
    print(("forgot " if r.get("forgotten") else "NOT forgotten ") + m["id"] + ("" if r.get("forgotten") else f": {r.get('error')}"))
