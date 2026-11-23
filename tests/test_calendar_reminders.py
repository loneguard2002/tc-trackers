"""Calendar reminders are remembered and kept in step with the tracker (database required)."""

from __future__ import annotations

import re
from datetime import date, datetime, timezone

import pytest

from tracker.calendar_invites import service
from tracker.mail import smtp
from tracker.models import CalendarReminder, TrackerRole
from tracker.sched.runner import run_scheduler_cycle

NOW = datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc)


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
