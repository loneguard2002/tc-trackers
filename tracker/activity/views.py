"""The Activity screen (spec section 7): newest first, 50 a page, filtered by person, action and date range."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import NamedTuple

from flask import render_template, request, url_for
from sqlalchemy import or_, select
from sqlalchemy.orm import aliased

from ..auth import current_user
from ..auth.permissions import permission_required
from ..auth.session import admin_required
from ..db import get_session
from ..models import AuditLog, Tracker, User
from . import bp
from .labels import ACTION_LABELS, action_label, describe
from .retention import retention_days, save_retention

PAGE_SIZE = 50
_MAX_ID = 2**31 - 1
_MAX_PAGE = 10**6


class ActivityFilters(NamedTuple):
    person: int | None
    action: str | None
    start: date | None
    end: date | None
    page: int


def _number(value: str | None, upper: int) -> int | None:
    text = (value or "").strip()
    if not (text.isascii() and text.isdigit()) or len(text) > 12 or int(text) > upper:
        return None
    return int(text)


def _date(value: str | None) -> date | None:
    try:
        return date.fromisoformat((value or "").strip())
    except ValueError:
        return None


def parse_filters(args) -> ActivityFilters:
    """The filters in a query string; any value that cannot be read is ignored."""
    person = _number(args.get("person"), _MAX_ID)
    action = args.get("action", "").strip()
    page = _number(args.get("page"), _MAX_PAGE) or 1
    return ActivityFilters(
        person=person if person else None,
        action=action if action in ACTION_LABELS else None,
        start=_date(args.get("from")),
        end=_date(args.get("to")),
        page=max(page, 1),
    )


def _midnight(day: date) -> datetime:
    return datetime.combine(day, time.min, tzinfo=timezone.utc)


def _query_args(filters: ActivityFilters, page: int) -> dict[str, str | int]:
    args: dict[str, str | int] = {}
    if filters.person:
        args["person"] = filters.person
    if filters.action:
        args["action"] = filters.action
    if filters.start:
        args["from"] = filters.start.isoformat()
    if filters.end:
        args["to"] = filters.end.isoformat()
    if page > 1:
        args["page"] = page
    return args


@bp.get("")
@permission_required("view_activity")
def index():
    db = get_session()
    filters = parse_filters(request.args)
    actor, affected = aliased(User), aliased(User)
    query = (
        select(AuditLog, actor.full_name, affected.full_name, Tracker.name)
        .outerjoin(actor, actor.id == AuditLog.user_id)
        .outerjoin(affected, affected.id == AuditLog.target_user_id)
        .outerjoin(Tracker, Tracker.id == AuditLog.tracker_id)
    )
    if filters.person:
        query = query.where(or_(AuditLog.user_id == filters.person, AuditLog.target_user_id == filters.person))
    if filters.action:
        query = query.where(AuditLog.action == filters.action)
    if filters.start:
        query = query.where(AuditLog.at >= _midnight(filters.start))
    if filters.end and filters.end < date.max:
        query = query.where(AuditLog.at < _midnight(filters.end) + timedelta(days=1))
    rows = db.execute(
        query.order_by(AuditLog.at.desc(), AuditLog.id.desc())
        .limit(PAGE_SIZE + 1)
        .offset((filters.page - 1) * PAGE_SIZE)
    ).all()
    entries = [
        {
            "id": entry.id,
            "at": entry.at,
            "actor": actor_name,
            "affected": affected_name,
            "label": action_label(entry.action),
            "tracker": tracker_name,
            "lines": describe(entry.action, entry.detail),
        }
        for entry, actor_name, affected_name, tracker_name in rows[:PAGE_SIZE]
    ]
    newer = url_for("activity.index", **_query_args(filters, filters.page - 1)) if filters.page > 1 else None
    older = url_for("activity.index", **_query_args(filters, filters.page + 1)) if len(rows) > PAGE_SIZE else None
    people = db.execute(select(User.id, User.full_name).order_by(User.full_name, User.id)).all()
    return render_template(
        "activity/index.html",
        current_page="activity",
        entries=entries,
        filters=filters,
        people=people,
        actions=sorted(ACTION_LABELS.items(), key=lambda item: item[1]),
        newer=newer,
        older=older,
        retention=retention_days(db),
        filtered=any((filters.person, filters.action, filters.start, filters.end)),
    )


@bp.post("/retention")
@admin_required
def retention():
    return save_retention(get_session(), current_user().id, request.form.get("retention_days"))
