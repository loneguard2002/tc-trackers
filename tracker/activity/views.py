"""The Activity screen (spec section 7): newest first, paged, sorted and searched on the server, filtered by person,
action and date range.

Names, not contents (spec section 2): a viewer who is not an administrator sees every entry, but the detail of an entry
about a tracker they cannot open is hidden; its time, people, action and tracker name stay.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import NamedTuple

from flask import render_template, request, url_for
from sqlalchemy import Text, case, func, or_, select
from sqlalchemy.orm import aliased

from ..auth import current_user, has_permission, tracker_roles
from ..auth.permissions import permission_required, user_permissions
from ..auth.session import admin_required
from ..db import get_session
from ..ids import parse_id
from ..models import AuditLog, Tracker, User
from ..servertable import DEFAULT_SIZE, clamp_page, like_pattern, read_state, sort_changes, state_args
from . import bp
from .kinds import KIND_ACTIONS, KIND_LABELS
from .labels import ACTION_LABELS, action_label, describe, feedback_text
from .retention import retention_days, save_retention
from .scope import visible_actions, visible_entries

SORT_KEYS = ("time", "actor", "action", "tracker")
DEFAULT_SORT, DEFAULT_DESCENDING = "time", True
HIDDEN_DETAIL_MESSAGE = "Details hidden: you cannot open this tracker."


class ActivityFilters(NamedTuple):
    person: int | None
    action: str | None
    start: date | None
    end: date | None
    kind: str | None = None  # a kind of change (activity/kinds.py), set by the Overview's links


def _date(value: str | None) -> date | None:
    try:
        return date.fromisoformat((value or "").strip())
    except ValueError:
        return None


def parse_filters(args) -> ActivityFilters:
    """The filters in a query string; any value that cannot be read is ignored."""
    person = parse_id(args.get("person"))
    action = args.get("action", "").strip()
    kind = args.get("kind", "").strip()
    return ActivityFilters(
        person=person,
        action=action if action in ACTION_LABELS else None,
        start=_date(args.get("from")),
        end=_date(args.get("to")),
        kind=kind if kind in KIND_LABELS else None,
    )


def _midnight(day: date) -> datetime:
    return datetime.combine(day, time.min, tzinfo=timezone.utc)


def _filter_args(filters: ActivityFilters) -> dict[str, str | int]:
    """The filters as address keys, kept by every sort, page and size link."""
    args: dict[str, str | int] = {}
    if filters.person:
        args["person"] = filters.person
    if filters.action:
        args["action"] = filters.action
    if filters.start:
        args["from"] = filters.start.isoformat()
    if filters.end:
        args["to"] = filters.end.isoformat()
    if filters.kind:
        args["kind"] = filters.kind
    return args


def _action_order():
    """The action's label, as an SQL expression, so that sorting by Action sorts what the page shows."""
    return case(ACTION_LABELS, value=AuditLog.action, else_=AuditLog.action)


@bp.get("")
@permission_required("view_activity")
def index():
    db = get_session()
    filters = parse_filters(request.args)
    state = read_state(request.args, SORT_KEYS, DEFAULT_SORT, DEFAULT_DESCENDING)
    actor, affected = aliased(User), aliased(User)
    viewer = current_user()
    can_open = None if viewer.is_admin else tracker_roles(db, viewer)  # None: every detail is shown
    # Only the entries the viewer may see (activity/scope.py); administrators see every entry.
    held = user_permissions(db, viewer)
    scope = visible_entries(viewer, held, can_open)
    # The Action filter offers what the viewer can see: their areas' actions and the kinds of their own actions.
    shown_actions = (
        None
        if scope is None
        else visible_actions(held, bool(can_open))
        | set(db.scalars(select(AuditLog.action).where(AuditLog.user_id == viewer.id).distinct()))
    )
    base = [scope] if scope is not None else []
    conditions = list(base)
    if filters.person:
        conditions.append(or_(AuditLog.user_id == filters.person, AuditLog.target_user_id == filters.person))
    if filters.action:
        conditions.append(AuditLog.action == filters.action)
    if filters.kind:
        conditions.append(AuditLog.action.in_(sorted(KIND_ACTIONS[filters.kind])))
    if filters.start:
        conditions.append(AuditLog.at >= _midnight(filters.start))
    if filters.end and filters.end < date.max:
        conditions.append(AuditLog.at < _midnight(filters.end) + timedelta(days=1))
    if state.q:
        pattern = like_pattern(state.q)
        # The detail is searched only where the viewer may read it (spec, Call 1): an entry about a tracker they cannot
        # open matches on its tracker name, never on its contents.
        # The detail is searched as its stored JSON text (keys and values alike).
        detail = AuditLog.detail.cast(Text).ilike(pattern, escape="\\")
        if can_open is not None:
            detail = detail & or_(AuditLog.tracker_id.is_(None), AuditLog.tracker_id.in_(list(can_open)))
        conditions.append(
            or_(
                *(
                    column.ilike(pattern, escape="\\")
                    for column in (actor.full_name, actor.email, affected.full_name, affected.email, Tracker.name)
                ),
                detail,
            )
        )

    def joined(query):
        return (
            query.select_from(AuditLog)
            .outerjoin(actor, actor.id == AuditLog.user_id)
            .outerjoin(affected, affected.id == AuditLog.target_user_id)
            .outerjoin(Tracker, Tracker.id == AuditLog.tracker_id)
            .where(*conditions)
        )

    total = db.scalar(joined(select(func.count(AuditLog.id)))) or 0
    # Without a search or filter every entry the viewer may see matches, so the second count is not needed.
    overall = (db.scalar(select(func.count(AuditLog.id)).where(*base)) or 0) if conditions != base else total
    state = clamp_page(state, total)
    order = {
        "time": AuditLog.at,
        "actor": func.lower(actor.full_name),
        "action": func.lower(_action_order()),
        "tracker": func.lower(Tracker.name),
    }[state.sort]
    # Rows equal on the sorted column keep the default order (newest first), whichever way the column runs.
    tie_break = (AuditLog.at.desc(), AuditLog.id.desc())
    rows = db.execute(
        joined(
            select(
                AuditLog,
                actor.full_name,
                actor.email,
                actor.status,
                affected.full_name,
                affected.email,
                affected.status,
                Tracker.name,
            )
        )
        .order_by((order.desc() if state.descending else order.asc()).nulls_last(), *tie_break)
        .limit(state.size)
        .offset((state.page - 1) * state.size)
    ).all()

    def hidden(entry: AuditLog) -> bool:
        return can_open is not None and entry.tracker_id is not None and entry.tracker_id not in can_open

    # A feedback entry reads "FB-0042: question sent"; its reference opens the request only for people who may read it.
    reads_feedback = has_permission(viewer, "manage_feedback")

    def feedback(entry: AuditLog) -> dict | None:
        if entry.entity != "feedback":
            return None
        detail = entry.detail if isinstance(entry.detail, dict) else {}
        request_id = parse_id(entry.entity_id)
        return {
            "reference": str(detail.get("reference", "")),
            "url": url_for("feedback.admin_request", request_id=request_id) if reads_feedback and request_id else None,
            "text": feedback_text(entry.action, detail),
        }

    entries = [
        {
            "id": entry.id,
            "at": entry.at,
            "actor": actor_name,
            "actor_email": actor_email,
            "actor_deleted": actor_status == "deleted",
            "affected": affected_name,
            "affected_email": affected_email,
            "affected_deleted": affected_status == "deleted",
            "label": action_label(entry.action),
            "tracker": tracker_name,
            "hidden": hidden(entry),
            "lines": [] if hidden(entry) else describe(entry.action, entry.detail),
            "feedback": feedback(entry),
        }
        for (
            entry,
            actor_name,
            actor_email,
            actor_status,
            affected_name,
            affected_email,
            affected_status,
            tracker_name,
        ) in rows
    ]
    filter_args = _filter_args(filters)
    first = (state.page - 1) * state.size + 1

    def link(**changes) -> str:
        return url_for(
            "activity.index", **filter_args, **state_args(state, DEFAULT_SORT, DEFAULT_DESCENDING, **changes)
        )

    sort_urls = {key: link(**sort_changes(state, key)) for key in SORT_KEYS}
    # The Rows per page form keeps the search, sort and filters; page and size are its own.
    size_form = {**filter_args, **state_args(state, DEFAULT_SORT, DEFAULT_DESCENDING, page=1, size=DEFAULT_SIZE)}
    # Clear filters empties the search and the filters and goes to page 1; the sort and the rows per page stay.
    keep = state_args(state, DEFAULT_SORT, DEFAULT_DESCENDING, q="", page=1)
    clear_url = url_for("activity.index", **keep)
    # People can share a name, and a deleted person's email may be reused by a new account, so a label carries both.
    # The Person filter names only the people in entries the viewer may see.
    people_query = select(User.id, User.full_name, User.email, User.status)
    if scope is not None:
        people_query = people_query.where(
            or_(
                User.id.in_(select(AuditLog.user_id).where(scope)),
                User.id.in_(select(AuditLog.target_user_id).where(scope)),
            )
        )
    people = [
        (id, f"{name} ({email})" + (" – deleted" if status == "deleted" else ""))
        for id, name, email, status in db.execute(people_query.order_by(User.full_name, User.email, User.id))
    ]
    return render_template(
        "activity/index.html",
        current_page="activity",
        entries=entries,
        filters=filters,
        people=people,
        actions=sorted(
            ((key, label) for key, label in ACTION_LABELS.items() if shown_actions is None or key in shown_actions),
            key=lambda item: item[1],
        ),
        state=state,
        total=total,
        overall=overall,
        clear_url=clear_url,
        keep_args=keep,
        first=first,
        last=first + len(entries) - 1,
        sort_urls=sort_urls,
        page_url=lambda page: link(page=page),
        size_form=size_form,
        retention=retention_days(db),
        filtered=bool(state.q or any((filters.person, filters.action, filters.start, filters.end, filters.kind))),
        kinds=list(KIND_LABELS.items()),
        hidden_detail=HIDDEN_DETAIL_MESSAGE,
    )


@bp.post("/retention")
@admin_required
def retention():
    return save_retention(get_session(), current_user().id, request.form.get("retention_days"))
