"""Signing out, and an administrator's End sessions, raise the person's session version: every session they have, and
every copy of its cookie, stops working (auth/session.py)."""

from __future__ import annotations

import hashlib
import hmac

import pytest
from conftest import TEST_PASSWORD, post, sign_in
from sqlalchemy import select

from tracker.auth.session import session_key
from tracker.models import AuditLog, User


def _signed_in(client) -> bool:
    return client.get("/").status_code == 200


def _signed_in_elsewhere(app, user: User):
    other = app.test_client()
    post(other, "/login", {"email": user.email, "password": TEST_PASSWORD})
    assert _signed_in(other)
    return other


@pytest.fixture
def user_manager(client, user_factory, give_set):
    actor = user_factory(full_name="Manager")
    give_set(["manage_users"], user=actor)
    sign_in(client, actor)
    return actor


def test_a_copied_session_cookie_stops_working_after_sign_out(app, client, user_factory):
    user = user_factory()
    post(client, "/login", {"email": user.email, "password": TEST_PASSWORD})
    copied = client.get_cookie("session").value
    thief = app.test_client()
    thief.set_cookie("session", copied)
    assert _signed_in(thief)
    assert post(client, "/logout").status_code == 302
    assert thief.get("/").headers["Location"].startswith("/login")


def test_sign_out_ends_the_persons_sessions_on_other_devices(app, client, user_factory):
    user = user_factory()
    laptop = _signed_in_elsewhere(app, user)
    post(client, "/login", {"email": user.email, "password": TEST_PASSWORD})
    post(client, "/logout")
    assert not _signed_in(laptop)
    post(laptop, "/login", {"email": user.email, "password": TEST_PASSWORD})
    assert _signed_in(laptop)  # signing in again works at once


def test_version_0_keeps_the_fingerprint_from_before_versions(app, user_factory):
    """Sessions open when this was deployed stay signed in."""
    user = user_factory()
    assert user.session_version == 0
    secret = app.secret_key.encode() if isinstance(app.secret_key, str) else app.secret_key
    before = hmac.new(secret, user.password_hash.encode(), hashlib.sha256).hexdigest()
    assert session_key(user, app.secret_key) == before
    user.session_version = 1
    assert session_key(user, app.secret_key) != before


def test_end_sessions_signs_a_microsoft_account_out_everywhere(app, client, db, user_manager, user_factory):
    person = user_factory(full_name="Sso Person", auth_source="sso", password_hash=None, sso_subject="subject-9")
    phone = app.test_client()
    sign_in(phone, person)
    assert _signed_in(phone)
    page = client.get(f"/admin/users/{person.id}/access").get_data(as_text=True)
    assert "End sessions" in page and f"/admin/users/{person.id}/end-sessions" in page

    response = post(client, f"/admin/users/{person.id}/end-sessions")
    assert response.status_code == 302 and response.headers["Location"].endswith(f"/admin/users/{person.id}/access")
    assert not _signed_in(phone)
    assert _signed_in(client)  # the manager's own session is untouched
    rows = db.scalars(select(AuditLog).where(AuditLog.action == "user_sessions_ended")).all()
    assert [(row.user_id, row.target_user_id) for row in rows] == [(user_manager.id, person.id)]


def test_end_sessions_is_not_for_yourself_or_someone_who_cannot_sign_in(client, db, user_manager, user_factory):
    own_page = client.get(f"/admin/users/{user_manager.id}/access").get_data(as_text=True)
    assert "/end-sessions" not in own_page
    post(client, f"/admin/users/{user_manager.id}/end-sessions")
    assert _signed_in(client)
    disabled = user_factory(status="disabled")
    assert "/end-sessions" not in client.get(f"/admin/users/{disabled.id}/access").get_data(as_text=True)
    assert post(client, f"/admin/users/{disabled.id}/end-sessions").status_code == 400
    assert db.scalars(select(AuditLog).where(AuditLog.action == "user_sessions_ended")).all() == []


def test_end_sessions_needs_manage_users(client, logged_in_user, user_factory):
    person = user_factory()
    assert post(client, f"/admin/users/{person.id}/end-sessions").status_code == 403
