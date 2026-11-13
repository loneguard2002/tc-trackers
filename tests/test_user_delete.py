"""Deleting a person (design 2026-11-13, "Delete"): what goes, what stays, who may delete, and the refusals.

The person is a disabled former administrator with a team place, region access, a direct tracker role, a set held
directly, the lead of one tracker, their email on two recipient lists (one stored in mixed case), a queued send to that
email alone and a queued send shared with someone else.
"""

import html
import re
from datetime import date, datetime, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import event, func, select

from tests.conftest import post, sign_in
from tracker.admin.deletion import DeletionSummary, deletion_summary
from tracker.admin.users import _actions
from tracker.db import get_engine
from tracker.models import (
    AuditLog,
    PermissionSetHolder,
    Recipient,
    RegionGrant,
    ReportInput,
    ReportSend,
    TeamMember,
    Tracker,
    TrackerRole,
    User,
)

EMAIL = "jordan.lee@example.com"
MIXED = "Jordan.Lee@Example.com"
OTHER_EMAIL = "other@example.com"
DELETED_MESSAGE = "This person has been deleted."
HIDDEN = "Details hidden: you cannot open this tracker."
NEW_PASSWORD = "new-password-456"
NOW = datetime(2026, 11, 13, 12, 0, tzinfo=timezone.utc)
NOTE = "The email address becomes free, so the person can be added again as a new account. This cannot be undone."
# What the confirmation says for the fixture's person: what is removed, what stays.
SUMMARY_LINES = [
    "Removed",
    "Teams: 1",
    "Region access: 1",
    "Tracker roles: 1",
    "Permission sets: 1",
    "Lead of 1 tracker",
    "Report emails: 2 trackers",
    "Sign-in",
    "Kept",
    "3 activity entries",
    "1 report input",
    "Their name in all history",
    NOTE,
]


def text_of(response) -> str:
    return html.unescape(response.get_data(as_text=True))


def plain(markup: str) -> str:
    """The text of some markup, with the tags dropped and the spaces collapsed."""
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", markup)).split())


def title_with_email_beneath(markup: str) -> bool:
    return re.search(r"<h2[^>]*>Delete Jordan Lee</h2>\s*<p[^>]*>jordan\.lee@example\.com</p>", markup) is not None


def delete_url(user: User) -> str:
    return f"/admin/users/{user.id}/delete"


def reloaded(db, user: User) -> User:
    db.expire_all()
    return db.get(User, user.id)


def queued_send(tracker: Tracker, week: date, recipients: list[str]) -> ReportSend:
    return ReportSend(
        tracker_id=tracker.id, week_ending=week, trigger="manual", status="queued", recipients=recipients,
        pdf=b"%PDF-fake", attempts=1, next_attempt_at=NOW,
    )  # fmt: skip


@pytest.fixture
def s(
    db,
    logged_in_admin,
    user_factory,
    tracker_factory,
    team_factory,
    add_member,
    region_factory,
    region_grant,
    grant,
    give_set,
):
    person = user_factory(email=EMAIL, full_name="Jordan Lee", status="disabled", is_admin=True, sso_subject="sub-1")
    other = user_factory(full_name="Sam Other")
    team = team_factory(name="Windows")
    add_member(team, person, "editor")
    add_member(team, other, "viewer")
    region = region_factory("EMEA")
    region_grant(region, person, "viewer")
    laptops = tracker_factory(name="Laptop refresh")
    grant(person, laptops, "owner")
    desktops = tracker_factory(name="Desktop rollout", lead_user_id=person.id)
    auditors = give_set(["view_activity"], user=person, name="Auditors")
    queued = queued_send(desktops, date(2026, 9, 4), [MIXED])
    shared = queued_send(desktops, date(2026, 9, 11), [EMAIL, OTHER_EMAIL])
    login = AuditLog(action="login", entity="user", entity_id=str(person.id), user_id=person.id)
    db.add_all(
        [
            Recipient(tracker_id=laptops.id, email=EMAIL),
            Recipient(tracker_id=desktops.id, email=MIXED),
            Recipient(tracker_id=laptops.id, email=OTHER_EMAIL),
            queued,
            shared,
            login,
            AuditLog(action="user_disabled", entity="user", user_id=logged_in_admin.id, target_user_id=person.id),
            AuditLog(action="sso_linked", entity="user", user_id=person.id, target_user_id=person.id),
            AuditLog(action="login", entity="user", user_id=other.id),
            ReportInput(tracker_id=laptops.id, week_ending=date(2026, 9, 4), prepared_by=person.id),
        ]
    )
    db.commit()
    return SimpleNamespace(
        person=person,
        other=other,
        team=team,
        region=region,
        laptops=laptops,
        desktops=desktops,
        auditors=auditors,
        queued=queued,
        shared=shared,
        login=login,
    )


def assert_unchanged(db, s, status: str = "disabled") -> None:
    """Nothing of the person's was removed, and no delete was recorded."""
    person = reloaded(db, s.person)
    assert (person.status, person.is_admin, person.sso_subject) == (status, True, "sub-1")
    assert person.password_hash is not None
    for model in (TeamMember, RegionGrant, TrackerRole, PermissionSetHolder):
        assert len(db.scalars(select(model).where(model.user_id == s.person.id)).all()) == 1, model
    assert db.get(Tracker, s.desktops.id).lead_user_id == s.person.id
    assert db.scalar(select(func.count()).select_from(Recipient)) == 3
    assert (db.get(ReportSend, s.queued.id).status, db.get(ReportSend, s.queued.id).recipients) == ("queued", [MIXED])
    assert db.scalars(select(AuditLog).where(AuditLog.action == "user_deleted")).all() == []


# --- The delete -----------------------------------------------------------------------------------------------------


def test_delete_removes_access_leads_report_emails_and_sign_in(client, db, s):
    response = post(client, delete_url(s.person), {"confirm_email": "  Jordan.Lee@Example.com "})
    assert response.status_code == 302 and response.headers["Location"].endswith("/admin/users")
    assert "Deleted Jordan Lee (jordan.lee@example.com)." in text_of(client.get("/admin/users"))
    db.expire_all()
    for model in (TeamMember, RegionGrant, TrackerRole, PermissionSetHolder):
        assert db.scalars(select(model).where(model.user_id == s.person.id)).all() == [], model
    assert db.get(TeamMember, (s.team.id, s.other.id)) is not None  # someone else's place stays
    assert db.get(Tracker, s.desktops.id).lead_user_id is None
    assert db.scalars(select(Recipient.email)).all() == [OTHER_EMAIL]
    queued, shared = db.get(ReportSend, s.queued.id), db.get(ReportSend, s.shared.id)
    assert (queued.status, queued.error, queued.recipients, queued.next_attempt_at) == (
        "failed",
        "No recipients left",
        [],
        None,
    )
    assert (shared.status, shared.recipients, shared.error) == ("queued", [OTHER_EMAIL], None)
    assert shared.next_attempt_at == NOW
    person = db.get(User, s.person.id)
    assert (person.status, person.is_admin, person.password_hash, person.sso_subject) == ("deleted", False, None, None)
    assert (person.full_name, person.email) == ("Jordan Lee", EMAIL)


def test_delete_records_each_removal_and_a_summary(client, db, s, logged_in_admin):
    before = db.scalar(select(func.max(AuditLog.id)))
    post(client, delete_url(s.person), {"confirm_email": EMAIL})
    rows = db.scalars(select(AuditLog).where(AuditLog.id > before).order_by(AuditLog.id)).all()
    summary = {
        "name": "Jordan Lee",
        "email": EMAIL,
        "teams": 1,
        "regions": 1,
        "tracker_roles": 1,
        "permission_sets": 1,
        "trackers_led": 1,
        "report_emails": 2,
    }
    person_id = str(s.person.id)
    assert [(row.action, row.tracker_id, row.entity, row.entity_id, row.detail) for row in rows] == [
        ("team_member_removed", None, "team", str(s.team.id), {"team": "Windows", "role": "editor"}),
        ("region_access_removed", None, "region", str(s.region.id), {"region": "EMEA", "role": "viewer"}),
        ("role_removed", s.laptops.id, "user", person_id, {"before": "owner", "after": None}),
        ("permission_set_holder_removed", None, "permission_set", str(s.auditors.id), {"set": "Auditors"}),
        ("settings_updated", s.desktops.id, "tracker", str(s.desktops.id), {"lead": ["Jordan Lee", None]}),
        ("recipient_removed", s.desktops.id, "email_settings", MIXED, {"email": MIXED}),
        ("recipient_removed", s.laptops.id, "email_settings", EMAIL, {"email": EMAIL}),
        ("user_deleted", None, "user", person_id, summary),
    ]
    assert {(row.user_id, row.target_user_id) for row in rows} == {(logged_in_admin.id, s.person.id)}


def test_history_keeps_the_name_and_the_email_can_be_used_again(client, db, s):
    post(client, delete_url(s.person), {"confirm_email": EMAIL})
    performer = select(User.id, User.full_name).join(AuditLog, AuditLog.user_id == User.id)
    assert db.execute(performer.where(AuditLog.id == s.login.id)).one() == (s.person.id, "Jordan Lee")
    response = post(client, "/admin/users", {"email": EMAIL, "full_name": "Jordan Lee", "password": "a long password"})
    assert response.status_code == 302
    again = db.scalars(select(User).where(User.email == EMAIL, User.status == "active")).one()
    assert again.id != s.person.id


def test_summary_counts(db, s):
    db.add(Recipient(tracker_id=s.laptops.id, email="JORDAN.LEE@EXAMPLE.COM"))  # a second row on the same tracker
    db.commit()
    assert deletion_summary(db, s.person) == DeletionSummary(
        teams=[(s.team.id, "Windows")],
        regions=[(s.region.id, "EMEA", "viewer")],
        roles=[(s.laptops.id, "Laptop refresh", "owner")],
        sets=[(s.auditors.id, "Auditors")],
        led=[(s.desktops.id, "Desktop rollout")],
        recipient_trackers=[(s.desktops.id, "Desktop rollout"), (s.laptops.id, "Laptop refresh")],
        activity_entries=3,
        report_inputs=1,
    )


# --- The confirmation ------------------------------------------------------------------------------------------------


def test_access_page_has_the_delete_dialog_for_a_disabled_person(client, s):
    page = text_of(client.get(f"/admin/users/{s.person.id}/access"))
    assert f'href="{delete_url(s.person)}"' in page and "data-delete-person" in page  # the danger button
    dialog = re.search(r'<dialog id="delete-dialog".*?</dialog>', page, re.S).group(0)
    assert title_with_email_beneath(dialog)
    text = plain(dialog)
    assert "Type jordan.lee@example.com to confirm" in text
    for line in SUMMARY_LINES:
        assert line in text, line
    assert 'data-email="jordan.lee@example.com"' in dialog
    assert re.search(r"<button\b(?=[^>]*\bdata-delete-submit\b)(?=[^>]*\bdisabled\b)", dialog)  # waits for the email
    assert f'action="{delete_url(s.person)}"' in dialog


def test_the_delete_dialog_is_offered_only_where_delete_is_allowed(client, s, user_factory, give_set):
    assert 'id="delete-dialog"' in text_of(client.get(f"/admin/users/{s.person.id}/access"))  # an administrator sees it
    for path in (f"/admin/users/{s.other.id}/access", "/admin/users"):  # an active person; the list has no dialog
        page = text_of(client.get(path))
        assert 'id="delete-dialog"' not in page and "data-delete-person" not in page, path
    manager = user_factory(full_name="Manager")
    give_set(["manage_users"], user=manager)
    sign_in(client, manager)
    page = text_of(client.get(f"/admin/users/{s.person.id}/access"))  # a disabled person, seen by a non-administrator
    assert 'id="delete-dialog"' not in page and "data-delete-person" not in page


def test_delete_page_works_without_javascript(client, s):
    response = client.get(delete_url(s.person))
    assert response.status_code == 200
    page = text_of(response)
    assert "<title>Delete Jordan Lee · " in page
    assert title_with_email_beneath(page)
    text = plain(page)
    assert "Type jordan.lee@example.com to confirm" in text
    for line in SUMMARY_LINES:
        assert line in text, line
    assert f'<form method="post" action="{delete_url(s.person)}">' in page and 'name="confirm_email"' in page
    assert re.search(r'<button class="button danger" type="submit">\s*Delete\s*</button>', page)  # not locked
    for href, name in ((f"/admin/users/{s.person.id}/access", "Access"), ("/admin/users", "Users")):
        assert f'<a href="{href}">{name}</a>' in page  # the title crumb
    assert 'id="delete-dialog"' not in page


# --- Who may delete whom --------------------------------------------------------------------------------------------


def test_delete_is_for_administrators_only(client, db, s, user_factory, give_set):
    manager = user_factory(full_name="Manager")
    give_set(["manage_users"], user=manager)
    sign_in(client, manager)
    assert client.get(delete_url(s.person)).status_code == 403
    assert post(client, delete_url(s.person), {"confirm_email": EMAIL}).status_code == 403
    assert_unchanged(db, s)


def test_the_delete_locks_the_person_without_blocking_foreign_keys(client, db, s):
    """``FOR NO KEY UPDATE``, not ``FOR UPDATE``: a retry of a queued send holds the send and then writes an entry whose
    foreign key takes ``KEY SHARE`` on its creator's row, so ``FOR UPDATE`` on that person could deadlock with it."""
    statements = []

    def capture(_connection, _cursor, statement, *_args):
        statements.append(statement)

    engine = get_engine(client.application)
    event.listen(engine, "before_cursor_execute", capture)
    try:
        assert post(client, delete_url(s.person), {"confirm_email": EMAIL}).status_code == 302
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    locks = [lock for st in statements for lock in re.findall(r"\bFROM users\b.*?\bFOR ((?:NO KEY )?UPDATE)", st, re.S)]
    assert locks == ["NO KEY UPDATE"]
    assert reloaded(db, s.person).status == "deleted"


def test_delete_needs_a_disabled_or_pending_account(client, db, s, user_factory):
    """A delete posted after the person was re-enabled in another tab is refused, and nothing changes."""
    assert client.get(delete_url(s.person)).status_code == 200
    assert post(client, f"/admin/users/{s.person.id}/enable").status_code == 302
    response = post(client, delete_url(s.person), {"confirm_email": EMAIL})
    assert response.status_code == 400
    assert "Only a disabled or pending person can be deleted." in text_of(response)
    assert client.get(delete_url(s.person)).status_code == 400
    assert_unchanged(db, s, status="active")
    pending = user_factory(email="new.starter@example.com", status="pending")
    assert client.get(delete_url(pending)).status_code == 200
    assert post(client, delete_url(pending), {"confirm_email": "new.starter@example.com"}).status_code == 302
    assert reloaded(db, pending).status == "deleted"


def test_delete_refuses_own_account(client, db, logged_in_admin):
    own = delete_url(logged_in_admin)
    for response in (client.get(own), post(client, own, {"confirm_email": logged_in_admin.email})):
        assert response.status_code == 302 and response.headers["Location"].endswith("/admin/users")
    assert "You cannot delete your own account." in text_of(client.get("/admin/users"))
    assert reloaded(db, logged_in_admin).status == "active"


@pytest.mark.parametrize("typed", ["jordan.lee@example.org", "jordan.lee", ""])
def test_a_mismatched_email_is_refused(client, db, s, typed):
    response = post(client, delete_url(s.person), {"confirm_email": typed})
    assert response.status_code == 400
    assert "The email does not match." in text_of(response)
    assert_unchanged(db, s)


def test_delete_is_offered_to_administrators_for_disabled_or_pending_people(
    app, db, s, logged_in_admin, user_factory, give_set
):
    pending, active, manager = user_factory(status="pending"), user_factory(), user_factory()
    give_set(["manage_users"], user=manager)
    with app.app_context():
        assert _actions(db, logged_in_admin, s.person)["delete"] is True
        assert _actions(db, logged_in_admin, pending)["delete"] is True
        assert _actions(db, logged_in_admin, active)["delete"] is False
        assert _actions(db, logged_in_admin, logged_in_admin)["delete"] is False
        assert _actions(db, manager, pending)["delete"] is False


def test_a_deleted_person_cannot_be_changed_again(app, client, sso_client, db, s, logged_in_admin):
    post(client, delete_url(s.person), {"confirm_email": EMAIL})
    entries = db.scalar(select(func.count()).select_from(AuditLog))
    person_id = s.person.id
    for path, data in [
        (f"/admin/users/{person_id}/approve", {}),
        (f"/admin/users/{person_id}/enable", {}),
        (f"/admin/users/{person_id}/disable", {}),
        (f"/admin/users/{person_id}/admin", {"is_admin": "1"}),
        (f"/admin/users/{person_id}/password", {"password": NEW_PASSWORD, "password_confirm": NEW_PASSWORD}),
        (f"/trackers/{s.laptops.id}/roles", {"user_id": str(person_id), "role": "viewer"}),
        (f"/trackers/{s.laptops.id}/roles", {"user_id": str(person_id), "role": "remove"}),
    ]:
        response = post(client, path, data)
        assert response.status_code == 400 and DELETED_MESSAGE in text_of(response), (path, data)
    assert client.get(f"/admin/users/{person_id}/password").status_code == 400
    assert post(client, delete_url(s.person), {"confirm_email": EMAIL}).status_code == 400
    sign_in(sso_client, logged_in_admin)
    assert post(sso_client, f"/admin/users/{person_id}/sign-in").status_code == 400
    person = reloaded(db, s.person)
    assert (person.status, person.is_admin, person.password_hash, person.auth_source) == (
        "deleted",
        False,
        None,
        "local",
    )
    assert db.scalars(select(TrackerRole).where(TrackerRole.user_id == person_id)).all() == []
    assert db.scalar(select(func.count()).select_from(AuditLog)) == entries
    with app.app_context():
        assert set(_actions(db, logged_in_admin, person).values()) == {False}


# --- After the delete -----------------------------------------------------------------------------------------------


def test_a_tracker_whose_lead_was_deleted_still_opens_its_settings(client, s):
    post(client, delete_url(s.person), {"confirm_email": EMAIL})
    response = client.get(f"/trackers/{s.desktops.id}/settings")
    assert response.status_code == 200
    assert '<option value="" selected>Choose a person</option>' in text_of(response)  # the Lead field is empty


def test_activity_hides_tracker_removals_from_viewers_who_cannot_open_the_tracker(
    client, db, s, user_factory, give_set, grant
):
    post(client, delete_url(s.person), {"confirm_email": EMAIL})
    viewer = user_factory()
    give_set(["view_activity"], user=viewer)
    grant(viewer, s.desktops, "viewer")  # Desktop rollout only, not Laptop refresh
    sign_in(client, viewer)
    page = text_of(client.get("/admin/activity"))

    def row(action: str) -> str:
        entry = db.scalars(select(AuditLog).where(AuditLog.action == action)).one()
        return re.search(rf'<tr data-entry="{entry.id}">(.*?)</tr>', page, re.S).group(1)

    assert HIDDEN in row("role_removed") and "owner" not in row("role_removed")
    assert HIDDEN not in row("settings_updated") and '<span class="activity-field">lead</span>' in row(
        "settings_updated"
    )
    summary = row("user_deleted")
    assert HIDDEN not in summary and "jordan.lee@example.com" in summary
    assert "Laptop refresh" not in summary and "Desktop rollout" not in summary
