"""A deleted person stays in ``users`` with their history, but no sign-in or lookup by email finds them."""

from sqlalchemy import select

from tests.conftest import TEST_PASSWORD, post
from tests.test_sso import FakeMsal, claims, start
from tracker.models import User


def test_password_sign_in_skips_a_deleted_account(client, user_factory):
    user_factory(email="a@example.com", status="deleted")
    response = post(client, "/login", {"email": "a@example.com", "password": TEST_PASSWORD})
    assert b"Invalid email or password." in response.data
    with client.session_transaction() as sess:
        assert "user_id" not in sess


def test_password_sign_in_finds_the_live_account_beside_a_deleted_one(client, user_factory):
    user_factory(email="a@example.com", status="deleted")
    active = user_factory(email="a@example.com")
    response = post(client, "/login", {"email": "a@example.com", "password": TEST_PASSWORD})
    assert response.status_code == 302
    with client.session_transaction() as sess:
        assert sess["user_id"] == active.id


def test_microsoft_sign_in_ignores_a_deleted_account_with_the_same_email(sso_client, monkeypatch, db, user_factory):
    deleted = user_factory(auth_source="sso", password_hash=None, email="person@example.com", status="deleted")
    start(sso_client, monkeypatch, FakeMsal(claims()))
    sso_client.get("/auth/callback?code=c&state=s")
    created = db.scalars(select(User).where(User.email == "person@example.com", User.status == "pending")).one()
    assert created.id != deleted.id and created.sso_subject is not None


def test_reset_password_command_skips_a_deleted_account(app, user_factory):
    user_factory(email="gone@example.com", status="deleted")
    result = app.test_cli_runner().invoke(args=["reset-password", "gone@example.com", "--password", "new-password-456"])
    assert result.exit_code != 0
    assert "No user with the email" in result.output
