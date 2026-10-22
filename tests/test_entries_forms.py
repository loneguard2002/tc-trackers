"""Pure validation helpers for data entry (no database)."""

from datetime import date

import pytest

from tracker.entries.forms import (
    check_entry_date,
    next_risk_ref,
    parse_quantity,
    parse_targets,
    validate_inputs_form,
    validate_risk_form,
)

FIRST, LAST = date(2026, 9, 4), date(2026, 12, 25)


@pytest.mark.parametrize("text,expected", [("1", 1), (" 12 ", 12), ("+3", 3)])
def test_quantity_accepts_whole_numbers(text, expected):
    assert parse_quantity(text) == (expected, None)


@pytest.mark.parametrize("text", ["0", "-2", "1.5", "", "abc", None])
def test_quantity_rejects_others(text):
    value, error = parse_quantity(text)
    assert value is None and error == "The quantity must be a whole number of at least 1."


def test_entry_date_maps_to_week_ending():
    assert check_entry_date(date(2026, 10, 14), 4, FIRST, LAST) == (date(2026, 10, 16), None)


def test_entry_date_outside_range_message():
    expected = "That date is outside this tracker's weeks (04 Sep 2026 to 25 Dec 2026)."
    assert check_entry_date(date(2026, 12, 26), 4, FIRST, LAST) == (None, expected)
    assert check_entry_date(date(2026, 8, 28), 4, FIRST, LAST) == (None, expected)


def test_entry_date_boundaries_accepted():
    assert check_entry_date(date(2026, 8, 29), 4, FIRST, LAST)[1] is None  # week ending 4 Sep
    assert check_entry_date(date(2026, 12, 25), 4, FIRST, LAST)[1] is None


def test_entry_date_missing():
    assert check_entry_date(None, 4, FIRST, LAST)[1] == "Enter a valid date."


def test_targets_parse_blank_as_none():
    weeks = [date(2026, 9, 4), date(2026, 9, 11), date(2026, 9, 18)]
    form = {"target-2026-09-04": "10", "target-2026-09-11": "", "target-2026-09-18": "0"}
    targets, errors = parse_targets(form, weeks)
    assert targets == {weeks[0]: 10, weeks[1]: None, weeks[2]: 0} and errors == []


def test_targets_reject_negative_and_text():
    weeks = [date(2026, 9, 4), date(2026, 9, 11)]
    _, errors = parse_targets({"target-2026-09-04": "-1", "target-2026-09-11": "x"}, weeks)
    assert len(errors) == 2


def test_inputs_status_validation():
    assert validate_inputs_form({"status": "Amber", "headline": " h "})[0]["headline"] == "h"
    assert validate_inputs_form({"status": ""})[0]["status"] is None
    assert validate_inputs_form({"status": "Blue"})[1]


def test_risk_ref_numbering():
    assert next_risk_ref([]) == "R1"
    assert next_risk_ref(["R1", "R2", "X9", "R10"]) == "R11"


def test_risk_form_validation():
    values, errors = validate_risk_form({"description": "d", "group_id": "3", "raised_on": "2026-10-01"}, [3])
    assert errors == [] and values["status"] == "Open" and values["group_id"] == 3 and values["ref"] == ""
    assert validate_risk_form({"group_id": "9"}, [3])[1]
    assert validate_risk_form({"status": "Done"}, [])[1]
    assert validate_risk_form({"rag": "Pink"}, [])[1]
    assert validate_risk_form({"target_date": "nope"}, [])[1]
