"""`fixonce` command line.

    fixonce demo                          page + agents + the demo shop SIMULATION, one process
    fixonce serve --target URL            watch your own HTTP service (see target.py for the 4 endpoints)
    fixonce serve --target pkg.mod:obj    ...or a Python object with the Target methods
    fixonce seed                          write the seeded demo history into your Meko datapack (once)
    fixonce check                         call every Meko tool FixOnce uses against your datapack

Settings come from environment variables, or from a .env file in the current folder (see .env.example).
"""
from __future__ import annotations

import argparse
import asyncio
import importlib
import os
import sys
from pathlib import Path


def load_env(path: str) -> None:
    """KEY=value lines; variables already set in the environment win."""
    p = Path(path)
    if not p.is_file():
        return
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def load_target(spec: str) -> object:
    """'pkg.module:attr' -> that object (a class is instantiated with no arguments)."""
    module, _, attr = spec.partition(":")
    sys.path.insert(0, os.getcwd())
    obj = getattr(importlib.import_module(module), attr or "target")
    return obj() if isinstance(obj, type) else obj


def _serve(host: str, port: int, target: object | None = None) -> None:
    import uvicorn

    from . import create_app
    app = create_app(target=target)
    print(f"FixOnce on http://{host if host != '0.0.0.0' else 'localhost'}:{port}")
    uvicorn.run(app, host=host, port=port)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="fixonce", description="On-call agent that remembers (Meko).")
    ap.add_argument("--env-file", default=".env", help="read settings from this file if it exists")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name, help_ in [("demo", "run with the built-in demo shop simulation"),
                        ("serve", "watch your own service")]:
        sp = sub.add_parser(name, help=help_)
        sp.add_argument("--host", default="127.0.0.1")
        sp.add_argument("--port", type=int, default=8000)
        if name == "serve":
            sp.add_argument("--target", required=True,
                            help="http(s)://service-url, or pkg.module:object with the Target methods")
    sp_seed = sub.add_parser("seed", help="write the seeded demo history into your Meko datapack (once)")
    sp_seed.add_argument("--only", help="only the seeded lessons of this date, e.g. 2026-10-02")
    sub.add_parser("check", help="check every Meko call against your datapack")
    for sp in sub.choices.values():  # `fixonce demo --env-file x` works as well as `fixonce --env-file x demo`
        sp.add_argument("--env-file", default=argparse.SUPPRESS, help="read settings from this file if it exists")
    args = ap.parse_args(argv)

    load_env(args.env_file)
    # settings are read when fixonce.config is first imported, so set them before importing the app
    if args.cmd == "demo":
        os.environ["TARGET_URL"] = "inprocess"
        os.environ["FIXONCE_DEMO"] = "true"
        _serve(args.host, args.port)
    elif args.cmd == "serve":
        os.environ.setdefault("FIXONCE_DEMO", "false")
        if args.target.startswith(("http://", "https://")):
            os.environ["TARGET_URL"] = args.target
            _serve(args.host, args.port)
        else:
            _serve(args.host, args.port, load_target(args.target))
    elif args.cmd == "seed":
        from .seed import seed
        print("seeded memory ids:", asyncio.run(seed(only=args.only)))
    elif args.cmd == "check":
        from .meko_check import main as check
        asyncio.run(check())


if __name__ == "__main__":
    main()
