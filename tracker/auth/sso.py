"""Microsoft Entra ID single sign-on (ported from the CAPACITY app). Registered only when SSO is configured."""

from __future__ import annotations

from flask import Blueprint, current_app, flash, redirect, request, session, url_for
from itsdangerous import BadSignature, URLSafeTimedSerializer
from sqlalchemy import select

from ..audit import change, record
from ..db import get_session
from ..models import User
from .accounts import find_by_email
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
EXPIRED_MESSAGE = "Sign-in failed: the sign-in request has expired. Please try again."

# Microsoft returns the person by posting a form (response_mode=form_post), so the one-time code never appears in an
# address, a browser history or an access log. A browser sends no SameSite=Lax cookie, the session's included, with a
# form posted from another site, so the sign-in in progress (MSAL's flow: state, nonce and the PKCE verifier) travels in
# its own signed cookie instead: SameSite=None, Secure and HttpOnly, sent only to the callback, good for ten minutes and
# removed by the callback whatever happens.
FLOW_COOKIE = "pt_sso_flow"
FLOW_MAX_AGE_SECONDS = 600


def _flow_serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(current_app.secret_key, salt="sso-flow")


def _read_flow() -> dict | None:
    raw = request.cookies.get(FLOW_COOKIE)
    if not raw:
        return None
    try:
        flow = _flow_serializer().loads(raw, max_age=FLOW_MAX_AGE_SECONDS)
    except BadSignature:  # tampered, or older than FLOW_MAX_AGE_SECONDS (SignatureExpired)
        return None
    return flow if isinstance(flow, dict) else None


def _forget_flow(response):
    response.delete_cookie(FLOW_COOKIE, path=url_for("sso.sso_callback"), secure=True, httponly=True, samesite="None")
    return response


@bp.get("/auth/sso")
def sso_start():
    flow = _msal_app().initiate_auth_code_flow(scopes=[], redirect_uri=_redirect_uri(), response_mode="form_post")
    response = redirect(flow["auth_uri"])
    response.set_cookie(
        FLOW_COOKIE,
        _flow_serializer().dumps(flow),
        max_age=FLOW_MAX_AGE_SECONDS,
        path=url_for("sso.sso_callback"),
        secure=True,
        httponly=True,
        samesite="None",
    )
    return response


def _resolve_user(db, subject: str, claims: dict, full_name: str):
    """Return (user, refusal message, created). Matches by subject first, then links or creates by email."""
    user = db.scalar(select(User).where(User.sso_subject == subject))
    if user is not None:
        return user, None, False
    email = (claims.get("email") or claims.get("preferred_username") or "").strip().lower()
    if not email:
        return None, "Sign-in failed: no email address was returned by the identity provider.", False
    user = find_by_email(db, email)
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
            target_user_id=user.id,
            detail={"email": email, "source": "sso", "status": "pending", "sso_subject": subject},
        )
        return user, None, True
    if user.auth_source != "sso":
        return None, REFUSED_PASSWORD_ACCOUNT, False
    if user.sso_subject is not None:
        return None, "Sign-in failed: this email address is linked to a different Microsoft account.", False
    user.sso_subject = subject
    record(
        db,
        user_id=user.id,
        tracker_id=None,
        action="sso_linked",
        entity="user",
        entity_id=user.id,
        target_user_id=user.id,
        detail={"sso_subject": subject},
    )
    return user, None, False


@bp.route("/auth/callback", methods=["GET", "POST"])
def sso_callback():
    """Where Microsoft posts the sign-in result. It carries no CSRF token (auth/csrf.py exempts this endpoint): MSAL
    checks the posted state against the flow cookie, which only this app can sign. A GET has no flow to finish."""
    flow = _read_flow() if request.method == "POST" else None
    response = _finish_sign_in(flow, request.form.to_dict()) if flow else _fail(EXPIRED_MESSAGE)
    return _forget_flow(response)


def _finish_sign_in(flow: dict, auth_response: dict):
    try:
        result = _msal_app().acquire_token_by_auth_code_flow(flow, auth_response)
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
    user, refusal, created = _resolve_user(db, subject, claims, full_name)
    if refusal:
        db.rollback()
        return _fail(refusal)

    if user.status == "active" and user.auth_source == "sso" and full_name and user.full_name != full_name:
        record(
            db,
            user_id=user.id,
            tracker_id=None,
            action="user_name_synced",
            entity="user",
            entity_id=user.id,
            detail=change(user.full_name, full_name),
            target_user_id=user.id,
        )
        user.full_name = full_name
    db.commit()

    if user.status == "pending":
        if created:  # a first sign-in: tell the approvers and the person (design 2026-11-18)
            from ..mail import access  # here: the mail package imports views that need this blueprint's helpers

            access.request_received(db, user)
            db.commit()
        session["pending_user_id"] = user.id
        return redirect(url_for("auth.pending"))
    if user.status == "declined":  # turned down: the message again, no new request and nobody emailed
        record(
            db, user_id=None, tracker_id=None, action="sso_declined_attempt", entity="user", entity_id=user.id,
            target_user_id=user.id,
        )  # fmt: skip
        db.commit()
        session["declined_user_id"] = user.id
        return redirect(url_for("auth.declined"))
    if user.status != "active":
        return _fail("Your account is inactive. Contact your administrator.")

    login_user(user)
    record(
        db,
        user_id=user.id,
        tracker_id=None,
        action="sso_login",
        entity="user",
        entity_id=user.id,
        target_user_id=user.id,
    )
    db.commit()
    return redirect(url_for("index"))
