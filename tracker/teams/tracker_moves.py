"""Moving trackers into a team from its page: the picker's rows, the access preview and the move itself.

A tracker belongs to one team, so it moves here from its current team (or from none). It keeps every region it has and
gains the team's region when it lacks it, so people who reach it by region keep their access and the team's region is
covered; nothing is removed. A team without a region, or whose region is retired (a retired region cannot be given to
a tracker), adds none.

The preview applies the move inside a savepoint, reads the roles of everyone who could be affected again and rolls
the savepoint back. Only people who belong to a team or hold a region grant can be affected: a direct role and the
``view_all_trackers`` permission do not depend on the tracker's team or regions. Administrators and people who are
not active are left out, as on the Higher teams preview.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import NamedTuple

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..audit import change, record
from ..auth.roles import tracker_roles
from ..ids import parse_id
from ..lists.catalogue import tracker_labels
from ..models import Region, RegionGrant, Team, TeamMember, Tracker, TrackerRegion, User
from .impact import AccessChange, MoveImpact
from .tree import load_team_rows, team_labels

CHOOSE_TRACKERS_MESSAGE = "Choose at least one tracker."
TRACKER_CHOICE_ERROR = "Choose trackers from the list. A tracker may have been moved or deleted at the same moment."
TRACKERS_CHANGED_MESSAGE = (
    "Nothing was moved: someone moved, changed or deleted one of these trackers at the same moment. Choose them again."
)
TEAM_DELETED_MESSAGE = "Nothing was moved: someone deleted the team at the same moment."


class MovingTracker(NamedTuple):
    """One tracker as the picker and the preview show it."""

    tracker: Tracker
    team_name: str | None  # its current team, or None
    regions: list[str]  # its region codes now
    added: str | None  # the team's region code when the move adds it


def team_region(session: Session, team: Team) -> Region | None:
    """The region a tracker moved into the team gains when it lacks it, or ``None``."""
    region = session.get(Region, team.region_id) if team.region_id is not None else None
    return region if region is not None and not region.retired else None


def _by_name(trackers: Iterable[Tracker]) -> list[Tracker]:
    return sorted(trackers, key=lambda t: (t.name.casefold(), t.name, t.id))


def moving_trackers(session: Session, team: Team, trackers: Sequence[Tracker]) -> list[MovingTracker]:
    """Each tracker with its current team, its regions and the region the move to ``team`` adds."""
    labels = team_labels(load_team_rows(session))
    regions = tracker_labels(session, [t.id for t in trackers])
    region = team_region(session, team)
    rows = []
    for tracker in trackers:
        codes = regions[tracker.id].regions
        added = region.code if region is not None and region.code not in codes else None
        rows.append(MovingTracker(tracker, labels.get(tracker.team_id), codes, added))
    return rows


def picker_trackers(session: Session, team: Team) -> list[MovingTracker]:
    """The trackers not in the team, archived included, by name."""
    found = session.scalars(
        select(Tracker)
        .where(or_(Tracker.team_id.is_(None), Tracker.team_id != team.id))
        .order_by(func.lower(Tracker.name), Tracker.id)
    )
    return moving_trackers(session, team, list(found))


def parse_trackers(session: Session, team: Team, texts: Iterable[str]) -> tuple[list[Tracker], str | None]:
    """The trackers chosen to move into ``team``, by name, or ``([], message)``.

    Blank values are ignored. Anything else that is not the id of a tracker outside the team refuses the whole choice.
    """
    texts = [text for text in texts if text.strip()]
    if not texts:
        return [], CHOOSE_TRACKERS_MESSAGE
    ids = {parse_id(text) for text in texts}
    if None in ids:
        return [], TRACKER_CHOICE_ERROR
    trackers = list(session.scalars(select(Tracker).where(Tracker.id.in_(ids))))
    if len(trackers) != len(ids) or any(tracker.team_id == team.id for tracker in trackers):
        return [], TRACKER_CHOICE_ERROR
    return _by_name(trackers), None


def _apply(session: Session, team: Team, trackers: Sequence[Tracker]) -> dict[int, str]:
    """Put the trackers in the team and add its region where missing; the region code added, by tracker id."""
    region = team_region(session, team)
    covered = (
        set(
            session.scalars(
                select(TrackerRegion.tracker_id).where(
                    TrackerRegion.region_id == region.id, TrackerRegion.tracker_id.in_([t.id for t in trackers])
                )
            )
        )
        if region is not None
        else set()
    )
    added = {}
    for tracker in trackers:
        tracker.team_id = team.id
        if region is not None and tracker.id not in covered:
            session.add(TrackerRegion(tracker_id=tracker.id, region_id=region.id))
            added[tracker.id] = region.code
    return added


def tracker_move_impact(session: Session, team: Team, trackers: Sequence[Tracker]) -> MoveImpact:
    """Compare each person's role on the trackers before and after moving them into ``team``.

    Leaves the session as it found it: the move is made in a savepoint that is always rolled back.
    """
    tracker_ids = {tracker.id for tracker in trackers}
    by_id = {tracker.id: tracker for tracker in trackers}
    users = list(
        session.scalars(
            select(User)
            .where(
                User.status == "active",
                User.is_admin.is_(False),
                or_(User.id.in_(select(TeamMember.user_id)), User.id.in_(select(RegionGrant.user_id))),
            )
            .order_by(User.id)
        )
    )

    def read() -> dict[int, dict[int, str]]:
        return {
            user.id: {t: role for t, role in tracker_roles(session, user).items() if t in tracker_ids} for user in users
        }

    before = read()
    with session.begin_nested() as savepoint:
        _apply(session, team, trackers)
        session.flush()
        after = read()
        savepoint.rollback()
    losses, gains, changes = [], [], []
    for user in users:
        for tracker_id in tracker_ids:
            was, now = before[user.id].get(tracker_id), after[user.id].get(tracker_id)
            if was == now:
                continue
            item = AccessChange(user, by_id[tracker_id], was, now)
            (losses if now is None else gains if was is None else changes).append(item)
    for found in (losses, gains, changes):
        found.sort(key=lambda c: (c.user.full_name.casefold(), c.tracker.name.casefold(), c.tracker.id, c.user.id))
    return MoveImpact(losses, gains, changes, _by_name(trackers))


def move_trackers(session: Session, actor: User, team: Team, trackers: Sequence[Tracker]) -> None:
    """Move the trackers into ``team`` and record it; the caller runs the self-promotion guard and commits.

    Each tracker gets a ``tracker_team_changed`` entry (the old and new team) and, when it gains the team's region,
    a ``settings_updated`` entry with its regions before and after, as a change of regions in its settings logs it.
    """
    labels = team_labels(load_team_rows(session))
    regions = tracker_labels(session, [t.id for t in trackers])
    old_teams = {tracker.id: tracker.team_id for tracker in trackers}
    added = _apply(session, team, trackers)
    for tracker in trackers:
        record(
            session,
            user_id=actor.id,
            tracker_id=tracker.id,
            action="tracker_team_changed",
            entity="tracker",
            entity_id=tracker.id,
            detail=change(labels.get(old_teams[tracker.id]), labels.get(team.id, team.name)),
        )
        if tracker.id in added:
            before = regions[tracker.id].regions
            after = sorted([*before, added[tracker.id]], key=lambda code: (code.casefold(), code))
            record(
                session,
                user_id=actor.id,
                tracker_id=tracker.id,
                action="settings_updated",
                entity="tracker",
                entity_id=tracker.id,
                detail={"regions": [before, after]},
            )
