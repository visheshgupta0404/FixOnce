"""All settings come from environment variables (see .env.example)."""
import os


def _bool(name: str, default: str) -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


class Settings:
    # Meko (product datapack, NOT the build datapack)
    meko_url: str = os.getenv("MEKO_MCP_URL", "https://mcp.mekodata.ai/mcp")
    meko_api_key: str = os.getenv("MEKO_API_KEY", "")
    meko_datapack_id: str = os.getenv("MEKO_DATAPACK_ID", "")
    meko_enabled_at_start: bool = _bool("MEKO_ENABLED", "true")
    # fake = in-memory stand-in with the same interface (tests, offline work)
    meko_mode: str = os.getenv("MEKO_MODE", "fake" if not os.getenv("MEKO_API_KEY") else "real")

    # LLM
    gemini_api_key: str = os.getenv("GEMINI_API_KEY", "")
    gemini_model: str = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
    llm_mode: str = os.getenv("LLM_MODE", "fake" if not os.getenv("GEMINI_API_KEY") else "gemini")

    # The service FixOnce watches (see target.py). SHOP_URL is the older name, kept for the demo.
    target_url: str = os.getenv("TARGET_URL") or os.getenv("SHOP_URL", "http://localhost:8001")
    # demo = the target is the demo shop SIMULATION: seeded history offline, chaos buttons shown
    demo: bool = _bool("FIXONCE_DEMO", "true")
    # mask emails, IPs, secrets, card and phone numbers in logs before agents, the LLM or Meko see them
    redact: bool = _bool("FIXONCE_REDACT", "true")

    # Outgoing webhook for n8n / Slack / WhatsApp (notify.py); empty = off
    webhook_url: str = os.getenv("FIXONCE_WEBHOOK_URL", "")
    webhook_secret: str = os.getenv("FIXONCE_WEBHOOK_SECRET", "")
    # where people open FixOnce (the link in notifications)
    public_url: str = os.getenv("FIXONCE_PUBLIC_URL", "http://localhost:8000")

    # Timings
    watch_interval_s: float = float(os.getenv("WATCH_INTERVAL_SECONDS", "3"))
    error_threshold: float = float(os.getenv("ERROR_THRESHOLD", "0.05"))
    check_seconds: float = float(os.getenv("CHECK_SECONDS", "8"))
    fast_path_confidence: float = float(os.getenv("FAST_PATH_CONFIDENCE", "0.6"))
    max_fix_attempts: int = int(os.getenv("MAX_FIX_ATTEMPTS", "3"))


settings = Settings()
