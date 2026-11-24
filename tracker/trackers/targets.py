"""The history of a tracker's target completion date: recording each change and reading what held on a given day."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from typing import Literal
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import TargetChange, Tracker, User


@dataclass(frozen=True)
class TargetEntry:
    number: int
    date: date | None
    kind: Literal["set", "moved", "removed"]
    changed_on: date
    by: str | None
    reason: str
    days: int | None
    current: bool


def record_target_change(
    session: Session, tracker_id: int, old: date | None, new: date | None, user_id: int | None, reason: str = ""
) -> None:
    """Add the change to ``session`` (the caller commits); an unchanged date adds nothing."""
    if old == new:
        return
    session.add(TargetChange(tracker_id=tracker_id, changed_by=user_id, old_date=old, new_date=new, reason=reason))


def _changes_by(session: Session, tracker: Tracker, upto: date) -> list[tuple[TargetChange, date]]:
    """The tracker's changes made on or before ``upto`` (a calendar day in its own time zone), oldest first."""
    zone = ZoneInfo(tracker.send_timezone)
    rows = session.scalars(select(TargetChange).where(TargetChange.tracker_id == tracker.id).order_by(TargetChange.id))
    dated = [(row, row.changed_at.astimezone(zone).date()) for row in rows]
    return [(row, day) for row, day in dated if day <= upto]


def target_history(session: Session, tracker: Tracker, upto: date) -> list[TargetEntry]:
    changes = _changes_by(session, tracker, upto)
    names = {
        user.id: user.full_name
        for user in session.scalars(select(User).where(User.id.in_({c.changed_by for c, _ in changes if c.changed_by})))
    }
    entries = []
    for number, (change, day) in enumerate(changes, start=1):
        if change.new_date is None:
            kind, days = "removed", None
        elif change.old_date is None:
            kind, days = "set", None
        else:
            kind, days = "moved", (change.new_date - change.old_date).days
        entries.append(
            TargetEntry(
                number=number,
                date=change.new_date,
                kind=kind,
                changed_on=day,
                by=names.get(change.changed_by),
                reason=change.reason,
                days=days,
                current=number == len(changes),
            )
        )
    return entries


def target_as_of(session: Session, tracker: Tracker, upto: date) -> date | None:
    """The target in force on ``upto``: the last change by then; before the first change, the date it replaced."""
    zone = ZoneInfo(tracker.send_timezone)
    rows = list(
        session.scalars(select(TargetChange).where(TargetChange.tracker_id == tracker.id).order_by(TargetChange.id))
    )
    if not rows:
        return tracker.target_completion
    held = [row for row in rows if row.changed_at.astimezone(zone).date() <= upto]
    return held[-1].new_date if held else rows[0].old_date


def shows_history(entries: Iterable[TargetEntry]) -> bool:
    """Whether the target's history is worth drawing and listing: it has moved or been removed. A target set once and
    never changed is just "the target", with no numbered badges and no list."""
    entries = list(entries)
    return moves(entries) > 0 or any(entry.kind == "removed" for entry in entries)


def moves(entries: Iterable[TargetEntry]) -> int:
    return sum(1 for entry in entries if entry.kind == "moved")
