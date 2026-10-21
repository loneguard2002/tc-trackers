"""Validation of tracker settings and group forms. Pure functions; no database or Flask access."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date

from ..engine.weeks import first_week_ending, week_endings

RAG_VALUES = ("Green", "Amber", "Red")
WEEKDAY_ERROR = "The week-ending day cannot change once entries exist."


def parse_date(value: str | None) -> date | None:
    try:
        return date.fromisoformat((value or "").strip())
    except ValueError:
        return None


def parse_int(value: str | None) -> int | None:
    try:
        return int((value or "").strip())
    except ValueError:
        return None


def _text(form: Mapping[str, str], key: str) -> str:
    return (form.get(key) or "").strip()


def validate_tracker_form(form: Mapping[str, str], *, locked_weekday: int | None = None) -> tuple[dict, list[str]]:
    """Validate tracker settings.

    ``locked_weekday`` is the current week-ending day when entries exist (so it cannot change), otherwise ``None``.
    The "start date" may be any date; it is stored as the first week-ending on or after it.
    """
    errors: list[str] = []
    values: dict = {
        "name": _text(form, "name"),
        "unit_label": _text(form, "unit_label"),
        "group_label": _text(form, "group_label"),
        "description": _text(form, "description"),
    }
    if not values["name"]:
        errors.append("A name is required.")

    weekday = parse_int(form.get("week_ending_weekday"))
    if weekday is None or not 0 <= weekday <= 6:
        errors.append("Choose the week-ending day.")
        weekday = None
    elif locked_weekday is not None and weekday != locked_weekday:
        errors.append(WEEKDAY_ERROR)
    values["week_ending_weekday"] = weekday

    start = parse_date(form.get("start_date"))
    last = parse_date(form.get("last_week_ending"))
    if start is None:
        errors.append("Enter a valid first week-ending date.")
    if last is None:
        errors.append("Enter a valid last week-ending date.")
    if weekday is not None and start is not None:
        first = first_week_ending(start, weekday)
        values["first_week_ending"] = first
        if last is not None:
            if last.weekday() != weekday:
                errors.append("The last week-ending must fall on the week-ending day.")
            else:
                try:
                    week_endings(first, last)
                except ValueError as exc:
                    if last < first:
                        errors.append("The last week-ending cannot be before the first.")
                    else:
                        errors.append(f"The last week-ending must be at most 52 weeks after the first ({exc}).")
            values["last_week_ending"] = last

    target = _text(form, "target_completion")
    values["target_completion"] = parse_date(target)
    if target and values["target_completion"] is None:
        errors.append("Enter a valid target completion date.")

    before = parse_int(form.get("completed_before_first") or "0")
    if before is None or before < 0:
        errors.append("The quantity completed before the first week must be zero or more.")
    values["completed_before_first"] = before

    average = parse_int(form.get("moving_average_weeks") or "3")
    if average is None or not 1 <= average <= 12:
        errors.append("The moving-average period must be between 1 and 12 weeks.")
    values["moving_average_weeks"] = average
    return values, errors


def validate_group_form(form: Mapping[str, str]) -> tuple[dict, list[str]]:
    errors: list[str] = []
    name = _text(form, "name")
    if not name:
        errors.append("A name is required.")
    baseline = parse_int(form.get("baseline"))
    if baseline is None or baseline < 0:
        errors.append("The baseline must be a whole number, zero or more.")
    starting = parse_int(form.get("starting_completed") or "0")
    if starting is None or starting < 0:
        errors.append("The starting completed figure must be a whole number, zero or more.")
    return {"name": name, "baseline": baseline, "starting_completed": starting}, errors


def validate_snapshot_form(form: Mapping[str, str]) -> tuple[dict, list[str]]:
    errors: list[str] = []
    ready = parse_int(form.get("ready_not_complete") or "0")
    if ready is None or ready < 0:
        errors.append("The ready-not-complete figure must be a whole number, zero or more.")
    planned_text = _text(form, "planned_completion")
    planned = parse_date(planned_text)
    if planned_text and planned is None:
        errors.append("Enter a valid planned completion date.")
    rag = _text(form, "rag") or None
    if rag is not None and rag not in RAG_VALUES:
        errors.append("The status must be Green, Amber or Red.")
    return {
        "ready_not_complete": ready,
        "planned_completion": planned,
        "rag": rag,
        "comment": _text(form, "comment"),
    }, errors
