"""FixOnce: an on-call agent that remembers, as a package you run inside your own infrastructure.

    pip install "fixonce[gemini]"
    fixonce demo                                  # everything in one process, with the demo shop simulation
    fixonce serve --target http://my-service:9000 # watch your own service

or from Python:

    import fixonce
    app = fixonce.create_app(target=MyTarget(), actions={"drain_queue": "Drain the job queue"})

Nothing is sent anywhere except the Meko datapack and the LLM key you configure yourself.
Importing this package is cheap: the API and agents load only when create_app() is called.
"""
from __future__ import annotations

__version__ = "0.1.0"


def configure(target: object | None = None, actions: dict[str, str] | None = None,
              rules: list[dict] | None = None) -> None:
    """Point FixOnce at your service. Call before create_app() or before serving.

    target:  an HttpTarget, or any object with the async methods of fixonce.target.Target.
             A target may also carry `actions` and `rules` attributes instead of passing them here.
    actions: {name: plain-words label} of the safe actions your target can run. Replaces the demo
             set; the agents only ever propose a name from this catalog.
    rules:   team rules that block an action ({"id", "text", "action", "service", "when"});
             replaces the demo rule.
    """
    from .models import ACTION_LABELS, SAFE_ACTIONS
    from .rules import RULES
    from .target import target as current

    if target is not None:
        current.use(target)
        actions = actions if actions is not None else getattr(target, "actions", None)
        rules = rules if rules is not None else getattr(target, "rules", None)
    if actions is not None:
        if not actions:
            raise ValueError("actions must name at least one safe action")
        ACTION_LABELS.clear()
        ACTION_LABELS.update(actions)
        SAFE_ACTIONS[:] = list(actions)  # same list object everywhere, including the fixer's schema
    if rules is not None:
        RULES[:] = list(rules)


def create_app(**kwargs):
    """configure(**kwargs), then return the FastAPI app (API + on-call page) for any ASGI server."""
    configure(**kwargs)
    from .main import app
    return app


__all__ = ["__version__", "configure", "create_app"]
