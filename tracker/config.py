"""Environment-backed application configuration."""

from __future__ import annotations

import os
import subprocess
from functools import cache
from pathlib import Path

from dotenv import load_dotenv

MULTI_TENANT_AUTHORITIES = {"common", "organizations", "consumers"}


class ConfigurationError(RuntimeError):
    """Raised when the application cannot start securely."""


def _cookie_secure(raw: str | None) -> bool:
    """Fail closed: only an explicit false-like value turns the Secure flag off."""
    return (raw or "true").strip().lower() not in {"false", "0", "no", "off"}


def _git(*args: str) -> str:
    """The output of a git command run in the application's folder, or "" when git or the clone is not there."""
    try:
        done = subprocess.run(
            ["git", *args],
            cwd=Path(__file__).resolve().parent.parent,
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return done.stdout.strip()


@cache
def running_commit() -> tuple[str, str]:
    """The commit the application runs (its full id) and that commit's date, read once per process.

    ``GIT_COMMIT`` wins when set; on Render, ``RENDER_GIT_COMMIT`` names the deployed commit (the image has no .git);
    otherwise a git clone (the local copy) gives its checked-out commit. The date is known only from a clone. Either
    is "" when it cannot be found.
    """
    commit = os.getenv("GIT_COMMIT") or os.getenv("RENDER_GIT_COMMIT") or _git("rev-parse", "HEAD")
    date = _git("show", "-s", "--format=%cd", "--date=format:%d %b %Y %H:%M", commit) if commit else ""
    return commit, date


def normalise_database_url(url: str) -> str:
    """Use the psycopg 3 driver for plain ``postgres://`` and ``postgresql://`` URLs (as providers hand them out)."""
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix) :]
    return url


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
        # The sidebar's version: the running commit's short id ("local" when unknown), with the full id and date.
        "APP_VERSION": (running_commit()[0] or "local")[:7],
        "APP_COMMIT": running_commit()[0],
        "APP_COMMIT_DATE": running_commit()[1],
        "SESSION_COOKIE_HTTPONLY": True,
        "SESSION_COOKIE_SAMESITE": "Lax",
        "SESSION_COOKIE_SECURE": _cookie_secure(os.getenv("SESSION_COOKIE_SECURE")),
        "PERMANENT_SESSION_LIFETIME": 60 * 60 * 8,
    }
    if overrides:
        config.update(overrides)
    config["DATABASE_URL"] = normalise_database_url(str(config.get("DATABASE_URL") or ""))
    # SSO is enabled only when tenant, client id and client secret are all present.
    config["SSO_ENABLED"] = all(config.get(key) for key in ("SSO_TENANT_ID", "SSO_CLIENT_ID", "SSO_CLIENT_SECRET"))
    return config


def validate_config(config: dict) -> None:
    missing = [name for name in ("SECRET_KEY", "DATABASE_URL") if not config.get(name)]
    if missing:
        raise ConfigurationError("Missing required configuration: " + ", ".join(missing))
    if not config.get("TESTING") and len(str(config["SECRET_KEY"])) < 32:
        raise ConfigurationError("FLASK_SECRET_KEY must be at least 32 characters")
    if config.get("SSO_ENABLED") and str(config.get("SSO_TENANT_ID", "")).strip().lower() in MULTI_TENANT_AUTHORITIES:
        raise ConfigurationError("SSO_TENANT_ID must be a specific tenant, not a multi-tenant authority")
