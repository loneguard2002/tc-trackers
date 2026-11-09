"""Views for trackers, settings, groups and role assignment (spec sections 5.1 to 5.3)."""

from __future__ import annotations

from datetime import date, datetime, time, timezone

from flask import abort, flash, g, redirect, render_template, request, url_for
from sqlalchemy import func, select, union_all
from sqlalchemy.exc import IntegrityError

from ..audit import NO_CHANGES_MESSAGE, change, record
from ..auth import (
    ROLE_ORDER,
    ROLES,
    admin_required,
    current_user,
    has_permission,
    login_required,
    permission_required,
    require_tracker_role,
    tracker_roles,
    user_role,
    visible_trackers,
)
from ..auth.accounts import vouched_refusal
from ..auth.guards import SELF_PROMOTION_MESSAGE, raises_own_access, snapshot_access
from ..auth.roles import give_creator_ownership, lead_candidates, lead_in_charge, tracker_access_list
from ..db import get_session
from ..engine.calc import (
    COMPLETE,
    GroupInput,
    Headline,
    WeekRow,
    build_headline,
    build_week_rows,
    group_positions,
    status_mismatch,
)
from ..engine.weeks import week_endings
from ..ids import parse_id
from ..lists.catalogue import (
    business_line_choices,
    parse_business_line,
    parse_regions,
    region_choices,
    set_tracker_regions,
    team_places,
    tracker_labels,
    tracker_region_ids,
)
from ..models import (
    CompletionEntry,
    Group,
    Recipient,
    Region,
    ReportInput,
    Risk,
    Team,
    Tracker,
    TrackerRegion,
    TrackerRole,
    User,
    Week,
)
from ..teams.tree import TEAM_CHOICE_ERROR, load_team_rows, parse_team_id, team_choices, team_labels
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
INACTIVE_PERSON_MESSAGE = "This person's account is not active, so it cannot be given access."


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
    """Bars and target segments for the home card's chart of the last completed weeks (SVG user units).

    The chart always has SPARK_WEEKS slots, newest on the right, so a tracker with few weeks done keeps narrow bars;
    the slots before its first week are returned as `empty` for a faint stub on the baseline.
    """
    done = [r for r in rows if r.state == COMPLETE][-SPARK_WEEKS:]
    if not done:
        return None
    peak = max([r.actual or 0 for r in done] + [r.target or 0 for r in done]) or 1
    scale = (SPARK_HEIGHT - SPARK_HEADROOM) / (peak * 1.05)
    step = SPARK_WIDTH / SPARK_WEEKS
    offset = SPARK_WEEKS - len(done)
    empty = [{"x": round(i * step + 4, 1), "width": round(step - 8, 1)} for i in range(offset)]
    bars, target = [], []
    for i, row in enumerate(done, start=offset):
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
    return {
        "bars": bars,
        "empty": empty,
        "target": " ".join(target),
        "weeks": len(done),
        "actual": last.actual,
        "goal": last.target,
    }


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


def _tracker_regions(session, tracker_ids: list[int]) -> dict[int, list[tuple[int, str]]]:
    """Each tracker's regions as (id, code), in code order: the home filter data and the Region choices."""
    regions: dict[int, list[tuple[int, str]]] = {tracker_id: [] for tracker_id in tracker_ids}
    if tracker_ids:
        for tracker_id, region_id, code in session.execute(
            select(TrackerRegion.tracker_id, Region.id, Region.code)
            .join(Region, TrackerRegion.region_id == Region.id)
            .where(TrackerRegion.tracker_id.in_(tracker_ids))
            .order_by(func.lower(Region.code), Region.id)
        ):
            regions[tracker_id].append((region_id, code))
    return regions


def _filter_options(cards: list[dict], regions: dict[int, list[tuple[int, str]]]) -> dict:
    """The Business line and Region choices: those the shown cards use, by name or code, and whether any lacks one."""
    lines = {c["tracker"].business_line_id: c["labels"].business_line for c in cards if c["labels"].business_line}
    used = {region for c in cards for region in regions[c["tracker"].id]}
    return {
        "lines": sorted(lines.items(), key=lambda item: (item[1].lower(), item[0])),
        "regions": sorted(used, key=lambda item: (item[1].lower(), item[0])),
        "line_unset": any(not c["labels"].business_line for c in cards),
        "regions_unset": any(not regions[c["tracker"].id] for c in cards),
    }


@login_required
def home():
    from ..report.build import compute_position  # local import: the report package imports this module

    db = get_session()
    user = current_user()
    show_archived = request.args.get("archived") == "1"
    trackers = [t for t in visible_trackers(db, user) if show_archived or t.status == "active"]
    roles = tracker_roles(db, user)
    ids = [t.id for t in trackers]
    last_entries = _last_entry_dates(db, ids)
    statuses = _latest_statuses(db, ids)
    risks = _risk_counts(db, ids)
    written = _written_weeks(db, ids)
    today = date.today()
    team_names = {row.id: row.name for row in load_team_rows(db)}
    labels = tracker_labels(db, ids)
    regions = _tracker_regions(db, ids)
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
            "role": roles.get(t.id),
            "team": team_names.get(t.team_id),
            "open_risks": risks.get(t.id, (0, 0))[0],
            "red_risks": risks.get(t.id, (0, 0))[1],
            "starts": t.first_week_ending if t.first_week_ending > today else None,
            "inputs_missing": live and (t.id, headline.report_week) not in written,
            "entry_stale": live and (last_entry is None or (today - last_entry).days > 7),
            "behind": dvt is not None and dvt > 0,
            "mismatch": status_mismatch(status, headline),
            "lead": lead_in_charge(db, t),
            "spark": spark_chart(position.rows),
            "labels": labels[t.id],
            "line_data": str(t.business_line_id) if t.business_line_id is not None else "none",
            "regions_data": " " + (" ".join(str(region_id) for region_id, _ in regions[t.id]) or "none") + " ",
        }
        card["disagree"] = bool(card["mismatch"]) and card["mismatch"][0] == "warning"
        card["attention"] = (
            (10 if t.status != "active" else 0)
            + STATUS_ATTENTION.get(status, 4)
            - (1 if card["behind"] else 0)
            - (1.5 if card["mismatch"] and card["mismatch"][0] == "warning" else 0)  # Green yet behind: before Amber
            - (0.5 if card["inputs_missing"] else 0)
        )
        cards.append(card)
    cards.sort(key=lambda c: (c["attention"], c["tracker"].name.lower()))
    return render_template(
        "home.html",
        cards=cards,
        filter_options=_filter_options(cards, regions),
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
        "business_line_id": "",
        "region_ids": [],
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
        "business_line_id": str(t.business_line_id or ""),
        "region_ids": [str(region_id) for region_id in tracker_region_ids(get_session(), t.id)],
        "lead_user_id": str(t.lead_user_id or ""),
    }


def _parse_labels(db, form, tracker: Tracker | None):
    """The business line and regions posted on New tracker or Settings, with their errors; the tracker's current
    entries stay valid even when retired since."""
    line, line_error = parse_business_line(
        db, form.get("business_line_id"), tracker.business_line_id if tracker else None
    )
    regions, regions_error = parse_regions(
        db, form.getlist("region_ids"), tracker_region_ids(db, tracker.id) if tracker else ()
    )
    return line, regions, [error for error in (line_error, regions_error) if error]


@bp.route("/trackers/new", methods=["GET", "POST"])
@permission_required("create_trackers")
def new():
    db = get_session()
    if request.method == "POST":
        values, errors = validate_tracker_form(request.form)
        team, team_error = parse_team_id(db, request.form.get("team_id"))
        if team_error:
            errors.append(team_error)
        line, regions, label_errors = _parse_labels(db, request.form, None)
        errors += label_errors
        if not errors:
            actor = current_user()
            team_path = team_labels(load_team_rows(db)).get(team.id, team.name) if team else None
            tracker = Tracker(**values, team_id=team.id if team else None, business_line_id=line.id)
            db.add(tracker)
            try:
                db.flush()
                set_tracker_regions(db, tracker.id, [region.id for region in regions])
                record(
                    db,
                    user_id=actor.id,
                    tracker_id=tracker.id,
                    action="tracker_created",
                    entity="tracker",
                    entity_id=tracker.id,
                    detail={
                        "name": tracker.name,
                        "team": team_path,
                        "business_line": line.name,
                        "regions": [region.code for region in regions],
                    },
                )
                give_creator_ownership(db, tracker, actor)
                db.commit()
            except IntegrityError:  # the team was deleted at the same moment
                db.rollback()
                return _render_settings(None, request.form, [TEAM_CHOICE_ERROR], status=400)
            flash("Tracker created.", "success")
            return redirect(url_for("trackers.settings", tracker_id=tracker.id))
        return _render_settings(None, request.form, errors, status=400)
    return _render_settings(None, _defaults_form(), [])


@bp.post("/trackers/<int:tracker_id>/team")
@permission_required("manage_teams")
def set_team(tracker_id: int):
    """Put a tracker in a team, or in none (empty ``team_id``); the confirmation is in the page."""
    db = get_session()
    tracker = db.get(Tracker, tracker_id)
    if tracker is None:
        abort(404)
    destination = request.form.get("next", "settings")
    team, team_error = parse_team_id(db, request.form.get("team_id"))
    if team_error:
        abort(400, description=team_error)
    new_team_id = team.id if team else None
    actor = current_user()
    if new_team_id == tracker.team_id:
        flash(NO_CHANGES_MESSAGE, "info")
        return _after_team_change(actor, tracker, destination)
    old_team_id, name = tracker.team_id, tracker.name
    labels = team_labels(load_team_rows(db))
    new_path = labels.get(new_team_id, team.name) if team else None
    before = snapshot_access(db, actor)
    try:  # the change is flushed by the guard's query, so a team deleted at the same moment fails there or on commit
        tracker.team_id = new_team_id
        if raises_own_access(db, actor, before):
            db.rollback()
            flash(SELF_PROMOTION_MESSAGE, "danger")
            return _after_team_change(actor, tracker, destination)
        record(
            db,
            user_id=actor.id,
            tracker_id=tracker.id,
            action="tracker_team_changed",
            entity="tracker",
            entity_id=tracker.id,
            detail=change(labels.get(old_team_id), new_path),
        )
        db.commit()
    except IntegrityError:
        db.rollback()
        flash(TEAM_CHOICE_ERROR, "danger")
        return _after_team_change(actor, tracker, destination)
    flash(f"Moved {name} to {new_path or 'no team'}.", "success")
    return _after_team_change(actor, tracker, destination)


def _after_team_change(actor: User, tracker: Tracker, destination: str):
    """Back to where the change was made, or to the home page when the actor no longer reaches that screen.

    ``"team"`` is the Trackers tab of the team named by the form's ``team`` field (the row Remove there).
    """
    db = get_session()
    if destination == "access" and has_permission(actor, "manage_teams"):
        return redirect(url_for("trackers.roles", tracker_id=tracker.id))
    if destination == "team" and has_permission(actor, "manage_teams"):
        team_id = parse_id(request.form.get("team"))
        if team_id is not None and db.get(Team, team_id) is not None:
            return redirect(url_for("teams.view", team_id=team_id, tab="trackers"))
    if destination == "settings" and user_role(db, actor, tracker.id) == "owner":
        return redirect(url_for("trackers.settings", tracker_id=tracker.id))
    return redirect(url_for("index"))


MOVING_AVERAGE_RANGE = range(1, 13)


def _settings_live(db, tracker: Tracker) -> dict:
    """Figures for the line under each settings section: the report's totals, the weekly rate and forecast for every
    moving-average period (so the line can follow the period as it is changed), and the next scheduled send."""
    from ..report.build import default_report_week
    from ..sched.runner import next_send

    today = date.today()
    week = default_report_week(tracker, today)
    as_of = min(week, today)
    weeks, targets, actuals, group_inputs, entry_totals = load_engine_inputs(db, tracker, as_of)
    positions = group_positions(group_inputs, entry_totals)
    scope = sum(p.baseline for p in positions)
    headline = None
    forecasts = {}
    for weeks_averaged in MOVING_AVERAGE_RANGE:
        rows = build_week_rows(
            weeks,
            targets,
            actuals,
            scope,
            tracker.completed_before_first,
            weeks_averaged,
            as_of,
            tracker.week_ending_weekday,
        )
        result = build_headline(rows, positions, tracker.completed_before_first, tracker.target_completion, week)
        if weeks_averaged == tracker.moving_average_weeks:
            headline = result
        complete = [r.actual for r in rows if r.state == COMPLETE and r.week_ending <= week]
        forecasts[weeks_averaged] = {
            "rate": round(result.forecast_rate, 1) if result.forecast_rate is not None else None,
            "forecast": result.forecast_completion.isoformat() if result.forecast_completion else None,
            "window": complete[-weeks_averaged:],
        }
    recipients = db.scalar(select(func.count()).select_from(Recipient).where(Recipient.tracker_id == tracker.id))
    return {
        "headline": headline,
        "forecasts": forecasts,
        "today": today,
        "next_send": next_send(tracker, datetime.now(timezone.utc)),
        "recipients": recipients,
    }


def _team_path(tracker: Tracker | None) -> str | None:
    if tracker is None or tracker.team_id is None:
        return None
    return team_labels(load_team_rows(get_session())).get(tracker.team_id)


def _chosen_region_ids(form) -> set[str]:
    """The ticked regions of a posted form (repeated fields) or of a form built in the view (a list)."""
    chosen = form.getlist("region_ids") if hasattr(form, "getlist") else form.get("region_ids", [])
    return {str(region_id) for region_id in chosen}


def _render_settings(tracker: Tracker | None, form, errors: list[str], status: int = 200):
    template = "trackers/settings.html" if tracker is not None else "trackers/new.html"
    db = get_session()
    locked = tracker is not None and _has_entries(db, tracker)
    return (
        render_template(
            template,
            tracker=tracker,
            form=form,
            errors=errors,
            weekdays=list(enumerate(WEEKDAYS)),
            weekday_locked=locked,
            team_choices=team_choices(db),
            team_regions={team_id: place.region_id for team_id, place in team_places(db).items()}
            if tracker is None
            else {},
            business_line_choices=business_line_choices(db, tracker.business_line_id if tracker else None),
            region_choices=region_choices(db, tracker_region_ids(db, tracker.id) if tracker else ()),
            chosen_regions=_chosen_region_ids(form),
            team_path=_team_path(tracker),
            live=_settings_live(get_session(), tracker) if tracker is not None else None,
            lead_choices=lead_candidates(db, tracker) if tracker is not None else [],
            lead_missing=tracker is not None and lead_in_charge(db, tracker) is None,
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


def _parse_lead(db, form, tracker: Tracker) -> tuple[User | None, str | None]:
    """The person in charge chosen on the form: ``(None, None)`` when the form does not carry the field (it keeps the
    stored value), an error when the choice is empty or the person cannot write the weekly update."""
    if "lead_user_id" not in form:
        return None, None
    chosen = parse_id(form.get("lead_user_id"))
    if chosen is None:
        return None, "Choose the person in charge."
    lead = next((user for user in lead_candidates(db, tracker) if user.id == chosen), None)
    if lead is None:
        return None, "Choose someone who can write the weekly update (Editor or Owner on this tracker)."
    return lead, None


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
    line, regions, label_errors = _parse_labels(db, request.form, tracker)
    errors += label_errors
    lead, lead_error = _parse_lead(db, request.form, tracker)
    if lead_error:
        errors.append(lead_error)
    if errors:
        return _render_settings(tracker, request.form, errors, status=400)
    before = tracker_labels(db, [tracker.id])[tracker.id]
    changed = {}
    for field, new_value in values.items():
        old_value = getattr(tracker, field)
        if old_value != new_value:
            changed[field] = [_jsonable(old_value), _jsonable(new_value)]
            setattr(tracker, field, new_value)
    if line.id != tracker.business_line_id:
        changed["business_line"] = [before.business_line, line.name]
        tracker.business_line_id = line.id
    region_ids = {region.id for region in regions}
    if region_ids != tracker_region_ids(db, tracker.id):
        changed["regions"] = [before.regions, [region.code for region in regions]]
        set_tracker_regions(db, tracker.id, region_ids)
    if lead is not None and lead.id != tracker.lead_user_id:
        old = db.get(User, tracker.lead_user_id) if tracker.lead_user_id else None
        changed["lead"] = [old.full_name if old else None, lead.full_name]
        tracker.lead_user_id = lead.id
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
    group_id = parse_id(request.form.get("group_id"))
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
@permission_required("manage_teams")
def roles(tracker_id: int):
    db = get_session()
    tracker = db.get(Tracker, tracker_id)
    if tracker is None:
        abort(404)
    actor = current_user()
    g.tracker, g.role = tracker, user_role(db, actor, tracker.id)
    if request.method == "POST":
        refused = _refuse_if_archived(tracker, "trackers.roles")
        if refused:
            return refused
        user_id = parse_id(request.form.get("user_id"))
        user = db.get(User, user_id) if user_id else None
        choice = request.form.get("role", "")
        if user is None or user.is_admin or choice not in (*ROLES, "remove"):
            abort(400, description="Choose a user and a role.")
        existing = db.get(TrackerRole, (user.id, tracker.id))
        previous = existing.role if existing else None
        if previous == (None if choice == "remove" else choice):
            flash(NO_CHANGES_MESSAGE, "info")
            return redirect(url_for("trackers.roles", tracker_id=tracker_id))
        if choice != "remove":
            if user.status != "active":
                abort(400, description=INACTIVE_PERSON_MESSAGE)
            # Lowering a role gives nothing, so only a new or higher role is refused.
            raised = previous is None or ROLE_ORDER[choice] > ROLE_ORDER[previous]
            refusal = vouched_refusal(db, actor, user) if raised else None
            if refusal:
                flash(refusal, "danger")
                return redirect(url_for("trackers.roles", tracker_id=tracker_id))
        before = snapshot_access(db, actor)
        if choice == "remove":
            if existing:
                db.delete(existing)
        elif existing:
            existing.role = choice
        else:
            db.add(TrackerRole(user_id=user.id, tracker_id=tracker.id, role=choice))
        if raises_own_access(db, actor, before):
            db.rollback()
            flash(SELF_PROMOTION_MESSAGE, "danger")
            return redirect(url_for("trackers.roles", tracker_id=tracker_id))
        record(
            db,
            user_id=actor.id,
            tracker_id=tracker.id,
            action="role_removed" if choice == "remove" else "role_set",
            entity="user",
            entity_id=user.id,
            detail=change(previous, None if choice == "remove" else choice),
            target_user_id=user.id,
        )
        name = user.full_name
        db.commit()
        flash(f"Updated access for {name}.", "success")
        return redirect(url_for("trackers.roles", tracker_id=tracker_id))
    current = {r.user_id: r.role for r in db.scalars(select(TrackerRole).where(TrackerRole.tracker_id == tracker.id))}
    access = tracker_access_list(db, tracker)
    candidates = [
        u
        for u in db.scalars(select(User).where(User.status == "active").order_by(User.full_name, User.id))
        if not u.is_admin and u.id not in current and (actor.is_admin or u.id != actor.id)
    ]
    return render_template(
        "trackers/roles.html",
        tracker=tracker,
        access=access,
        candidates=candidates,
        roles=ROLES,
        team_choices=team_choices(db),
        team_path=_team_path(tracker),
        page_title=f"{tracker.name} access",
        current_page="trackers",
    )
