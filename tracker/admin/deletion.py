"""Deleting a person (design 2026-11-13, "Delete").

The person's row stays, with status ``deleted``, so the history keeps their name and email; the email becomes free for a
new account. Everything else that ties them to the application goes: team places, region access, direct tracker roles,
permission sets held directly, the lead of trackers (left with nobody in charge), their email on every tracker's report
recipient list and on report sends still queued for a retry, and their sign-in (password, Microsoft link and the
administrator flag). Recipients are typed-in addresses with no link to accounts, so they are matched by email,
ignoring case.

Each removal is recorded with the entry the same change writes elsewhere (a queued send left with nobody records its
failure, as a send that fails does), then one ``user_deleted`` entry holds the name, the email, whether they were an
administrator and the counts; every entry names the person in ``target_user_id``. Entries about one tracker carry its
``tracker_id``, so the Activity page hides their detail from viewers who cannot open that tracker; the summary names no
tracker.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import partial

from sqlalchemy import Select, delete, func, or_, select, update
from sqlalchemy.orm import Session, defer

from ..audit import change, record
from ..mail import sending
from ..models import (
    AuditLog,
    PermissionSet,
    PermissionSetHolder,
    Recipient,
    Region,
    RegionGrant,
    ReportInput,
    ReportSend,
    TeamMember,
    Tracker,
    TrackerRole,
    User,
)
from ..teams.tree import load_team_rows, team_labels

NO_RECIPIENTS_LEFT = "No recipients left"


@dataclass(frozen=True)
class DeletionSummary:
    """What deleting a person removes, and how much of their history stays, as things stand now."""

    teams: list[tuple[int, str]]  # (team id, team path)
    regions: list[tuple[int, str, str]]  # (region id, code, role)
    roles: list[tuple[int, str, str]]  # (tracker id, tracker name, role), direct tracker roles
    sets: list[tuple[int, str]]  # (set id, name), held directly
    led: list[tuple[int, str]]  # (tracker id, tracker name)
    recipient_trackers: list[tuple[int, str]]  # trackers whose recipient list holds the email, any case
    activity_entries: int  # entries with user_id or target_user_id = the person
    report_inputs: int  # report_inputs.prepared_by = the person


def _rows(session: Session, query: Select) -> list[tuple]:
    return [tuple(row) for row in session.execute(query)]


def _team_places(session: Session, user: User) -> list[tuple[int, str, str]]:
    """``(team id, team path, role)`` for each of the person's team places, by path."""
    labels = team_labels(load_team_rows(session))
    places = session.execute(select(TeamMember.team_id, TeamMember.role).where(TeamMember.user_id == user.id))
    return sorted(
        ((team_id, labels.get(team_id, ""), role) for team_id, role in places),
        key=lambda place: (place[1].casefold(), place[0]),
    )


def _regions(user: User) -> Select:
    """``(region id, code, role)`` for each region the person has access to, by code."""
    return (
        select(Region.id, Region.code, RegionGrant.role)
        .join(RegionGrant, RegionGrant.region_id == Region.id)
        .where(RegionGrant.user_id == user.id)
        .order_by(func.lower(Region.code), Region.id)
    )


def _roles(user: User) -> Select:
    """``(tracker id, tracker name, role)`` for each direct tracker role, by tracker name."""
    return (
        select(Tracker.id, Tracker.name, TrackerRole.role)
        .join(TrackerRole, TrackerRole.tracker_id == Tracker.id)
        .where(TrackerRole.user_id == user.id)
        .order_by(func.lower(Tracker.name), Tracker.id)
    )


def _sets(user: User) -> Select:
    """``(set id, name)`` for each permission set held directly, by name."""
    return (
        select(PermissionSet.id, PermissionSet.name)
        .join(PermissionSetHolder, PermissionSetHolder.set_id == PermissionSet.id)
        .where(PermissionSetHolder.user_id == user.id)
        .order_by(func.lower(PermissionSet.name), PermissionSet.id)
    )


def _led(user: User) -> Select:
    """``(tracker id, tracker name)`` for each tracker the person leads, by name."""
    return (
        select(Tracker.id, Tracker.name)
        .where(Tracker.lead_user_id == user.id)
        .order_by(func.lower(Tracker.name), Tracker.id)
    )


def _recipients(user: User) -> Select:
    """``(recipient id, tracker id, tracker name, stored email)`` for each recipient row holding the email, any case."""
    return (
        select(Recipient.id, Tracker.id, Tracker.name, Recipient.email)
        .join(Tracker, Tracker.id == Recipient.tracker_id)
        .where(func.lower(Recipient.email) == user.email.lower())
        .order_by(func.lower(Tracker.name), Tracker.id, Recipient.email)
    )


def deletion_summary(session: Session, user: User) -> DeletionSummary:
    """What deleting ``user`` would remove and keep, for the confirmation."""
    recipients = _rows(session, _recipients(user))
    mentions = or_(AuditLog.user_id == user.id, AuditLog.target_user_id == user.id)
    return DeletionSummary(
        teams=[(team_id, path) for team_id, path, _role in _team_places(session, user)],
        regions=_rows(session, _regions(user)),
        roles=_rows(session, _roles(user)),
        sets=_rows(session, _sets(user)),
        led=_rows(session, _led(user)),
        recipient_trackers=list(dict.fromkeys((tracker_id, name) for _id, tracker_id, name, _email in recipients)),
        activity_entries=session.scalar(select(func.count()).select_from(AuditLog).where(mentions)),
        report_inputs=session.scalar(
            select(func.count()).select_from(ReportInput).where(ReportInput.prepared_by == user.id)
        ),
    )


def _drop_from_queued_sends(session: Session, actor: User, user: User) -> None:
    """Take the person's email (any case) off every report send still queued for a retry, and record each change.

    A send that keeps other recipients records a ``recipient_removed`` entry for each address taken off; a send left
    with nobody fails, and records the ``report_send_failed`` entry that any failed send records.

    The queued sends are read ``FOR UPDATE``, in id order, so a retry that has claimed one finishes first, and none
    starts until the caller commits.
    """
    queued = (
        select(ReportSend)
        .options(defer(ReportSend.pdf))
        .where(ReportSend.status == "queued")
        .order_by(ReportSend.id)
        .with_for_update()
    )
    email = user.email.lower()
    for send in session.scalars(queued).all():
        removed = [address for address in send.recipients if address.lower() == email]
        if not removed:
            continue
        send.recipients = [address for address in send.recipients if address.lower() != email]
        if not send.recipients:
            send.status, send.error, send.next_attempt_at = "failed", NO_RECIPIENTS_LEFT, None
            sending._audit(session, send, session.get(Tracker, send.tracker_id), actor.id, target_user_id=user.id)
            continue
        for address in removed:
            record(
                session,
                user_id=actor.id,
                tracker_id=send.tracker_id,
                action="recipient_removed",
                entity="report_send",
                entity_id=send.id,
                detail={"email": address, "week_ending": send.week_ending.isoformat()},
                target_user_id=user.id,
            )


def delete_person(session: Session, actor: User, user: User) -> None:
    """Remove access, leads, report emails and sign-in, and record each removal; the caller has locked and
    checked the person, and commits."""
    teams = _team_places(session, user)
    regions = _rows(session, _regions(user))
    roles = _rows(session, _roles(user))
    sets = _rows(session, _sets(user))
    led = _rows(session, _led(user))
    recipients = _rows(session, _recipients(user))
    log = partial(record, session, user_id=actor.id, target_user_id=user.id)
    for team_id, path, role in teams:
        log(
            tracker_id=None,
            action="team_member_removed",
            entity="team",
            entity_id=team_id,
            detail={"team": path, "role": role},
        )
    for region_id, code, role in regions:
        log(
            tracker_id=None,
            action="region_access_removed",
            entity="region",
            entity_id=region_id,
            detail={"region": code, "role": role},
        )
    for tracker_id, _name, role in roles:
        log(tracker_id=tracker_id, action="role_removed", entity="user", entity_id=user.id, detail=change(role, None))
    for set_id, name in sets:
        log(
            tracker_id=None,
            action="permission_set_holder_removed",
            entity="permission_set",
            entity_id=set_id,
            detail={"set": name},
        )
    for tracker_id, _name in led:
        log(
            tracker_id=tracker_id,
            action="settings_updated",
            entity="tracker",
            entity_id=tracker_id,
            detail={"lead": [user.full_name, None]},
        )
    for _id, tracker_id, _name, email in recipients:
        log(
            tracker_id=tracker_id,
            action="recipient_removed",
            entity="email_settings",
            entity_id=email,
            detail={"email": email},
        )
    for model in (TeamMember, RegionGrant, TrackerRole, PermissionSetHolder):
        session.execute(delete(model).where(model.user_id == user.id))
    session.execute(update(Tracker).where(Tracker.lead_user_id == user.id).values(lead_user_id=None))
    session.execute(delete(Recipient).where(Recipient.id.in_([recipient_id for recipient_id, *_ in recipients])))
    _drop_from_queued_sends(session, actor, user)
    log(
        tracker_id=None,
        action="user_deleted",
        entity="user",
        entity_id=user.id,
        detail={  # the Activity page prints each key as it is, so the keys use the Delete dialog's words
            "name": user.full_name,
            "email": user.email,
            "administrator": user.is_admin,  # read before the flag is cleared below
            "teams": len(teams),
            "region access": len(regions),
            "tracker roles": len(roles),
            "permission sets": len(sets),
            "trackers led": len(led),
            "report emails": len({tracker_id for _id, tracker_id, _name, _email in recipients}),
        },
    )
    user.is_admin = False
    user.password_hash = None
    user.sso_subject = None
    user.status = "deleted"
