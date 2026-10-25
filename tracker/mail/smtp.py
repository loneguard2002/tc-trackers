"""SMTP delivery, ported from the capacity app (``_get_smtp_config``, ``_get_oauth2_token``, ``_xoauth2_string`` and
the SMTP part of ``_send_now``).

Non-secret settings come from ``app_settings`` (edited on /admin/smtp); the secrets ``SMTP_PASSWORD`` and
``SMTP_CLIENT_SECRET`` come from the environment only. Passwords, tokens and message bodies are never logged.
"""

from __future__ import annotations

import base64
import logging
import os
import smtplib
from email.message import EmailMessage

from sqlalchemy import select

from ..db import get_session
from ..models import AppSetting

logger = logging.getLogger(__name__)

SMTP_TIMEOUT_SECONDS = 30
DEFAULT_PORT = 587
SMTPS_PORT = 465
OAUTH2_SCOPE = "https://outlook.office365.com/.default"
SETTING_KEYS = ("smtp_host", "smtp_port", "smtp_auth", "smtp_user", "smtp_from", "smtp_tenant_id", "smtp_client_id")


class MailError(Exception):
    """Delivery failed. The message is safe to store and show: it never contains credentials."""


def build_config(settings: dict[str, str], env: dict[str, str] | os._Environ) -> dict:
    """The SMTP configuration from stored settings and environment secrets."""
    try:
        port = int(settings.get("smtp_port") or DEFAULT_PORT)
    except ValueError:
        port = DEFAULT_PORT
    return {
        "host": settings.get("smtp_host", ""),
        "port": port,
        "auth": settings.get("smtp_auth") or "none",
        "user": settings.get("smtp_user", ""),
        "from_": settings.get("smtp_from", "") or settings.get("smtp_user", ""),
        "tenant_id": settings.get("smtp_tenant_id", ""),
        "client_id": settings.get("smtp_client_id", ""),
        "password": env.get("SMTP_PASSWORD", ""),
        "client_secret": env.get("SMTP_CLIENT_SECRET", ""),
    }


def get_smtp_config(session=None) -> dict:
    session = session or get_session()
    rows = session.scalars(select(AppSetting).where(AppSetting.key.in_(SETTING_KEYS)))
    return build_config({row.key: row.value for row in rows}, os.environ)


def get_oauth2_token(tenant: str, client_id: str, client_secret: str) -> str:
    """Acquire a bearer token by client credentials for SMTP.Send."""
    import msal

    app = msal.ConfidentialClientApplication(
        client_id=client_id,
        client_credential=client_secret,
        authority=f"https://login.microsoftonline.com/{tenant}",
    )
    result = app.acquire_token_for_client(scopes=[OAUTH2_SCOPE])
    if "access_token" not in result:
        raise MailError(f"OAuth2 token request failed: {str(result.get('error', 'unknown'))[:100]}")
    return result["access_token"]


def xoauth2_string(user: str, token: str) -> str:
    """The base64 XOAUTH2 initial response."""
    return base64.b64encode(f"user={user}\x01auth=Bearer {token}\x01\x01".encode()).decode()


def deliver(msg: EmailMessage, cfg: dict) -> None:
    """One delivery attempt using ``cfg``; raises ``MailError`` on any failure."""
    if not cfg["host"]:
        raise MailError("The SMTP host is not configured (Admin, Email settings).")
    sender = cfg["from_"]
    if not sender:
        raise MailError("No sender address is configured (Admin, Email settings).")
    if "From" not in msg:
        msg["From"] = sender
    if "To" not in msg:
        msg["To"] = sender
    try:
        _talk(msg, cfg)
    except MailError:
        raise
    except Exception as exc:  # smtplib, socket, ssl and msal errors all become one type
        raise MailError(str(exc)[:200] or type(exc).__name__) from exc


def _talk(msg: EmailMessage, cfg: dict) -> None:
    secure_from_start = cfg["port"] == SMTPS_PORT
    factory = smtplib.SMTP_SSL if secure_from_start else smtplib.SMTP
    # Not a ``with`` block: a failing QUIT after acceptance must not turn a delivered message into a failure.
    server = factory(cfg["host"], cfg["port"], timeout=SMTP_TIMEOUT_SECONDS)
    try:
        server.ehlo()
        encrypted = secure_from_start
        if not secure_from_start and "starttls" in server.esmtp_features:
            server.starttls()
            server.ehlo()
            encrypted = True
        if cfg["auth"] in ("plain", "xoauth2") and not encrypted:
            raise MailError("The server offers no encryption; credentials are not sent unencrypted.")
        if cfg["auth"] == "plain":
            if cfg["user"] and cfg["password"]:
                server.login(cfg["user"], cfg["password"])
        elif cfg["auth"] == "xoauth2":
            token = get_oauth2_token(cfg["tenant_id"], cfg["client_id"], cfg["client_secret"])
            code, response = server.docmd("AUTH", "XOAUTH2 " + xoauth2_string(cfg["user"], token))
            if code != 235:
                raise smtplib.SMTPAuthenticationError(code, response)
        server.send_message(msg)
    finally:
        try:
            server.quit()
        except Exception:
            logger.debug("SMTP QUIT failed; closing the socket instead")
            try:
                server.close()
            except Exception:
                pass


def send_message(msg: EmailMessage) -> None:
    """Send ``msg`` with the stored configuration. Missing From and To default to the configured sender.

    Bcc addresses are delivered to but not transmitted as a header (``smtplib.send_message`` strips them).
    """
    deliver(msg, get_smtp_config())
