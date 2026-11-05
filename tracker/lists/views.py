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
from ..models import BusinessLine, Location, Region, RegionGrant, Team, Tracker, TrackerRegion
from ..naming import MAX_NAME_LENGTH, name_error
from . import bp
from .catalogue import REGION_CHOICE_ERROR, location_label
from .countries import COUNTRIES, country_name, flag_path, parse_country

manage_lists_required = admin_required

MAX_CODE_LENGTH = 20
REGION_CODE_REQUIRED = "Enter a region code."
REGION_CODE_TOO_LONG = f"A region code can be at most {MAX_CODE_LENGTH} characters."
REGION_CODE_TAKEN = "A region with that code already exists."
LOCATION_CODE_REQUIRED = "Enter a location code."
LOCATION_CODE_FORMAT = "A location code is 2 to 6 letters, such as LON."
LOCATION_CODE_TAKEN = "A location with that code already exists."
LOCATION_TAKEN = "A location with that name and country already exists."
REGION_IN_USE = "This region has locations, teams, trackers or people with access, so it can only be retired."
LOCATION_IN_USE = "Teams use this location, so it can only be retired."
TEAM_NOTE_ONE = "Used by 1 team. Changing the region moves the team with it."
TEAM_NOTE_MANY = "Used by {n} teams. Changing the region moves them to it."  # lists.js fills in {n} too
BUSINESS_LINE_TAKEN = "A business line with that name already exists."
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

# Errors for a submitted entry, by field ("code", "name", ...), in the order the fields appear; only fields with errors.
FieldErrors = dict[str, list[str]]


def _summary(errors: FieldErrors) -> list[str]:
    """Every message, field by field, for the list at the top of the dialog."""
    return [message for messages in errors.values() for message in messages]


def _region_errors(code: str, name: str, exclude_id: int | None = None) -> FieldErrors:
    db = get_session()
    if not code:
        code_error = REGION_CODE_REQUIRED
    elif len(code) > MAX_CODE_LENGTH:
        code_error = REGION_CODE_TOO_LONG
    else:
        code_error = REGION_CODE_TAKEN if name_error(db, Region, code, "region", exclude_id, Region.code) else None
    found = {"code": code_error, "name": name_error(db, Region, name, "region", exclude_id)}
    return {field: [error] for field, error in found.items() if error}


def _location_errors(
    code: str, city: str, country_text: str, exclude_id: int | None = None
) -> tuple[FieldErrors, str | None]:
    """The errors for a submitted location by field ("code", "city", "country_code"), and the parsed country code
    (None when it is not a listed one). A city and country already used shows beside the city."""
    db = get_session()
    errors: FieldErrors = {}
    if not code:
        errors["code"] = [LOCATION_CODE_REQUIRED]
    elif not re.fullmatch(r"[A-Z]{2,6}", code):
        errors["code"] = [LOCATION_CODE_FORMAT]
    else:
        query = select(Location.id).where(func.lower(Location.code) == code.lower())
        if exclude_id is not None:
            query = query.where(Location.id != exclude_id)
        if db.scalar(query.limit(1)) is not None:
            errors["code"] = [LOCATION_CODE_TAKEN]
    city_error = _text_error(city, "location name")
    if city_error:
        errors["city"] = [city_error]
    country_code, country_error = parse_country(country_text)
    if country_error:
        errors["country_code"] = [country_error]
    if city_error is None and country_code is not None:
        query = select(Location.id).where(
            func.lower(Location.city) == city.lower(), Location.country_code == country_code
        )
        if exclude_id is not None:
            query = query.where(Location.id != exclude_id)
        if db.scalar(query.limit(1)) is not None:
            errors["city"] = [LOCATION_TAKEN]
    return errors, country_code


def _tab_counts() -> dict[str, int]:
    """The number of entries, retired ones included, for each tab of the tab bar."""
    db = get_session()
    return {
        key: db.scalar(select(func.count()).select_from(model)) or 0
        for key, model in (("regions", Region), ("locations", Location), ("business_lines", BusinessLine))
    }


def _region_form() -> dict:
    return {"code": request.form.get("code", "").strip(), "name": request.form.get("name", "").strip()}


def _location_form() -> dict:
    return {
        "region_id": request.form.get("region_id", "").strip(),
        "code": request.form.get("code", "").strip().upper(),
        "city": request.form.get("city", "").strip(),
        "country_code": request.form.get("country_code", "").strip().upper(),
    }


def _region_in_use(region_id: int) -> bool:
    db = get_session()
    return bool(
        db.scalar(select(exists().where(Location.region_id == region_id)))
        or db.scalar(select(exists().where(Team.region_id == region_id)))
        or db.scalar(select(exists().where(TrackerRegion.region_id == region_id)))
        or db.scalar(select(exists().where(RegionGrant.region_id == region_id)))
    )


def _team_count(location_id: int) -> int:
    return get_session().scalar(select(func.count()).select_from(Team).where(Team.location_id == location_id)) or 0


def _render_regions(
    status: int,
    *,
    page_errors: list[str] | None = None,
    field_errors: FieldErrors | None = None,
    form: dict | None = None,
    dialog: str | None = None,
    edit_id: int | None = None,
):
    """The Regions table. ``page_errors`` show above the table. ``dialog`` ("add" or "edit") names the dialog rendered
    open, showing ``form`` (the typed values) and ``field_errors`` beside its fields; ``edit_id`` is the region the
    Edit dialog saves."""
    db = get_session()
    regions = db.scalars(select(Region).order_by(func.lower(Region.code), Region.id)).all()
    locations = dict(db.execute(select(Location.region_id, func.count()).group_by(Location.region_id)).all())
    teams = dict(db.execute(select(Team.region_id, func.count()).group_by(Team.region_id)).all())
    trackers = dict(db.execute(select(TrackerRegion.region_id, func.count()).group_by(TrackerRegion.region_id)).all())
    people = dict(db.execute(select(RegionGrant.region_id, func.count()).group_by(RegionGrant.region_id)).all())
    editing = db.get(Region, edit_id) if dialog == "edit" else None
    page = render_template(
        "lists/regions.html",
        regions=regions,
        location_counts=locations,
        team_counts=teams,
        tracker_counts=trackers,
        people_counts=people,
        region_in_use=REGION_IN_USE,
        dialog=dialog,
        editing=editing,
        form=form or {},
        page_errors=page_errors or [],
        dialog_errors=_summary(field_errors or {}),
        field_errors=field_errors or {},
        page_title="Regions",
        current_page="lists",
        tab_counts=_tab_counts(),
    )
    return page, status


def _to_regions(anchor: str | None = None):
    return redirect(url_for("lists.regions", _anchor=anchor))


@bp.get("/regions")
@manage_lists_required
def regions():
    return _render_regions(200)


@bp.get("/regions/new")
@manage_lists_required
def new_region():
    return _render_regions(200, dialog="add")


@bp.get("/regions/<int:region_id>/edit")
@manage_lists_required
def edit_region(region_id: int):
    region = _or_404(Region, region_id)
    return _render_regions(200, form={"code": region.code, "name": region.name}, dialog="edit", edit_id=region.id)


@bp.post("/regions")
@manage_lists_required
def create_region():
    db = get_session()
    submitted = _region_form()
    errors = _region_errors(submitted["code"], submitted["name"])
    if errors:
        return _render_regions(400, field_errors=errors, form=submitted, dialog="add")
    region = Region(**submitted)
    db.add(region)
    try:
        db.flush()
        _log(action="region_created", entity="region", entity_id=region.id, detail={"region": region.code})
        db.commit()
    except IntegrityError:  # the same code or name was taken at the same moment
        db.rollback()
        errors = _region_errors(submitted["code"], submitted["name"]) or {"code": [REGION_CODE_TAKEN]}
        return _render_regions(400, field_errors=errors, form=submitted, dialog="add")
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
            return _render_regions(400, page_errors=[REGION_IN_USE])
        _log(action="region_deleted", entity="region", entity_id=region.id, detail={"region": code})
        db.delete(region)
        try:
            db.commit()
        except IntegrityError:  # a location, team, tracker or grant took it up at the same moment
            db.rollback()
            return _render_regions(400, page_errors=[REGION_IN_USE])
        flash(f"Deleted the region {code}.", "success")
        return _to_regions()
    if action in ("retire", "restore"):
        _set_retired(region, action, "region", code, "region", {"region": code})
        return _to_regions(f"region-{region.id}")
    submitted = _region_form()
    errors = _region_errors(submitted["code"], submitted["name"], region.id)
    if errors:
        return _render_regions(400, field_errors=errors, form=submitted, dialog="edit", edit_id=region.id)
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
        errors = _region_errors(submitted["code"], submitted["name"], region.id) or {"code": [REGION_CODE_TAKEN]}
        return _render_regions(400, field_errors=errors, form=submitted, dialog="edit", edit_id=region.id)
    flash(f"Saved the region {region.code}.", "success")
    return _to_regions(f"region-{region.id}")


def _parse_region(text: str | None, current_id: int | None = None) -> Region | None:
    """The chosen region: an active one, or the location's current one (``current_id``) even when retired."""
    region_id = parse_id(text)
    region = get_session().get(Region, region_id) if region_id is not None else None
    if region is None or (region.retired and region.id != current_id):
        return None
    return region


def _render_locations(
    status: int,
    *,
    page_errors: list[str] | None = None,
    field_errors: FieldErrors | None = None,
    form: dict | None = None,
    dialog: str | None = None,
    edit_id: int | None = None,
):
    """The Locations table, ordered by region code and then city. The arguments work as for
    :func:`_render_regions`."""
    db = get_session()
    regions = db.scalars(select(Region).order_by(func.lower(Region.code), Region.id)).all()
    locations = db.scalars(
        select(Location)
        .join(Region, Location.region_id == Region.id)
        .order_by(func.lower(Region.code), Region.id, func.lower(Location.city), Location.id)
    ).all()
    teams = dict(
        db.execute(
            select(Team.location_id, func.count()).where(Team.location_id.is_not(None)).group_by(Team.location_id)
        ).all()
    )
    editing = db.get(Location, edit_id) if dialog == "edit" else None
    # (region, held back) pairs. The Edit dialog lists every retired region, held back (hidden and disabled) for
    # lists.js to offer to that region's own locations only; when the server fills it, the location's own retired
    # region is offered.
    own_region = editing.region_id if editing is not None else None
    edit_regions = [(r, r.retired and r.id != own_region) for r in regions]
    used = teams.get(editing.id, 0) if editing is not None else 0
    note = TEAM_NOTE_ONE if used == 1 else TEAM_NOTE_MANY.replace("{n}", str(used)) if used > 1 else ""
    page = render_template(
        "lists/locations.html",
        regions=regions,
        add_regions=[(r, False) for r in regions if not r.retired],
        edit_regions=edit_regions,
        edit_note_text=note,
        note_one=TEAM_NOTE_ONE,
        note_many=TEAM_NOTE_MANY,
        regions_by_id={region.id: region for region in regions},
        locations=locations,
        team_counts=teams,
        location_in_use=LOCATION_IN_USE,
        chosen_region=request.args.get("region", ""),
        countries=COUNTRIES,
        country_name=country_name,
        flag_path=flag_path,
        location_label=location_label,
        dialog=dialog,
        editing=editing,
        form=form or {},
        page_errors=page_errors or [],
        dialog_errors=_summary(field_errors or {}),
        field_errors=field_errors or {},
        page_title="Locations",
        current_page="lists",
        tab_counts=_tab_counts(),
    )
    return page, status


def _to_locations(anchor: str | None = None):
    return redirect(url_for("lists.locations", _anchor=anchor))


def _location_values(location: Location) -> dict:
    return {
        "region_id": str(location.region_id),
        "code": location.code or "",
        "city": location.city,
        "country_code": location.country_code or "",
    }


@bp.get("/locations")
@manage_lists_required
def locations():
    return _render_locations(200)


@bp.get("/locations/new")
@manage_lists_required
def new_location():
    return _render_locations(200, dialog="add")


@bp.get("/locations/<int:location_id>/edit")
@manage_lists_required
def edit_location(location_id: int):
    location = _or_404(Location, location_id)
    return _render_locations(200, form=_location_values(location), dialog="edit", edit_id=location.id)


@bp.post("/locations")
@manage_lists_required
def create_location():
    db = get_session()
    submitted = _location_form()
    region = _parse_region(submitted["region_id"])
    errors: FieldErrors = {} if region else {"region_id": [REGION_CHOICE_ERROR]}
    found, country_code = _location_errors(submitted["code"], submitted["city"], submitted["country_code"])
    errors.update(found)
    if errors:
        return _render_locations(400, field_errors=errors, form=submitted, dialog="add")
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
    except IntegrityError:  # the same code, or city and country, were added at the same moment
        db.rollback()
        errors = _location_errors(submitted["code"], submitted["city"], submitted["country_code"])[0]
        return _render_locations(400, field_errors=errors or {"city": [LOCATION_TAKEN]}, form=submitted, dialog="add")
    flash(f"Added the location {label} to {region.code}.", "success")
    return _to_locations(f"location-{location.id}")


@bp.post("/locations/<int:location_id>")
@manage_lists_required
def update_location(location_id: int):
    location = _or_404(Location, location_id)
    db = get_session()
    action = _action()
    region = db.get(Region, location.region_id)
    label = location_label(location.city, location.country_code)
    named = {"location": label, "region": region.code}
    anchor = f"location-{location.id}"
    if action == "delete":
        if _team_count(location.id):
            return _render_locations(400, page_errors=[LOCATION_IN_USE])
        _log(action="location_deleted", entity="location", entity_id=location.id, detail=named)
        db.delete(location)
        try:
            db.commit()
        except IntegrityError:  # a team was placed there at the same moment
            db.rollback()
            return _render_locations(400, page_errors=[LOCATION_IN_USE])
        flash(f"Deleted the location {label}.", "success")
        return _to_locations()
    if action in ("retire", "restore"):
        _set_retired(location, action, "location", label, "location", named)
        return _to_locations(anchor)
    submitted = _location_form()
    new_region = _parse_region(submitted["region_id"], location.region_id)
    errors: FieldErrors = {} if new_region else {"region_id": [REGION_CHOICE_ERROR]}
    found, country_code = _location_errors(submitted["code"], submitted["city"], submitted["country_code"], location.id)
    errors.update(found)
    if errors:
        return _render_locations(400, field_errors=errors, form=submitted, dialog="edit", edit_id=location.id)
    before, after = _changed(location, {"code": submitted["code"], "city": submitted["city"]})
    if location.country_code != country_code:
        before["country"], after["country"] = country_name(location.country_code), country_name(country_code)
    if new_region.id != region.id:
        before["region"], after["region"] = region.code, new_region.code
    if not before:
        flash(NO_CHANGES_MESSAGE, "info")
        return _to_locations(anchor)
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
        return _render_locations(
            400, field_errors=errors or {"city": [LOCATION_TAKEN]}, form=submitted, dialog="edit", edit_id=location.id
        )
    flash(f"Saved the location {location_label(location.city, location.country_code)}.", "success")
    return _to_locations(anchor)


# --- Business lines -------------------------------------------------------------------------------------------------


def _line_error(name: str, exclude_id: int | None = None) -> str | None:
    return name_error(get_session(), BusinessLine, name, "business line", exclude_id)


def _render_business_lines(
    status: int,
    *,
    page_errors: list[str] | None = None,
    field_errors: FieldErrors | None = None,
    form: dict | None = None,
    dialog: str | None = None,
    edit_id: int | None = None,
):
    """The Business lines table. The arguments work as for :func:`_render_regions`."""
    db = get_session()
    lines = db.scalars(select(BusinessLine).order_by(func.lower(BusinessLine.name), BusinessLine.id)).all()
    trackers = dict(
        db.execute(
            select(Tracker.business_line_id, func.count())
            .where(Tracker.business_line_id.is_not(None))
            .group_by(Tracker.business_line_id)
        ).all()
    )
    editing = db.get(BusinessLine, edit_id) if dialog == "edit" else None
    page = render_template(
        "lists/business_lines.html",
        lines=lines,
        tracker_counts=trackers,
        business_line_in_use=BUSINESS_LINE_IN_USE,
        dialog=dialog,
        editing=editing,
        form=form or {},
        page_errors=page_errors or [],
        dialog_errors=_summary(field_errors or {}),
        field_errors=field_errors or {},
        page_title="Business lines",
        current_page="lists",
        tab_counts=_tab_counts(),
    )
    return page, status


def _to_business_lines(anchor: str | None = None):
    return redirect(url_for("lists.business_lines", _anchor=anchor))


@bp.get("/business-lines")
@manage_lists_required
def business_lines():
    return _render_business_lines(200)


@bp.get("/business-lines/new")
@manage_lists_required
def new_business_line():
    return _render_business_lines(200, dialog="add")


@bp.get("/business-lines/<int:line_id>/edit")
@manage_lists_required
def edit_business_line(line_id: int):
    line = _or_404(BusinessLine, line_id)
    return _render_business_lines(200, form={"name": line.name}, dialog="edit", edit_id=line.id)


@bp.post("/business-lines")
@manage_lists_required
def create_business_line():
    db = get_session()
    name = request.form.get("name", "").strip()
    error = _line_error(name)
    if error:
        return _render_business_lines(400, field_errors={"name": [error]}, form={"name": name}, dialog="add")
    line = BusinessLine(name=name)
    db.add(line)
    try:
        db.flush()
        _log(action="business_line_created", entity="business_line", entity_id=line.id, detail={"business_line": name})
        db.commit()
    except IntegrityError:  # the same name was taken at the same moment
        db.rollback()
        error = _line_error(name) or BUSINESS_LINE_TAKEN
        return _render_business_lines(400, field_errors={"name": [error]}, form={"name": name}, dialog="add")
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
    anchor = f"line-{line.id}"
    if action == "delete":
        if db.scalar(select(exists().where(Tracker.business_line_id == line.id))):
            return _render_business_lines(400, page_errors=[BUSINESS_LINE_IN_USE])
        _log(action="business_line_deleted", entity="business_line", entity_id=line.id, detail=named)
        db.delete(line)
        try:
            db.commit()
        except IntegrityError:  # a tracker took it up at the same moment
            db.rollback()
            return _render_business_lines(400, page_errors=[BUSINESS_LINE_IN_USE])
        flash(f"Deleted the business line {name}.", "success")
        return _to_business_lines()
    if action in ("retire", "restore"):
        _set_retired(line, action, "business line", name, "business_line", named)
        return _to_business_lines(anchor)
    submitted = {"name": request.form.get("name", "").strip()}
    error = _line_error(submitted["name"], line.id)
    if error:
        return _render_business_lines(
            400, field_errors={"name": [error]}, form=submitted, dialog="edit", edit_id=line.id
        )
    before, after = _changed(line, submitted)
    if not before:
        flash(NO_CHANGES_MESSAGE, "info")
        return _to_business_lines(anchor)
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
        error = _line_error(submitted["name"], line.id) or BUSINESS_LINE_TAKEN
        return _render_business_lines(
            400, field_errors={"name": [error]}, form=submitted, dialog="edit", edit_id=line.id
        )
    flash(f"Saved the business line {line.name}.", "success")
    return _to_business_lines(anchor)
