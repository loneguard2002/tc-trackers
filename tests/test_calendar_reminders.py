"""Calendar reminders are remembered and kept in step with the tracker (database required)."""

from __future__ import annotations

import logging
import re
import smtplib
import socket
from datetime import date, datetime, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from tracker.calendar_invites import service
from tracker.calendar_invites.ics import describe_series, inputs_url, series_for
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


# --- the event log -------------------------------------------------------------------------------------------


def events(db, setup):
    tracker, person = setup
    return [(e.kind, e.detail) for e in reversed(service.events_for(db, person.id, tracker.id))]


def test_event_labels_and_groups():
    assert service.EVENT_LABELS == {
        "switched_on": "Switched on",
        "switched_off": "Switched off",
        "sent": "Invite sent",
        "updated": "Update sent",
        "cancelled": "Cancellation sent",
        "failed": "Sending failed",
        "downloaded": "Downloaded",
    }
    assert service.EVENT_GROUPS == {
        "sent": "sent", "updated": "sent", "cancelled": "sent", "failed": "failed", "downloaded": "download",
        "switched_on": "change", "switched_off": "change",
    }  # fmt: skip


def test_a_first_send_records_sent_with_the_series_description(db, setup, row, mail):
    tracker, person = setup
    service.sync_reminder(db, row, NOW)
    expected = describe_series(series_for(tracker, person, inputs_url(tracker.id)))
    assert events(db, setup) == [("sent", expected)]


def test_a_rename_records_updated_tracker_renamed(db, setup, row, mail):
    tracker, _ = setup
    service.sync_reminder(db, row, NOW)
    tracker.name = "Fit-out phase 2"
    db.commit()
    service.sync_reminder(db, row, NOW)
    assert events(db, setup)[-1] == ("updated", "Tracker renamed")


@pytest.mark.parametrize(
    ("changes", "detail"),
    [
        ({"last_week_ending": date(2027, 1, 8)}, "Dates changed"),
        ({"first_week_ending": date(2026, 9, 11)}, "Dates changed"),
        ({"week_ending_weekday": 3, "first_week_ending": date(2026, 9, 3)}, "Dates changed; Week-ending day changed"),
        ({"send_timezone": "Asia/Tokyo"}, "Time zone changed"),
        ({"name": "Other", "send_timezone": "Asia/Tokyo"}, "Tracker renamed; Time zone changed"),
    ],
)
def test_an_update_names_what_changed(db, setup, row, mail, changes, detail):
    tracker, _ = setup
    service.sync_reminder(db, row, NOW)
    for key, value in changes.items():
        setattr(tracker, key, value)
    db.commit()
    service.sync_reminder(db, row, NOW)
    assert events(db, setup)[-1] == ("updated", detail)


def test_the_weekday_alone_is_week_ending_day_changed(db, setup, row, mail):
    tracker, _ = setup
    service.sync_reminder(db, row, NOW)
    tracker.week_ending_weekday = 3
    db.commit()
    service.sync_reminder(db, row, NOW)
    assert events(db, setup)[-1] == ("updated", "Week-ending day changed")


def test_force_without_a_change_records_sent_again(db, row, setup, mail):
    service.sync_reminder(db, row, NOW)
    service.sync_reminder(db, row, NOW, force=True)
    assert events(db, setup)[-1] == ("updated", "Sent again")


def test_archiving_records_cancelled_tracker_archived(db, setup, row, mail):
    tracker, _ = setup
    service.sync_reminder(db, row, NOW)
    tracker.status = "archived"
    db.commit()
    service.sync_reminder(db, row, NOW)
    assert events(db, setup)[-1] == ("cancelled", "Tracker archived")


def test_lost_rights_record_cancelled_edit_rights_removed(db, setup, row, mail):
    tracker, person = setup
    service.sync_reminder(db, row, NOW)
    db.query(TrackerRole).filter_by(user_id=person.id, tracker_id=tracker.id).update({"role": "viewer"})
    db.commit()
    service.sync_reminder(db, row, NOW)
    assert events(db, setup)[-1] == ("cancelled", "Edit rights removed")


def test_an_inactive_person_records_cancelled_account_not_active(db, setup, row, mail):
    _, person = setup
    service.sync_reminder(db, row, NOW)
    person.status = "disabled"
    db.commit()
    service.sync_reminder(db, row, NOW)
    assert events(db, setup)[-1] == ("cancelled", "Account not active")


def test_switching_off_records_cancelled_switched_off(db, setup, row, mail):
    service.sync_reminder(db, row, NOW)
    row.enabled = False
    db.commit()
    service.sync_reminder(db, row, NOW)
    assert events(db, setup)[-1] == ("cancelled", "Switched off")


def test_a_failed_delivery_records_one_failed_event_with_the_error(db, setup, row, monkeypatch):
    def boom(_msg):
        raise OSError("connection refused " + "x" * 400)

    monkeypatch.setattr(smtp, "send_message", boom)
    service.sync_reminder(db, row, NOW)
    [(kind, detail)] = events(db, setup)
    assert (kind, detail) == ("failed", "The mail server did not answer")
    assert "connection refused" in row.last_error  # the raw text stays for the log and the row


@pytest.mark.parametrize(
    "error, detail",
    [
        (ConnectionRefusedError("connection refused"), "The mail server did not answer"),
        (TimeoutError("timed out"), "The mail server did not answer"),
        (socket.gaierror("name not known"), "The mail server did not answer"),
        (smtplib.SMTPServerDisconnected("gone"), "The mail server did not answer"),
        (smtplib.SMTPAuthenticationError(535, b"bad"), "The mail server refused the sign-in"),
        (smtp.MailError("OAuth2 token request failed: invalid_client"), "The mail server refused the sign-in"),
        (smtplib.SMTPRecipientsRefused({"a@b.c": (550, b"no")}), "The mail server refused the address"),
        (smtplib.SMTPDataError(554, b"spam"), "The mail server refused the message"),
        (ValueError("odd"), "The mail server refused the message"),
    ],
)
def test_a_failure_detail_is_in_plain_language(db, setup, row, monkeypatch, error, detail):
    def boom(_msg):
        raise error

    monkeypatch.setattr(smtp, "send_message", boom)
    service.sync_reminder(db, row, NOW)
    assert events(db, setup) == [("failed", detail)]
    assert row.last_error


def test_a_wrapped_error_is_read_by_its_cause(db, setup, row, monkeypatch):
    def boom(_msg):
        try:
            raise smtplib.SMTPAuthenticationError(535, b"bad")
        except smtplib.SMTPException as exc:
            raise smtp.MailError("(535, b'bad')") from exc

    monkeypatch.setattr(smtp, "send_message", boom)
    service.sync_reminder(db, row, NOW)
    assert events(db, setup) == [("failed", "The mail server refused the sign-in")]


def test_events_for_is_one_persons_one_tracker_newest_first(db, setup, user_factory, tracker_factory):
    tracker, person = setup
    other_user, other_tracker = user_factory(), tracker_factory()
    service.record_event(db, person.id, tracker.id, "switched_on", "By you")
    service.record_event(db, person.id, tracker.id, "switched_off", "By you")
    service.record_event(db, other_user.id, tracker.id, "switched_on", "By you")
    service.record_event(db, person.id, other_tracker.id, "switched_on", "By you")
    db.commit()
    found = service.events_for(db, person.id, tracker.id)
    assert [e.kind for e in found] == ["switched_off", "switched_on"]
    assert all(e.user_id == person.id and e.tracker_id == tracker.id for e in found)


def _raiser(error):
    def boom(_msg):
        raise error

    return boom


def _failing_with(monkeypatch, text):
    def boom(_msg):
        raise OSError(text)

    monkeypatch.setattr(smtp, "send_message", boom)


def test_a_repeated_failure_records_one_failed_event(db, setup, row, monkeypatch):
    _failing_with(monkeypatch, "down")
    for _ in range(3):
        service.sync_reminder(db, row, NOW)
    assert [kind for kind, _ in events(db, setup)] == ["failed"]


def test_a_different_error_records_a_second_failed_event(db, setup, row, monkeypatch):
    _failing_with(monkeypatch, "down")
    service.sync_reminder(db, row, NOW)
    service.sync_reminder(db, row, NOW)
    monkeypatch.setattr(smtp, "send_message", _raiser(smtplib.SMTPAuthenticationError(535, b"bad")))
    service.sync_reminder(db, row, NOW)
    assert [kind for kind, _ in events(db, setup)] == ["failed", "failed"]


def test_a_success_between_failures_records_another_failed_event(db, setup, row, mail, monkeypatch):
    _failing_with(monkeypatch, "down")
    service.sync_reminder(db, row, NOW)
    monkeypatch.setattr(smtp, "send_message", mail.append)
    service.sync_reminder(db, row, NOW)
    setup[0].name = "Renamed"
    db.commit()
    _failing_with(monkeypatch, "down")
    service.sync_reminder(db, row, NOW)
    assert [kind for kind, _ in events(db, setup)] == ["failed", "sent", "failed"]


def test_events_are_ordered_by_insert_order_not_by_time(db, setup):
    from tracker.models import CalendarReminderEvent

    tracker, person = setup
    later, earlier = datetime(2026, 10, 2, tzinfo=timezone.utc), datetime(2026, 10, 1, tzinfo=timezone.utc)
    for kind, at in (("switched_on", later), ("failed", earlier)):
        db.add(CalendarReminderEvent(user_id=person.id, tracker_id=tracker.id, kind=kind, at=at, detail="down"))
        db.flush()
    db.commit()
    assert [e.kind for e in service.events_for(db, person.id, tracker.id)] == ["failed", "switched_on"]


def test_the_failure_dedupe_looks_at_the_last_inserted_event(db, setup, row, monkeypatch):
    from tracker.models import CalendarReminderEvent

    tracker, person = setup
    _failing_with(monkeypatch, "down")
    service.sync_reminder(db, row, NOW)
    # a later-inserted event that carries an older time must still count as the newest
    db.add(
        CalendarReminderEvent(
            user_id=person.id, tracker_id=tracker.id, kind="switched_off", at=datetime(2000, 1, 1, tzinfo=timezone.utc)
        )
    )
    db.commit()
    service.sync_reminder(db, row, NOW)
    assert [kind for kind, _ in events(db, setup)] == ["failed", "switched_off", "failed"]
