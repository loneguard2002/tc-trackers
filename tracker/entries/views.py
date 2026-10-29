"""Views for completion entries, targets, weekly inputs and risks (spec section 5.1)."""

from __future__ import annotations

import csv
import io
from datetime import date, datetime, timezone

from flask import Response, abort, flash, g, redirect, render_template, request, url_for
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from ..audit import record
from ..auth import current_user, require_tracker_role
from ..db import get_session
from ..engine.calc import COMPLETE
from ..engine.weeks import in_progress_week, week_endings
from ..models import CompletionEntry, Group, ReportInput, Risk, Tracker, User, Week
from ..report.build import compute_position, default_report_week, select_top_risks
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


def _entry_filters(tracker: Tracker, week: date | None, group_id: int | None) -> list:
    conditions = [CompletionEntry.tracker_id == tracker.id]
    if week is not None:
        conditions.append(CompletionEntry.week_ending == week)
    if group_id is not None:
        conditions.append(CompletionEntry.group_id == group_id)
    return conditions


@bp.get("/trackers/<int:tracker_id>/entries")
@require_tracker_role("editor")
def list_entries(tracker_id: int):
    tracker, db = g.tracker, get_session()
    today = date.today()
    current = in_progress_week(today, tracker.week_ending_weekday)
    week = parse_date(request.args.get("week"))
    group_id = request.args.get("group", type=int)
    conditions = _entry_filters(tracker, week, group_id)
    # One row beyond the limit tells the page whether older entries were left out.
    entries = db.scalars(
        select(CompletionEntry)
        .where(*conditions)
        .order_by(CompletionEntry.week_ending.desc(), CompletionEntry.entry_date.desc(), CompletionEntry.id.desc())
        .limit(LIST_LIMIT + 1)
    ).all()
    capped = len(entries) > LIST_LIMIT
    by_week: dict[date, list[CompletionEntry]] = {}
    for entry in entries[:LIST_LIMIT]:
        by_week.setdefault(entry.week_ending, []).append(entry)
    # Week totals cover every matching entry, including any beyond the list limit.
    totals = {
        week_ending: (int(total), count)
        for week_ending, total, count in db.execute(
            select(CompletionEntry.week_ending, func.sum(CompletionEntry.quantity), func.count())
            .where(*conditions)
            .group_by(CompletionEntry.week_ending)
        )
    }
    targets = dict(db.execute(select(Week.week_ending, Week.target).where(Week.tracker_id == tracker.id)).all())
    # Location chips count the entries in the chosen week, across every location.
    chip_counts = dict(
        db.execute(
            select(CompletionEntry.group_id, func.count())
            .where(*_entry_filters(tracker, week, None))
            .group_by(CompletionEntry.group_id)
        ).all()
    )
    groups = _ordered_groups(db, tracker)
    weeks = [w for w in week_endings(tracker.first_week_ending, tracker.last_week_ending) if w <= (current or today)]
    if week is not None and week not in weeks:
        weeks.append(week)
    return render_template(
        "entries/list.html",
        by_week=by_week,
        totals=totals,
        targets=targets,
        groups={grp.id: grp for grp in groups},
        group_list=groups,
        active_groups=[grp for grp in groups if not grp.retired],
        chip_counts=chip_counts,
        weeks=list(reversed(weeks)),
        selected_week=week,
        selected_group=group_id,
        current_week=current,
        today=today,
        format_date=format_date,
        capped=capped,
        list_limit=LIST_LIMIT,
        **_page(tracker, "Entries"),
    )


def _csv_cell(value) -> str:
    """Text for one CSV cell; a leading formula character is quoted so a spreadsheet shows it as text."""
    text = "" if value is None else str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


@bp.get("/trackers/<int:tracker_id>/entries.csv")
@require_tracker_role("editor")
def entries_csv(tracker_id: int):
    tracker, db = g.tracker, get_session()
    week = parse_date(request.args.get("week"))
    group_id = request.args.get("group", type=int)
    names = {grp.id: grp.name for grp in _ordered_groups(db, tracker)}
    entries = db.scalars(
        select(CompletionEntry)
        .where(*_entry_filters(tracker, week, group_id))
        .order_by(CompletionEntry.entry_date.desc(), CompletionEntry.id.desc())
    ).all()
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["Date", "Week ending", tracker.group_label or "Group", "Quantity", "Note"])
    for e in entries:
        writer.writerow(
            [
                e.entry_date.isoformat(),
                e.week_ending.isoformat(),
                _csv_cell(names.get(e.group_id, e.group_id)),
                e.quantity,
                _csv_cell(e.note),
            ]
        )
    return Response(
        "\ufeff" + out.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=entries.csv"},
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
    flash(f"Recorded {quantity} for {group.name} on {format_date(entry.entry_date)}.", "success")
    if request.form.get("return_to") == "list":
        return redirect(url_for("entries.list_entries", tracker_id=tracker.id))
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
    today = date.today()
    position = compute_position(get_session(), tracker, None, today)
    actuals = {r.week_ending: r.actual for r in position.rows if r.state == COMPLETE}
    saved = {w: r.target for w, r in rows.items() if r.target is not None}
    planned = sum(saved.values())
    past = [w for w in weeks if w in actuals]
    return (
        render_template(
            "entries/targets.html",
            weeks=weeks,
            form=form,
            actuals=actuals,
            current_week=in_progress_week(today, tracker.week_ending_weekday),
            scope=position.headline.total_scope,
            planned=planned,
            unplanned=position.headline.total_scope - tracker.completed_before_first - planned,
            done_to_date=sum(actuals[w] or 0 for w in past),
            planned_to_date=sum(saved.get(w, 0) for w in past),
            last_planned=max(saved) if saved else None,
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
    db = get_session()
    today = date.today()
    preparer = db.get(User, row.prepared_by) if row and row.prepared_by else None
    saved = {r.week_ending: r for r in db.scalars(select(ReportInput).where(ReportInput.tracker_id == tracker.id))}
    index = weeks.index(week)
    previous = saved.get(weeks[index - 1]) if index else None
    risks = list(db.scalars(select(Risk).where(Risk.tracker_id == tracker.id, Risk.status != "Closed")))
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
            saved=saved,
            previous=previous if previous and (previous.status or previous.headline or previous.decisions) else None,
            prev_week=weeks[index - 1] if index else None,
            next_week=weeks[index + 1] if index + 1 < len(weeks) else None,
            latest_week=default_report_week(tracker, today),
            current_week=in_progress_week(today, tracker.week_ending_weekday),
            today=today,
            headline=compute_position(db, tracker, week, today).headline,
            red_risks=sum(1 for r in risks if r.rag == "Red"),
            overdue_risks=sum(1 for r in risks if r.target_date and r.target_date < min(week, today)),
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
            return _render_risk_form(tracker, None, context, request.form, errors, 400)
        values["ref"] = values["ref"] or next_risk_ref(existing)
        risk = Risk(tracker_id=tracker.id, **values)
        db.add(risk)
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
            return _render_risk_form(tracker, None, context, request.form, ["That reference is already used."], 400)
        _audit(db, tracker, "risk_created", "risk", risk.id, {"ref": risk.ref})
        db.commit()
        flash(f"Risk {risk.ref} added.", "success")
        return redirect(url_for("entries.risks", tracker_id=tracker.id))
    items = db.scalars(select(Risk).where(Risk.tracker_id == tracker.id).order_by(Risk.id)).all()
    today = date.today()
    # Open risks in the report's Top risks order, so the register reads the same as the report.
    live = select_top_risks(items, limit=len(items))
    overdue = {r.id for r in live if r.target_date is not None and r.target_date < today}
    counts = {rag: sum(1 for r in live if r.rag == rag) for rag in RAG_VALUES}
    counts.update({"open": len(live), "none": sum(1 for r in live if not r.rag), "overdue": len(overdue)})
    return render_template(
        "entries/risks.html",
        risks=live,
        closed=[r for r in items if r.status == "Closed"],
        overdue=overdue,
        counts=counts,
        today=today,
        group_names={grp.id: grp.name for grp in context["groups"]},
        format_date=format_date,
        **_page(tracker, "Risks"),
    )


@bp.get("/trackers/<int:tracker_id>/risks/new")
@require_tracker_role("editor")
def new_risk(tracker_id: int):
    tracker, db = g.tracker, get_session()
    return _render_risk_form(tracker, None, _risk_context(db, tracker), {}, [], 200)


def _render_risk_form(tracker: Tracker, risk: Risk | None, context: dict, form, errors: list[str], status: int):
    title = f"Risk {risk.ref}" if risk else "New risk"
    next_ref = None
    if risk is None:
        next_ref = next_risk_ref(list(get_session().scalars(select(Risk.ref).where(Risk.tracker_id == tracker.id))))
    return (
        render_template("entries/risk_form.html", risk=risk, form=form, errors=errors, next_ref=next_ref,
                        today=date.today(), format_date=format_date, **context, **_page(tracker, title)),
        status,
    )  # fmt: skip


@bp.route("/trackers/<int:tracker_id>/risks/<int:risk_id>", methods=["GET", "POST"])
@require_tracker_role("editor")
def edit_risk(tracker_id: int, risk_id: int):
    tracker, db = g.tracker, get_session()
    item = db.get(Risk, risk_id)
    if item is None or item.tracker_id != tracker.id:
        abort(404)
    context = _risk_context(db, tracker)

    def render(form, errors, status):
        return _render_risk_form(tracker, item, context, form, errors, status)

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


@bp.post("/trackers/<int:tracker_id>/risks/<int:risk_id>/delete")
@require_tracker_role("editor")
def delete_risk(tracker_id: int, risk_id: int):
    tracker, db = g.tracker, get_session()
    refused = _refuse_if_archived(tracker, "entries.risks")
    if refused:
        return refused
    item = db.get(Risk, risk_id)
    if item is None or item.tracker_id != tracker.id:
        abort(404)
    _audit(db, tracker, "risk_deleted", "risk", item.id, {"ref": item.ref, "description": item.description})
    db.delete(item)
    db.commit()
    flash(f"Risk {item.ref} deleted.", "success")
    return redirect(url_for("entries.risks", tracker_id=tracker.id))
