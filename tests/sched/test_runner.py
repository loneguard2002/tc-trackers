"""Scheduler cycle: claiming, sending once, failure isolation (database required)."""

from __future__ import annotations

from datetime import date, datetime, time, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from tracker.mail import sending, smtp
from tracker.models import AuditLog, Recipient, ReportSend
from tracker.sched import runner
from tracker.sched.runner import due_sends, run_scheduler_cycle

FIRE = date(2026, 10, 16)
AFTER = datetime(2026, 10, 16, 16, 5, tzinfo=timezone.utc)


@pytest.fixture
def scheduled(tracker_factory, db):
    tracker = tracker_factory(schedule_enabled=True, send_time=time(17, 0), send_timezone="Europe/London")
    db.add(Recipient(tracker_id=tracker.id, email="a@example.com"))
    db.commit()
    return tracker


@pytest.fixture
def mail(monkeypatch):
    sent: list = []
    monkeypatch.setattr(smtp, "send_message", sent.append)
    monkeypatch.setattr(sending, "html_to_pdf", lambda html: b"%PDF-fake")
    return sent


def sends(db):
    return list(db.scalars(select(ReportSend).order_by(ReportSend.id)))


def test_due_after_fire_time_london(db, scheduled):
    assert due_sends(db, AFTER) == [(scheduled.id, FIRE)]


def test_not_due_before_fire_time(db, scheduled):
    assert due_sends(db, datetime(2026, 10, 16, 15, 55, tzinfo=timezone.utc)) == []


def test_dst_end_week(db, scheduled):
    assert due_sends(db, datetime(2026, 10, 30, 16, 5, tzinfo=timezone.utc)) == []
    assert due_sends(db, datetime(2026, 10, 30, 17, 5, tzinfo=timezone.utc)) == [(scheduled.id, date(2026, 10, 30))]


def test_fire_older_than_24h_skipped(db, scheduled):
    assert due_sends(db, datetime(2026, 10, 17, 16, 5, tzinfo=timezone.utc)) == []


def test_schedule_disabled_not_due(db, tracker_factory):
    tracker_factory(schedule_enabled=False)
    assert due_sends(db, AFTER) == []


def test_archived_tracker_not_due(db, tracker_factory):
    tracker_factory(schedule_enabled=True, status="archived")
    assert due_sends(db, AFTER) == []


def test_week_outside_tracker_not_due(db, tracker_factory):
    tracker_factory(schedule_enabled=True, last_week_ending=date(2026, 10, 9))
    assert due_sends(db, AFTER) == []


def test_existing_scheduled_send_not_due_again(db, scheduled):
    db.add(ReportSend(tracker_id=scheduled.id, week_ending=FIRE, trigger="scheduled", status="sent", recipients=[]))
    db.commit()
    assert due_sends(db, AFTER) == []


def test_manual_send_does_not_block_scheduled(db, scheduled):
    db.add(ReportSend(tracker_id=scheduled.id, week_ending=FIRE, trigger="manual", status="sent", recipients=[]))
    db.commit()
    assert due_sends(db, AFTER) == [(scheduled.id, FIRE)]


def test_scheduler_cycle_twice_sends_once(app, db, _db_engine, scheduled, mail):
    with app.app_context():
        assert run_scheduler_cycle(db, AFTER) == 1
        assert run_scheduler_cycle(db, AFTER) == 0
        with Session(_db_engine, expire_on_commit=False) as other:
            assert run_scheduler_cycle(other, AFTER) == 0
    assert len(mail) == 1
    (send,) = sends(db)
    assert send.trigger == "scheduled" and send.status == "sent" and send.recipients == ["a@example.com"]
    assert send.week_ending == FIRE and send.pdf == b"%PDF-fake"


def test_lost_claim_is_not_sent(app, db, scheduled, mail, monkeypatch):
    """A second process that loses the claim (the row exists by the time it inserts) sends nothing."""
    monkeypatch.setattr(runner, "due_sends", lambda session, now: [(scheduled.id, FIRE)])
    db.add(ReportSend(tracker_id=scheduled.id, week_ending=FIRE, trigger="scheduled", status="sending", recipients=[]))
    db.commit()
    with app.app_context():
        assert run_scheduler_cycle(db, AFTER) == 0
    assert mail == [] and len(sends(db)) == 1


def test_smtp_failure_queues_and_retries(app, db, scheduled, monkeypatch):
    def fail(msg):
        raise smtp.MailError("connection refused")

    monkeypatch.setattr(smtp, "send_message", fail)
    monkeypatch.setattr(sending, "html_to_pdf", lambda html: b"%PDF-fake")
    with app.app_context():
        run_scheduler_cycle(db, AFTER)
    (send,) = sends(db)
    assert send.status == "queued" and send.attempts == 1 and send.next_attempt_at is not None


def test_no_recipients_marks_failed_without_retry(app, db, tracker_factory, mail):
    tracker = tracker_factory(schedule_enabled=True)
    with app.app_context():
        run_scheduler_cycle(db, AFTER)
        run_scheduler_cycle(db, AFTER)
    (send,) = sends(db)
    assert send.tracker_id == tracker.id and send.status == "failed" and send.next_attempt_at is None
    assert send.error == sending.NO_RECIPIENTS_MESSAGE
    assert mail == []
    audit = db.scalars(select(AuditLog).where(AuditLog.action == "report_send_failed")).all()
    assert len(audit) == 1 and audit[0].detail["trigger"] == "scheduled"


def test_build_exception_marks_failed_and_cycle_continues(app, db, scheduled, tracker_factory, mail, monkeypatch):
    other = tracker_factory(name="Other tracker", schedule_enabled=True)
    db.add(Recipient(tracker_id=other.id, email="b@example.com"))
    db.commit()
    original = sending._report_and_pdf

    def broken(session, tracker, week_ending, *args):
        if tracker.id == scheduled.id:
            raise RuntimeError("render exploded")
        return original(session, tracker, week_ending, *args)

    monkeypatch.setattr(sending, "_report_and_pdf", broken)
    with app.app_context():
        assert run_scheduler_cycle(db, AFTER) == 2
    by_tracker = {s.tracker_id: s for s in sends(db)}
    assert by_tracker[scheduled.id].status == "failed"
    assert by_tracker[scheduled.id].error.startswith("RuntimeError: render exploded")
    assert by_tracker[other.id].status == "sent"
    assert len(mail) == 1
    assert (
        db.scalars(select(AuditLog).where(AuditLog.action == "report_send_failed")).one().detail["status"] == "failed"
    )
