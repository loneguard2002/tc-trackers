"""Calendar reminders are remembered and kept in step with the tracker (database required)."""

from __future__ import annotations

import logging
import re
from datetime import date, datetime, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from tracker.calendar_invites import service
from tracker.mail import smtp
from tracker.models import CalendarReminder, TrackerRole
from tracker.sched.runner import run_scheduler_cycle

NOW = datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def email_set_up(monkeypatch):
    monkeypatch.setattr(
        smtp, "get_smtp_config", lambda session=None: {"host": "smtp.example.com", "from_": "reports@example.com"}
    )


@pytest.fixture
def mail(monkeypatch):
    sent: list = []
    monkeypatch.setattr(smtp, "send_message", sent.append)
    return sent


@pytest.fixture
def setup(app, db, tracker_factory, user_factory, grant):
    tracker = tracker_factory(name="Fit-out")
    person = user_factory(email="person@example.com")
    grant(person, tracker, "editor")
    with app.app_context():
        yield tracker, person


@pytest.fixture
def row(db, setup):
    tracker, person = setup
    reminder = CalendarReminder(user_id=person.id, tracker_id=tracker.id, enabled=True)
    db.add(reminder)
    db.commit()
    return reminder


def calendar_of(msg) -> str:
    for part in msg.walk():
        if part.get_content_type() == "text/calendar":
            return part.get_content()
    raise AssertionError("no calendar part")


def field(msg, name: str) -> str:
    return re.search(rf"^{name}:(.*)$", calendar_of(msg), flags=re.M).group(1).strip()


def test_switching_on_sends_one_request_with_sequence_zero(db, row, mail):
    assert service.sync_reminder(db, row, NOW) == "request"
    assert service.sync_reminder(db, row, NOW) is None
    assert len(mail) == 1
    assert field(mail[0], "METHOD") == "REQUEST"
    assert field(mail[0], "SEQUENCE") == "0"
    assert mail[0]["To"] == "person@example.com"
    db.refresh(row)
    assert (row.sent_state, row.sequence, row.last_error) == ("sent", 0, None)
    assert row.sent_fingerprint["name"] == "Fit-out" and row.sent_at is not None


def test_renaming_the_tracker_sends_an_update_with_the_same_uid(db, setup, row, mail):
    tracker, _ = setup
    service.sync_reminder(db, row, NOW)
    tracker.name = "Fit-out phase 2"
    db.commit()
    assert service.sync_all(db, NOW) == 1
    assert service.sync_all(db, NOW) == 0
    assert len(mail) == 2
    assert field(mail[1], "SEQUENCE") == "1"
    assert field(mail[1], "UID") == field(mail[0], "UID")
    assert "Fit-out phase 2" in calendar_of(mail[1])


def test_changing_the_last_week_ending_sends_an_update(db, setup, row, mail):
    tracker, _ = setup
    service.sync_reminder(db, row, NOW)
    tracker.last_week_ending = date(2027, 1, 8)
    db.commit()
    assert service.sync_all(db, NOW) == 1
    assert field(mail[1], "SEQUENCE") == "1"
    assert field(mail[1], "METHOD") == "REQUEST"


def test_archiving_cancels_once_and_restoring_requests_again(db, setup, row, mail):
    tracker, _ = setup
    service.sync_reminder(db, row, NOW)
    tracker.status = "archived"
    db.commit()
    assert service.sync_all(db, NOW) == 1
    assert service.sync_all(db, NOW) == 0
    assert len(mail) == 2 and field(mail[1], "METHOD") == "CANCEL"
    assert field(mail[1], "SEQUENCE") == "1"
    db.refresh(row)
    assert row.sent_state == "cancelled" and row.sent_fingerprint is None
    tracker.status = "active"
    db.commit()
    assert service.sync_all(db, NOW) == 1
    assert field(mail[2], "METHOD") == "REQUEST"
    assert field(mail[2], "SEQUENCE") == "2"
    assert field(mail[2], "UID") == field(mail[0], "UID")


def test_dropping_to_viewer_cancels(db, setup, row, mail):
    tracker, person = setup
    service.sync_reminder(db, row, NOW)
    db.query(TrackerRole).filter_by(user_id=person.id, tracker_id=tracker.id).update({"role": "viewer"})
    db.commit()
    assert service.sync_all(db, NOW) == 1
    assert field(mail[1], "METHOD") == "CANCEL"


def test_a_disabled_person_cancels(db, setup, row, mail):
    _, person = setup
    service.sync_reminder(db, row, NOW)
    person.status = "disabled"
    db.commit()
    assert service.sync_all(db, NOW) == 1
    assert field(mail[1], "METHOD") == "CANCEL"
    assert service.sync_all(db, NOW) == 0


def test_switching_off_cancels(db, row, mail):
    service.sync_reminder(db, row, NOW)
    row.enabled = False
    db.commit()
    assert service.sync_reminder(db, row, NOW) == "cancel"
    assert field(mail[1], "METHOD") == "CANCEL"
    assert service.sync_all(db, NOW) == 0


def test_a_never_sent_row_switched_off_sends_nothing(db, row, mail):
    row.enabled = False
    db.commit()
    assert service.sync_reminder(db, row, NOW) is None
    assert service.sync_all(db, NOW) == 0
    assert mail == []


def test_a_person_without_edit_rights_gets_no_request(db, setup, user_factory, mail):
    tracker, _ = setup
    stranger = CalendarReminder(user_id=user_factory().id, tracker_id=tracker.id, enabled=True)
    db.add(stranger)
    db.commit()
    assert service.sync_reminder(db, stranger, NOW) is None
    assert mail == []


def test_a_failed_delivery_changes_nothing_remembered_and_is_retried(db, setup, row, mail, monkeypatch):
    tracker, _ = setup
    service.sync_reminder(db, row, NOW)
    tracker.name = "Renamed"
    db.commit()

    def boom(_msg):
        raise OSError("connection refused")

    monkeypatch.setattr(smtp, "send_message", boom)
    assert service.sync_reminder(db, row, NOW) is None
    db.refresh(row)
    assert (row.sent_state, row.sequence) == ("sent", 0)
    assert row.sent_fingerprint["name"] == "Fit-out"
    assert "connection refused" in row.last_error

    monkeypatch.setattr(smtp, "send_message", mail.append)
    assert service.sync_all(db, NOW) == 1
    db.refresh(row)
    assert (row.sequence, row.last_error) == (1, None)
    assert field(mail[-1], "SEQUENCE") == "1"


def test_a_failed_first_request_stays_unsent(db, row, monkeypatch):
    def boom(_msg):
        raise OSError("down")

    monkeypatch.setattr(smtp, "send_message", boom)
    assert service.sync_reminder(db, row, NOW) is None
    db.refresh(row)
    assert (row.sent_state, row.sequence, row.sent_fingerprint) == ("none", 0, None)
    assert row.last_error


def test_force_sends_an_update_with_a_higher_sequence(db, row, mail):
    service.sync_reminder(db, row, NOW)
    assert service.sync_reminder(db, row, NOW, force=True) == "update"
    assert field(mail[1], "SEQUENCE") == "1"
    assert field(mail[1], "UID") == field(mail[0], "UID")


def test_the_scheduler_cycle_sends_a_due_update(db, setup, row, mail):
    tracker, _ = setup
    service.sync_reminder(db, row, NOW)
    tracker.name = "Renamed"
    db.commit()
    run_scheduler_cycle(db, NOW)
    assert len(mail) == 2 and field(mail[1], "SEQUENCE") == "1"


def _failing(monkeypatch):
    def boom(_msg):
        raise OSError("connection refused")

    monkeypatch.setattr(smtp, "send_message", boom)


def test_a_new_uncommitted_row_survives_a_failed_delivery(db, setup, monkeypatch):
    tracker, person = setup
    _failing(monkeypatch)
    new = CalendarReminder(user_id=person.id, tracker_id=tracker.id, enabled=True)
    db.add(new)
    assert service.sync_reminder(db, new, NOW) is None
    db.expire_all()
    stored = db.get(CalendarReminder, (person.id, tracker.id))
    assert stored.enabled is True and stored.sent_state == "none"
    assert "connection refused" in stored.last_error


def test_a_failed_delivery_keeps_the_callers_other_pending_changes(db, setup, row, monkeypatch):
    tracker, person = setup
    _failing(monkeypatch)
    person.full_name = "Changed by the caller"
    assert service.sync_reminder(db, row, NOW) is None
    db.expire_all()
    assert db.get(type(person), person.id).full_name == "Changed by the caller"
    assert db.get(CalendarReminder, (person.id, tracker.id)).last_error


def test_a_cancellation_is_built_from_what_was_sent(db, setup, row, mail):
    tracker, _ = setup
    service.sync_reminder(db, row, NOW)
    tracker.name = "Renamed"
    tracker.status = "archived"
    db.commit()
    assert service.sync_all(db, NOW) == 1
    assert field(mail[1], "METHOD") == "CANCEL"
    assert field(mail[1], "SUMMARY") == r"Write the weekly update: Fit-out"
    assert mail[1]["Subject"] == "Calendar reminder cancelled: Fit-out"


def test_the_scheduler_skips_a_row_that_a_request_holds_locked(db, _db_engine, row, mail):
    db.scalars(select(CalendarReminder).with_for_update()).all()  # the request handler's lock, held while it sends
    with Session(_db_engine, expire_on_commit=False) as other:
        assert service.sync_all(other, NOW) == 0  # returns at once: a blocked wait would hang here
    assert mail == []
    db.rollback()
    with Session(_db_engine, expire_on_commit=False) as other:
        assert service.sync_all(other, NOW) == 1
    assert len(mail) == 1


def test_a_stale_row_does_not_send_a_second_request(db, _db_engine, row, mail):
    with Session(_db_engine, expire_on_commit=False) as other:
        stale = other.get(CalendarReminder, (row.user_id, row.tracker_id))  # read before the first send
        assert service.sync_reminder(db, row, NOW) == "request"
        assert service.sync_reminder(other, stale, NOW) is None
        assert (stale.sent_state, stale.sequence) == ("sent", 0)
    assert len(mail) == 1


def test_a_lock_does_not_lose_the_callers_changes_on_failure(db, setup, row, monkeypatch):
    def boom(_msg):
        raise OSError("down")

    monkeypatch.setattr(smtp, "send_message", boom)
    row.enabled = False
    row.sent_state = "sent"  # pretend a request went out, so switching off needs a cancellation
    row.sent_fingerprint = {"name": "Fit-out", "weekday": 4, "first": "2026-09-04", "last": "2026-12-25", "tz": "UTC"}
    row.sent_at = NOW
    assert service.sync_reminder(db, row, NOW) is None
    db.expire_all()
    stored = db.get(CalendarReminder, (row.user_id, row.tracker_id))
    assert stored.enabled is False and "down" in stored.last_error


@pytest.fixture
def not_set_up(monkeypatch):
    monkeypatch.setattr(smtp, "get_smtp_config", lambda session=None: {"host": "", "from_": ""})
    monkeypatch.setattr(service, "_not_set_up_logged", False)


def test_without_email_set_up_the_scheduler_attempts_nothing_and_logs_once(db, row, mail, not_set_up, caplog):
    caplog.set_level(logging.INFO, logger=service.logger.name)
    assert service.sync_all(db, NOW) == 0
    assert service.sync_all(db, NOW) == 0
    assert mail == []
    records = [r for r in caplog.records if r.name == service.logger.name]
    assert len(records) == 1 and records[0].levelno == logging.INFO and records[0].exc_info is None
    db.refresh(row)
    assert (row.sent_state, row.last_error) == ("none", None)


def test_without_email_set_up_a_direct_sync_sends_nothing_and_records_no_error(db, row, mail, not_set_up):
    assert service.sync_reminder(db, row, NOW) is None
    assert mail == [] and row.last_error is None
