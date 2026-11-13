"""While Microsoft sign-in is on, one active administrator keeps signing in with a password (spec section 6.3)."""

import html

import pytest

from tests.conftest import post, sign_in
from tracker.auth.accounts import LAST_PASSWORD_ADMIN_MESSAGE, last_password_admin_refusal


def text_of(response) -> str:
    return html.unescape(response.get_data(as_text=True))


@pytest.fixture
def sso_admin(user_factory):
    """The signed-in administrator: a Microsoft account, so never the password administrator under test."""
    return user_factory(
        full_name="Microsoft Administrator",
        is_admin=True,
        auth_source="sso",
        password_hash=None,
        sso_subject="admin-subject",
    )


def test_last_password_administrator_refusal(db, user_factory):
    only = user_factory(is_admin=True)
    assert last_password_admin_refusal(db, only) == LAST_PASSWORD_ADMIN_MESSAGE
    # Only an active administrator who signs in with a password counts as another one.
    user_factory(is_admin=True, auth_source="sso", password_hash=None, sso_subject="s-1")
    user_factory(is_admin=True, status="disabled")
    user_factory()
    assert last_password_admin_refusal(db, only) == LAST_PASSWORD_ADMIN_MESSAGE
    user_factory(is_admin=True)
    assert last_password_admin_refusal(db, only) is None


def test_last_password_administrator_refusal_ignores_other_targets(db, user_factory):
    # No active administrator signs in with a password here, so only the kind of target keeps the guard silent.
    assert last_password_admin_refusal(db, user_factory()) is None
    assert last_password_admin_refusal(db, user_factory(is_admin=True, status="disabled")) is None
    assert last_password_admin_refusal(db, user_factory(is_admin=True, status="pending")) is None
    microsoft = user_factory(is_admin=True, auth_source="sso", password_hash=None, sso_subject="s-2")
    assert last_password_admin_refusal(db, microsoft) is None


def test_disable_refuses_the_last_password_administrator_while_sso_is_on(sso_client, sso_admin, user_factory, db):
    target = user_factory(is_admin=True)
    sign_in(sso_client, sso_admin)
    response = post(sso_client, f"/admin/users/{target.id}/disable", follow_redirects=True)
    assert LAST_PASSWORD_ADMIN_MESSAGE in text_of(response)
    db.refresh(target)
    assert target.status == "active"


def test_removing_administrator_refuses_the_last_password_administrator_while_sso_is_on(
    sso_client, sso_admin, user_factory, db
):
    target = user_factory(is_admin=True)
    sign_in(sso_client, sso_admin)
    response = post(sso_client, f"/admin/users/{target.id}/admin", {"is_admin": "0"}, follow_redirects=True)
    assert LAST_PASSWORD_ADMIN_MESSAGE in text_of(response)
    db.refresh(target)
    assert target.is_admin is True


def test_both_are_allowed_when_another_password_administrator_remains(sso_client, sso_admin, user_factory, db):
    demoted, disabled, remaining = (user_factory(is_admin=True) for _ in range(3))
    sign_in(sso_client, sso_admin)
    removed = post(sso_client, f"/admin/users/{demoted.id}/admin", {"is_admin": "0"}, follow_redirects=True)
    assert "Administrator access removed from" in text_of(removed)
    response = post(sso_client, f"/admin/users/{disabled.id}/disable", follow_redirects=True)
    assert "has been disabled." in text_of(response)
    db.expire_all()
    assert demoted.is_admin is False and disabled.status == "disabled"
    assert remaining.is_admin is True and remaining.status == "active"


def test_disable_is_allowed_while_sso_is_off(client, sso_admin, user_factory, db):
    target = user_factory(is_admin=True)
    sign_in(client, sso_admin)
    response = post(client, f"/admin/users/{target.id}/disable", follow_redirects=True)
    assert "has been disabled." in text_of(response)
    assert LAST_PASSWORD_ADMIN_MESSAGE not in text_of(response)
    db.refresh(target)
    assert target.status == "disabled"
