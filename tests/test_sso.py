"""SSO callback behaviour with MSAL replaced by a fake."""

import pytest
from conftest import TENANT
from sqlalchemy import select

from tracker.auth import sso
from tracker.models import AuditLog, User


class FakeMsal:
    def __init__(self, result=None, error=None):
        self.result, self.error = result, error

    def initiate_auth_code_flow(self, scopes, redirect_uri, response_mode=None):
        self.response_mode = response_mode
        return {"auth_uri": "https://login.example/authorize", "state": "s", "nonce": "n"}

    def acquire_token_by_auth_code_flow(self, flow, args):
        if self.error:
            raise self.error
        return self.result


def claims(oid="oid-1", tid=TENANT, email="person@example.com", name="Person"):
    return {"id_token_claims": {"tid": tid, "oid": oid, "email": email, "name": name}}


def use(monkeypatch, fake):
    monkeypatch.setattr(sso, "_msal_app", lambda: fake)


def start(client, monkeypatch, fake):
    use(monkeypatch, fake)
    response = client.get("/auth/sso")
    assert response.status_code == 302 and response.headers["Location"].startswith("https://login.example/")
    assert fake.response_mode == "form_post"
    assert client.get_cookie(sso.FLOW_COOKIE, path="/auth/callback") is not None


def callback(client, state="s", **kwargs):
    """Microsoft's answer as it arrives with response_mode=form_post: a cross-site POST without the app's CSRF token."""
    return client.post("/auth/callback", data={"code": "c", "state": state}, **kwargs)


def location(response):
    return response.headers["Location"]


def test_start_keeps_the_flow_in_a_cookie_that_survives_the_cross_site_post(sso_client, monkeypatch):
    use(monkeypatch, FakeMsal(claims()))
    header = sso_client.get("/auth/sso").headers["Set-Cookie"]
    assert header.startswith(f"{sso.FLOW_COOKIE}=")
    for attribute in ("Secure", "HttpOnly", "SameSite=None", "Path=/auth/callback", "Max-Age=600"):
        assert attribute in header


def test_a_get_callback_is_refused_even_with_a_flow(sso_client, monkeypatch, db):
    start(sso_client, monkeypatch, FakeMsal(claims()))
    response = sso_client.get("/auth/callback?code=c&state=s")  # the code in the address: not accepted any more
    assert "/login" in location(response)
    assert db.scalar(select(User).where(User.email == "person@example.com")) is None
    assert sso_client.get_cookie(sso.FLOW_COOKIE, path="/auth/callback") is None


def test_a_tampered_flow_cookie_is_refused(sso_client, monkeypatch, db):
    start(sso_client, monkeypatch, FakeMsal(claims()))
    sso_client.set_cookie(sso.FLOW_COOKIE, "eyJzdGF0ZSI6InMifQ.forged", path="/auth/callback")
    assert "/login" in location(callback(sso_client))
    assert db.scalar(select(User).where(User.email == "person@example.com")) is None


def test_an_expired_flow_cookie_is_refused(sso_client, monkeypatch, db):
    start(sso_client, monkeypatch, FakeMsal(claims()))
    monkeypatch.setattr(sso, "FLOW_MAX_AGE_SECONDS", -1)
    assert "/login" in location(callback(sso_client))
    assert db.scalar(select(User).where(User.email == "person@example.com")) is None


def test_only_the_callback_skips_the_csrf_token(sso_client):
    assert sso_client.post("/logout").status_code == 400
    assert sso_client.post("/login", data={"email": "a@example.com", "password": "x"}).status_code == 400


def test_callback_without_flow_is_refused(sso_client, monkeypatch):
    use(monkeypatch, FakeMsal(claims()))
    response = callback(sso_client)
    assert response.status_code == 302 and "/login" in location(response)


def test_callback_flow_is_single_use(sso_client, monkeypatch):
    start(sso_client, monkeypatch, FakeMsal(claims(tid="other-tenant")))
    callback(sso_client)
    assert sso_client.get_cookie(sso.FLOW_COOKIE, path="/auth/callback") is None
    use(monkeypatch, FakeMsal(claims()))
    response = callback(sso_client)
    assert "/login" in location(response)  # replay: no flow left


def test_state_mismatch_refused(sso_client, monkeypatch):
    start(sso_client, monkeypatch, FakeMsal(error=ValueError("state mismatch")))
    response = callback(sso_client, state="wrong")
    assert "/login" in location(response)
    with sso_client.session_transaction() as sess:
        assert "user_id" not in sess


def test_token_error_refused(sso_client, monkeypatch):
    start(sso_client, monkeypatch, FakeMsal({"error": "invalid_grant"}))
    assert "/login" in location(callback(sso_client))


def test_tenant_mismatch_refused(sso_client, monkeypatch):
    start(sso_client, monkeypatch, FakeMsal(claims(tid="other-tenant")))
    response = callback(sso_client)
    assert "/login" in location(response)
    with sso_client.session_transaction() as sess:
        assert "user_id" not in sess


def test_missing_object_id_refused(sso_client, monkeypatch):
    start(sso_client, monkeypatch, FakeMsal(claims(oid="")))
    assert "/login" in location(callback(sso_client))


def test_first_login_creates_pending_user_with_subject(sso_client, monkeypatch, db):
    start(sso_client, monkeypatch, FakeMsal(claims()))
    response = callback(sso_client)
    assert location(response).endswith("/auth/pending")
    user = db.scalars(select(User).where(User.email == "person@example.com")).one()
    assert user.status == "pending" and user.auth_source == "sso"
    assert user.sso_subject == f"{TENANT}:oid-1" and user.password_hash is None
    assert db.scalars(select(AuditLog).where(AuditLog.action == "user_created")).one().entity_id == str(user.id)
    with sso_client.session_transaction() as sess:
        assert "user_id" not in sess


def test_second_login_matches_subject_even_if_email_changed(sso_client, monkeypatch, db, user_factory):
    user = user_factory(auth_source="sso", password_hash=None, sso_subject=f"{TENANT}:oid-1", email="old@example.com")
    start(sso_client, monkeypatch, FakeMsal(claims(email="new@example.com")))
    response = callback(sso_client)
    assert response.status_code == 302 and location(response).endswith("/")
    with sso_client.session_transaction() as sess:
        assert sess["user_id"] == user.id
    assert db.scalars(select(User)).all() == [user]


def test_existing_sso_user_without_subject_is_linked(sso_client, monkeypatch, db, user_factory):
    user = user_factory(auth_source="sso", password_hash=None, email="person@example.com")
    start(sso_client, monkeypatch, FakeMsal(claims()))
    callback(sso_client)
    db.expire_all()
    assert db.get(User, user.id).sso_subject == f"{TENANT}:oid-1"
    assert db.scalars(select(AuditLog).where(AuditLog.action == "sso_linked")).one()


def test_sso_user_with_different_subject_refused(sso_client, monkeypatch, user_factory):
    user_factory(auth_source="sso", password_hash=None, email="person@example.com", sso_subject=f"{TENANT}:other")
    start(sso_client, monkeypatch, FakeMsal(claims()))
    response = callback(sso_client)
    assert "/login" in location(response)
    with sso_client.session_transaction() as sess:
        assert "user_id" not in sess


def test_local_account_with_same_email_refused(sso_client, monkeypatch, user_factory, db):
    user = user_factory(email="person@example.com")
    start(sso_client, monkeypatch, FakeMsal(claims()))
    response = callback(sso_client, follow_redirects=True)
    assert b"signs in with a password" in response.data
    with sso_client.session_transaction() as sess:
        assert "user_id" not in sess
    db.expire_all()
    assert db.get(User, user.id).sso_subject is None


def test_disabled_sso_user_refused(sso_client, monkeypatch, user_factory):
    user_factory(auth_source="sso", password_hash=None, status="disabled", sso_subject=f"{TENANT}:oid-1")
    start(sso_client, monkeypatch, FakeMsal(claims()))
    callback(sso_client)
    with sso_client.session_transaction() as sess:
        assert "user_id" not in sess


def test_changed_entra_name_is_synced_and_logged(sso_client, monkeypatch, db, user_factory):
    user = user_factory(auth_source="sso", password_hash=None, sso_subject=f"{TENANT}:oid-1", full_name="Old Name")
    start(sso_client, monkeypatch, FakeMsal(claims(name="New Name")))
    callback(sso_client)
    db.expire_all()
    assert db.get(User, user.id).full_name == "New Name"
    entry = db.scalars(select(AuditLog).where(AuditLog.action == "user_name_synced")).one()
    assert entry.detail == {"before": "Old Name", "after": "New Name"}
    assert entry.user_id == user.id and entry.target_user_id == user.id and entry.entity_id == str(user.id)


def test_unchanged_entra_name_writes_no_entry(sso_client, monkeypatch, db, user_factory):
    user_factory(auth_source="sso", password_hash=None, sso_subject=f"{TENANT}:oid-1", full_name="Person")
    start(sso_client, monkeypatch, FakeMsal(claims(name="Person")))
    callback(sso_client)
    assert db.scalars(select(AuditLog).where(AuditLog.action == "user_name_synced")).all() == []


def test_first_sign_in_entry_names_the_new_user(sso_client, monkeypatch, db):
    start(sso_client, monkeypatch, FakeMsal(claims()))
    callback(sso_client)
    user = db.scalars(select(User).where(User.email == "person@example.com")).one()
    entry = db.scalars(select(AuditLog).where(AuditLog.action == "user_created")).one()
    assert entry.target_user_id == user.id


def test_sso_sign_in_and_link_entries_name_the_user(sso_client, monkeypatch, db, user_factory):
    user = user_factory(auth_source="sso", password_hash=None, email="person@example.com")
    start(sso_client, monkeypatch, FakeMsal(claims()))
    callback(sso_client)
    for action in ("sso_linked", "sso_login"):
        entry = db.scalars(select(AuditLog).where(AuditLog.action == action)).one()
        assert entry.target_user_id == user.id


@pytest.mark.parametrize(
    "overrides",
    [
        {"status": "pending", "auth_source": "sso", "password_hash": None},
        {"status": "disabled", "auth_source": "sso", "password_hash": None},
        {"status": "active", "auth_source": "local"},
    ],
)
def test_name_not_synced_for_a_user_who_is_not_active_or_not_microsoft(
    sso_client, monkeypatch, db, user_factory, overrides
):
    user = user_factory(sso_subject=f"{TENANT}:oid-1", full_name="Old Name", **overrides)
    start(sso_client, monkeypatch, FakeMsal(claims(name="New Name")))
    callback(sso_client)
    db.expire_all()
    assert db.get(User, user.id).full_name == "Old Name"
    assert db.scalars(select(AuditLog).where(AuditLog.action == "user_name_synced")).all() == []
