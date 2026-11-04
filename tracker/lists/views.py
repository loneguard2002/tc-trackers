"""Screens for the administered lists (spec section 1): regions, their locations, and business lines.

Administrators only. An entry nothing uses can be deleted; one in use can only be retired, and the delete is refused
again on the server (the foreign keys restrict it too, so a use added at the same moment refuses it on commit). Every
change is committed with its activity entry in one transaction. Moving a location to another region moves the teams
placed there, so its entry counts them.
"""

from __future__ import annotations

import re

from flask import abort, flash, redirect, render_template, request, url_for
from sqlalchemy import exists, func, select
from sqlalchemy.exc import IntegrityError

from ..audit import NO_CHANGES_MESSAGE, change, record
from ..auth import admin_required, current_user
from ..db import get_session
from ..ids import in_range, parse_id
from ..models import BusinessLine, Location, Region, Team, Tracker, TrackerRegion
from ..naming import MAX_NAME_LENGTH, name_error
from . import bp
from .catalogue import location_label
from .countries import country_name, parse_country

manage_lists_required = admin_required

MAX_CODE_LENGTH = 20
REGION_CODE_REQUIRED = "Enter a region short name."
REGION_CODE_TOO_LONG = f"A region short name can be at most {MAX_CODE_LENGTH} characters."
REGION_CODE_TAKEN = "A region with that short name already exists."
REGION_CODE_ERRORS = (REGION_CODE_REQUIRED, REGION_CODE_TOO_LONG, REGION_CODE_TAKEN)
REGION_CHOICE_ERROR = "Choose a region from the list."
LOCATION_CODE_REQUIRED = "Enter a location code."
LOCATION_CODE_FORMAT = "A location code is 2 to 6 letters, such as LON."
LOCATION_CODE_TAKEN = "A location with that code already exists."
LOCATION_TAKEN = "A location with that city and country already exists."
REGION_IN_USE = "This region has locations or trackers, so it can only be retired."
LOCATION_IN_USE = "Teams use this location, so it can only be retired."
BUSINESS_LINE_IN_USE = "Trackers use this business line, so it can only be retired."
ACTIONS = ("save", "retire", "restore", "delete")


def _or_404(model, entry_id: int):
    entry = get_session().get(model, entry_id) if in_range(entry_id) else None
    if entry is None:
        abort(404)
    return entry


def _action() -> str:
    action = request.form.get("action", "")
    if action not in ACTIONS:
        abort(400, description="Choose save, retire, restore or delete.")
    return action


def _log(*, action: str, entity: str, entity_id: int, detail: dict) -> None:
    record(
        get_session(),
        user_id=current_user().id,
        tracker_id=None,
        action=action,
        entity=entity,
        entity_id=entity_id,
        detail=detail,
    )


def _changed(entry, submitted: dict) -> tuple[dict, dict]:
    """The fields ``submitted`` changes, as ``(before, after)``; both empty when nothing changes."""
    before = {field: getattr(entry, field) for field, value in submitted.items() if getattr(entry, field) != value}
    return before, {field: submitted[field] for field in before}


def _set_retired(entry, action: str, noun: str, label: str, entity: str, detail: dict) -> None:
    """Retire or restore (``action``); nothing is written when the entry is already so."""
    retired = action == "retire"
    if entry.retired == retired:
        flash(NO_CHANGES_MESSAGE, "info")
        return
    entry.retired = retired
    logged = f"{entity}_{'retired' if retired else 'restored'}"  # region_retired, location_restored, ...
    _log(action=logged, entity=entity, entity_id=entry.id, detail=detail)
    get_session().commit()
    flash(f"{'Retired' if retired else 'Restored'} the {noun} {label}.", "success")


def _text_error(value: str, noun: str) -> str | None:
    if not value:
        return f"Enter a {noun}."
    if len(value) > MAX_NAME_LENGTH:
        return f"A {noun} can be at most {MAX_NAME_LENGTH} characters."
    return None


# --- Regions and locations ------------------------------------------------------------------------------------------


def _region_errors(code: str, name: str, exclude_id: int | None = None) -> list[str]:
    db = get_session()
    if not code:
        code_error = REGION_CODE_REQUIRED
    elif len(code) > MAX_CODE_LENGTH:
        code_error = REGION_CODE_TOO_LONG
    else:
        code_error = REGION_CODE_TAKEN if name_error(db, Region, code, "region", exclude_id, Region.code) else None
    return [e for e in (code_error, name_error(db, Region, name, "region", exclude_id)) if e]


def _location_errors(
    code: str, city: str, country_text: str, exclude_id: int | None = None
) -> tuple[list[str], str | None]:
    """The errors for a submitted location, and the parsed country code (None when it is not a listed one)."""
    db = get_session()
    errors: list[str] = []
    if not code:
        errors.append(LOCATION_CODE_REQUIRED)
    elif not re.fullmatch(r"[A-Z]{2,6}", code):
        errors.append(LOCATION_CODE_FORMAT)
    else:
        query = select(Location.id).where(func.lower(Location.code) == code.lower())
        if exclude_id is not None:
            query = query.where(Location.id != exclude_id)
        if db.scalar(query.limit(1)) is not None:
            errors.append(LOCATION_CODE_TAKEN)
    city_error = _text_error(city, "city")
    country_code, country_error = parse_country(country_text)
    errors += [e for e in (city_error, country_error) if e]
    if city_error is None and country_code is not None:
        query = select(Location.id).where(
            func.lower(Location.city) == city.lower(), Location.country_code == country_code
        )
        if exclude_id is not None:
            query = query.where(Location.id != exclude_id)
        if db.scalar(query.limit(1)) is not None:
            errors.append(LOCATION_TAKEN)
    return errors, country_code


def _region_form() -> dict:
    return {"code": request.form.get("code", "").strip(), "name": request.form.get("name", "").strip()}


def _location_form() -> dict:
    return {
        "code": request.form.get("code", "").strip().upper(),
        "city": request.form.get("city", "").strip(),
        "country_code": request.form.get("country_code", "").strip(),
    }


def _region_in_use(region_id: int) -> bool:
    db = get_session()
    return bool(
        db.scalar(select(exists().where(Location.region_id == region_id)))
        or db.scalar(select(exists().where(TrackerRegion.region_id == region_id)))
    )


def _team_count(location_id: int) -> int:
    return get_session().scalar(select(func.count()).select_from(Team).where(Team.location_id == location_id)) or 0


def _render_regions(
    errors: list[str], status: int, form: dict | None = None, dialog: str | None = None, edit_id: int | None = None
):
    """The Regions table. ``dialog`` ("add" or "edit") names the dialog rendered open, showing ``form`` (the typed
    values) and ``errors`` beside its fields; ``edit_id`` is the region the Edit dialog saves. Without a dialog the
    errors show above the table."""
    db = get_session()
    regions = db.scalars(select(Region).order_by(func.lower(Region.code), Region.id)).all()
    locations = dict(db.execute(select(Location.region_id, func.count()).group_by(Location.region_id)).all())
    teams = dict(
        db.execute(
            select(Location.region_id, func.count(Team.id))
            .join(Location, Team.location_id == Location.id)
            .group_by(Location.region_id)
        ).all()
    )
    trackers = dict(db.execute(select(TrackerRegion.region_id, func.count()).group_by(TrackerRegion.region_id)).all())
    editing = db.get(Region, edit_id) if dialog == "edit" else None
    field_errors: dict[str, list[str]] = {}
    if dialog:
        for error in errors:
            field_errors.setdefault("code" if error in REGION_CODE_ERRORS else "name", []).append(error)
    page = render_template(
        "lists/regions.html",
        regions=regions,
        location_counts=locations,
        team_counts=teams,
        tracker_counts=trackers,
        dialog=dialog,
        editing=editing,
        form=form or {},
        errors=errors,
        field_errors=field_errors,
        page_title="Regions",
        current_page="regions",
    )
    return page, status


def _to_regions(anchor: str | None = None):
    return redirect(url_for("lists.regions", _anchor=anchor))


@bp.get("/regions")
@manage_lists_required
def regions():
    return _render_regions([], 200)


@bp.get("/regions/new")
@manage_lists_required
def new_region():
    return _render_regions([], 200, dialog="add")


@bp.get("/regions/<int:region_id>/edit")
@manage_lists_required
def edit_region(region_id: int):
    region = _or_404(Region, region_id)
    return _render_regions([], 200, {"code": region.code, "name": region.name}, "edit", region.id)


@bp.post("/regions")
@manage_lists_required
def create_region():
    db = get_session()
    submitted = _region_form()
    errors = _region_errors(submitted["code"], submitted["name"])
    if errors:
        return _render_regions(errors, 400, submitted, "add")
    region = Region(**submitted)
    db.add(region)
    try:
        db.flush()
        _log(action="region_created", entity="region", entity_id=region.id, detail={"region": region.code})
        db.commit()
    except IntegrityError:  # the same short name or name was taken at the same moment
        db.rollback()
        errors = _region_errors(submitted["code"], submitted["name"]) or [REGION_CODE_TAKEN]
        return _render_regions(errors, 400, submitted, "add")
    flash(f"Added the region {region.code}.", "success")
    return _to_regions(f"region-{region.id}")


@bp.post("/regions/<int:region_id>")
@manage_lists_required
def update_region(region_id: int):
    region = _or_404(Region, region_id)
    db = get_session()
    action = _action()
    code = region.code
    if action == "delete":
        if _region_in_use(region.id):
            return _render_regions([REGION_IN_USE], 400)
        _log(action="region_deleted", entity="region", entity_id=region.id, detail={"region": code})
        db.delete(region)
        try:
            db.commit()
        except IntegrityError:  # a location or tracker took it up at the same moment
            db.rollback()
            return _render_regions([REGION_IN_USE], 400)
        flash(f"Deleted the region {code}.", "success")
        return _to_regions()
    if action in ("retire", "restore"):
        _set_retired(region, action, "region", code, "region", {"region": code})
        return _to_regions(f"region-{region.id}")
    submitted = _region_form()
    errors = _region_errors(submitted["code"], submitted["name"], region.id)
    if errors:
        return _render_regions(errors, 400, submitted, "edit", region.id)
    before, after = _changed(region, submitted)
    if not before:
        flash(NO_CHANGES_MESSAGE, "info")
        return _to_regions(f"region-{region.id}")
    for field, value in after.items():
        setattr(region, field, value)
    _log(
        action="region_changed", entity="region", entity_id=region.id, detail={"region": code, **change(before, after)}
    )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        errors = _region_errors(submitted["code"], submitted["name"], region.id) or [REGION_CODE_TAKEN]
        return _render_regions(errors, 400, submitted, "edit", region.id)
    flash(f"Saved the region {region.code}.", "success")
    return _to_regions(f"region-{region.id}")


@bp.post("/regions/<int:region_id>/locations")
@manage_lists_required
def create_location(region_id: int):
    region = _or_404(Region, region_id)
    db = get_session()
    submitted = _location_form()
    errors, country_code = _location_errors(submitted["code"], submitted["city"], submitted["country_code"])
    if errors:
        return _render_regions(errors, 400)
    location = Location(region_id=region.id, code=submitted["code"], city=submitted["city"], country_code=country_code)
    db.add(location)
    label = location_label(location.city, location.country_code)
    try:
        db.flush()
        _log(
            action="location_created",
            entity="location",
            entity_id=location.id,
            detail={"location": label, "code": location.code, "region": region.code},
        )
        db.commit()
    except IntegrityError:  # the same city and country were added at the same moment
        db.rollback()
        errors = _location_errors(submitted["code"], submitted["city"], submitted["country_code"])[0] or [
            LOCATION_TAKEN
        ]
        return _render_regions(errors, 400)
    flash(f"Added the location {label} to {region.code}.", "success")
    return _to_regions(f"region-{region.id}")


def _parse_region(text: str | None, current_id: int) -> Region | None:
    """The chosen region: an active one, or the location's current one even when retired."""
    region_id = parse_id(text)
    region = get_session().get(Region, region_id) if region_id is not None else None
    if region is None or (region.retired and region.id != current_id):
        return None
    return region


@bp.post("/locations/<int:location_id>")
@manage_lists_required
def update_location(location_id: int):
    location = _or_404(Location, location_id)
    db = get_session()
    action = _action()
    region = db.get(Region, location.region_id)
    label = location_label(location.city, location.country_code)
    named = {"location": label, "region": region.code}
    if action == "delete":
        if _team_count(location.id):
            return _render_regions([LOCATION_IN_USE], 400)
        _log(action="location_deleted", entity="location", entity_id=location.id, detail=named)
        db.delete(location)
        try:
            db.commit()
        except IntegrityError:  # a team was placed there at the same moment
            db.rollback()
            return _render_regions([LOCATION_IN_USE], 400)
        flash(f"Deleted the location {label}.", "success")
        return _to_regions(f"region-{region.id}")
    if action in ("retire", "restore"):
        _set_retired(location, action, "location", label, "location", named)
        return _to_regions(f"location-{location.id}")
    submitted = _location_form()
    submitted_region = request.form.get("region_id", "").strip()
    anchor = f"location-{location.id}"
    errors, country_code = _location_errors(
        submitted["code"], submitted["city"], submitted["country_code"], location.id
    )
    new_region = _parse_region(submitted_region, location.region_id)
    if new_region is None:
        errors.append(REGION_CHOICE_ERROR)
    if errors:
        return _render_regions(errors, 400)
    before, after = _changed(location, {"code": submitted["code"], "city": submitted["city"]})
    if location.country_code != country_code:
        before["country"], after["country"] = country_name(location.country_code), country_name(country_code)
    if new_region.id != region.id:
        before["region"], after["region"] = region.code, new_region.code
    if not before:
        flash(NO_CHANGES_MESSAGE, "info")
        return _to_regions(anchor)
    detail = {"location": label, **change(before, after)}
    if "region" in before:
        detail["teams"] = _team_count(location.id)
    location.code, location.city, location.country_code = submitted["code"], submitted["city"], country_code
    location.region_id = new_region.id
    _log(action="location_changed", entity="location", entity_id=location.id, detail=detail)
    try:
        db.commit()
    except IntegrityError:  # the same code, or city and country, were saved at the same moment
        db.rollback()
        errors = _location_errors(submitted["code"], submitted["city"], submitted["country_code"], location.id)[0]
        return _render_regions(errors or [LOCATION_TAKEN], 400)
    flash(f"Saved the location {location_label(location.city, location.country_code)}.", "success")
    return _to_regions(anchor)


# --- Business lines -------------------------------------------------------------------------------------------------


def _line_error(name: str, exclude_id: int | None = None) -> str | None:
    return name_error(get_session(), BusinessLine, name, "business line", exclude_id)


def _render_business_lines(errors: list[str], status: int, form: dict | None = None, editing: str = ""):
    db = get_session()
    lines = db.scalars(select(BusinessLine).order_by(func.lower(BusinessLine.name), BusinessLine.id)).all()
    trackers = dict(
        db.execute(
            select(Tracker.business_line_id, func.count())
            .where(Tracker.business_line_id.is_not(None))
            .group_by(Tracker.business_line_id)
        ).all()
    )
    page = render_template(
        "lists/business_lines.html",
        lines=lines,
        tracker_counts=trackers,
        business_line_in_use=BUSINESS_LINE_IN_USE,
        form=form or {},
        editing=editing,
        errors=errors,
        page_title="Business lines",
        current_page="business_lines",
    )
    return page, status


def _to_business_lines(anchor: str | None = None):
    return redirect(url_for("lists.business_lines", _anchor=anchor))


@bp.get("/business-lines")
@manage_lists_required
def business_lines():
    return _render_business_lines([], 200)


@bp.post("/business-lines")
@manage_lists_required
def create_business_line():
    db = get_session()
    name = request.form.get("name", "").strip()
    error = _line_error(name)
    if error:
        return _render_business_lines([error], 400, {"name": name}, "new-line")
    line = BusinessLine(name=name)
    db.add(line)
    try:
        db.flush()
        _log(action="business_line_created", entity="business_line", entity_id=line.id, detail={"business_line": name})
        db.commit()
    except IntegrityError:  # the same name was taken at the same moment
        db.rollback()
        error = _line_error(name) or "A business line with that name already exists."
        return _render_business_lines([error], 400, {"name": name}, "new-line")
    flash(f"Added the business line {name}.", "success")
    return _to_business_lines(f"line-{line.id}")


@bp.post("/business-lines/<int:line_id>")
@manage_lists_required
def update_business_line(line_id: int):
    line = _or_404(BusinessLine, line_id)
    db = get_session()
    action = _action()
    name = line.name
    named = {"business_line": name}
    editing = f"line-{line.id}"
    if action == "delete":
        if db.scalar(select(exists().where(Tracker.business_line_id == line.id))):
            return _render_business_lines([BUSINESS_LINE_IN_USE], 400)
        _log(action="business_line_deleted", entity="business_line", entity_id=line.id, detail=named)
        db.delete(line)
        try:
            db.commit()
        except IntegrityError:  # a tracker took it up at the same moment
            db.rollback()
            return _render_business_lines([BUSINESS_LINE_IN_USE], 400)
        flash(f"Deleted the business line {name}.", "success")
        return _to_business_lines()
    if action in ("retire", "restore"):
        _set_retired(line, action, "business line", name, "business_line", named)
        return _to_business_lines(editing)
    submitted = {"name": request.form.get("name", "").strip()}
    error = _line_error(submitted["name"], line.id)
    if error:
        return _render_business_lines([error], 400, submitted, editing)
    before, after = _changed(line, submitted)
    if not before:
        flash(NO_CHANGES_MESSAGE, "info")
        return _to_business_lines(editing)
    line.name = submitted["name"]
    _log(
        action="business_line_changed",
        entity="business_line",
        entity_id=line.id,
        detail={**named, **change(before, after)},
    )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        error = _line_error(submitted["name"], line.id) or "A business line with that name already exists."
        return _render_business_lines([error], 400, submitted, editing)
    flash(f"Saved the business line {line.name}.", "success")
    return _to_business_lines(editing)
