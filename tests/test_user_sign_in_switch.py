"""Switching a password account to Microsoft sign-in, and the one administrator who keeps a password (spec 6.3)."""

import html

import pytest
from markupsafe import escape
from sqlalchemy import select

from tests.conftest import TEST_PASSWORD, post, sign_in
from tests.test_sso import FakeMsal, claims, start
from tests.test_teams import entries
from tracker.auth.accounts import (
    ELEVATED_MESSAGE,
    LAST_PASSWORD_ADMIN_MESSAGE,
    OWN_ACCOUNT_MESSAGE,
    last_password_admin_refusal,
)
from tracker.models import TeamMember, TrackerRole


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


# --- Switching a password account to Microsoft sign-in ---------------------------------------------------------------


def switch(client, person, **kwargs):
    return post(client, f"/admin/users/{person.id}/sign-in", **kwargs)


def test_switch_then_microsoft_sign_in_links_and_keeps_access(
    sso_app, sso_client, sso_admin, user_factory, team_factory, add_member, tracker_factory, grant, db, monkeypatch
):
    person = user_factory(full_name="Jordan Lee")
    team = team_factory()
    add_member(team, person, "editor")
    tracker = tracker_factory()
    grant(person, tracker, "viewer")
    sign_in(sso_client, sso_admin)
    response = switch(sso_client, person, follow_redirects=True)
    assert "Jordan Lee now signs in with Microsoft." in text_of(response)
    db.expire_all()
    assert person.auth_source == "sso" and person.password_hash is None and person.sso_subject is None
    (entry,) = entries(db, "sign_in_switched")
    assert entry.detail == {"before": "local", "after": "sso"}
    assert (entry.user_id, entry.target_user_id, entry.entity) == (sso_admin.id, person.id, "user")

    person_client = sso_app.test_client()
    start(person_client, monkeypatch, FakeMsal(claims(email=person.email)))
    person_client.get("/auth/callback?code=c&state=s")
    with person_client.session_transaction() as sess:
        assert sess["user_id"] == person.id
    db.expire_all()
    assert person.sso_subject is not None
    assert len(entries(db, "sso_linked")) == 1
    assert db.execute(select(TeamMember.team_id, TeamMember.role).where(TeamMember.user_id == person.id)).all() == [
        (team.id, "editor")
    ]
    assert db.execute(
        select(TrackerRole.tracker_id, TrackerRole.role).where(TrackerRole.user_id == person.id)
    ).all() == [(tracker.id, "viewer")]


def test_the_old_password_stops_working(sso_app, sso_client, sso_admin, user_factory):
    person = user_factory()
    sign_in(sso_client, sso_admin)
    switch(sso_client, person)
    person_client = sso_app.test_client()
    response = post(person_client, "/login", {"email": person.email, "password": TEST_PASSWORD})
    assert "Invalid email or password." in text_of(response)
    with person_client.session_transaction() as sess:
        assert "user_id" not in sess


@pytest.mark.parametrize("kind", ["self", "admin", "direct_set"])
def test_switch_refused_for_a_manage_users_holder_on_own_or_elevated_account(
    sso_client, user_factory, give_set, db, kind
):
    holder = user_factory(full_name="Manager")
    give_set(["manage_users"], user=holder)
    if kind == "self":
        target = holder
    elif kind == "admin":
        target = user_factory(is_admin=True)
    else:
        target = user_factory()
        give_set(["view_activity"], user=target)
    sign_in(sso_client, holder)
    response = switch(sso_client, target, follow_redirects=True)
    assert (OWN_ACCOUNT_MESSAGE if kind == "self" else ELEVATED_MESSAGE) in text_of(response)
    db.expire_all()
    assert target.auth_source == "local" and target.password_hash is not None
    assert entries(db, "sign_in_switched") == []


def test_switch_refused_on_the_last_password_administrator(sso_client, sso_admin, user_factory, db):
    target = user_factory(is_admin=True)
    sign_in(sso_client, sso_admin)
    response = switch(sso_client, target, follow_redirects=True)
    assert LAST_PASSWORD_ADMIN_MESSAGE in text_of(response)
    db.expire_all()
    assert target.auth_source == "local" and target.password_hash is not None
    assert entries(db, "sign_in_switched") == []


def test_switch_is_allowed_when_another_password_administrator_remains(sso_client, sso_admin, user_factory, db):
    target, remaining = user_factory(is_admin=True), user_factory(is_admin=True)
    sign_in(sso_client, sso_admin)
    response = switch(sso_client, target, follow_redirects=True)
    assert "now signs in with Microsoft." in text_of(response)
    db.expire_all()
    assert target.auth_source == "sso" and remaining.auth_source == "local"


def test_switch_needs_sso_and_a_password_account(client, sso_client, logged_in_admin, sso_admin, user_factory, db):
    local = user_factory(full_name="Local Person")
    assert switch(client, local).status_code == 400
    assert "Switch to Microsoft sign-in" not in text_of(client.get(f"/admin/users/{local.id}/access"))
    microsoft = user_factory(auth_source="sso", password_hash=None, sso_subject="s-3")
    sign_in(sso_client, sso_admin)
    assert switch(sso_client, microsoft).status_code == 400
    assert "Switch to Microsoft sign-in" not in text_of(sso_client.get(f"/admin/users/{microsoft.id}/access"))
    db.expire_all()
    assert local.auth_source == "local" and microsoft.sso_subject == "s-3"
    assert entries(db, "sign_in_switched") == []


@pytest.mark.parametrize("status", ["pending", "deleted"])
def test_switch_needs_an_active_or_disabled_account(sso_client, sso_admin, user_factory, db, status):
    target = user_factory(status=status)
    sign_in(sso_client, sso_admin)
    assert switch(sso_client, target).status_code == 400
    db.expire_all()
    assert target.auth_source == "local" and target.password_hash is not None


def test_a_disabled_password_account_can_be_switched(sso_client, sso_admin, user_factory, db):
    target = user_factory(status="disabled")
    sign_in(sso_client, sso_admin)
    assert "Switch to Microsoft sign-in" in text_of(sso_client.get(f"/admin/users/{target.id}/access"))
    switch(sso_client, target)
    db.expire_all()
    assert target.auth_source == "sso" and target.status == "disabled"


def test_access_page_offers_the_switch_with_its_confirmation(sso_client, sso_admin, user_factory):
    person = user_factory(full_name="Jordan O'Lee & Co", email="jordan.lee@example.com")
    sign_in(sso_client, sso_admin)
    page = sso_client.get(f"/admin/users/{person.id}/access").get_data(as_text=True)
    assert "Switch to Microsoft sign-in" in page
    assert f'action="/admin/users/{person.id}/sign-in"' in page
    confirmation = (
        "Switch Jordan O'Lee & Co (jordan.lee@example.com) to Microsoft sign-in? Their password stops working now. "
        "They keep all their access, and sign in with Microsoft using this email address from now on."
    )
    assert f'data-confirm="{escape(confirmation)}"' in page
    box = page.split("data-confirm-box", 1)[1]
    assert f"<strong>{escape(person.full_name)} ({person.email})</strong>" in box
    assert "Their password stops working now." in box
