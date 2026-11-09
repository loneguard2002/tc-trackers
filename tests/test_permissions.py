"""Permission sets: what a user holds, the gated screens and the links that follow (database required)."""

import pytest
from sqlalchemy import select

from tests.conftest import post
from tracker.auth import PERMISSIONS, has_permission, user_permissions
from tracker.models import AuditLog, Tracker

TRACKER_FORM = {
    "name": "Rollout",
    "unit_label": "thin clients",
    "group_label": "Location",
    "description": "",
    "week_ending_weekday": "4",
    "start_date": "2026-09-02",
    "last_week_ending": "2026-12-25",
    "target_completion": "2026-12-18",
    "completed_before_first": "0",
    "moving_average_weeks": "3",
}


def test_permission_names_in_order():
    assert list(PERMISSIONS) == [
        "manage_users",
        "manage_teams",
        "create_trackers",
        "import_workbooks",
        "manage_email_settings",
        "view_all_trackers",
        "view_activity",
    ]


def test_admin_holds_every_permission(db, user_factory):
    assert user_permissions(db, user_factory(is_admin=True)) == frozenset(PERMISSIONS)


def test_permission_held_directly(db, user_factory, give_set):
    user = user_factory()
    give_set(["view_activity"], user=user)
    assert user_permissions(db, user) == {"view_activity"}


def test_permission_held_through_a_direct_team_membership(db, user_factory, team_factory, add_member, give_set):
    user, team = user_factory(), team_factory()
    add_member(team, user, "viewer")
    give_set(["view_activity", "create_trackers"], team=team)
    assert user_permissions(db, user) == {"view_activity", "create_trackers"}


def test_permission_not_held_through_teams_below_or_above(db, user_factory, team_factory, add_member, give_set):
    a = team_factory()
    b = team_factory(parent=a)
    c = team_factory(parent=b)
    above, below = user_factory(), user_factory()
    add_member(a, above, "owner")
    add_member(c, below, "owner")
    give_set(["view_activity"], team=b)
    assert user_permissions(db, above) == frozenset()
    assert user_permissions(db, below) == frozenset()


def test_unknown_permission_names_in_the_database_are_ignored(db, user_factory, give_set):
    user = user_factory()
    give_set(["approve", "view_activity"], user=user)
    assert user_permissions(db, user) == {"view_activity"}


@pytest.mark.parametrize("status", ["pending", "disabled"])
def test_inactive_user_holds_nothing(db, user_factory, give_set, status):
    user = user_factory(status=status)
    give_set(["view_activity"], user=user)
    assert user_permissions(db, user) == frozenset()


def test_has_permission_rejects_an_unknown_name(app, user_factory):
    with app.test_request_context("/"), pytest.raises(ValueError):
        has_permission(None, "approve")


def test_has_permission_is_false_for_nobody(app):
    with app.test_request_context("/"):
        assert has_permission(None, "view_activity") is False


@pytest.mark.parametrize(
    "method,url",
    [
        ("get", "/trackers/new"),
        ("post", "/trackers/new"),
        ("get", "/import"),
        ("post", "/import/confirm"),
        ("get", "/admin/smtp"),
        ("post", "/admin/smtp"),
    ],
)
def test_screens_refused_without_the_permission(client, logged_in_user, method, url):
    response = client.get(url) if method == "get" else post(client, url)
    assert response.status_code == 403


def test_anonymous_user_is_sent_to_sign_in(client):
    response = client.get("/import")
    assert response.status_code == 302 and "/login" in response.headers["Location"]


def test_create_trackers_holder_creates_a_tracker(client, logged_in_user, give_set, db, labels_form):
    give_set(["create_trackers"], user=logged_in_user)
    response = post(client, "/trackers/new", {**TRACKER_FORM, **labels_form})
    assert response.status_code == 302
    assert db.scalar(select(Tracker).where(Tracker.name == "Rollout")) is not None


def test_import_workbooks_holder_opens_import(client, logged_in_user, give_set):
    give_set(["import_workbooks"], user=logged_in_user)
    assert client.get("/import").status_code == 200


def test_email_settings_holder_saves_the_sender_address(client, logged_in_user, give_set, db):
    give_set(["manage_email_settings"], user=logged_in_user)
    response = post(client, "/admin/smtp", {"smtp_from": "reports@example.com"})
    assert response.status_code == 302
    entry = db.scalar(select(AuditLog).where(AuditLog.action == "smtp_settings_updated"))
    assert entry is not None and entry.detail == {"changed": ["smtp_from"]}


def test_email_settings_holder_sees_the_server_read_only_and_cannot_change_it(client, logged_in_user, give_set, db):
    from tracker.admin.smtp import SERVER_LOCKED_MESSAGE
    from tracker.models import AppSetting

    for key, value in (("smtp_host", "smtp.example.com"), ("smtp_port", "587"), ("smtp_auth", "plain")):
        db.merge(AppSetting(key=key, value=value))
    db.commit()
    give_set(["manage_email_settings"], user=logged_in_user)
    page = client.get("/admin/smtp").get_data(as_text=True)
    assert 'name="smtp_from"' in page and 'value="smtp.example.com"' in page
    for key in ("smtp_host", "smtp_port", "smtp_auth", "smtp_user", "smtp_tenant_id", "smtp_client_id"):
        assert f'name="{key}"' not in page
    for key, value in (
        ("smtp_host", "evil.example.com"),
        ("smtp_port", "25"),
        ("smtp_auth", "none"),
        ("smtp_user", "me@example.com"),
        ("smtp_tenant_id", "other"),
        ("smtp_client_id", "other"),
    ):
        response = post(client, "/admin/smtp", {"smtp_from": "x@example.com", key: value})
        assert response.status_code == 400 and SERVER_LOCKED_MESSAGE in response.get_data(as_text=True)
    db.expire_all()
    stored = {row.key: row.value for row in db.scalars(select(AppSetting))}
    assert stored == {"smtp_host": "smtp.example.com", "smtp_port": "587", "smtp_auth": "plain"}
    assert db.scalar(select(AuditLog).where(AuditLog.action == "smtp_settings_updated")) is None
    unchanged = {"smtp_host": "smtp.example.com", "smtp_from": "x@example.com"}  # a stale copy of the same value
    assert post(client, "/admin/smtp", unchanged).status_code == 302
    db.expire_all()
    assert db.get(AppSetting, "smtp_from").value == "x@example.com"
    assert db.get(AppSetting, "smtp_host").value == "smtp.example.com"


def test_administrator_still_changes_every_email_setting(client, logged_in_admin, db):
    from tracker.models import AppSetting

    page = client.get("/admin/smtp").get_data(as_text=True)
    assert 'name="smtp_host"' in page and 'name="smtp_auth"' in page and "readonly" not in page
    assert post(client, "/admin/smtp", {"smtp_host": "new.example.com", "smtp_auth": "none"}).status_code == 302
    assert db.get(AppSetting, "smtp_host").value == "new.example.com"


def test_email_settings_holder_sets_the_report_email_subject(client, logged_in_user, give_set, db):
    from tracker.models import AppSetting

    give_set(["manage_email_settings"], user=logged_in_user)
    response = post(client, "/admin/smtp", {"smtp_from": "", "report_email_subject": "{{summary}} [weekly]"})
    assert response.status_code == 302
    assert db.get(AppSetting, "report_email_subject").value == "{{summary}} [weekly]"
