"""The Users screen (spec sections 6.3, 7 and 8.1): people, approval, password reset, re-enable and effective access.

Open to ``manage_users`` holders; the administrator flag stays administrator-only. Every action on a person asks
``account_refusal`` first and only then looks at the account's status, so a refusal on one's own or an elevated
account always gives its own message. Each change is committed with its activity entries in one transaction, and the
entries name the affected user in ``target_user_id``.
"""

from __future__ import annotations

from flask import abort, flash, redirect, render_template, request, url_for
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from ..audit import change, record
from ..auth import ROLE_ORDER, admin_required, current_user, has_permission, permission_required, tracker_roles
from ..auth.accounts import account_refusal, last_admin_refusal
from ..auth.guards import TEAM_WITH_SETS_MESSAGE, team_holds_sets
from ..auth.passwords import hash_password, validate_new_password
from ..auth.permissions import PERMISSIONS, permission_sources
from ..auth.roles import tracker_access_routes
from ..db import get_session
from ..models import PermissionSet, PermissionSetHolder, TeamMember, User
from ..teams.tree import load_team_rows, parse_team_id, paths, team_choices
from ..teams.views import ALREADY_MEMBER_MESSAGE, CHOOSE_ROLE_MESSAGE
from . import bp

SSO_PASSWORD_MESSAGE = "This person signs in with Microsoft and has no password here."
NO_CHANGES_MESSAGE = "No changes to save."
ROLES = tuple(ROLE_ORDER)
_MAX_ID = 2**31 - 1  # the largest Postgres integer; a larger id cannot exist and must not reach a query


def _get_user_or_404(user_id: int) -> User:
    user = get_session().get(User, user_id) if user_id <= _MAX_ID else None
    if user is None:
        abort(404)
    return user


def _refuse(message: str):
    """A refusal by a guard: nothing is changed (any lock taken is released) and the message is shown on Users."""
    get_session().rollback()
    flash(message, "danger")
    return redirect(url_for("admin.users"))


def _team_labels(db) -> dict[int, str]:
    rows = load_team_rows(db)
    return {row.id: row.name for row in rows} | paths(rows)  # the bare name for a team the tree cannot place


# --- The list -------------------------------------------------------------------------------------------------------


def _teams_and_sets(db, labels: dict[int, str]) -> tuple[dict[int, list[tuple[str, str]]], dict[int, list[str]]]:
    """User id to their teams ``(path, role)`` and to their permission sets (direct, then through a team)."""
    teams: dict[int, list[tuple[str, str]]] = {}
    for user_id, team_id, role in db.execute(select(TeamMember.user_id, TeamMember.team_id, TeamMember.role)):
        teams.setdefault(user_id, []).append((labels.get(team_id, ""), role))
    direct = db.execute(
        select(PermissionSetHolder.user_id, PermissionSet.name)
        .join(PermissionSet, PermissionSet.id == PermissionSetHolder.set_id)
        .where(PermissionSetHolder.user_id.is_not(None))
    )
    through = db.execute(
        select(TeamMember.user_id, PermissionSet.name, PermissionSetHolder.team_id)
        .join(PermissionSetHolder, PermissionSetHolder.team_id == TeamMember.team_id)
        .join(PermissionSet, PermissionSet.id == PermissionSetHolder.set_id)
    )
    found: dict[int, list[tuple[bool, str, str]]] = {}
    for user_id, name in direct:
        found.setdefault(user_id, []).append((False, name.casefold(), name))
    for user_id, name, team_id in through:
        found.setdefault(user_id, []).append((True, name.casefold(), f"{name} (through {labels.get(team_id, '')})"))
    sets = {user_id: [text for _by_team, _key, text in sorted(items)] for user_id, items in found.items()}
    return {user_id: sorted(items) for user_id, items in teams.items()}, sets


def _actions(db, actor: User, user: User) -> dict[str, bool]:
    """The actions the actor may take on the user, so the row offers only those."""
    may_act = account_refusal(db, actor, user) is None
    return {
        "approve": may_act and user.status == "pending",
        "enable": may_act and user.status == "disabled",
        "disable": may_act and user.status != "disabled" and user.id != actor.id,
        "password": may_act and user.auth_source == "local",
        "set_admin": actor.is_admin and user.id != actor.id,
    }


@bp.get("/users")
@permission_required("manage_users")
def users():
    db = get_session()
    actor = current_user()
    rows = db.scalars(select(User).order_by(User.status != "pending", User.full_name, User.id)).all()
    labels = _team_labels(db)
    teams, sets = _teams_and_sets(db, labels)
    place_choices = []
    if has_permission(actor, "manage_teams"):
        place_choices = team_choices(db)
        if not actor.is_admin:  # a team that holds a set takes new members from administrators only
            holding = set(
                db.scalars(select(PermissionSetHolder.team_id).where(PermissionSetHolder.team_id.is_not(None)))
            )
            place_choices = [(team_id, label) for team_id, label in place_choices if team_id not in holding]
    return render_template(
        "admin/users.html",
        users=rows,
        teams=teams,
        sets=sets,
        actions={user.id: _actions(db, actor, user) for user in rows},
        place_choices=place_choices,
        roles=ROLES,
        page_title="Users",
        current_page="users",
    )


def _render_new_user(form, errors: list[str], status: int):
    return (
        render_template("admin/user_form.html", form=form, errors=errors, page_title="New user", current_page="users"),
        status,
    )


@bp.get("/users/new")
@permission_required("manage_users")
def new_user():
    return _render_new_user({}, [], 200)


@bp.post("/users")
@permission_required("manage_users")
def create_user():
    email = request.form.get("email", "").strip().lower()
    full_name = request.form.get("full_name", "").strip()
    password = request.form.get("password", "")
    error = None
    if not email or "@" not in email or not full_name:
        error = "An email address and a full name are required."
    else:
        error = validate_new_password(password)
    if error:
        return _render_new_user(request.form, [error], 400)
    db = get_session()
    user = User(
        email=email, full_name=full_name, password_hash=hash_password(password), auth_source="local", status="active"
    )
    db.add(user)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        return _render_new_user(request.form, ["A user with that email address already exists."], 400)
    record(
        db,
        user_id=current_user().id,
        tracker_id=None,
        action="user_created",
        entity="user",
        entity_id=user.id,
        detail={"email": email, "source": "local"},
        target_user_id=user.id,
    )
    db.commit()
    flash(f"Created {email}.", "success")
    return redirect(url_for("admin.users"))


# --- Status changes -------------------------------------------------------------------------------------------------


@bp.post("/users/<int:user_id>/approve")
@permission_required("manage_users")
def approve(user_id: int):
    """Approve a pending user, optionally placing them in one team with a role (``manage_teams`` holders only).

    The person approved is never the actor (``account_refusal`` refuses one's own account), so the place cannot
    change the actor's own access and needs no self-promotion check.
    """
    user = _get_user_or_404(user_id)
    db = get_session()
    actor = current_user()
    refusal = account_refusal(db, actor, user)
    if refusal:
        return _refuse(refusal)
    if user.status != "pending":
        abort(400, description="Only a person awaiting approval can be approved.")
    team, role, path = None, None, None
    if request.form.get("team_id", "").strip():
        if not has_permission(actor, "manage_teams"):
            abort(403, description="You do not have permission to place people in teams.")
        team, error = parse_team_id(db, request.form.get("team_id"))
        if error:
            abort(400, description=error)
        role = request.form.get("team_role", "")
        if role not in ROLE_ORDER:
            abort(400, description=CHOOSE_ROLE_MESSAGE)
        if not actor.is_admin and team_holds_sets(db, team.id):
            return _refuse(TEAM_WITH_SETS_MESSAGE)
        if db.get(TeamMember, (team.id, user.id)) is not None:
            abort(400, description=ALREADY_MEMBER_MESSAGE)
        path = _team_labels(db).get(team.id, team.name)
    user.status = "active"
    record(
        db,
        user_id=actor.id,
        tracker_id=None,
        action="user_approved",
        entity="user",
        entity_id=user.id,
        detail=change("pending", "active"),
        target_user_id=user.id,
    )
    if team is not None:
        db.add(TeamMember(team_id=team.id, user_id=user.id, role=role))
        record(
            db,
            user_id=actor.id,
            tracker_id=None,
            action="team_member_added",
            entity="team",
            entity_id=team.id,
            detail={"team": path, "role": role},
            target_user_id=user.id,
        )
    try:
        db.commit()
    except IntegrityError:  # the team was deleted, or the person added to it, at the same moment
        db.rollback()
        abort(400, description="The team has changed since the page was opened. Please try again.")
    if team is not None:
        flash(f"{user.full_name} is now active and {role} in {team.name}.", "success")
    else:
        flash(f"{user.full_name} is now active.", "success")
    return redirect(url_for("admin.users"))


@bp.post("/users/<int:user_id>/enable")
@permission_required("manage_users")
def enable(user_id: int):
    user = _get_user_or_404(user_id)
    db = get_session()
    actor = current_user()
    refusal = account_refusal(db, actor, user)
    if refusal:
        return _refuse(refusal)
    if user.status != "disabled":
        abort(400, description="Only a disabled person can be re-enabled.")
    user.status = "active"
    record(
        db,
        user_id=actor.id,
        tracker_id=None,
        action="user_enabled",
        entity="user",
        entity_id=user.id,
        detail=change("disabled", "active"),
        target_user_id=user.id,
    )
    db.commit()
    flash(f"{user.full_name} can sign in again.", "success")
    return redirect(url_for("admin.users"))


@bp.post("/users/<int:user_id>/disable")
@permission_required("manage_users")
def disable(user_id: int):
    user = _get_user_or_404(user_id)
    db = get_session()
    actor = current_user()
    refusal = account_refusal(db, actor, user)
    if refusal:
        return _refuse(refusal)
    if user.status == "disabled":
        abort(400, description="This person is already disabled.")
    if user.id == actor.id:
        return _refuse("You cannot disable your own account.")
    refusal = last_admin_refusal(db, user)
    if refusal:
        return _refuse(refusal)
    previous = user.status
    user.status = "disabled"
    record(
        db,
        user_id=actor.id,
        tracker_id=None,
        action="user_disabled",
        entity="user",
        entity_id=user.id,
        detail=change(previous, "disabled"),
        target_user_id=user.id,
    )
    db.commit()
    flash(f"{user.full_name} has been disabled.", "success")
    return redirect(url_for("admin.users"))


@bp.post("/users/<int:user_id>/admin")
@admin_required
def set_admin(user_id: int):
    user = _get_user_or_404(user_id)
    make_admin = request.form.get("is_admin") == "1"
    actor = current_user()
    if user.id == actor.id and not make_admin:
        return _refuse("You cannot remove your own administrator access.")
    if user.is_admin == make_admin:
        flash(NO_CHANGES_MESSAGE, "info")
        return redirect(url_for("admin.users"))
    db = get_session()
    if not make_admin:
        refusal = last_admin_refusal(db, user)
        if refusal:
            return _refuse(refusal)
    user.is_admin = make_admin
    record(
        db,
        user_id=actor.id,
        tracker_id=None,
        action="user_admin_changed",
        entity="user",
        entity_id=user.id,
        detail=change(not make_admin, make_admin),
        target_user_id=user.id,
    )
    db.commit()
    flash(f"Administrator access {'granted to' if make_admin else 'removed from'} {user.full_name}.", "success")
    return redirect(url_for("admin.users"))


# --- Password reset -------------------------------------------------------------------------------------------------


def _render_password(user: User, errors: list[str], status: int):
    page = render_template(
        "admin/user_password.html", person=user, errors=errors, page_title="Reset password", current_page="users"
    )
    return page, status


@bp.route("/users/<int:user_id>/password", methods=["GET", "POST"])
@permission_required("manage_users")
def password(user_id: int):
    user = _get_user_or_404(user_id)
    db = get_session()
    actor = current_user()
    refusal = account_refusal(db, actor, user)
    if refusal:
        return _refuse(refusal)
    if user.auth_source != "local":
        return _refuse(SSO_PASSWORD_MESSAGE)
    if request.method == "GET":
        return _render_password(user, [], 200)
    new_password = request.form.get("password", "")
    error = validate_new_password(new_password)
    if error:
        return _render_password(user, [error], 400)
    user.password_hash = hash_password(new_password)
    record(
        db,
        user_id=actor.id,
        tracker_id=None,
        action="password_reset",
        entity="user",
        entity_id=user.id,
        detail={"source": "web"},
        target_user_id=user.id,
    )
    db.commit()
    flash(f"Set a new password for {user.full_name}. Share it with them securely.", "success")
    return redirect(url_for("admin.users"))


# --- Effective access -----------------------------------------------------------------------------------------------


@bp.get("/users/<int:user_id>/access")
@permission_required("manage_users")
def access(user_id: int):
    """Every tracker the user reaches and every permission they hold, with where each comes from.

    Tracker names are shown to administrators and ``manage_teams`` holders (spec section 6.2), and otherwise only for
    trackers the viewer can open themselves; the rest are counted, never named.
    """
    user = _get_user_or_404(user_id)
    db = get_session()
    viewer = current_user()
    reached = tracker_access_routes(db, user)
    if viewer.is_admin or has_permission(viewer, "manage_teams"):
        shown = reached
    else:
        own = tracker_roles(db, viewer)
        shown = [entry for entry in reached if entry.tracker.id in own]
    return render_template(
        "admin/user_access.html",
        person=user,
        trackers=shown,
        hidden=len(reached) - len(shown),
        sources=permission_sources(db, user),
        permission_labels={name: label for name, (label, _description) in PERMISSIONS.items()},
        page_title=f"Effective access: {user.full_name}",
        current_page="users",
    )
