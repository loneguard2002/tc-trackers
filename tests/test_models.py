from datetime import date

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from tracker.audit import record
from tracker.models import AuditLog, ReportSend, User


def test_scheduled_send_unique_per_week(db, tracker_factory):
    t = tracker_factory()
    db.add(
        ReportSend(tracker_id=t.id, week_ending=t.first_week_ending, trigger="scheduled", status="sent", recipients=[])
    )
    db.commit()
    db.add(
        ReportSend(tracker_id=t.id, week_ending=t.first_week_ending, trigger="scheduled", status="sent", recipients=[])
    )
    with pytest.raises(IntegrityError):
        db.commit()


def test_manual_sends_not_limited(db, tracker_factory):
    t = tracker_factory()
    for _ in range(2):
        db.add(
            ReportSend(tracker_id=t.id, week_ending=t.first_week_ending, trigger="manual", status="sent", recipients=[])
        )
    db.commit()
    assert db.scalar(select(func.count()).select_from(ReportSend)) == 2


def test_tracker_span_limited_to_52_weeks(db, tracker_factory):
    with pytest.raises(IntegrityError):
        tracker_factory(first_week_ending=date(2026, 1, 2), last_week_ending=date(2027, 1, 8))  # 53 weeks


def test_tracker_span_of_52_weeks_is_allowed(db, tracker_factory):
    t = tracker_factory(first_week_ending=date(2026, 1, 2), last_week_ending=date(2026, 12, 25))
    assert t.id is not None


def test_audit_record_writes_row(db, tracker_factory):
    t = tracker_factory()
    record(
        db, user_id=None, tracker_id=t.id, action="update", entity="group", entity_id=5, detail={"baseline": [10, 12]}
    )
    db.commit()
    assert db.scalar(select(func.count()).select_from(AuditLog)) == 1
    row = db.scalars(select(AuditLog)).one()
    assert row.entity_id == "5"
    assert row.detail == {"baseline": [10, 12]}


def test_user_email_stored_lowercase_and_unique(db):
    db.add(User(email="Jane.Doe@Example.com", full_name="Jane Doe"))
    db.commit()
    assert db.scalars(select(User.email)).one() == "jane.doe@example.com"
    db.add(User(email="JANE.DOE@example.com", full_name="Jane Again"))
    with pytest.raises(IntegrityError):
        db.commit()


def test_tracker_defaults(db, tracker_factory):
    t = tracker_factory()
    db.refresh(t)
    assert (t.moving_average_weeks, t.completed_before_first, t.schedule_enabled) == (3, 0, False)
    assert t.send_timezone == "Europe/London"
    assert t.send_time.hour == 17
