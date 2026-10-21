"""Microsoft Entra ID single sign-on (ported from the CAPACITY app). Registered only when SSO is configured."""

from __future__ import annotations

import secrets

from flask import Blueprint, current_app, flash, redirect, request, session, url_for
from sqlalchemy import select

from ..audit import record
from ..db import get_session
from ..models import User
from .passwords import hash_password
from .session import login_user

bp = Blueprint("sso", __name__)


def _msal_app():
    import msal

    config = current_app.config
    return msal.ConfidentialClientApplication(
        config["SSO_CLIENT_ID"],
        authority=f"https://login.microsoftonline.com/{config['SSO_TENANT_ID']}",
        client_credential=config["SSO_CLIENT_SECRET"],
    )


def _redirect_uri() -> str:
    return current_app.config["APP_URL"].rstrip("/") + "/auth/callback"


def _fail(message: str):
    flash(message, "danger")
    return redirect(url_for("auth.login"))


@bp.get("/auth/sso")
def sso_start():
    state = secrets.token_urlsafe(16)
    session["sso_state"] = state
    # MSAL adds openid, profile and offline_access automatically.
    url = _msal_app().get_authorization_request_url(scopes=[], state=state, redirect_uri=_redirect_uri())
    return redirect(url)


@bp.get("/auth/callback")
def sso_callback():
    expected = session.pop("sso_state", None)
    received = request.args.get("state")
    if not expected or not received or not secrets.compare_digest(received, expected):
        current_app.logger.warning("SSO state mismatch")
        return _fail("Sign-in failed: invalid state. Please try again.")

    code = request.args.get("code")
    if not code:
        current_app.logger.warning("SSO callback without code: %s", request.args.get("error"))
        return _fail("Sign-in failed: the identity provider did not return a code.")

    result = _msal_app().acquire_token_by_authorization_code(code, scopes=[], redirect_uri=_redirect_uri())
    if "error" in result:
        current_app.logger.error("SSO token exchange failed: %s", result.get("error"))
        return _fail("Sign-in failed: the identity provider rejected the request.")

    claims = result.get("id_token_claims", {})
    email = (claims.get("preferred_username") or claims.get("email") or claims.get("upn") or "").strip().lower()
    full_name = claims.get("name") or email
    if not email:
        return _fail("Sign-in failed: no email address was returned by the identity provider.")

    db = get_session()
    user = db.scalar(select(User).where(User.email == email))
    if user is None:
        user = User(
            email=email,
            full_name=full_name,
            password_hash=hash_password(secrets.token_hex(32)),
            auth_source="sso",
            status="pending",
        )
        db.add(user)
        db.flush()
        record(
            db,
            user_id=None,
            tracker_id=None,
            action="user_created",
            entity="user",
            entity_id=user.id,
            detail={"email": email, "source": "sso", "status": "pending"},
        )
        db.commit()
    elif user.status == "active" and user.auth_source == "sso" and user.full_name != full_name:
        user.full_name = full_name
        db.commit()

    if user.status == "pending":
        session["pending_name"] = full_name
        return redirect(url_for("auth.pending"))
    if user.status != "active":
        return _fail("Your account is inactive. Contact your administrator.")

    login_user(user)
    record(db, user_id=user.id, tracker_id=None, action="sso_login", entity="user", entity_id=user.id)
    db.commit()
    return redirect(url_for("index"))
