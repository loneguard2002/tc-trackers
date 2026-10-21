"""Environment-backed application configuration."""

from __future__ import annotations

import os

from dotenv import load_dotenv


class ConfigurationError(RuntimeError):
    """Raised when the application cannot start securely."""


def _cookie_secure(raw: str | None) -> bool:
    """Fail closed: only an explicit false-like value turns the Secure flag off."""
    return (raw or "true").strip().lower() not in {"false", "0", "no", "off"}


def load_config(overrides: dict | None = None) -> dict:
    load_dotenv()
    config = {
        "SECRET_KEY": os.getenv("FLASK_SECRET_KEY", ""),
        "DATABASE_URL": os.getenv("DATABASE_URL", ""),
        "APP_URL": os.getenv("APP_URL", "http://localhost:5000"),
        "SSO_TENANT_ID": os.getenv("SSO_TENANT_ID", ""),
        "SSO_CLIENT_ID": os.getenv("SSO_CLIENT_ID", ""),
        "SSO_CLIENT_SECRET": os.getenv("SSO_CLIENT_SECRET", ""),
        "TESTING": False,
        # Reject oversized request bodies before Werkzeug buffers them in memory.
        "MAX_CONTENT_LENGTH": 1024 * 1024,
        "APP_VERSION": (os.getenv("GIT_COMMIT") or "local")[:7],
        "SESSION_COOKIE_HTTPONLY": True,
        "SESSION_COOKIE_SAMESITE": "Lax",
        "SESSION_COOKIE_SECURE": _cookie_secure(os.getenv("SESSION_COOKIE_SECURE")),
        "PERMANENT_SESSION_LIFETIME": 60 * 60 * 8,
    }
    if overrides:
        config.update(overrides)
    # SSO is enabled only when tenant, client id and client secret are all present.
    config["SSO_ENABLED"] = all(config.get(key) for key in ("SSO_TENANT_ID", "SSO_CLIENT_ID", "SSO_CLIENT_SECRET"))
    return config


def validate_config(config: dict) -> None:
    missing = [name for name in ("SECRET_KEY", "DATABASE_URL") if not config.get(name)]
    if missing:
        raise ConfigurationError("Missing required configuration: " + ", ".join(missing))
    if not config.get("TESTING") and len(str(config["SECRET_KEY"])) < 32:
        raise ConfigurationError("FLASK_SECRET_KEY must be at least 32 characters")
