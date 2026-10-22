"""Validation for entries, targets, weekly inputs and risks. Pure functions; no database or Flask access."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from datetime import date

from ..engine.weeks import week_ending_for
from ..trackers.forms import RAG_VALUES, parse_date, parse_int

RISK_STATUSES = ("Open", "In progress", "Closed")
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
QUANTITY_ERROR = "The quantity must be a whole number of at least 1."
_DIGITS = re.compile(r"^[+-]?\d+$")


def format_date(d: date) -> str:
    """Format as DD Mon YYYY (locale independent)."""
    return f"{d.day:02d} {MONTHS[d.month - 1]} {d.year}"


def parse_quantity(value: str | None) -> tuple[int | None, str | None]:
    """Parse an entry quantity: a whole number of at least 1."""
    text = (value or "").strip()
    if not _DIGITS.match(text) or int(text) < 1:
        return None, QUANTITY_ERROR
    return int(text), None


def check_entry_date(entry_date: date | None, weekday: int, first: date, last: date) -> tuple[date | None, str | None]:
    """Return the week-ending for ``entry_date`` or an error when it falls outside the tracker's weeks."""
    if entry_date is None:
        return None, "Enter a valid date."
    week_ending = week_ending_for(entry_date, weekday)
    if week_ending < first or week_ending > last:
        return None, f"That date is outside this tracker's weeks ({format_date(first)} to {format_date(last)})."
    return week_ending, None


def parse_target(value: str | None) -> tuple[int | None, bool]:
    """Parse one target: ``(value, ok)``. Blank gives ``(None, True)``; otherwise an integer of zero or more."""
    text = (value or "").strip()
    if not text:
        return None, True
    if not _DIGITS.match(text) or int(text) < 0:
        return None, False
    return int(text), True


def parse_targets(form: Mapping[str, str], weeks: Iterable[date]) -> tuple[dict[date, int | None], list[str]]:
    """Read ``target-YYYY-MM-DD`` fields for each week. Blank clears the target."""
    targets: dict[date, int | None] = {}
    errors: list[str] = []
    for week in weeks:
        value, ok = parse_target(form.get(f"target-{week.isoformat()}"))
        if not ok:
            errors.append(f"The target for {format_date(week)} must be a whole number, zero or more, or blank.")
        targets[week] = value
    return targets, errors


def validate_inputs_form(form: Mapping[str, str]) -> tuple[dict, list[str]]:
    errors: list[str] = []
    status = (form.get("status") or "").strip() or None
    if status is not None and status not in RAG_VALUES:
        errors.append("The status must be Green, Amber or Red.")
    return {
        "status": status,
        "headline": (form.get("headline") or "").strip(),
        "decisions": (form.get("decisions") or "").strip(),
    }, errors


def next_risk_ref(existing: Iterable[str]) -> str:
    """The next ``R{n}``: one more than the highest numbered existing reference."""
    numbers = [int(m.group(1)) for ref in existing if (m := re.fullmatch(r"R(\d+)", ref))]
    return f"R{max(numbers, default=0) + 1}"


def validate_risk_form(form: Mapping[str, str], group_ids: Iterable[int]) -> tuple[dict, list[str]]:
    """Validate a risk. ``ref`` is returned as an empty string when blank (the caller assigns it)."""
    errors: list[str] = []
    text = lambda key: (form.get(key) or "").strip()  # noqa: E731
    status = text("status") or "Open"
    if status not in RISK_STATUSES:
        errors.append("The status must be Open, In progress or Closed.")
    rag = text("rag") or None
    if rag is not None and rag not in RAG_VALUES:
        errors.append("The RAG must be Green, Amber or Red.")
    group_id = None
    if text("group_id"):
        group_id = parse_int(form.get("group_id"))
        if group_id is None or group_id not in set(group_ids):
            errors.append("Choose a group from this tracker.")
            group_id = None
    dates = {}
    for key, label in (("raised_on", "raised date"), ("target_date", "target date")):
        dates[key] = parse_date(form.get(key))
        if text(key) and dates[key] is None:
            errors.append(f"Enter a valid {label}.")
    return {
        "ref": text("ref"),
        "description": text("description"),
        "impact": text("impact"),
        "group_id": group_id,
        "owner_role": text("owner_role"),
        "status": status,
        "rag": rag,
        "latest_update": text("latest_update"),
        **dates,
    }, errors
