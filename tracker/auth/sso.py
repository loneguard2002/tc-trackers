"""Microsoft Entra ID single sign-on (ported from the CAPACITY app). Registered only when SSO is configured."""

from __future__ import annotations

from flask import Blueprint, current_app, flash, redirect, request, session, url_for
from sqlalchemy import select

from ..audit import record
from ..db import get_session
from ..models import User
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


REFUSED_PASSWORD_ACCOUNT = "This account signs in with a password. Ask an administrator for help."


@bp.get("/auth/sso")
def sso_start():
    # The flow carries state, nonce and the PKCE verifier; it is single use and kept only in the session.
    flow = _msal_app().initiate_auth_code_flow(scopes=[], redirect_uri=_redirect_uri())
    session["sso_flow"] = flow
    return redirect(flow["auth_uri"])


def _resolve_user(db, subject: str, claims: dict, full_name: str):
    """Return (user, refusal message). Matches by subject first, then links or creates by email."""
    user = db.scalar(select(User).where(User.sso_subject == subject))
    if user is not None:
        return user, None
    email = (claims.get("email") or claims.get("preferred_username") or "").strip().lower()
    if not email:
        return None, "Sign-in failed: no email address was returned by the identity provider."
    user = db.scalar(select(User).where(User.email == email))
    if user is None:
        user = User(
            email=email,
            full_name=full_name,
            password_hash=None,
            auth_source="sso",
            status="pending",
            sso_subject=subject,
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
            detail={"email": email, "source": "sso", "status": "pending", "sso_subject": subject},
        )
        return user, None
    if user.auth_source != "sso":
        return None, REFUSED_PASSWORD_ACCOUNT
    if user.sso_subject is not None:
        return None, "Sign-in failed: this email address is linked to a different Microsoft account."
    user.sso_subject = subject
    record(
        db,
        user_id=user.id,
        tracker_id=None,
        action="sso_linked",
        entity="user",
        entity_id=user.id,
        detail={"sso_subject": subject},
    )
    return user, None


@bp.get("/auth/callback")
def sso_callback():
    flow = session.pop("sso_flow", None)
    if not isinstance(flow, dict):
        return _fail("Sign-in failed: the sign-in request has expired. Please try again.")

    try:
        result = _msal_app().acquire_token_by_auth_code_flow(flow, request.args.to_dict())
    except ValueError:
        current_app.logger.warning("SSO state mismatch")
        return _fail("Sign-in failed: invalid state. Please try again.")
    if not result or "error" in result:
        current_app.logger.error("SSO token exchange failed: %s", (result or {}).get("error"))
        return _fail("Sign-in failed: the identity provider rejected the request.")

    claims = result.get("id_token_claims") or {}
    tenant = current_app.config["SSO_TENANT_ID"]
    if claims.get("tid") != tenant or not claims.get("oid"):
        current_app.logger.warning("SSO tenant or subject claim mismatch")
        return _fail("Sign-in failed: the account does not belong to the expected organisation.")
    subject = f"{claims['tid']}:{claims['oid']}"
    email_hint = (claims.get("email") or claims.get("preferred_username") or "").strip().lower()
    full_name = claims.get("name") or email_hint

    db = get_session()
    user, refusal = _resolve_user(db, subject, claims, full_name)
    if refusal:
        db.rollback()
        return _fail(refusal)

    if user.status == "active" and user.auth_source == "sso" and full_name and user.full_name != full_name:
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
