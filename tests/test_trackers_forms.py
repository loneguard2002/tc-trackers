"""Form validation for trackers and groups (pure; no database)."""

from datetime import date, time

import pytest

from tracker.trackers.forms import (
    parse_date,
    parse_int,
    validate_group_form,
    validate_schedule_form,
    validate_snapshot_form,
    validate_tracker_form,
)


def tracker_form(**overrides) -> dict:
    values = {
        "name": "Rollout",
        "unit_label": "thin clients",
        "group_label": "Location",
        "description": "",
        "week_ending_weekday": "4",
        "start_date": "2026-09-02",
        "last_week_ending": "2026-12-25",
        "target_completion": "2026-12-18",
        "completed_before_first": "10",
        "moving_average_weeks": "3",
    }
    values.update(overrides)
    return values


def test_parse_helpers():
    assert parse_date("2026-09-04") == date(2026, 9, 4)
    assert parse_date("") is None
    assert parse_date("not a date") is None
    assert parse_int(" 12 ") == 12
    assert parse_int("1.5") is None
    assert parse_int("") is None


def test_first_week_snaps_to_week_ending_day():
    values, errors = validate_tracker_form(tracker_form())
    assert errors == []
    assert values["first_week_ending"] == date(2026, 9, 4)  # Wednesday 2 Sep, Friday week-ending
    assert values["week_ending_weekday"] == 4
    assert values["completed_before_first"] == 10


def test_last_week_beyond_52_rejected():
    _, errors = validate_tracker_form(tracker_form(last_week_ending="2027-12-31"))
    assert any("52 weeks" in e for e in errors)


def test_last_week_must_be_week_ending_day():
    _, errors = validate_tracker_form(tracker_form(last_week_ending="2026-12-24"))
    assert errors


def test_last_before_first_rejected():
    _, errors = validate_tracker_form(tracker_form(last_week_ending="2026-08-28"))
    assert errors


def test_required_and_ranges():
    _, errors = validate_tracker_form(tracker_form(name=" ", moving_average_weeks="13", completed_before_first="-1"))
    assert len(errors) == 3


def test_weekday_change_refused_when_locked():
    _, errors = validate_tracker_form(tracker_form(week_ending_weekday="3"), locked_weekday=4)
    assert "The week-ending day cannot change once entries exist." in errors


def test_weekday_unchanged_allowed_when_locked():
    _, errors = validate_tracker_form(tracker_form(), locked_weekday=4)
    assert errors == []


def test_group_form():
    values, errors = validate_group_form({"name": " Site A ", "baseline": "40", "starting_completed": ""})
    assert errors == []
    assert values == {"name": "Site A", "baseline": 40, "starting_completed": 0}
    _, errors = validate_group_form({"name": "", "baseline": "-3"})
    assert len(errors) == 2


def test_snapshot_form():
    values, errors = validate_snapshot_form(
        {"ready_not_complete": "5", "planned_completion": "2026-11-06", "rag": "Amber", "comment": " late stock "}
    )
    assert errors == []
    assert values == {
        "ready_not_complete": 5,
        "planned_completion": date(2026, 11, 6),
        "rag": "Amber",
        "comment": "late stock",
    }
    values, errors = validate_snapshot_form({"ready_not_complete": "", "planned_completion": "", "rag": ""})
    assert errors == [] and values["rag"] is None and values["planned_completion"] is None
    _, errors = validate_snapshot_form({"rag": "Blue", "ready_not_complete": "-1"})
    assert len(errors) == 2


# --- Scheduled sending fields ----------------------------------------------------------------------------------


def schedule(form):
    return validate_schedule_form(form, current_time=time(17, 0), current_timezone="Europe/London")


def test_schedule_form_valid():
    values, errors = schedule({"schedule_enabled": "1", "send_time": "08:30", "send_timezone": "Asia/Dubai"})
    assert errors == []
    assert values == {"schedule_enabled": True, "send_time": time(8, 30), "send_timezone": "Asia/Dubai"}


def test_schedule_form_absent_checkbox_disables_and_keeps_values():
    values, errors = schedule({})
    assert errors == [] and values["schedule_enabled"] is False
    assert values["send_timezone"] == "Europe/London" and values["send_time"].hour == 17


@pytest.mark.parametrize("bad", ["25:00", "9:30", "17:60", "5pm", "17:00:00"])
def test_schedule_form_rejects_bad_time(bad):
    _, errors = schedule({"send_time": bad})
    assert errors and "HH:MM" in errors[0]


@pytest.mark.parametrize("bad", ["Mars/Olympus", "../etc/passwd", "Europe/"])
def test_schedule_form_rejects_unknown_zone(bad):
    _, errors = schedule({"send_timezone": bad})
    assert errors and "not recognised" in errors[0]
