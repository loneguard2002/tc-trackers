"""Activity screen (database required)."""

import html
import json
import re
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from tests.conftest import post, sign_in
from tracker.models import AuditLog

URL = "/admin/activity"


def text_of(response) -> str:
    return html.unescape(response.get_data(as_text=True))


def add(db, **kw) -> AuditLog:
    values = {"action": "login", "entity": "user", "entity_id": "1"}
    values.update(kw)
    row = AuditLog(**values)
    db.add(row)
    db.commit()
    return row


def at(day: int, hour: int = 12) -> datetime:
    return datetime(2026, 10, day, hour, 0, tzinfo=timezone.utc)


def test_activity_refused_without_view_activity(client, logged_in_user):
    assert client.get(URL).status_code == 403


def test_anonymous_goes_to_sign_in(client):
    assert client.get(URL).status_code in (302, 303)


def test_holder_and_admin_open_activity(client, logged_in_admin, user_factory, give_set):
    assert client.get(URL).status_code == 200
    holder = user_factory()
    give_set(["view_activity"], user=holder)
    other = client.application.test_client()
    sign_in(other, holder)
    assert other.get(URL).status_code == 200


def test_newest_first_50_a_page(client, logged_in_admin, db):
    for n in range(120):
        add(db, at=at(1, 0).replace(minute=n % 60, hour=n // 60), action="entry_created", entity_id=str(n))
    first = text_of(client.get(URL))
    assert first.count("<tr data-entry") == 50
    assert first.index('data-entry="120"') < first.index('data-entry="119"')  # ids run 1..120 from a clean table
    assert "Older" in first and "Newer" not in first
    last = text_of(client.get(URL + "?page=3"))
    assert last.count("<tr data-entry") == 20
    assert "Newer" in last and "Older" not in last
    assert "page=2" in last
    assert "page=2" in first


def test_person_filter_matches_who_acted_or_who_was_affected(client, logged_in_admin, db, user_factory):
    a, b, c = user_factory(), user_factory(), user_factory()
    acted = add(db, user_id=a.id, target_user_id=c.id)
    affected = add(db, user_id=b.id, target_user_id=a.id)
    other = add(db, user_id=b.id, target_user_id=c.id)
    body = text_of(client.get(f"{URL}?person={a.id}"))
    assert f'data-entry="{acted.id}"' in body and f'data-entry="{affected.id}"' in body
    assert f'data-entry="{other.id}"' not in body


def test_action_and_date_range_filters(client, logged_in_admin, db):
    early = add(db, at=at(10, 0), action="login")
    late = add(db, at=at(12, 23), action="login")
    edge = add(db, at=at(12, 23), action="entry_created")
    body = text_of(client.get(f"{URL}?action=login&from=2026-10-10&to=2026-10-12"))
    assert f'data-entry="{early.id}"' in body and f'data-entry="{late.id}"' in body  # "to" is inclusive
    assert f'data-entry="{edge.id}"' not in body
    body = text_of(client.get(f"{URL}?from=2026-10-11"))
    assert f'data-entry="{early.id}"' not in body and f'data-entry="{late.id}"' in body
    body = text_of(client.get(f"{URL}?to=2026-10-11"))
    assert f'data-entry="{early.id}"' in body and f'data-entry="{late.id}"' not in body


@pytest.mark.parametrize(
    "query",
    [
        "page=abc",
        "page=0",
        "page=-3",
        "page=99999999999999999999",
        "from=2026-13-45",
        "to=zzz",
        "to=9999-12-31",
        "from=0001-01-01",
        "person=xyz",
        "person=99999999999999999999",
        "action=<b>",
    ],
)
def test_malformed_filters_fall_back_to_the_full_list(client, logged_in_admin, db, query):
    add(db)
    response = client.get(f"{URL}?{query}")
    assert response.status_code == 200
    assert "<b>" not in response.get_data(as_text=True)


def test_rows_with_deleted_people_or_trackers_and_any_detail_shape_render(client, logged_in_admin, db):
    add(db, user_id=None, target_user_id=None, tracker_id=None, detail=None)
    add(db, action="role_set", detail={"role": [None, "viewer"]})
    add(db, action="mystery", detail={"weird": [1, 2, 3], "nested": {"a": None}})
    add(db, action="team_renamed", detail={"before": "A", "after": "B"})
    add(db, action="entry_updated", detail={"before": "x", "after": {"q": 1}})
    add(db, action="login", detail={"before": ["a"], "after": None})
    body = text_of(client.get(URL))
    assert "mystery" in body and "viewer" in body and "nested" in body
    assert "Team details changed" in body


def test_tracker_names_shown_to_a_view_activity_holder_without_access(
    client, db, user_factory, give_set, tracker_factory
):
    tracker = tracker_factory(name="Secret rollout")
    add(db, tracker_id=tracker.id)
    holder = user_factory()
    give_set(["view_activity"], user=holder)
    sign_in(client, holder)
    assert client.get(f"/trackers/{tracker.id}").status_code == 404
    assert "Secret rollout" in text_of(client.get(URL))


def test_no_secrets_in_any_entry(client, logged_in_admin, user_factory, db):
    p1, p2, p3 = "Pass-One-1111", "Pass-Two-2222", "Pass-Three-3333"
    post(client, "/admin/users", {"email": "new@example.com", "full_name": "New Person", "password": p1})
    victim = user_factory()
    post(client, f"/admin/users/{victim.id}/password", {"password": p2, "password_confirm": p2})
    post(client, "/admin/smtp", {"smtp_host": "smtp.example.com", "smtp_port": "25", "smtp_password": "smtp-secret-9"})
    fresh = client.application.test_client()
    post(fresh, "/login", {"email": victim.email, "password": p3})
    failed = db.scalars(select(AuditLog).where(AuditLog.action == "login_failed")).all()
    assert len(failed) == 1
    blob = json.dumps([e.detail for e in db.scalars(select(AuditLog))])
    for secret in (p1, p2, p3, "smtp-secret-9", "$2b$", "password_hash", "smtp_password"):
        assert secret not in blob


# --- Names, not contents ----------------------------------------------------------------------------------------------

HIDDEN = "Details hidden: you cannot open this tracker."


def test_detail_hidden_from_a_holder_who_cannot_open_the_tracker(
    client, db, user_factory, give_set, tracker_factory, grant
):
    secret, shared = tracker_factory(name="Secret rollout"), tracker_factory(name="Shared rollout")
    add(db, tracker_id=secret.id, action="entry_created", detail={"quantity": 4242})
    add(db, tracker_id=shared.id, action="entry_created", detail={"quantity": 5151})
    add(db, action="team_created", detail={"name": "Teamwide"})
    holder = user_factory()
    give_set(["view_activity"], user=holder)
    grant(holder, shared, "viewer")
    sign_in(client, holder)
    page = text_of(client.get(URL))
    assert "Secret rollout" in page and "4242" not in page and page.count(HIDDEN) == 1
    assert "Shared rollout" in page and "5151" in page and "Teamwide" in page


def test_administrator_sees_every_detail(client, logged_in_admin, db, tracker_factory):
    secret = tracker_factory(name="Secret rollout")
    add(db, tracker_id=secret.id, action="entry_created", detail={"quantity": 4242})
    page = text_of(client.get(URL))
    assert "4242" in page and HIDDEN not in page


def test_a_very_long_person_filter_is_ignored(client, logged_in_admin, db):
    add(db)
    response = client.get(URL + "?person=" + "9" * 5000)
    assert response.status_code == 200 and text_of(response).count("<tr data-entry") == 1


# --- Emails beside names ----------------------------------------------------------------------------------------------


def cells_of(body: str, entry: AuditLog) -> list[str]:
    """The inner HTML of each cell in an entry's row: time, performed by, user affected, action, tracker, detail."""
    row = re.search(rf'<tr data-entry="{entry.id}">(.*?)</tr>', body, re.DOTALL)
    assert row, f"entry {entry.id} is not on the page"
    return re.findall(r"<td[^>]*>(.*?)</td>", row.group(1), re.DOTALL)


def test_entries_show_the_email_under_each_name(client, logged_in_admin, db, user_factory):
    first = user_factory(full_name="Jordan Lee", email="jordan.first@example.com")
    second = user_factory(full_name="Jordan Lee", email="jordan.second@example.com")
    forward = add(db, user_id=first.id, target_user_id=second.id)
    backward = add(db, user_id=second.id, target_user_id=first.id)
    body = client.get(URL).get_data(as_text=True)
    first_email = '<span class="member-email">jordan.first@example.com</span>'
    second_email = '<span class="member-email">jordan.second@example.com</span>'
    performed, affected = cells_of(body, forward)[1:3]
    assert "Jordan Lee" in performed and first_email in performed and second_email not in performed
    assert "Jordan Lee" in affected and second_email in affected and first_email not in affected
    performed, affected = cells_of(body, backward)[1:3]
    assert second_email in performed and first_email not in performed
    assert first_email in affected and second_email not in affected


def test_a_deleted_person_shows_a_deleted_badge_and_stays_in_the_filter(client, logged_in_admin, db, user_factory):
    gone = user_factory(full_name="Jordan Lee", email="jordan.lee@example.com", status="deleted")
    kept = user_factory(full_name="Jordan Lee", email="jordan.kept@example.com")
    entry = add(db, user_id=gone.id, target_user_id=kept.id)
    body = client.get(URL).get_data(as_text=True)
    assert f'<option value="{gone.id}">Jordan Lee (jordan.lee@example.com) – deleted</option>' in body
    assert f'<option value="{kept.id}">Jordan Lee (jordan.kept@example.com)</option>' in body
    badge = '<span class="badge badge-muted">Deleted</span>'
    performed, affected = cells_of(body, entry)[1:3]
    assert "jordan.lee@example.com" in performed and badge in performed
    assert "jordan.kept@example.com" in affected and badge not in affected


def test_filtering_by_a_new_account_with_a_reused_email_shows_only_its_entries(
    client, logged_in_admin, db, user_factory
):
    old = user_factory(full_name="Jordan Lee", email="jordan.lee@example.com", status="deleted")
    new = user_factory(full_name="Jordan Lee", email="jordan.lee@example.com")
    old_entry, new_entry = add(db, user_id=old.id), add(db, user_id=new.id)
    body = client.get(f"{URL}?person={new.id}").get_data(as_text=True)
    assert f'data-entry="{new_entry.id}"' in body and f'data-entry="{old_entry.id}"' not in body
    assert f'<option value="{new.id}" selected>Jordan Lee (jordan.lee@example.com)</option>' in body
    assert f'<option value="{old.id}">Jordan Lee (jordan.lee@example.com) – deleted</option>' in body


def test_entries_without_a_person_show_a_dash(client, logged_in_admin, db, user_factory):
    person = user_factory(full_name="Jordan Lee", email="jordan.lee@example.com")
    nobody = add(db, user_id=None, target_user_id=None)
    only_affected = add(db, user_id=None, target_user_id=person.id)
    body = client.get(URL).get_data(as_text=True)
    assert [cell.strip() for cell in cells_of(body, nobody)[1:3]] == ["–", "–"]
    performed, affected = cells_of(body, only_affected)[1:3]
    assert performed.strip() == "–"
    assert "jordan.lee@example.com" in affected
