"""Reading and checking the administered lists: regions, locations and business lines.

No Flask imports. Retired entries stay on the records that already use them but cannot be chosen anew, so every
chooser takes the id (or ids) already in use and keeps those entries visible.
"""

from __future__ import annotations

from collections.abc import Collection
from typing import NamedTuple

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from ..ids import parse_id
from ..models import BusinessLine, Location, Region, Team, Tracker, TrackerRegion
from .countries import country_name

REGION_REQUIRED = "Choose a region."
REGION_CHOICE_ERROR = "Choose a region from the list."
LOCATION_CHOICE_ERROR = "Choose a location from the list."
LOCATION_REGION_MISMATCH = "The location is not in the chosen region."
BUSINESS_LINE_REQUIRED = "Choose a business line."
BUSINESS_LINE_CHOICE_ERROR = "Choose a business line from the list."
REGIONS_REQUIRED = "Tick at least one region."
REGIONS_CHOICE_ERROR = "Choose regions from the list."


def location_label(city: str, country_code: str | None) -> str:
    """ "Geneva, Switzerland", or just the city while the country is unset."""
    country = country_name(country_code)
    return f"{city}, {country}" if country else city


class Place(NamedTuple):
    region_id: int
    region_code: str
    location_id: int | None
    location: str | None  # "Geneva, Switzerland", or None for a team in a region without a location
    city: str | None


def team_places(session: Session) -> dict[int, Place]:
    """Team id to its place, for teams that have a region."""
    rows = session.execute(
        select(Team.id, Region.id, Region.code, Location.id, Location.city, Location.country_code)
        .join(Region, Team.region_id == Region.id)
        .outerjoin(Location, Team.location_id == Location.id)
    )
    return {
        team_id: Place(region_id, code, location_id, location_label(city, country_code) if location_id else None, city)
        for team_id, region_id, code, location_id, city, country_code in rows
    }


class RegionOption(NamedTuple):
    id: int
    code: str
    name: str
    retired: bool
    locations: list[tuple[int, str, bool]]


def location_choices(
    session: Session, keep_region_id: int | None = None, keep_location_id: int | None = None
) -> list[RegionOption]:
    """Every region with its locations, for a team's place. Retired regions and locations appear only where the team
    already uses them (``keep_region_id``, ``keep_location_id``)."""
    options: dict[int, RegionOption] = {}
    for region in session.scalars(select(Region).order_by(func.lower(Region.code), Region.id)):
        options[region.id] = RegionOption(region.id, region.code, region.name, region.retired, [])
    locations = session.scalars(
        select(Location).order_by(func.lower(Location.city), Location.country_code, Location.id)
    )
    for location in locations:
        region = options[location.region_id]
        if location.id != keep_location_id and (location.retired or region.retired):
            continue
        region.locations.append(
            (location.id, location_label(location.city, location.country_code), location.retired or region.retired)
        )
    # Labels sort as "city, country", so order the result by label rather than by city alone.
    for region in options.values():
        region.locations.sort(key=lambda item: item[1].lower())
    return [r for r in options.values() if not r.retired or r.id == keep_region_id or r.locations]


def region_choices(session: Session, keep_ids: Collection[int] = ()) -> list[RegionOption]:
    """Regions without locations; retired ones only when in ``keep_ids``."""
    regions = session.scalars(select(Region).order_by(func.lower(Region.code), Region.id))
    return [RegionOption(r.id, r.code, r.name, r.retired, []) for r in regions if not r.retired or r.id in keep_ids]


def business_line_choices(session: Session, keep_id: int | None = None) -> list[tuple[int, str, bool]]:
    lines = session.scalars(select(BusinessLine).order_by(func.lower(BusinessLine.name), BusinessLine.id))
    return [(b.id, b.name, b.retired) for b in lines if not b.retired or b.id == keep_id]


def parse_place(
    session: Session,
    region_text: str | None,
    location_text: str | None,
    current_region_id: int | None,
    current_location_id: int | None,
) -> tuple[Region | None, Location | None, str | None]:
    """A team's region (required) and location (optional, in that region): ``(region, location, error)``."""
    region_text, location_text = (region_text or "").strip(), (location_text or "").strip()
    if not region_text:
        return None, None, REGION_REQUIRED
    region_id = parse_id(region_text)
    region = session.get(Region, region_id) if region_id is not None else None
    if region is None or (region.retired and region.id != current_region_id):
        return None, None, REGION_CHOICE_ERROR
    if not location_text:
        return region, None, None
    location_id = parse_id(location_text)
    location = session.get(Location, location_id) if location_id is not None else None
    if location is None:
        return None, None, LOCATION_CHOICE_ERROR
    if location.id != current_location_id:
        location_region = session.get(Region, location.region_id)
        if location.retired or location_region is None or location_region.retired:
            return None, None, LOCATION_CHOICE_ERROR
    if region.id != location.region_id:
        return None, None, LOCATION_REGION_MISMATCH
    return region, location, None


def parse_business_line(
    session: Session, text: str | None, current_id: int | None
) -> tuple[BusinessLine | None, str | None]:
    text = (text or "").strip()
    if not text:
        return None, BUSINESS_LINE_REQUIRED
    line_id = parse_id(text)
    line = session.get(BusinessLine, line_id) if line_id is not None else None
    if line is None or (line.retired and line.id != current_id):
        return None, BUSINESS_LINE_CHOICE_ERROR
    return line, None


def parse_regions(session: Session, texts: list[str], current_ids: Collection[int]) -> tuple[list[Region], str | None]:
    if not texts:
        return [], REGIONS_REQUIRED
    ids: set[int] = set()
    for text in texts:
        region_id = parse_id(text)
        if region_id is None:
            return [], REGIONS_CHOICE_ERROR
        ids.add(region_id)
    regions = list(
        session.scalars(select(Region).where(Region.id.in_(ids)).order_by(func.lower(Region.code), Region.id))
    )
    if len(regions) != len(ids) or any(r.retired and r.id not in current_ids for r in regions):
        return [], REGIONS_CHOICE_ERROR
    return regions, None


class TrackerLabels(NamedTuple):
    business_line: str | None
    regions: list[str]


def tracker_labels(session: Session, tracker_ids: Collection[int]) -> dict[int, TrackerLabels]:
    labels = {tracker_id: TrackerLabels(None, []) for tracker_id in tracker_ids}
    if not labels:
        return labels
    lines = session.execute(
        select(Tracker.id, BusinessLine.name)
        .join(BusinessLine, Tracker.business_line_id == BusinessLine.id)
        .where(Tracker.id.in_(labels))
    )
    for tracker_id, name in lines:
        labels[tracker_id] = TrackerLabels(name, [])
    regions = session.execute(
        select(TrackerRegion.tracker_id, Region.code)
        .join(Region, TrackerRegion.region_id == Region.id)
        .where(TrackerRegion.tracker_id.in_(labels))
        .order_by(func.lower(Region.code), Region.id)
    )
    for tracker_id, code in regions:
        labels[tracker_id].regions.append(code)
    return labels


def tracker_region_ids(session: Session, tracker_id: int) -> set[int]:
    return set(session.scalars(select(TrackerRegion.region_id).where(TrackerRegion.tracker_id == tracker_id)))


def set_tracker_regions(session: Session, tracker_id: int, region_ids: Collection[int]) -> None:
    """Replace the tracker's regions; the caller commits."""
    session.execute(delete(TrackerRegion).where(TrackerRegion.tracker_id == tracker_id))
    session.add_all(TrackerRegion(tracker_id=tracker_id, region_id=region_id) for region_id in set(region_ids))
