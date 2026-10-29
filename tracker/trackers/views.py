"""Views for trackers, settings, groups and role assignment (spec sections 5.1 to 5.3)."""

from __future__ import annotations

from datetime import date, time

from flask import abort, flash, g, redirect, render_template, request, url_for
from sqlalchemy import func, select, union_all

from ..audit import record
from ..auth import (
    ROLE_ORDER,
    admin_required,
    current_user,
    login_required,
    require_tracker_role,
    user_role,
    visible_trackers,
)
from ..db import get_session
from ..engine.calc import COMPLETE, GroupInput, Headline, WeekRow
from ..engine.weeks import week_endings
from ..models import CompletionEntry, Group, ReportInput, Risk, Tracker, TrackerRole, User, Week
from . import bp
from .forms import (
    RAG_VALUES,
    validate_group_form,
    validate_schedule_form,
    validate_snapshot_form,
    validate_tracker_form,
)

WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
ARCHIVED_MESSAGE = "This tracker is archived."
ROLES = ("viewer", "editor", "owner")


# --- Data loading --------------------------------------------------------------------------------------------


def load_engine_inputs(
    session, tracker: Tracker, as_of: date
) -> tuple[list[date], dict, dict, list[GroupInput], dict[int, int]]:
    """Load weeks, targets, actuals, groups and per-group entry totals for the engine.

    Actuals and entry totals count only entries dated on or before ``as_of`` (ruling R14); actuals also include each
    week's imported actual. Actuals are keyed by week-ending date.
    """
    weeks = week_endings(tracker.first_week_ending, tracker.last_week_ending)
    week_rows = session.scalars(select(Week).where(Week.tracker_id == tracker.id)).all()
    targets = {w.week_ending: w.target for w in week_rows}

    actuals: dict[date, int] = {}
    for week_ending, total in session.execute(
        select(CompletionEntry.week_ending, func.sum(CompletionEntry.quantity))
        .where(CompletionEntry.tracker_id == tracker.id, CompletionEntry.entry_date <= as_of)
        .group_by(CompletionEntry.week_ending)
    ):
        actuals[week_ending] = int(total)
    for w in week_rows:
        if w.imported_actual is not None:
            actuals[w.week_ending] = actuals.get(w.week_ending, 0) + w.imported_actual

    groups = [
        GroupInput(
            group_id=g_.id,
            name=g_.name,
            baseline=g_.baseline,
            starting_completed=g_.starting_completed,
            ready_not_complete=g_.ready_not_complete,
            planned_completion=g_.planned_completion,
            rag=g_.rag,
            comment=g_.comment,
            retired=g_.retired,
        )
        for g_ in session.scalars(
            select(Group).where(Group.tracker_id == tracker.id).order_by(Group.sort_order, Group.id)
        )
    ]
    entry_totals = {
        group_id: int(total)
        for group_id, total in session.execute(
            select(CompletionEntry.group_id, func.sum(CompletionEntry.quantity))
            .where(CompletionEntry.tracker_id == tracker.id, CompletionEntry.entry_date <= as_of)
            .group_by(CompletionEntry.group_id)
        )
    }
    return weeks, targets, actuals, groups, entry_totals


def tracker_summary(session, tracker: Tracker, today: date) -> Headline:
    """Headline figures for the default report week (shares its calculation with the report)."""
    from ..report.build import compute_position  # local import: the report package imports this module

    return compute_position(session, tracker, None, today).headline


def _last_entry_dates(session, tracker_ids: list[int]) -> dict[int, date]:
    if not tracker_ids:
        return {}
    return dict(
        session.execute(
            select(CompletionEntry.tracker_id, func.max(CompletionEntry.entry_date))
            .where(CompletionEntry.tracker_id.in_(tracker_ids))
            .group_by(CompletionEntry.tracker_id)
        ).all()
    )


def _latest_statuses(session, tracker_ids: list[int]) -> dict[int, str | None]:
    """The weekly Red/Amber/Green status of each tracker's latest report input (ruling R18)."""
    if not tracker_ids:
        return {}
    latest: dict[int, str | None] = {}
    for tracker_id, status in session.execute(
        select(ReportInput.tracker_id, ReportInput.status)
        .where(ReportInput.tracker_id.in_(tracker_ids))
        .order_by(ReportInput.tracker_id, ReportInput.week_ending)
    ):
        latest[tracker_id] = status
    return latest


def _deployed_by_group(session, tracker: Tracker) -> dict[int, int]:
    return {
        group_id: int(total)
        for group_id, total in session.execute(
            select(CompletionEntry.group_id, func.sum(CompletionEntry.quantity))
            .where(CompletionEntry.tracker_id == tracker.id)
            .group_by(CompletionEntry.group_id)
        )
    }


def _dated_rows(tracker: Tracker):
    """Selects of ``week_ending`` for every kind of data that is tied to the tracker's week-ending day."""
    return [
        select(model.week_ending).where(model.tracker_id == tracker.id)
        for model in (CompletionEntry, Week, ReportInput)
    ]


def _has_entries(session, tracker: Tracker) -> bool:
    """True when any completion entry, week (target or imported actual) or weekly input exists for the tracker."""
    return any(session.scalar(query.limit(1)) is not None for query in _dated_rows(tracker))


def _data_range(session, tracker: Tracker) -> tuple[date | None, date | None]:
    """The earliest and latest week-ending that holds any entry, target, imported actual or weekly input."""
    dates = union_all(*_dated_rows(tracker)).subquery()
    return session.execute(select(func.min(dates.c.week_ending), func.max(dates.c.week_ending))).one()


# --- Home ----------------------------------------------------------------------------------------------------


SPARK_WEEKS = 8
SPARK_WIDTH, SPARK_HEIGHT, SPARK_HEADROOM = 320, 84, 6
STATUS_ATTENTION = {"Red": 0, "Amber": 2, "Green": 3}


def spark_chart(rows: list[WeekRow]) -> dict | None:
    """Bars and target segments for the home card's chart of the last completed weeks (SVG user units)."""
    done = [r for r in rows if r.state == COMPLETE][-SPARK_WEEKS:]
    if not done:
        return None
    peak = max([r.actual or 0 for r in done] + [r.target or 0 for r in done]) or 1
    scale = (SPARK_HEIGHT - SPARK_HEADROOM) / (peak * 1.05)
    step = SPARK_WIDTH / len(done)
    bars, target = [], []
    for i, row in enumerate(done):
        actual = row.actual or 0
        height = actual * scale
        bars.append(
            {
                "x": round(i * step + 4, 1),
                "y": round(SPARK_HEIGHT - height, 1),
                "width": round(step - 8, 1),
                "height": round(height, 1),
                "low": row.target is not None and actual < row.target,
            }
        )
        if row.target is not None:
            y = round(SPARK_HEIGHT - row.target * scale, 1)
            target.append(f"M{round(i * step + 1, 1)},{y} H{round((i + 1) * step - 1, 1)}")
    last = done[-1]
    return {"bars": bars, "target": " ".join(target), "weeks": len(done), "actual": last.actual, "goal": last.target}


def _risk_counts(session, tracker_ids: list[int]) -> dict[int, tuple[int, int]]:
    """Open and open-Red risk counts per tracker."""
    counts: dict[int, tuple[int, int]] = {}
    for tracker_id, rag in session.execute(
        select(Risk.tracker_id, Risk.rag).where(Risk.tracker_id.in_(tracker_ids), Risk.status != "Closed")
    ):
        open_, red = counts.get(tracker_id, (0, 0))
        counts[tracker_id] = (open_ + 1, red + (rag == "Red"))
    return counts


def _written_weeks(session, tracker_ids: list[int]) -> set[tuple[int, date]]:
    """(tracker id, week-ending) for every week whose commentary has a status or a headline."""
    return set(
        session.execute(
            select(ReportInput.tracker_id, ReportInput.week_ending).where(
                ReportInput.tracker_id.in_(tracker_ids),
                (ReportInput.status.is_not(None)) | (ReportInput.headline != ""),
            )
        ).all()
    )


@login_required
def home():
    from ..report.build import compute_position  # local import: the report package imports this module

    db = get_session()
    user = current_user()
    show_archived = request.args.get("archived") == "1"
    trackers = [t for t in visible_trackers(db, user) if show_archived or t.status == "active"]
    ids = [t.id for t in trackers]
    last_entries = _last_entry_dates(db, ids)
    statuses = _latest_statuses(db, ids)
    risks = _risk_counts(db, ids)
    written = _written_weeks(db, ids)
    today = date.today()
    cards = []
    for t in trackers:
        position = compute_position(db, t, None, today)
        headline = position.headline
        live = t.status == "active" and t.first_week_ending <= today
        last_entry = last_entries.get(t.id)
        dvt = headline.forecast_vs_target_days
        status = statuses.get(t.id)
        card = {
            "tracker": t,
            "headline": headline,
            "last_entry": last_entry,
            "status": status,
            "role": user_role(db, user, t.id),
            "open_risks": risks.get(t.id, (0, 0))[0],
            "red_risks": risks.get(t.id, (0, 0))[1],
            "starts": t.first_week_ending if t.first_week_ending > today else None,
            "inputs_missing": live and (t.id, headline.report_week) not in written,
            "entry_stale": live and (last_entry is None or (today - last_entry).days > 7),
            "behind": dvt is not None and dvt > 0,
            "spark": spark_chart(position.rows),
        }
        card["attention"] = (
            (10 if t.status != "active" else 0)
            + STATUS_ATTENTION.get(status, 4)
            - (1 if card["behind"] else 0)
            - (0.5 if card["inputs_missing"] else 0)
        )
        cards.append(card)
    cards.sort(key=lambda c: (c["attention"], c["tracker"].name.lower()))
    return render_template(
        "home.html",
        cards=cards,
        show_archived=show_archived,
        today=today,
        page_title="Trackers",
        current_page="trackers",
    )


# --- Create, view, archive -----------------------------------------------------------------------------------


def _defaults_form() -> dict:
    today = date.today()
    return {
        "name": "",
        "unit_label": "",
        "group_label": "",
        "description": "",
        "week_ending_weekday": "4",
        "start_date": today.isoformat(),
        "last_week_ending": "",
        "target_completion": "",
        "completed_before_first": "0",
        "moving_average_weeks": "3",
    }


def _form_from_tracker(t: Tracker) -> dict:
    return {
        "name": t.name,
        "unit_label": t.unit_label,
        "group_label": t.group_label,
        "description": t.description,
        "week_ending_weekday": str(t.week_ending_weekday),
        "start_date": t.first_week_ending.isoformat(),
        "last_week_ending": t.last_week_ending.isoformat(),
        "target_completion": t.target_completion.isoformat() if t.target_completion else "",
        "completed_before_first": str(t.completed_before_first),
        "moving_average_weeks": str(t.moving_average_weeks),
        "schedule_enabled": "1" if t.schedule_enabled else "",
        "send_time": t.send_time.strftime("%H:%M"),
        "send_timezone": t.send_timezone,
    }


@bp.route("/trackers/new", methods=["GET", "POST"])
@admin_required
def new():
    db = get_session()
    if request.method == "POST":
        values, errors = validate_tracker_form(request.form)
        if not errors:
            tracker = Tracker(**values)
            db.add(tracker)
            db.flush()
            db.add(TrackerRole(user_id=current_user().id, tracker_id=tracker.id, role="owner"))
            record(
                db,
                user_id=current_user().id,
                tracker_id=tracker.id,
                action="tracker_created",
                entity="tracker",
                entity_id=tracker.id,
                detail={"name": tracker.name},
            )
            db.commit()
            flash("Tracker created.", "success")
            return redirect(url_for("trackers.settings", tracker_id=tracker.id))
        return _render_settings(None, request.form, errors, status=400)
    return _render_settings(None, _defaults_form(), [])


def _render_settings(tracker: Tracker | None, form, errors: list[str], status: int = 200):
    template = "trackers/settings.html" if tracker is not None else "trackers/new.html"
    locked = tracker is not None and _has_entries(get_session(), tracker)
    return (
        render_template(
            template,
            tracker=tracker,
            form=form,
            errors=errors,
            weekdays=list(enumerate(WEEKDAYS)),
            weekday_locked=locked,
            page_title="New tracker" if tracker is None else f"{tracker.name} settings",
            current_page="trackers",
        ),
        status,
    )


@bp.get("/trackers/<int:tracker_id>")
@require_tracker_role("viewer")
def view(tracker_id: int):
    return redirect(url_for("report.view", tracker_id=tracker_id))


@bp.post("/trackers/<int:tracker_id>/archive")
@admin_required
@require_tracker_role("owner")
def archive(tracker_id: int):
    tracker, db = g.tracker, get_session()
    if tracker.status != "archived":
        tracker.status = "archived"
        record(
            db,
            user_id=current_user().id,
            tracker_id=tracker.id,
            action="tracker_archived",
            entity="tracker",
            entity_id=tracker.id,
        )
        db.commit()
    flash("Tracker archived.", "success")
    return redirect(url_for("index"))


# --- Settings ------------------------------------------------------------------------------------------------


def _refuse_if_archived(tracker: Tracker, endpoint: str):
    if tracker.status == "archived":
        flash(ARCHIVED_MESSAGE, "danger")
        return redirect(url_for(endpoint, tracker_id=tracker.id))
    return None


def _jsonable(value):
    return value.isoformat() if isinstance(value, (date, time)) else value


@bp.route("/trackers/<int:tracker_id>/settings", methods=["GET", "POST"])
@require_tracker_role("owner")
def settings(tracker_id: int):
    tracker, db = g.tracker, get_session()
    if request.method == "GET":
        return _render_settings(tracker, _form_from_tracker(tracker), [])
    refused = _refuse_if_archived(tracker, "trackers.settings")
    if refused:
        return refused
    locked = tracker.week_ending_weekday if _has_entries(db, tracker) else None
    values, errors = validate_tracker_form(request.form, locked_weekday=locked)
    schedule, schedule_errors = validate_schedule_form(
        request.form, current_time=tracker.send_time, current_timezone=tracker.send_timezone
    )
    errors += schedule_errors
    values.update(schedule)
    if not errors:
        low, high = _data_range(db, tracker)
        if low is not None and (low < values["first_week_ending"] or high > values["last_week_ending"]):
            errors.append("Data exists outside the new week range. Widen the range to include it.")
    if errors:
        return _render_settings(tracker, request.form, errors, status=400)
    changed = {}
    for field, new_value in values.items():
        old_value = getattr(tracker, field)
        if old_value != new_value:
            changed[field] = [_jsonable(old_value), _jsonable(new_value)]
            setattr(tracker, field, new_value)
    if changed:
        record(
            db,
            user_id=current_user().id,
            tracker_id=tracker.id,
            action="settings_updated",
            entity="tracker",
            entity_id=tracker.id,
            detail=changed,
        )
    db.commit()
    flash("Settings saved.", "success")
    return redirect(url_for("trackers.settings", tracker_id=tracker.id))


# --- Groups --------------------------------------------------------------------------------------------------


def _ordered_groups(db, tracker: Tracker) -> list[Group]:
    return list(db.scalars(select(Group).where(Group.tracker_id == tracker.id).order_by(Group.sort_order, Group.id)))


def _group_or_404(db, tracker: Tracker) -> Group:
    group_id = request.form.get("group_id", type=int)
    group = db.get(Group, group_id) if group_id is not None else None
    if group is None or group.tracker_id != tracker.id:
        abort(404)
    return group


def _name_taken(db, tracker: Tracker, name: str, exclude_id: int | None = None) -> bool:
    query = select(Group.id).where(Group.tracker_id == tracker.id, Group.name == name)
    if exclude_id is not None:
        query = query.where(Group.id != exclude_id)
    return db.scalar(query) is not None


def _require_owner() -> None:
    if ROLE_ORDER[g.role] < ROLE_ORDER["owner"]:
        abort(403, description="Only an owner can do this.")


def _audit_group(db, tracker: Tracker, action: str, group: Group, detail: dict | None = None) -> None:
    record(
        db,
        user_id=current_user().id,
        tracker_id=tracker.id,
        action=action,
        entity="group",
        entity_id=group.id,
        detail=detail,
    )


@bp.route("/trackers/<int:tracker_id>/groups", methods=["GET", "POST"])
@require_tracker_role("editor")
def groups(tracker_id: int):
    tracker, db = g.tracker, get_session()
    if request.method == "POST":
        refused = _refuse_if_archived(tracker, "trackers.groups")
        if refused:
            return refused
        error = _handle_group_action(db, tracker)
        if error:
            flash(error, "danger")
        return redirect(url_for("trackers.groups", tracker_id=tracker.id))
    deployed = _deployed_by_group(db, tracker)
    return render_template(
        "trackers/groups.html",
        tracker=tracker,
        groups=_ordered_groups(db, tracker),
        deployed=deployed,
        is_owner=g.role == "owner",
        page_title=f"{tracker.name}: {tracker.group_label or 'Groups'}",
        current_page="trackers",
    )


@bp.route("/trackers/<int:tracker_id>/groups/new", methods=["GET", "POST"])
@require_tracker_role("owner")
def new_group(tracker_id: int):
    tracker, db = g.tracker, get_session()
    if request.method == "GET":
        return _render_group_form(tracker, None, 0, {"starting_completed": "0"}, [], 200)
    refused = _refuse_if_archived(tracker, "trackers.groups")
    if refused:
        return refused
    errors = _create_group(db, tracker, request.form)
    if errors:
        return _render_group_form(tracker, None, 0, request.form, errors, 400)
    return redirect(url_for("trackers.groups", tracker_id=tracker.id))


@bp.route("/trackers/<int:tracker_id>/groups/<int:group_id>", methods=["GET", "POST"])
@require_tracker_role("editor")
def edit_group(tracker_id: int, group_id: int):
    tracker, db = g.tracker, get_session()
    group = db.get(Group, group_id)
    if group is None or group.tracker_id != tracker.id:
        abort(404)
    done = group.starting_completed + _deployed_by_group(db, tracker).get(group.id, 0)
    if request.method == "GET":
        form = {
            "name": group.name,
            "baseline": str(group.baseline),
            "starting_completed": str(group.starting_completed),
            "ready_not_complete": str(group.ready_not_complete),
            "planned_completion": group.planned_completion.isoformat() if group.planned_completion else "",
            "rag": group.rag or "",
            "comment": group.comment,
        }
        return _render_group_form(tracker, group, done, form, [], 200)
    refused = _refuse_if_archived(tracker, "trackers.groups")
    if refused:
        return refused
    errors = _update_group(db, tracker, group, request.form)
    if errors:
        return _render_group_form(tracker, group, done, request.form, errors, 400)
    return redirect(url_for("trackers.groups", tracker_id=tracker.id))


def _render_group_form(tracker: Tracker, group: Group | None, done: int, form, errors: list[str], status: int):
    label = tracker.group_label or "Group"
    return (
        render_template(
            "trackers/group_form.html",
            tracker=tracker,
            group=group,
            done=done,
            form=form,
            errors=errors,
            is_owner=g.role == "owner",
            rag_values=RAG_VALUES,
            page_title=f"{tracker.name}: {group.name if group else 'New ' + label.lower()}",
            current_page="trackers",
        ),
        status,
    )


def _handle_group_action(db, tracker: Tracker) -> str | None:
    """Apply one group action; return an error message, or ``None`` after committing a change."""
    action = request.form.get("action", "")
    if action == "update":
        errors = _update_group(db, tracker, _group_or_404(db, tracker), request.form)
        return errors[0] if errors else None
    _require_owner()
    if action == "create":
        errors = _create_group(db, tracker, request.form)
        return errors[0] if errors else None
    group = _group_or_404(db, tracker)
    if action == "delete":
        return _delete_group(db, tracker, group)
    if action == "retire":
        deployed = group.starting_completed + _deployed_by_group(db, tracker).get(group.id, 0)
        if group.baseline - deployed > 0:
            return "Correct the baseline to the deployed figure before retiring this group."
        group.retired = True
        _audit_group(db, tracker, "group_retired", group)
    elif action == "unretire":
        group.retired = False
        _audit_group(db, tracker, "group_unretired", group)
    elif action in ("up", "down"):
        # Active and retired groups are listed apart, so a group swaps places with its neighbour in its own list.
        ordered = _ordered_groups(db, tracker)
        peers = [i for i, item in enumerate(ordered) if item.retired == group.retired]
        here = peers.index(ordered.index(group))
        there = here - 1 if action == "up" else here + 1
        if 0 <= there < len(peers):
            a, b = peers[here], peers[there]
            ordered[a], ordered[b] = ordered[b], ordered[a]
        for position, item in enumerate(ordered):
            item.sort_order = position
        _audit_group(db, tracker, "group_reordered", group, {"direction": action})
    else:
        abort(400, description="Unknown action.")
    db.commit()
    return None


def _create_group(db, tracker: Tracker, form) -> list[str]:
    values, errors = validate_group_form(form)
    if not errors and _name_taken(db, tracker, values["name"]):
        errors.append("A group with that name already exists.")
    if errors:
        return errors
    order = db.scalar(select(func.max(Group.sort_order)).where(Group.tracker_id == tracker.id))
    group = Group(tracker_id=tracker.id, sort_order=(order or 0) + 1, **values)
    db.add(group)
    db.flush()
    _audit_group(db, tracker, "group_created", group, {"name": group.name, "baseline": group.baseline})
    db.commit()
    flash("Group added.", "success")
    return []


def _delete_group(db, tracker: Tracker, group: Group) -> str | None:
    """Delete a group that has no completions; risks that named it keep their place with no group."""
    used = db.scalar(select(func.count()).select_from(CompletionEntry).where(CompletionEntry.group_id == group.id))
    if used:
        return "This group has completions recorded, so it cannot be deleted. Retire it instead."
    _audit_group(db, tracker, "group_deleted", group, {"name": group.name, "baseline": group.baseline})
    db.delete(group)
    db.commit()
    flash("Group deleted.", "success")
    return None


def _update_group(db, tracker: Tracker, group: Group, form) -> list[str]:
    changes: dict[str, list] = {}
    snapshot, errors = validate_snapshot_form(form)
    if errors:
        return errors
    owner_values: dict = {}
    if g.role == "owner":
        owner_values, errors = validate_group_form(
            {**form, "starting_completed": form.get("starting_completed", str(group.starting_completed))}
        )
        if errors:
            return errors
        if _name_taken(db, tracker, owner_values["name"], exclude_id=group.id):
            return ["A group with that name already exists."]
    baseline_change = None
    for field, new_value in {**snapshot, **owner_values}.items():
        old_value = getattr(group, field)
        if old_value == new_value:
            continue
        if field == "baseline":
            baseline_change = [old_value, new_value]
        else:
            changes[field] = [_jsonable(old_value), _jsonable(new_value)]
        setattr(group, field, new_value)
    if baseline_change:
        _audit_group(db, tracker, "baseline_changed", group, {"baseline": baseline_change})
    if changes:
        _audit_group(db, tracker, "group_updated", group, changes)
    db.commit()
    flash("Group saved.", "success")
    return []


# --- Roles ---------------------------------------------------------------------------------------------------


@bp.route("/trackers/<int:tracker_id>/roles", methods=["GET", "POST"])
@admin_required
@require_tracker_role("owner")
def roles(tracker_id: int):
    tracker, db = g.tracker, get_session()
    if request.method == "POST":
        refused = _refuse_if_archived(tracker, "trackers.roles")
        if refused:
            return refused
        user = db.get(User, request.form.get("user_id", type=int) or 0)
        choice = request.form.get("role", "")
        if user is None or user.is_admin or choice not in (*ROLES, "remove"):
            abort(400, description="Choose a user and a role.")
        existing = db.get(TrackerRole, (user.id, tracker.id))
        previous = existing.role if existing else None
        if choice == "remove":
            if existing:
                db.delete(existing)
        elif existing:
            existing.role = choice
        else:
            db.add(TrackerRole(user_id=user.id, tracker_id=tracker.id, role=choice))
        record(
            db,
            user_id=current_user().id,
            tracker_id=tracker.id,
            action="role_removed" if choice == "remove" else "role_set",
            entity="user",
            entity_id=user.id,
            detail={"role": [previous, None if choice == "remove" else choice]},
        )
        db.commit()
        flash(f"Updated access for {user.full_name}.", "success")
        return redirect(url_for("trackers.roles", tracker_id=tracker.id))
    current = {r.user_id: r.role for r in db.scalars(select(TrackerRole).where(TrackerRole.tracker_id == tracker.id))}
    users = db.scalars(select(User).where(User.status == "active").order_by(User.full_name, User.id)).all()
    return render_template(
        "trackers/roles.html",
        tracker=tracker,
        users=users,
        current=current,
        roles=ROLES,
        page_title=f"{tracker.name} access",
        current_page="trackers",
    )
