"""The Access screen of a region (administrators only): who has been given access to the region, and at which role.

A grant reaches every tracker that covers the region (``tracker.auth.roles``). Giving, changing and removing a grant
each commit with their activity entry in one transaction; the grant is keyed by region and person, so a grant given
at the same moment by someone else is refused on commit.
"""

from __future__ import annotations

from flask import abort, flash, redirect, render_template, request, url_for
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError

from ..audit import NO_CHANGES_MESSAGE, change, record
from ..auth import admin_required, current_user
from ..auth.roles import ROLES
from ..db import get_session
from ..ids import in_range, parse_id
from ..models import Region, RegionGrant, User
from . import bp
from .views import _or_404, _tab_counts

# If this becomes a permission, giving access must add add_member's self-escalation checks (vouched_refusal,
# raises_own_access).
manage_region_access_required = admin_required

CHOOSE_PERSON = "Choose an active person from the list."
CHOOSE_ROLE = "Choose a role from the list."
CHOOSE_ACTION = "Choose an action."
ALREADY_HAS_ACCESS = "That person already has access to this region."
RETIRED_NO_NEW_ACCESS = "This region is retired. Restore it before giving anyone new access."
REMOVE = "remove"  # the role value that removes a grant


def _render_access(region: Region, status: int = 200, errors: list[str] | None = None):
    db = get_session()
    held = db.execute(
        select(User, RegionGrant.role)
        .join(RegionGrant, RegionGrant.user_id == User.id)
        .where(RegionGrant.region_id == region.id)
        .order_by(func.lower(User.full_name), User.id)
    ).all()
    candidates = db.scalars(
        select(User)
        .where(
            User.status == "active",
            ~select(RegionGrant.user_id)
            .where(RegionGrant.region_id == region.id, RegionGrant.user_id == User.id)
            .exists(),
        )
        .order_by(func.lower(User.full_name), User.id)
    ).all()
    page = render_template(
        "lists/region_access.html",
        region=region,
        holders=held,
        candidates=candidates,
        roles=ROLES,
        errors=errors or [],
        page_title=f"Access to {region.code}",
        current_page="lists",
        tab_counts=_tab_counts(),
    )
    return page, status


def _to_access(region: Region):
    return redirect(url_for("lists.region_access", region_id=region.id))


def _log(region: Region, code: str, user: User, action: str, detail: dict) -> None:
    record(
        get_session(),
        user_id=current_user().id,
        tracker_id=None,
        action=action,
        entity="region",
        entity_id=region.id,
        detail={"region": code, **detail},
        target_user_id=user.id,
    )


@bp.get("/regions/<int:region_id>/access")
@manage_region_access_required
def region_access(region_id: int):
    return _render_access(_or_404(Region, region_id))


@bp.post("/regions/<int:region_id>/access")
@manage_region_access_required
def change_region_access(region_id: int):
    region = _or_404(Region, region_id)
    db = get_session()
    code = region.code  # read now, so that the entry names the region as it was
    action = request.form.get("action", "")
    if action not in ("give", "set"):
        return _render_access(region, 400, [CHOOSE_ACTION])
    role = request.form.get("role", "")
    if action == "give":
        return _give(region, code, role)
    user_id = parse_id(request.form.get("user_id"))
    grant = db.get(RegionGrant, (region.id, user_id)) if user_id and in_range(user_id) else None
    if grant is None:
        abort(404)
    user = db.get(User, user_id)
    if role == REMOVE:
        old = grant.role
        removed = db.execute(
            delete(RegionGrant).where(RegionGrant.region_id == region.id, RegionGrant.user_id == user.id)
        ).rowcount
        if not removed:  # removed by someone else at the same moment
            db.rollback()
            flash(f"{user.full_name} no longer has access to {code}.", "info")
            return _to_access(region)
        _log(region, code, user, "region_access_removed", {"role": old})
        db.commit()
        flash(f"Removed {user.full_name}'s access to {code}.", "success")
        return _to_access(region)
    if role not in ROLES:
        return _render_access(region, 400, [CHOOSE_ROLE])
    old = grant.role
    if role == old:
        flash(NO_CHANGES_MESSAGE, "info")
        return _to_access(region)
    grant.role = role
    _log(region, code, user, "region_access_changed", change(old, role))
    db.commit()
    flash(f"{user.full_name} now has {role.title()} access to {code}.", "success")
    return _to_access(region)


def _give(region: Region, code: str, role: str):
    db = get_session()
    user_id = parse_id(request.form.get("user_id"))
    user = db.get(User, user_id) if user_id and in_range(user_id) else None
    if user is None or user.status != "active":
        return _render_access(region, 400, [CHOOSE_PERSON])
    if role not in ROLES:
        return _render_access(region, 400, [CHOOSE_ROLE])
    if region.retired:
        return _render_access(region, 400, [RETIRED_NO_NEW_ACCESS])
    if db.get(RegionGrant, (region.id, user.id)) is not None:
        return _render_access(region, 400, [ALREADY_HAS_ACCESS])
    db.add(RegionGrant(region_id=region.id, user_id=user.id, role=role))
    try:
        _log(region, code, user, "region_access_given", {"role": role})
        db.commit()
    except IntegrityError:  # given at the same moment by someone else
        db.rollback()
        return _render_access(region, 400, [ALREADY_HAS_ACCESS])
    flash(f"Gave {user.full_name} {role.title()} access to {code}.", "success")
    return _to_access(region)
