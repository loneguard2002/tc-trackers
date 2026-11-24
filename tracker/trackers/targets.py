"""The history of a tracker's target completion date: recording each change and reading what held on a given day."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, replace
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
    changed_on: date | None  # None: in place before changes were recorded
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


def _changes(session: Session, tracker: Tracker) -> list[tuple[TargetChange, date]]:
    """Every change of the tracker's target with the calendar day it was made in its own time zone, oldest first."""
    zone = ZoneInfo(tracker.send_timezone)
    rows = session.scalars(select(TargetChange).where(TargetChange.tracker_id == tracker.id).order_by(TargetChange.id))
    return [(row, row.changed_at.astimezone(zone).date()) for row in rows]


def target_history(session: Session, tracker: Tracker, upto: date) -> list[TargetEntry]:
    """The target's history as it stood on ``upto``: one entry per change made by then, oldest first.

    Changes made before recording began are not known (nothing is backfilled), but the target in place then is: a target
    with no recorded change, or the date the first recorded change replaced, stands as a "set" entry with no
    ``changed_on``. So the last entry is always the target in force on ``upto`` (none when it was removed or never set).
    """
    changes = _changes(session, tracker)
    in_place = changes[0][0].old_date if changes else tracker.target_completion
    held = [(change, day) for change, day in changes if day <= upto]
    names = {
        user.id: user.full_name
        for user in session.scalars(select(User).where(User.id.in_({c.changed_by for c, _ in held if c.changed_by})))
    }
    entries = []
    if in_place is not None:
        entries.append(TargetEntry(1, in_place, "set", None, None, "", None, False))
    for change, day in held:
        if change.new_date is None:
            kind, days = "removed", None
        elif change.old_date is None:
            kind, days = "set", None
        else:
            kind, days = "moved", (change.new_date - change.old_date).days
        entries.append(
            TargetEntry(
                number=len(entries) + 1,
                date=change.new_date,
                kind=kind,
                changed_on=day,
                by=names.get(change.changed_by),
                reason=change.reason,
                days=days,
                current=False,
            )
        )
    if entries:
        entries[-1] = replace(entries[-1], current=True)
    return entries


def target_as_of(session: Session, tracker: Tracker, upto: date) -> date | None:
    """The target in force on ``upto``: the last entry of its history by then."""
    history = target_history(session, tracker, upto)
    return history[-1].date if history else None


def shows_history(entries: Iterable[TargetEntry]) -> bool:
    """Whether the target's history is worth drawing and listing: it has moved or been removed. A target set once and
    never changed is just "the target", with no numbered badges and no list."""
    entries = list(entries)
    return moves(entries) > 0 or any(entry.kind == "removed" for entry in entries)


def moves(entries: Iterable[TargetEntry]) -> int:
    return sum(1 for entry in entries if entry.kind == "moved")
