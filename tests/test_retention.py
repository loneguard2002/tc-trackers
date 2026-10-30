"""Activity retention setting and the daily prune (database required)."""

import html
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from tests.conftest import post
from tracker.activity.retention import (
    LAST_PRUNED_KEY,
    RETENTION_ERROR,
    RETENTION_KEY,
    parse_retention,
    prune_audit_log,
    retention_days,
)
from tracker.models import AppSetting, AuditLog
from tracker.sched import runner

URL = "/admin/activity/retention"
NOW = datetime(2026, 10, 30, 3, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    "value,expected",
    [("", (None, None)), ("90", (90, None)), ("3650", (3650, None)), ("3,650", (3650, None)), (" 365 ", (365, None))],
)
def test_parse_retention_accepts(value, expected):
    assert parse_retention(value) == expected


@pytest.mark.parametrize("value", ["89", "0", "90.5", "3651", "abc", "-90"])
def test_parse_retention_refuses(value):
    assert parse_retention(value) == (None, RETENTION_ERROR)


def set_setting(db, key, value):
    db.merge(AppSetting(key=key, value=value))
    db.commit()


def entries(db, action):
    return list(db.scalars(select(AuditLog).where(AuditLog.action == action).order_by(AuditLog.id)))


def test_retention_form_and_route_are_administrator_only(client, logged_in_user, give_set):
    give_set(["view_activity", "manage_users", "manage_teams"], user=logged_in_user)
    assert "retention_days" not in client.get("/admin/activity").get_data(as_text=True)
    assert post(client, URL, {"retention_days": "365"}).status_code == 403


def test_form_shows_current_value_to_administrator(client, logged_in_admin, db):
    page = client.get("/admin/activity").get_data(as_text=True)
    assert 'name="retention_days"' in page
    set_setting(db, RETENTION_KEY, "365")
    assert 'value="365"' in client.get("/admin/activity").get_data(as_text=True)


def test_retention_set_and_cleared_are_logged(client, logged_in_admin, db):
    assert post(client, URL, {"retention_days": "365"}).status_code == 302
    assert retention_days(db) == 365
    assert entries(db, "audit_retention_changed")[-1].detail == {"before": None, "after": 365}
    assert post(client, URL, {"retention_days": ""}).status_code == 302
    db.expire_all()
    assert retention_days(db) is None
    assert db.get(AppSetting, RETENTION_KEY) is None
    last = entries(db, "audit_retention_changed")[-1]
    assert last.detail == {"before": 365, "after": None}
    assert (last.entity, last.entity_id) == ("app_settings", RETENTION_KEY)


def test_unchanged_retention_writes_no_entry(client, logged_in_admin, db):
    post(client, URL, {"retention_days": "3,650"})
    post(client, URL, {"retention_days": "3650"})
    assert len(entries(db, "audit_retention_changed")) == 1


def test_invalid_retention_is_refused_with_message(client, logged_in_admin, db):
    response = post(client, URL, {"retention_days": "89"}, follow_redirects=True)
    assert html.unescape(response.get_data(as_text=True)).count(RETENTION_ERROR) == 1
    assert retention_days(db) is None
    assert entries(db, "audit_retention_changed") == []


def seed(db):
    old = AuditLog(action="login", entity="user", entity_id="1", at=NOW - timedelta(days=100))
    new = AuditLog(action="login", entity="user", entity_id="2", at=NOW - timedelta(days=10))
    db.add_all([old, new])
    db.commit()


def test_prune_deletes_older_entries_and_records_its_own_entry(db):
    seed(db)
    set_setting(db, RETENTION_KEY, "90")
    assert prune_audit_log(db, NOW) == 1
    assert [e.entity_id for e in entries(db, "login")] == ["2"]
    (pruned,) = entries(db, "audit_pruned")
    assert pruned.entity == "audit_log"
    assert pruned.detail == {"removed": 1, "cutoff": (NOW - timedelta(days=90)).isoformat()}


def test_prune_runs_once_a_day(db):
    seed(db)
    set_setting(db, RETENTION_KEY, "90")
    assert prune_audit_log(db, NOW) == 1
    db.add(AuditLog(action="login", entity="user", entity_id="3", at=NOW - timedelta(days=200)))
    db.commit()
    assert prune_audit_log(db, NOW + timedelta(hours=5)) is None
    assert len(entries(db, "login")) == 2
    assert prune_audit_log(db, NOW + timedelta(days=1)) == 1


def test_prune_with_nothing_to_remove_writes_no_entry(db):
    set_setting(db, RETENTION_KEY, "90")
    assert prune_audit_log(db, NOW) == 0
    assert entries(db, "audit_pruned") == []
    assert db.get(AppSetting, LAST_PRUNED_KEY).value == NOW.date().isoformat()


def test_prune_without_retention_does_nothing(db):
    seed(db)
    assert prune_audit_log(db, NOW) is None
    assert len(entries(db, "login")) == 2
    assert db.get(AppSetting, LAST_PRUNED_KEY) is None


def test_scheduler_cycle_prunes_and_survives_a_prune_failure(app, db, monkeypatch):
    seed(db)
    set_setting(db, RETENTION_KEY, "90")
    runner.run_scheduler_cycle(db, NOW)
    assert [e.entity_id for e in entries(db, "login")] == ["2"]

    def boom(session, now_utc):
        raise RuntimeError("prune failed")

    monkeypatch.setattr(runner, "prune_audit_log", boom)
    assert runner.run_scheduler_cycle(db, NOW) == 0
