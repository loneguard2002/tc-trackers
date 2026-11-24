"""The history of a tracker's target date: recording, reading and the forms that feed it (database required)."""

from datetime import date, datetime, timezone
from io import BytesIO

from sqlalchemy import select

from tests.conftest import post
from tests.importer.build_fixture import workbook_bytes
from tests.test_trackers import SETTINGS
from tracker.importer import create_tracker_from_preview, read_workbook
from tracker.models import TargetChange
from tracker.trackers.targets import TargetEntry, moves, record_target_change, target_as_of, target_history


def changes(db, tracker):
    return list(db.scalars(select(TargetChange).where(TargetChange.tracker_id == tracker.id).order_by(TargetChange.id)))


def add(db, tracker, old, new, at, user=None, reason=""):
    db.add(
        TargetChange(
            tracker_id=tracker.id,
            changed_at=at,
            changed_by=user.id if user else None,
            old_date=old,
            new_date=new,
            reason=reason,
        )
    )
    db.commit()


# --- Recording -----------------------------------------------------------------------------------------------


def test_record_adds_nothing_when_the_date_is_unchanged(db, tracker_factory):
    tracker = tracker_factory()
    record_target_change(db, tracker.id, date(2026, 12, 18), date(2026, 12, 18), None, "ignored")
    record_target_change(db, tracker.id, None, None, None)
    db.commit()
    assert changes(db, tracker) == []


def test_record_stores_who_what_and_why(db, tracker_factory, user_factory):
    tracker, user = tracker_factory(), user_factory()
    record_target_change(db, tracker.id, date(2026, 12, 18), date(2026, 12, 25), user.id, "Stock arrives later")
    db.commit()
    [row] = changes(db, tracker)
    assert (row.old_date, row.new_date, row.changed_by, row.reason) == (
        date(2026, 12, 18),
        date(2026, 12, 25),
        user.id,
        "Stock arrives later",
    )
    assert row.changed_at is not None


def test_settings_saving_a_new_target_records_one_change(client, logged_in_admin, db, tracker_factory, labels_form):
    tracker = tracker_factory(target_completion=date(2026, 12, 18))
    form = {**SETTINGS, **labels_form, "target_completion": "2026-12-25", "target_reason": "Delivery slipped"}
    assert post(client, f"/trackers/{tracker.id}/settings", form).status_code == 302
    [row] = changes(db, tracker)
    assert (row.old_date, row.new_date, row.reason) == (date(2026, 12, 18), date(2026, 12, 25), "Delivery slipped")
    assert row.changed_by == logged_in_admin.id


def test_settings_with_the_date_unchanged_records_nothing_even_with_a_reason(
    client, logged_in_admin, db, tracker_factory, labels_form
):
    tracker = tracker_factory(target_completion=date(2026, 12, 18))
    form = {**SETTINGS, **labels_form, "name": "Renamed", "target_reason": "Typed but unused"}
    assert post(client, f"/trackers/{tracker.id}/settings", form).status_code == 302
    assert changes(db, tracker) == []


def test_settings_clearing_the_target_records_a_removal(client, logged_in_admin, db, tracker_factory, labels_form):
    tracker = tracker_factory(target_completion=date(2026, 12, 18))
    form = {**SETTINGS, **labels_form, "target_completion": ""}
    assert post(client, f"/trackers/{tracker.id}/settings", form).status_code == 302
    [row] = changes(db, tracker)
    assert (row.old_date, row.new_date, row.reason) == (date(2026, 12, 18), None, "")


def test_the_activity_record_still_carries_the_target_change(client, logged_in_admin, db, tracker_factory, labels_form):
    from tests.test_trackers import audit_actions

    tracker = tracker_factory(target_completion=date(2026, 12, 18))
    form = {**SETTINGS, **labels_form, "target_completion": "2026-12-25"}
    post(client, f"/trackers/{tracker.id}/settings", form)
    [entry] = [a for a in audit_actions(db, tracker.id) if a.action == "settings_updated"]
    assert entry.detail["target_completion"] == ["2026-12-18", "2026-12-25"]


def test_a_reason_over_500_characters_is_refused(client, logged_in_admin, db, tracker_factory, labels_form):
    tracker = tracker_factory(target_completion=date(2026, 12, 18))
    form = {**SETTINGS, **labels_form, "target_completion": "2026-12-25", "target_reason": "x" * 501}
    response = post(client, f"/trackers/{tracker.id}/settings", form)
    assert response.status_code == 400
    assert "Keep the reason under 500 characters." in response.get_data(as_text=True)
    assert changes(db, tracker) == []
    ok = {**form, "target_reason": "x" * 500}
    assert post(client, f"/trackers/{tracker.id}/settings", ok).status_code == 302


def test_creating_a_tracker_with_a_target_records_a_set_entry(client, logged_in_admin, db, labels_form):
    from tracker.models import Tracker

    assert post(client, "/trackers/new", {**SETTINGS, **labels_form}).status_code == 302
    tracker = db.scalars(select(Tracker).order_by(Tracker.id.desc())).first()
    [row] = changes(db, tracker)
    assert (row.old_date, row.new_date, row.changed_by) == (None, date(2026, 12, 18), logged_in_admin.id)


def test_creating_a_tracker_without_a_target_records_nothing(client, logged_in_admin, db, labels_form):
    from tracker.models import Tracker

    post(client, "/trackers/new", {**SETTINGS, **labels_form, "target_completion": ""})
    tracker = db.scalars(select(Tracker).order_by(Tracker.id.desc())).first()
    assert changes(db, tracker) == []


def test_an_import_with_a_target_records_one_set_entry(db, user_factory):
    admin = user_factory(is_admin=True)
    tracker = create_tracker_from_preview(
        db, read_workbook(BytesIO(workbook_bytes()), 4), "Rollout", "", "", admin.id, False
    )
    db.commit()
    [row] = changes(db, tracker)
    assert (row.old_date, row.new_date, row.changed_by) == (None, date(2026, 12, 18), admin.id)


# --- The forms -----------------------------------------------------------------------------------------------


def test_the_settings_form_asks_why_the_target_is_moving_and_the_create_form_does_not(
    client, logged_in_admin, tracker_factory
):
    tracker = tracker_factory()
    settings = client.get(f"/trackers/{tracker.id}/settings").get_data(as_text=True)
    assert "Why is the target moving?" in settings
    assert "Optional. Recorded with the change, and shown on the report." in settings
    assert 'name="target_reason"' in settings
    assert settings.index('name="target_completion"') < settings.index('name="target_reason"')
    new = client.get("/trackers/new").get_data(as_text=True)
    assert "Why is the target moving?" not in new and 'name="target_reason"' not in new


# --- Reading -------------------------------------------------------------------------------------------------


def utc(y, m, d, h=12):
    return datetime(y, m, d, h, tzinfo=timezone.utc)


def test_history_numbers_the_entries_with_kinds_days_and_the_current_one(db, tracker_factory, user_factory):
    tracker, user = tracker_factory(target_completion=date(2026, 12, 22)), user_factory()
    add(db, tracker, None, date(2026, 12, 18), utc(2026, 9, 7), user, "First plan")
    add(db, tracker, date(2026, 12, 18), date(2026, 12, 25), utc(2026, 10, 5))
    add(db, tracker, date(2026, 12, 25), date(2026, 12, 22), utc(2026, 11, 2))
    add(db, tracker, date(2026, 12, 22), None, utc(2026, 11, 9))
    entries = target_history(db, tracker, date(2026, 12, 31))
    assert [(e.number, e.kind, e.days, e.current) for e in entries] == [
        (1, "set", None, False),
        (2, "moved", 7, False),
        (3, "moved", -3, False),
        (4, "removed", None, True),
    ]
    assert entries[0] == TargetEntry(
        1, date(2026, 12, 18), "set", date(2026, 9, 7), user.full_name, "First plan", None, False
    )
    assert entries[3].date is None and entries[1].by is None
    assert moves(entries) == 2


def test_history_filters_by_the_trackers_own_zone(db, tracker_factory):
    tracker = tracker_factory(send_timezone="Asia/Tokyo")
    # 20:00 UTC on the 6th is 05:00 on the 7th in Tokyo.
    add(db, tracker, None, date(2026, 12, 18), utc(2026, 9, 6, 20))
    assert target_history(db, tracker, date(2026, 9, 6)) == []
    [entry] = target_history(db, tracker, date(2026, 9, 7))
    assert entry.changed_on == date(2026, 9, 7)


def test_target_as_of(db, tracker_factory):
    tracker = tracker_factory(target_completion=date(2026, 12, 25))
    add(db, tracker, date(2026, 12, 18), date(2026, 12, 25), utc(2026, 10, 5))
    add(db, tracker, date(2026, 12, 25), date(2027, 1, 8), utc(2026, 10, 19))
    assert target_as_of(db, tracker, date(2026, 9, 28)) == date(2026, 12, 18)
    assert target_as_of(db, tracker, date(2026, 10, 5)) == date(2026, 12, 25)
    assert target_as_of(db, tracker, date(2026, 11, 1)) == date(2027, 1, 8)


def test_target_as_of_without_changes_is_the_current_target(db, tracker_factory):
    assert target_as_of(db, tracker_factory(target_completion=date(2026, 12, 18)), date(2026, 9, 1)) == date(
        2026, 12, 18
    )
    assert target_as_of(db, tracker_factory(), date(2026, 9, 1)) is None
    assert target_history(db, tracker_factory(), date(2026, 9, 1)) == []
