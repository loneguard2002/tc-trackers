"""SSO callback behaviour with MSAL replaced by a fake."""

import pytest
from conftest import DATABASE_URL
from sqlalchemy import select

from tracker.app import create_app
from tracker.auth import sso
from tracker.models import AuditLog, User

TENANT = "tenant-1"


class FakeMsal:
    def __init__(self, result=None, error=None):
        self.result, self.error = result, error

    def initiate_auth_code_flow(self, scopes, redirect_uri):
        return {"auth_uri": "https://login.example/authorize", "state": "s", "nonce": "n"}

    def acquire_token_by_auth_code_flow(self, flow, args):
        if self.error:
            raise self.error
        return self.result


def claims(oid="oid-1", tid=TENANT, email="person@example.com", name="Person"):
    return {"id_token_claims": {"tid": tid, "oid": oid, "email": email, "name": name}}


@pytest.fixture
def sso_app():
    return create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test",
            "DATABASE_URL": DATABASE_URL,
            "SESSION_COOKIE_SECURE": False,
            "SSO_TENANT_ID": TENANT,
            "SSO_CLIENT_ID": "client",
            "SSO_CLIENT_SECRET": "secret",
        }
    )


@pytest.fixture
def sso_client(sso_app):
    return sso_app.test_client()


def use(monkeypatch, fake):
    monkeypatch.setattr(sso, "_msal_app", lambda: fake)


def start(client, monkeypatch, fake):
    use(monkeypatch, fake)
    response = client.get("/auth/sso")
    assert response.status_code == 302 and response.headers["Location"].startswith("https://login.example/")
    with client.session_transaction() as sess:
        assert sess["sso_flow"]["state"] == "s"


def location(response):
    return response.headers["Location"]


def test_callback_without_flow_is_refused(sso_client, monkeypatch):
    use(monkeypatch, FakeMsal(claims()))
    response = sso_client.get("/auth/callback?code=c&state=s")
    assert response.status_code == 302 and "/login" in location(response)


def test_callback_flow_is_single_use(sso_client, monkeypatch):
    start(sso_client, monkeypatch, FakeMsal(claims(tid="other-tenant")))
    sso_client.get("/auth/callback?code=c&state=s")
    with sso_client.session_transaction() as sess:
        assert "sso_flow" not in sess
    use(monkeypatch, FakeMsal(claims()))
    response = sso_client.get("/auth/callback?code=c&state=s")
    assert "/login" in location(response)  # replay: no flow left


def test_state_mismatch_refused(sso_client, monkeypatch):
    start(sso_client, monkeypatch, FakeMsal(error=ValueError("state mismatch")))
    response = sso_client.get("/auth/callback?code=c&state=wrong")
    assert "/login" in location(response)
    with sso_client.session_transaction() as sess:
        assert "user_id" not in sess


def test_token_error_refused(sso_client, monkeypatch):
    start(sso_client, monkeypatch, FakeMsal({"error": "invalid_grant"}))
    assert "/login" in location(sso_client.get("/auth/callback?code=c&state=s"))


def test_tenant_mismatch_refused(sso_client, monkeypatch):
    start(sso_client, monkeypatch, FakeMsal(claims(tid="other-tenant")))
    response = sso_client.get("/auth/callback?code=c&state=s")
    assert "/login" in location(response)
    with sso_client.session_transaction() as sess:
        assert "user_id" not in sess


def test_missing_object_id_refused(sso_client, monkeypatch):
    start(sso_client, monkeypatch, FakeMsal(claims(oid="")))
    assert "/login" in location(sso_client.get("/auth/callback?code=c&state=s"))


def test_first_login_creates_pending_user_with_subject(sso_client, monkeypatch, db):
    start(sso_client, monkeypatch, FakeMsal(claims()))
    response = sso_client.get("/auth/callback?code=c&state=s")
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
    response = sso_client.get("/auth/callback?code=c&state=s")
    assert response.status_code == 302 and location(response).endswith("/")
    with sso_client.session_transaction() as sess:
        assert sess["user_id"] == user.id
    assert db.scalars(select(User)).all() == [user]


def test_existing_sso_user_without_subject_is_linked(sso_client, monkeypatch, db, user_factory):
    user = user_factory(auth_source="sso", password_hash=None, email="person@example.com")
    start(sso_client, monkeypatch, FakeMsal(claims()))
    sso_client.get("/auth/callback?code=c&state=s")
    db.expire_all()
    assert db.get(User, user.id).sso_subject == f"{TENANT}:oid-1"
    assert db.scalars(select(AuditLog).where(AuditLog.action == "sso_linked")).one()


def test_sso_user_with_different_subject_refused(sso_client, monkeypatch, user_factory):
    user_factory(auth_source="sso", password_hash=None, email="person@example.com", sso_subject=f"{TENANT}:other")
    start(sso_client, monkeypatch, FakeMsal(claims()))
    response = sso_client.get("/auth/callback?code=c&state=s")
    assert "/login" in location(response)
    with sso_client.session_transaction() as sess:
        assert "user_id" not in sess


def test_local_account_with_same_email_refused(sso_client, monkeypatch, user_factory, db):
    user = user_factory(email="person@example.com")
    start(sso_client, monkeypatch, FakeMsal(claims()))
    response = sso_client.get("/auth/callback?code=c&state=s", follow_redirects=True)
    assert b"signs in with a password" in response.data
    with sso_client.session_transaction() as sess:
        assert "user_id" not in sess
    db.expire_all()
    assert db.get(User, user.id).sso_subject is None


def test_disabled_sso_user_refused(sso_client, monkeypatch, user_factory):
    user_factory(auth_source="sso", password_hash=None, status="disabled", sso_subject=f"{TENANT}:oid-1")
    start(sso_client, monkeypatch, FakeMsal(claims()))
    sso_client.get("/auth/callback?code=c&state=s")
    with sso_client.session_transaction() as sess:
        assert "user_id" not in sess
