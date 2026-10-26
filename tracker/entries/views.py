"""Views for completion entries, targets, weekly inputs and risks (spec section 5.1)."""

from __future__ import annotations

from datetime import date, datetime, timezone

from flask import abort, flash, g, redirect, render_template, request, url_for
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from ..audit import record
from ..auth import current_user, require_tracker_role
from ..db import get_session
from ..engine.weeks import week_endings
from ..models import CompletionEntry, Group, ReportInput, Risk, Tracker, User, Week
from ..report.build import default_report_week
from ..trackers.forms import RAG_VALUES, parse_date
from ..trackers.views import _jsonable, _ordered_groups, _refuse_if_archived
from . import bp
from .forms import (
    RISK_STATUSES,
    check_entry_date,
    format_date,
    next_risk_ref,
    parse_quantity,
    parse_targets,
    validate_inputs_form,
    validate_risk_form,
)

LIST_LIMIT = 500


def _audit(db, tracker: Tracker, action: str, entity: str, entity_id, detail: dict | None = None) -> None:
    record(
        db,
        user_id=current_user().id,
        tracker_id=tracker.id,
        action=action,
        entity=entity,
        entity_id=entity_id,
        detail=detail,
    )


def _page(tracker: Tracker, title: str) -> dict:
    return {"tracker": tracker, "page_title": f"{tracker.name}: {title}", "current_page": "trackers"}


# --- Entries -------------------------------------------------------------------------------------------------


@bp.get("/trackers/<int:tracker_id>/entries")
@require_tracker_role("editor")
def list_entries(tracker_id: int):
    tracker, db = g.tracker, get_session()
    weeks = week_endings(tracker.first_week_ending, tracker.last_week_ending)
    week = parse_date(request.args.get("week"))
    group_id = request.args.get("group", type=int)
    query = select(CompletionEntry).where(CompletionEntry.tracker_id == tracker.id)
    if week is not None:
        query = query.where(CompletionEntry.week_ending == week)
    if group_id is not None:
        query = query.where(CompletionEntry.group_id == group_id)
    # One row beyond the limit tells the page whether older entries were left out.
    entries = db.scalars(
        query.order_by(CompletionEntry.entry_date.desc(), CompletionEntry.id.desc()).limit(LIST_LIMIT + 1)
    ).all()
    capped = len(entries) > LIST_LIMIT
    entries = entries[:LIST_LIMIT]
    groups = _ordered_groups(db, tracker)
    return render_template(
        "entries/list.html",
        entries=entries,
        groups={grp.id: grp for grp in groups},
        group_list=groups,
        weeks=weeks,
        selected_week=week,
        selected_group=group_id,
        format_date=format_date,
        capped=capped,
        list_limit=LIST_LIMIT,
        **_page(tracker, "Entries"),
    )


def _render_new(tracker: Tracker, groups: list[Group], form, errors: list[str], status: int = 200):
    return (
        render_template("entries/new.html", groups=groups, form=form, errors=errors, **_page(tracker, "New entry")),
        status,
    )


@bp.route("/trackers/<int:tracker_id>/entries/new", methods=["GET", "POST"])
@require_tracker_role("editor")
def new_entry(tracker_id: int):
    tracker, db = g.tracker, get_session()
    groups = [grp for grp in _ordered_groups(db, tracker) if not grp.retired]
    if request.method == "GET":
        form = {"group_id": request.args.get("group", ""), "entry_date": date.today().isoformat(), "quantity": ""}
        return _render_new(tracker, groups, form, [])
    refused = _refuse_if_archived(tracker, "entries.new_entry")
    if refused:
        return refused
    errors: list[str] = []
    group = db.get(Group, request.form.get("group_id", type=int) or 0)
    if group is None or group.tracker_id != tracker.id:
        errors.append("Choose a group.")
    elif group.retired:
        errors.append("Entries cannot be recorded against a retired group.")
    week_ending, date_error = check_entry_date(
        parse_date(request.form.get("entry_date")),
        tracker.week_ending_weekday,
        tracker.first_week_ending,
        tracker.last_week_ending,
    )
    if date_error:
        errors.append(date_error)
    quantity, quantity_error = parse_quantity(request.form.get("quantity"))
    if quantity_error:
        errors.append(quantity_error)
    if errors:
        return _render_new(tracker, groups, request.form, errors, status=400)
    entry = CompletionEntry(
        tracker_id=tracker.id,
        group_id=group.id,
        entry_date=parse_date(request.form.get("entry_date")),
        week_ending=week_ending,
        quantity=quantity,
        note=(request.form.get("note") or "").strip(),
        created_by=current_user().id,
    )
    db.add(entry)
    db.flush()
    _audit(
        db,
        tracker,
        "entry_created",
        "entry",
        entry.id,
        {"group_id": group.id, "entry_date": entry.entry_date.isoformat(), "quantity": quantity},
    )
    db.commit()
    flash(f"Recorded {quantity} for {group.name}.", "success")
    return redirect(url_for("entries.new_entry", tracker_id=tracker.id, group=group.id))


@bp.post("/trackers/<int:tracker_id>/entries/<int:entry_id>/delete")
@require_tracker_role("editor")
def delete_entry(tracker_id: int, entry_id: int):
    tracker, db = g.tracker, get_session()
    refused = _refuse_if_archived(tracker, "entries.list_entries")
    if refused:
        return refused
    entry = db.get(CompletionEntry, entry_id)
    if entry is None or entry.tracker_id != tracker.id:
        abort(404)
    _audit(
        db,
        tracker,
        "entry_deleted",
        "entry",
        entry.id,
        {"group_id": entry.group_id, "entry_date": entry.entry_date.isoformat(), "quantity": entry.quantity},
    )
    db.delete(entry)
    db.commit()
    flash("Entry deleted.", "success")
    return redirect(url_for("entries.list_entries", tracker_id=tracker.id))


# --- Targets -------------------------------------------------------------------------------------------------


@bp.route("/trackers/<int:tracker_id>/targets", methods=["GET", "POST"])
@require_tracker_role("editor")
def targets(tracker_id: int):
    tracker, db = g.tracker, get_session()
    weeks = week_endings(tracker.first_week_ending, tracker.last_week_ending)
    rows = {w.week_ending: w for w in db.scalars(select(Week).where(Week.tracker_id == tracker.id))}
    if request.method == "POST":
        refused = _refuse_if_archived(tracker, "entries.targets")
        if refused:
            return refused
        new_targets, errors = parse_targets(request.form, weeks)
        if errors:
            for message in errors:
                flash(message, "danger")
            return _render_targets(tracker, weeks, rows, request.form, 400)
        changed: dict[str, list] = {}
        for week, value in new_targets.items():
            row = rows.get(week)
            old = row.target if row else None
            if row is None:
                if value is None:
                    continue
                db.add(Week(tracker_id=tracker.id, week_ending=week, target=value))
            else:
                row.target = value  # imported_actual is left untouched
            if old != value:
                changed[week.isoformat()] = [old, value]
        if changed:
            _audit(db, tracker, "targets_updated", "tracker", tracker.id, changed)
        db.commit()
        flash("Targets saved.", "success")
        return redirect(url_for("entries.targets", tracker_id=tracker.id))
    values = {f"target-{w.isoformat()}": "" if r.target is None else str(r.target) for w, r in rows.items()}
    return _render_targets(tracker, weeks, rows, values, 200)


def _render_targets(tracker: Tracker, weeks: list[date], rows: dict, form, status: int):
    return (
        render_template(
            "entries/targets.html",
            weeks=weeks,
            form=form,
            format_date=format_date,
            **_page(tracker, "Weekly targets"),
        ),
        status,
    )


# --- Weekly inputs -------------------------------------------------------------------------------------------


@bp.route("/trackers/<int:tracker_id>/inputs", methods=["GET", "POST"])
@require_tracker_role("editor")
def inputs(tracker_id: int):
    tracker, db = g.tracker, get_session()
    weeks = week_endings(tracker.first_week_ending, tracker.last_week_ending)
    requested = request.args.get("week")
    week = parse_date(requested) if requested else default_report_week(tracker, date.today())
    if week not in weeks:
        abort(404)
    row = db.get(ReportInput, (tracker.id, week))
    if request.method == "POST":
        refused = _refuse_if_archived(tracker, "entries.inputs")
        if refused:
            return refused
        values, errors = validate_inputs_form(request.form)
        if errors:
            return _render_inputs(tracker, weeks, week, row, request.form, errors, 400)
        old = (
            {k: getattr(row, k) for k in values}
            if row is not None
            else {"status": None, "headline": "", "decisions": ""}
        )
        if row is None:
            row = ReportInput(tracker_id=tracker.id, week_ending=week)
            db.add(row)
        for key, value in values.items():
            setattr(row, key, value)
        row.prepared_by = current_user().id
        row.updated_at = datetime.now(timezone.utc)
        changed = {k: [old[k], v] for k, v in values.items() if old[k] != v}
        _audit(db, tracker, "inputs_saved", "report_input", week.isoformat(), changed)
        db.commit()
        flash("Weekly inputs saved.", "success")
        return redirect(url_for("entries.inputs", tracker_id=tracker.id, week=week.isoformat()))
    form = {"status": row.status or "", "headline": row.headline, "decisions": row.decisions} if row else {}
    return _render_inputs(tracker, weeks, week, row, form, [], 200)


def _render_inputs(tracker: Tracker, weeks, week: date, row, form, errors: list[str], status: int):
    preparer = get_session().get(User, row.prepared_by) if row and row.prepared_by else None
    return (
        render_template(
            "entries/inputs.html",
            weeks=weeks,
            week=week,
            row=row,
            preparer=preparer,
            form=form,
            errors=errors,
            rag_values=RAG_VALUES,
            format_date=format_date,
            **_page(tracker, "Weekly inputs"),
        ),
        status,
    )


# --- Risks ---------------------------------------------------------------------------------------------------


def _risk_context(db, tracker: Tracker) -> dict:
    return {"groups": _ordered_groups(db, tracker), "rag_values": RAG_VALUES, "statuses": RISK_STATUSES}


@bp.route("/trackers/<int:tracker_id>/risks", methods=["GET", "POST"])
@require_tracker_role("editor")
def risks(tracker_id: int):
    tracker, db = g.tracker, get_session()
    context = _risk_context(db, tracker)
    if request.method == "POST":
        refused = _refuse_if_archived(tracker, "entries.risks")
        if refused:
            return refused
        values, errors = validate_risk_form(request.form, [grp.id for grp in context["groups"]])
        existing = list(db.scalars(select(Risk.ref).where(Risk.tracker_id == tracker.id)))
        if not errors and values["ref"] and values["ref"] in existing:
            errors.append("That reference is already used.")
        if errors:
            return _render_risks(tracker, db, context, request.form, errors, 400)
        values["ref"] = values["ref"] or next_risk_ref(existing)
        risk = Risk(tracker_id=tracker.id, **values)
        db.add(risk)
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
            return _render_risks(tracker, db, context, request.form, ["That reference is already used."], 400)
        _audit(db, tracker, "risk_created", "risk", risk.id, {"ref": risk.ref})
        db.commit()
        flash(f"Risk {risk.ref} added.", "success")
        return redirect(url_for("entries.risks", tracker_id=tracker.id))
    return _render_risks(tracker, db, context, {}, [], 200)


def _render_risks(tracker: Tracker, db, context: dict, form, errors: list[str], status: int):
    items = db.scalars(select(Risk).where(Risk.tracker_id == tracker.id).order_by(Risk.id)).all()
    return (
        render_template(
            "entries/risks.html",
            risks=items,
            group_names={grp.id: grp.name for grp in context["groups"]},
            form=form,
            errors=errors,
            risk=None,
            **context,
            **_page(tracker, "Risks"),
        ),
        status,
    )


@bp.route("/trackers/<int:tracker_id>/risks/<int:risk_id>", methods=["GET", "POST"])
@require_tracker_role("editor")
def edit_risk(tracker_id: int, risk_id: int):
    tracker, db = g.tracker, get_session()
    item = db.get(Risk, risk_id)
    if item is None or item.tracker_id != tracker.id:
        abort(404)
    context = _risk_context(db, tracker)

    def render(form, errors, status):
        return (
            render_template("entries/risks.html", risks=[], group_names={}, form=form, errors=errors, risk=item,
                            **context, **_page(tracker, f"Risk {item.ref}")),
            status,
        )  # fmt: skip

    if request.method == "GET":
        form = {
            "ref": item.ref,
            "description": item.description,
            "impact": item.impact,
            "group_id": "" if item.group_id is None else str(item.group_id),
            "owner_role": item.owner_role,
            "raised_on": item.raised_on.isoformat() if item.raised_on else "",
            "target_date": item.target_date.isoformat() if item.target_date else "",
            "status": item.status,
            "rag": item.rag or "",
            "latest_update": item.latest_update,
        }
        return render(form, [], 200)
    refused = _refuse_if_archived(tracker, "entries.risks")
    if refused:
        return refused
    values, errors = validate_risk_form(request.form, [grp.id for grp in context["groups"]])
    values["ref"] = values["ref"] or item.ref
    if not errors and values["ref"] != item.ref:
        clash = db.scalar(select(Risk.id).where(Risk.tracker_id == tracker.id, Risk.ref == values["ref"]))
        if clash is not None:
            errors.append("That reference is already used.")
    if errors:
        return render(request.form, errors, 400)
    changed = {}
    for key, value in values.items():
        old = getattr(item, key)
        if old != value:
            changed[key] = [_jsonable(old), _jsonable(value)]
            setattr(item, key, value)
    if changed:
        _audit(db, tracker, "risk_updated", "risk", item.id, changed)
    db.commit()
    flash(f"Risk {item.ref} saved.", "success")
    return redirect(url_for("entries.risks", tracker_id=tracker.id))
