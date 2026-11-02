"""Permission sets screens (spec sections 6.2, 7 and 8.1): the grid, a set's page and its holders.

Only administrators reach these screens, however many permissions they hold otherwise. Every change is committed with
its activity entries in one transaction; team holders are named by their path from the top of the tree.
"""

from __future__ import annotations

from flask import abort, flash, redirect, render_template, request, url_for
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError

from ..audit import NO_CHANGES_MESSAGE, change, record
from ..auth import admin_required, current_user
from ..auth.permissions import PERMISSION_GROUPS, PERMISSIONS
from ..db import get_session
from ..ids import in_range, parse_id
from ..models import PermissionSet, PermissionSetHolder, PermissionSetPermission, Team, User
from ..naming import description_error, name_error, name_taken
from ..teams.tree import load_team_rows, team_labels
from . import bp

ALREADY_HOLDS_MESSAGE = "That team or person already holds this set."
CHOOSE_HOLDER_MESSAGE = "Choose a team or an active person from the list."


def _set_or_404(set_id: int) -> PermissionSet:
    permission_set = get_session().get(PermissionSet, set_id) if in_range(set_id) else None
    if permission_set is None:
        abort(404)
    return permission_set


def _to_set(permission_set: PermissionSet):
    return redirect(url_for("permsets.view", set_id=permission_set.id))


def _permissions_of(set_ids: list[int]) -> dict[int, list[str]]:
    held: dict[int, list[str]] = {set_id: [] for set_id in set_ids}
    rows = get_session().execute(
        select(PermissionSetPermission.set_id, PermissionSetPermission.permission).where(
            PermissionSetPermission.set_id.in_(set_ids)
        )
    )
    for set_id, permission in rows:
        if permission in PERMISSIONS:
            held[set_id].append(permission)
    return {set_id: sorted(names) for set_id, names in held.items()}


def _holder_counts(set_ids: list[int]) -> dict[int, tuple[int, int]]:
    """Each set's holders as ``(teams, people)``; ``(0, 0)`` for a set nobody holds."""
    counts: dict[int, tuple[int, int]] = {set_id: (0, 0) for set_id in set_ids}
    rows = get_session().execute(
        select(
            PermissionSetHolder.set_id,
            func.count(PermissionSetHolder.team_id),
            func.count(PermissionSetHolder.user_id),
        )
        .where(PermissionSetHolder.set_id.in_(set_ids))
        .group_by(PermissionSetHolder.set_id)
    )
    for set_id, teams, people in rows:
        counts[set_id] = (teams, people)
    return counts


# --- The cards ------------------------------------------------------------------------------------------------------


def _render_index(form, errors: list[str], status: int):
    db = get_session()
    sets = db.scalars(select(PermissionSet).order_by(func.lower(PermissionSet.name), PermissionSet.id)).all()
    set_ids = [s.id for s in sets]
    page = render_template(
        "permsets/index.html",
        sets=sets,
        held=_permissions_of(set_ids),
        holder_counts=_holder_counts(set_ids),
        admin_count=db.scalar(
            select(func.count()).select_from(User).where(User.is_admin.is_(True), User.status == "active")
        ),
        permissions=PERMISSIONS,
        groups=PERMISSION_GROUPS,
        form=form,
        errors=errors,
        page_title="Permission sets",
        current_page="permsets",
    )
    return page, status


@bp.get("")
@admin_required
def index():
    return _render_index({}, [], 200)


@bp.post("/grid")
@admin_required
def save_grid():
    db = get_session()
    set_ids = {i for i in (parse_id(value) for value in request.form.getlist("sets")) if i is not None}
    sets = db.scalars(select(PermissionSet).where(PermissionSet.id.in_(set_ids)).order_by(PermissionSet.id)).all()
    current = _permissions_of([s.id for s in sets])
    changed = 0
    for permission_set in sets:
        before = current[permission_set.id]
        after = sorted({name for name in request.form.getlist(f"set-{permission_set.id}") if name in PERMISSIONS})
        if before == after:
            continue
        db.execute(delete(PermissionSetPermission).where(PermissionSetPermission.set_id == permission_set.id))
        db.add_all(PermissionSetPermission(set_id=permission_set.id, permission=name) for name in after)
        record(
            db,
            user_id=current_user().id,
            tracker_id=None,
            action="permission_set_permissions_changed",
            entity="permission_set",
            entity_id=permission_set.id,
            detail={"set": permission_set.name, **change(before, after)},
        )
        changed += 1
    db.commit()
    flash("Saved the permissions." if changed else NO_CHANGES_MESSAGE, "success" if changed else "info")
    return redirect(url_for("permsets.index"))


@bp.post("")
@admin_required
def create():
    db = get_session()
    name = request.form.get("name", "").strip()
    description = request.form.get("description", "").strip()
    errors = [e for e in (name_error(db, PermissionSet, name, "permission set"), description_error(description)) if e]
    if errors:
        return _render_index(request.form, errors, 400)
    permission_set = PermissionSet(name=name, description=description)
    db.add(permission_set)
    try:
        db.flush()
        record(
            db,
            user_id=current_user().id,
            tracker_id=None,
            action="permission_set_created",
            entity="permission_set",
            entity_id=permission_set.id,
            detail={"name": name},
        )
        db.commit()
    except IntegrityError:
        db.rollback()
        return _render_index(request.form, [name_taken("permission set")], 400)
    flash(f"Created the permission set {name}.", "success")
    return _to_set(permission_set)


# --- A set's page ---------------------------------------------------------------------------------------------------


def _holders(permission_set: PermissionSet):
    """The set's holders as ``(holder, team path or None, user or None)``, teams first."""
    db = get_session()
    labels = team_labels(load_team_rows(db))
    rows = db.execute(
        select(PermissionSetHolder, Team.name, User)
        .outerjoin(Team, Team.id == PermissionSetHolder.team_id)
        .outerjoin(User, User.id == PermissionSetHolder.user_id)
        .where(PermissionSetHolder.set_id == permission_set.id)
    ).all()
    holders = [(h, labels.get(h.team_id, team_name) if h.team_id else None, user) for h, team_name, user in rows]
    return sorted(
        holders,
        key=lambda item: (
            item[0].user_id is not None,
            (item[1] or item[2].full_name).lower(),
            item[0].id,
        ),
    )


def _render_set(permission_set: PermissionSet, errors: list[str], status: int, form=None):
    db = get_session()
    holders = _holders(permission_set)
    held_teams = {h.team_id for h, _path, _user in holders if h.team_id}
    held_users = {h.user_id for h, _path, _user in holders if h.user_id}
    team_choices = sorted(
        ((team_id, label) for team_id, label in team_labels(load_team_rows(db)).items() if team_id not in held_teams),
        key=lambda item: item[1].lower(),
    )
    people = [
        user
        for user in db.scalars(
            select(User).where(User.status == "active").order_by(func.lower(User.full_name), User.id)
        )
        if user.id not in held_users
    ]
    page = render_template(
        "permsets/set.html",
        permission_set=permission_set,
        permissions=[(name, PERMISSIONS[name][0]) for name in _permissions_of([permission_set.id])[permission_set.id]],
        holders=holders,
        team_choices=team_choices,
        people=people,
        form=form or {"name": permission_set.name, "description": permission_set.description},
        errors=errors,
        page_title=permission_set.name,
        current_page="permsets",
    )
    return page, status


@bp.get("/<int:set_id>")
@admin_required
def view(set_id: int):
    return _render_set(_set_or_404(set_id), [], 200)


@bp.post("/<int:set_id>/rename")
@admin_required
def rename(set_id: int):
    permission_set = _set_or_404(set_id)
    db = get_session()
    submitted = {
        "name": request.form.get("name", "").strip(),
        "description": request.form.get("description", "").strip(),
    }
    errors = [
        e
        for e in (
            name_error(db, PermissionSet, submitted["name"], "permission set", permission_set.id),
            description_error(submitted["description"]),
        )
        if e
    ]
    if errors:
        return _render_set(permission_set, errors, 400, form=submitted)
    before = {
        field: getattr(permission_set, field)
        for field, value in submitted.items()
        if getattr(permission_set, field) != value
    }
    if not before:
        flash(NO_CHANGES_MESSAGE, "info")
        return _to_set(permission_set)
    after = {field: submitted[field] for field in before}
    set_name = permission_set.name  # as it was before the change
    for field, value in after.items():
        setattr(permission_set, field, value)
    record(
        db,
        user_id=current_user().id,
        tracker_id=None,
        action="permission_set_renamed",
        entity="permission_set",
        entity_id=permission_set.id,
        detail={"set": set_name, **change(before, after)},
    )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return _render_set(permission_set, [name_taken("permission set")], 400, form=submitted)
    flash("Saved the permission set details.", "success")
    return _to_set(permission_set)


def _record_holder(permission_set: PermissionSet, action: str, team_path: str | None, user_id: int | None) -> None:
    detail = {"set": permission_set.name}
    if team_path is not None:
        detail["team"] = team_path
    record(
        get_session(),
        user_id=current_user().id,
        tracker_id=None,
        action=action,
        entity="permission_set",
        entity_id=permission_set.id,
        detail=detail,
        target_user_id=user_id,
    )


@bp.post("/<int:set_id>/delete")
@admin_required
def delete_set(set_id: int):
    permission_set = _set_or_404(set_id)
    db = get_session()
    name = permission_set.name
    permissions = _permissions_of([permission_set.id])[permission_set.id]
    for holder, team_path, _user in _holders(permission_set):
        _record_holder(permission_set, "permission_set_holder_removed", team_path, holder.user_id)
    record(
        db,
        user_id=current_user().id,
        tracker_id=None,
        action="permission_set_deleted",
        entity="permission_set",
        entity_id=permission_set.id,
        detail={"name": name, "permissions": permissions},
    )
    db.execute(delete(PermissionSetHolder).where(PermissionSetHolder.set_id == permission_set.id))
    db.execute(delete(PermissionSetPermission).where(PermissionSetPermission.set_id == permission_set.id))
    db.delete(permission_set)
    db.commit()
    flash(f"Deleted the permission set {name}.", "success")
    return redirect(url_for("permsets.index"))


# --- Holders --------------------------------------------------------------------------------------------------------


@bp.post("/<int:set_id>/holders")
@admin_required
def add_holder(set_id: int):
    permission_set = _set_or_404(set_id)
    db = get_session()
    kind, _, raw_id = request.form.get("holder", "").partition(":")
    holder_id = parse_id(raw_id)
    team = user = None
    if kind == "team" and holder_id:
        team = db.get(Team, holder_id)
    elif kind == "user" and holder_id:
        user = db.get(User, holder_id)
        if user is not None and user.status != "active":
            user = None
    if team is None and user is None:
        return _render_set(permission_set, [CHOOSE_HOLDER_MESSAGE], 400)
    column, value = (PermissionSetHolder.team_id, team.id) if team else (PermissionSetHolder.user_id, user.id)
    if db.scalar(
        select(PermissionSetHolder.id).where(PermissionSetHolder.set_id == permission_set.id, column == value)
    ):
        return _render_set(permission_set, [ALREADY_HOLDS_MESSAGE], 400)
    team_path = team_labels(load_team_rows(db)).get(team.id, team.name) if team else None
    db.add(
        PermissionSetHolder(
            set_id=permission_set.id, team_id=team.id if team else None, user_id=user.id if user else None
        )
    )
    try:
        _record_holder(permission_set, "permission_set_holder_added", team_path, user.id if user else None)
        db.commit()
    except IntegrityError:  # added at the same moment by someone else, or the team or person has just gone
        db.rollback()
        return _render_set(permission_set, [ALREADY_HOLDS_MESSAGE], 400)
    flash(f"Added {team_path if team else user.full_name} as a holder of {permission_set.name}.", "success")
    return _to_set(permission_set)


@bp.post("/<int:set_id>/holders/<int:holder_id>/delete")
@admin_required
def remove_holder(set_id: int, holder_id: int):
    permission_set = _set_or_404(set_id)
    db = get_session()
    holder = db.get(PermissionSetHolder, holder_id) if in_range(holder_id) else None
    if holder is None or holder.set_id != permission_set.id:
        abort(404)
    team_id, user_id = holder.team_id, holder.user_id
    team_path = team_labels(load_team_rows(db)).get(team_id) if team_id else None
    if not db.execute(delete(PermissionSetHolder).where(PermissionSetHolder.id == holder.id)).rowcount:
        db.rollback()  # removed by someone else at the same moment
        flash(f"That holder of {permission_set.name} has already been removed.", "info")
        return _to_set(permission_set)
    _record_holder(permission_set, "permission_set_holder_removed", team_path, user_id)
    db.commit()
    flash(f"Removed a holder of {permission_set.name}.", "success")
    return _to_set(permission_set)
