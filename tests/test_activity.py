"""Activity screen (database required)."""

import html
import json
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
    assert "Team renamed" in body


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
    post(client, f"/admin/users/{victim.id}/password", {"password": p2})
    post(client, "/admin/smtp", {"smtp_host": "smtp.example.com", "smtp_port": "25", "smtp_password": "smtp-secret-9"})
    fresh = client.application.test_client()
    post(fresh, "/login", {"email": victim.email, "password": p3})
    failed = db.scalars(select(AuditLog).where(AuditLog.action == "login_failed")).all()
    assert len(failed) == 1
    blob = json.dumps([e.detail for e in db.scalars(select(AuditLog))])
    for secret in (p1, p2, p3, "smtp-secret-9", "$2b$", "password_hash", "smtp_password"):
        assert secret not in blob
