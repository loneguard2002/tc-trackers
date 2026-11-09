"""The reminder to write the weekly update, 24 hours before the automatic send (database required)."""

from __future__ import annotations

from datetime import date, datetime, time, timezone

import pytest
from sqlalchemy import select

from tracker.mail import smtp
from tracker.models import AuditLog, ReportInput, ReportReminder, ReportSend
from tracker.sched import reminders
from tracker.sched.reminders import due_reminders, send_due_reminders
from tracker.sched.runner import run_scheduler_cycle

WEEK = date(2026, 10, 16)  # a Friday; the send is 17:00 London (16:00 UTC)
DAY_BEFORE = datetime(2026, 10, 15, 16, 5, tzinfo=timezone.utc)  # 23 h 55 min before the send
TOO_EARLY = datetime(2026, 10, 15, 15, 55, tzinfo=timezone.utc)  # 24 h 5 min before


@pytest.fixture
def people(user_factory):
    return user_factory(full_name="Lead", email="lead@example.com"), user_factory(
        full_name="Own", email="own@example.com"
    )


@pytest.fixture
def scheduled(tracker_factory, db, grant, people):
    lead, owner = people
    tracker = tracker_factory(schedule_enabled=True, send_time=time(17, 0), send_timezone="Europe/London")
    grant(lead, tracker, "editor")
    grant(owner, tracker, "owner")
    tracker.lead_user_id = lead.id
    db.commit()
    return tracker


@pytest.fixture
def mail(monkeypatch):
    sent: list = []
    monkeypatch.setattr(smtp, "send_message", sent.append)
    return sent


def test_due_within_24_hours_of_the_send_only(db, scheduled):
    assert due_reminders(db, DAY_BEFORE) == [(scheduled.id, WEEK)]
    assert due_reminders(db, TOO_EARLY) == []


def test_not_due_once_the_update_is_written(db, scheduled):
    db.add(ReportInput(tracker_id=scheduled.id, week_ending=WEEK, status="Green", headline="  ", decisions=""))
    db.commit()
    assert due_reminders(db, DAY_BEFORE) == [(scheduled.id, WEEK)]  # a blank update is not written
    db.get(ReportInput, (scheduled.id, WEEK)).headline = "Floor 3 done"
    db.commit()
    assert due_reminders(db, DAY_BEFORE) == []


def test_not_due_when_off_archived_or_already_sent(db, scheduled):
    scheduled.schedule_enabled = False
    db.commit()
    assert due_reminders(db, DAY_BEFORE) == []
    scheduled.schedule_enabled, scheduled.status = True, "archived"
    db.commit()
    assert due_reminders(db, DAY_BEFORE) == []
    scheduled.status = "active"
    db.add(ReportSend(tracker_id=scheduled.id, week_ending=WEEK, trigger="scheduled", status="sent", recipients=[]))
    db.commit()
    assert due_reminders(db, DAY_BEFORE) == []


def test_the_person_in_charge_is_reminded_once(app, db, scheduled, mail):
    with app.app_context():
        assert send_due_reminders(db, DAY_BEFORE) == 1
        assert send_due_reminders(db, DAY_BEFORE) == 0
    assert len(mail) == 1
    msg = mail[0]
    assert msg["To"] == "lead@example.com"
    assert msg["Subject"] == "Weekly update needed: Test tracker report goes out Fri 16 Oct at 17:00"
    page = msg.get_body(preferencelist=("html",)).get_content()
    assert f"/trackers/{scheduled.id}/inputs?week=2026-10-16" in page and "16 Oct 2026" in page
    entry = db.scalars(select(AuditLog).where(AuditLog.action == "report_reminder_sent")).one()
    assert entry.detail == {"week_ending": "2026-10-16", "recipients": ["lead@example.com"]}


def test_without_a_qualified_lead_the_direct_owners_are_reminded(app, db, scheduled, people, mail):
    lead, _ = people
    lead.status = "disabled"
    db.commit()
    with app.app_context():
        send_due_reminders(db, DAY_BEFORE)
    assert mail[0]["To"] == "own@example.com"


def test_a_failed_delivery_is_tried_again(app, db, scheduled, monkeypatch):
    def refuse(msg):
        raise smtp.MailError("down")

    monkeypatch.setattr(smtp, "send_message", refuse)
    with app.app_context():
        assert send_due_reminders(db, DAY_BEFORE) == 0
    assert db.scalars(select(ReportReminder)).all() == []
    sent: list = []
    monkeypatch.setattr(smtp, "send_message", sent.append)
    with app.app_context():
        assert send_due_reminders(db, DAY_BEFORE) == 1
    assert len(sent) == 1


def test_the_scheduler_cycle_sends_reminders(app, db, scheduled, mail, monkeypatch):
    calls = []
    monkeypatch.setattr(reminders, "send_due_reminders", lambda session, now: calls.append(now) or 0)
    with app.app_context():
        run_scheduler_cycle(db, DAY_BEFORE)
    assert calls == [DAY_BEFORE]
