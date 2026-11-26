"""The Users screen (spec sections 6.3, 7 and 8.1): people, approval, password reset, the switch to Microsoft sign-in,
re-enable, delete and effective access.

Open to ``manage_users`` holders; the administrator flag and deleting a person stay administrator-only. Every action on
a person asks ``account_refusal`` first and only then looks at the account's status, so a refusal on one's own or an
elevated account always gives its own message. A deleted person is kept for the history only: every action refuses
them. Each change is committed with its activity entries in one transaction, and the entries name the affected user in
``target_user_id``.
"""

from __future__ import annotations

from datetime import datetime

from flask import abort, current_app, flash, redirect, render_template, request, url_for
from sqlalchemy import exists, func, or_, select
from sqlalchemy.exc import IntegrityError

from ..audit import NO_CHANGES_MESSAGE, change, record
from ..auth import ROLES, admin_required, current_user, has_permission, permission_required, tracker_roles
from ..auth.accounts import (
    DELETED_MESSAGE,
    account_refusal,
    last_admin_refusal,
    last_password_admin_refusal,
    vouched_refusal,
)
from ..auth.guards import TEAM_WITH_SETS_MESSAGE, team_holds_sets
from ..auth.passwords import hash_password, validate_new_password
from ..auth.permissions import PERMISSIONS, permission_sources
from ..auth.roles import tracker_access_routes
from ..auth.session import end_sessions, login_user
from ..db import get_session
from ..ids import in_range, parse_id
from ..listview import list_url
from ..mail import access as access_mail
from ..models import AuditLog, PermissionSet, PermissionSetHolder, Region, RegionGrant, Team, TeamMember, User
from ..teams.tree import (
    ALREADY_MEMBER_MESSAGE,
    CHOOSE_ROLE_MESSAGE,
    load_team_rows,
    parse_team_id,
    team_choices,
    team_labels,
)
from . import bp
from .deletion import delete_person, deletion_summary

SSO_PASSWORD_MESSAGE = "This person signs in with Microsoft and has no password here."
PASSWORDS_DIFFER_MESSAGE = "The two passwords do not match."
EMAIL_MISMATCH_MESSAGE = "The email does not match."
ALREADY_DISABLED_MESSAGE = "This person is already disabled."


def _get_user_or_404(user_id: int, lock: bool = False) -> User:
    """The user, read ``FOR NO KEY UPDATE`` with ``lock`` (held until the request commits or rolls back).

    That lock waits for, and holds off, any other change to the row, such as a re-enable, but not the ``KEY SHARE``
    lock a foreign key to the row takes. ``FOR UPDATE`` would also block that: a report retry holding a queued send
    that the person created, and then writing its entry, would wait for the delete while the delete waits for the send.
    """
    for_update = {"key_share": True} if lock else None
    user = get_session().get(User, user_id, with_for_update=for_update) if in_range(user_id) else None
    if user is None:
        abort(404)
    return user


def _abort_if_deleted(user: User) -> None:
    if user.status == "deleted":
        abort(400, description=DELETED_MESSAGE)


def _users_url() -> str:
    """The Users list as the reader had it (the posted view), for after a row action."""
    return list_url("admin.users", USERS_VIEW_KEYS)


def _refuse(message: str):
    """A refusal by a guard: nothing is changed (any lock taken is released) and the message is shown on Users."""
    get_session().rollback()
    flash(message, "danger")
    return redirect(_users_url())


def _admin_loss_refusal(db, user: User) -> str | None:
    """Why ``user`` may not stop being an active administrator, or ``None``.

    The last administrator is kept, and, while Microsoft sign-in is on, the last one who signs in with a password.
    """
    refusal = last_admin_refusal(db, user)
    if not refusal and current_app.config["SSO_ENABLED"]:
        refusal = last_password_admin_refusal(db, user)
    return refusal


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


def _held_sets(db, user: User, labels: dict[int, str]) -> list[tuple[str, int | None]]:
    """The user's permission sets as ``(name, team id)``: ``None`` when held directly, else the holding team."""
    direct = db.scalars(
        select(PermissionSet.name)
        .join(PermissionSetHolder, PermissionSetHolder.set_id == PermissionSet.id)
        .where(PermissionSetHolder.user_id == user.id)
    )
    through = db.execute(
        select(PermissionSet.name, PermissionSetHolder.team_id)
        .join(PermissionSetHolder, PermissionSetHolder.set_id == PermissionSet.id)
        .join(TeamMember, TeamMember.team_id == PermissionSetHolder.team_id)
        .where(TeamMember.user_id == user.id)
    )
    found = [(name, None) for name in direct] + [(name, team_id) for name, team_id in through]
    return sorted(found, key=lambda h: (h[0].casefold(), h[0], h[1] is not None, labels.get(h[1] or 0, "")))


def _actions(db, actor: User, user: User) -> dict[str, bool]:
    """The actions the actor may take on the user, so the row offers only those; none on a deleted person."""
    may_act = account_refusal(db, actor, user) is None
    actions = {
        "approve": may_act and user.status in ("pending", "declined"),
        "decline": may_act and user.status == "pending",
        "enable": may_act and user.status == "disabled",
        "disable": may_act and user.status not in ("disabled", "declined") and user.id != actor.id,
        "end_sessions": may_act and user.status == "active" and user.id != actor.id,
        "password": may_act and user.auth_source == "local",
        "switch": may_act
        and user.auth_source == "local"
        and user.status in ("active", "disabled")
        and current_app.config["SSO_ENABLED"],
        "set_admin": actor.is_admin and user.id != actor.id,
        "delete": actor.is_admin and user.id != actor.id and user.status in ("disabled", "pending", "declined"),
    }
    return dict.fromkeys(actions, False) if user.status == "deleted" else actions


STATUS_FILTERS = {
    "active": "Active",
    "pending": "Awaiting approval",
    "declined": "Turned down",
    "disabled": "Disabled",
    "deleted": "Deleted",
}
ADMIN_FILTERS = {"yes": "Yes", "no": "No"}
# The keys of the Users view (lists.js writes sort, page and size to the address; the server filters are the others)
# that a row action sends the reader back to.
USERS_VIEW_KEYS = ("q", "status", "sign_in", "admin", "team", "set", "sort", "page", "size")
SIGN_IN_LABELS = {"local": "Local", "sso": "SSO"}
SIGN_IN_MEANINGS = {
    "local": "signs in with an email address and a password set in this app",
    "sso": "signs in with a work account (single sign-on)",
}


def _like_escaped(text: str) -> str:
    """``text`` as a literal inside a LIKE pattern (``\\`` is the escape character)."""
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _list_filters(db) -> dict[str, str | int | None]:
    """The filters on the list from the query string; anything unparseable or unknown is ignored."""
    team_id, set_id = parse_id(request.args.get("team")), parse_id(request.args.get("set"))
    status, sign_in, admin = (request.args.get(key, "") for key in ("status", "sign_in", "admin"))
    return {
        "q": request.args.get("q", "").strip(),
        "status": status if status in STATUS_FILTERS else "",
        "admin": admin if admin in ADMIN_FILTERS else "",
        "sign_in": sign_in if sign_in in SIGN_IN_LABELS else "",
        "team": team_id if team_id is not None and db.get(Team, team_id) is not None else None,
        "set": set_id if set_id is not None and db.get(PermissionSet, set_id) is not None else None,
    }


def _filtered_users(filters: dict[str, str | int | None]):
    query = select(User).order_by(User.status != "pending", User.full_name, User.id)
    if filters["q"]:
        pattern = f"%{_like_escaped(str(filters['q']))}%"
        query = query.where(or_(User.full_name.ilike(pattern, escape="\\"), User.email.ilike(pattern, escape="\\")))
    if filters["status"]:
        query = query.where(User.status == filters["status"])
    if filters["status"] != "deleted":  # a deleted person is listed only when asked for
        query = query.where(User.status != "deleted")
    if filters["admin"]:
        query = query.where(User.is_admin.is_(filters["admin"] == "yes"))
    if filters["sign_in"]:
        query = query.where(User.auth_source == filters["sign_in"])
    if filters["team"] is not None:
        query = query.where(exists().where(TeamMember.user_id == User.id, TeamMember.team_id == filters["team"]))
    if filters["set"] is not None:
        direct = exists().where(PermissionSetHolder.set_id == filters["set"], PermissionSetHolder.user_id == User.id)
        through = exists().where(
            PermissionSetHolder.set_id == filters["set"],
            PermissionSetHolder.team_id == TeamMember.team_id,
            TeamMember.user_id == User.id,
        )
        query = query.where(or_(direct, through))
    return query


@bp.get("/users")
@permission_required("manage_users")
def users():
    db = get_session()
    actor = current_user()
    everyone = db.scalars(
        select(User).where(User.status != "deleted").order_by(User.status != "pending", User.full_name, User.id)
    ).all()
    filters = _list_filters(db)
    filtered = any(filters.values())
    rows = db.scalars(_filtered_users(filters)).all()
    shown = everyone + [user for user in rows if user.status == "deleted"]
    labels = team_labels(load_team_rows(db))
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
        pending=[user for user in everyone if user.status == "pending"],
        declined=[user for user in everyone if user.status == "declined"],
        declined_notes=_declined_notes(db, [user.id for user in everyone if user.status == "declined"]),
        total=len(everyone),
        active_count=sum(1 for user in rows if user.status == "active"),
        filters=filters,
        filtered=filtered,
        status_filters=STATUS_FILTERS,
        admin_filters=ADMIN_FILTERS,
        sign_in_labels=SIGN_IN_LABELS,
        sign_in_meanings=SIGN_IN_MEANINGS,
        team_options=team_choices(db),
        set_options=db.execute(
            select(PermissionSet.id, PermissionSet.name).order_by(func.lower(PermissionSet.name))
        ).all(),
        teams=teams,
        sets=sets,
        actions={user.id: _actions(db, actor, user) for user in shown},
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
    """Approve a pending or turned-down user, optionally placing them in one team with a role (``manage_teams`` holders
    only), and email them that they are approved.

    The person approved is never the actor (``account_refusal`` refuses one's own account), so the place cannot
    change the actor's own access and needs no self-promotion check. The person is locked as a delete locks them, so an
    approval waits for a delete in progress and then refuses, instead of writing ``active`` over ``deleted``.
    """
    user = _get_user_or_404(user_id, lock=True)
    db = get_session()
    actor = current_user()
    refusal = account_refusal(db, actor, user)
    if refusal:
        return _refuse(refusal)
    _abort_if_deleted(user)
    if user.status not in ("pending", "declined"):
        abort(400, description="Only a person awaiting approval or turned down can be approved.")
    was = user.status
    team, role, path = None, None, None
    if request.form.get("team_id", "").strip():
        if not has_permission(actor, "manage_teams"):
            abort(403, description="You do not have permission to place people in teams.")
        team, error = parse_team_id(db, request.form.get("team_id"))
        if error:
            abort(400, description=error)
        role = request.form.get("team_role", "")
        if role not in ROLES:
            abort(400, description=CHOOSE_ROLE_MESSAGE)
        if not actor.is_admin and team_holds_sets(db, team.id):
            return _refuse(TEAM_WITH_SETS_MESSAGE)
        if db.get(TeamMember, (team.id, user.id)) is not None:
            abort(400, description=ALREADY_MEMBER_MESSAGE)
        refusal = vouched_refusal(db, actor, user)
        if refusal:
            return _refuse(refusal)
        path = team_labels(load_team_rows(db)).get(team.id, team.name)
    user.status = "active"
    record(
        db,
        user_id=actor.id,
        tracker_id=None,
        action="user_approved",
        entity="user",
        entity_id=user.id,
        detail=change(was, "active"),
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
    if access_mail.approved(db, user, actor, path, role):
        db.commit()
    if team is not None:
        flash(f"{user.full_name} is now active, as {role} in {team.name}.", "success")
    else:
        flash(f"{user.full_name} is now active.", "success")
    return redirect(url_for("admin.users"))


@bp.post("/users/<int:user_id>/decline")
@permission_required("manage_users")
def decline(user_id: int):
    """Turn down a person awaiting approval (design 2026-11-18) and email them. They keep their Microsoft link, so a
    later sign-in shows that the request was not approved instead of asking again; Approve still lets them in."""
    user = _get_user_or_404(user_id, lock=True)
    db = get_session()
    actor = current_user()
    refusal = account_refusal(db, actor, user)
    if refusal:
        return _refuse(refusal)
    _abort_if_deleted(user)
    if user.status != "pending":
        abort(400, description="Only a person awaiting approval can be turned down.")
    user.status = "declined"
    record(
        db,
        user_id=actor.id,
        tracker_id=None,
        action="user_declined",
        entity="user",
        entity_id=user.id,
        detail=change("pending", "declined"),
        target_user_id=user.id,
    )
    db.commit()
    if access_mail.declined(db, user, actor):
        db.commit()
        flash(f"Turned down {user.full_name}. They have been emailed.", "success")
    else:
        flash(f"Turned down {user.full_name}.", "success")
    return redirect(url_for("admin.users"))


def _declined_notes(db, user_ids: list[int]) -> dict[int, dict]:
    """For each turned-down person: when and by whom (the latest ``user_declined`` entry) and the latest sign-in tried
    since (``sso_declined_attempt``)."""
    notes: dict[int, dict] = {user_id: {"at": None, "by": None, "tried": None} for user_id in user_ids}
    if not user_ids:
        return notes
    rows = db.execute(
        select(AuditLog.target_user_id, AuditLog.action, AuditLog.at, User.full_name)
        .outerjoin(User, User.id == AuditLog.user_id)
        .where(AuditLog.target_user_id.in_(user_ids), AuditLog.action.in_(("user_declined", "sso_declined_attempt")))
        .order_by(AuditLog.at, AuditLog.id)
    )
    for user_id, action, at, name in rows:
        if action == "user_declined":
            notes[user_id].update(at=at, by=name, tried=None)  # an attempt counts only after the latest turn-down
        else:
            notes[user_id]["tried"] = at
    return notes


@bp.post("/users/<int:user_id>/enable")
@permission_required("manage_users")
def enable(user_id: int):
    """Re-enable a disabled person.

    The person is locked as a delete locks them, so a re-enable waits for a delete in progress and then refuses, instead
    of writing ``active`` over ``deleted``.
    """
    user = _get_user_or_404(user_id, lock=True)
    db = get_session()
    actor = current_user()
    refusal = account_refusal(db, actor, user)
    if refusal:
        return _refuse(refusal)
    _abort_if_deleted(user)
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
    return redirect(_users_url())


@bp.post("/users/<int:user_id>/disable")
@permission_required("manage_users")
def disable(user_id: int):
    """Disable a person.

    The administrators are locked first (``_admin_loss_refusal``), and only then the person, read again as a delete
    locks them, so a delete committed meanwhile is seen and refused instead of being overwritten with ``disabled``.
    Locking the person first could deadlock two disables of two administrators.
    """
    user = _get_user_or_404(user_id)
    db = get_session()
    actor = current_user()
    refusal = account_refusal(db, actor, user)
    if refusal:
        return _refuse(refusal)
    _abort_if_deleted(user)
    if user.status == "disabled":
        abort(400, description=ALREADY_DISABLED_MESSAGE)
    if user.id == actor.id:
        return _refuse("You cannot disable your own account.")
    refusal = _admin_loss_refusal(db, user)
    if refusal:
        return _refuse(refusal)
    db.refresh(user, with_for_update={"key_share": True})
    _abort_if_deleted(user)
    if user.status == "disabled":
        abort(400, description=ALREADY_DISABLED_MESSAGE)
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
    return redirect(_users_url())


@bp.post("/users/<int:user_id>/end-sessions")
@permission_required("manage_users")
def end_user_sessions(user_id: int):
    """Sign a person out everywhere: every session they have, and every copy of one, stops working. They can sign in
    again at once; to keep them out, disable them. Your own sessions end with Sign out instead."""
    user = _get_user_or_404(user_id)
    db = get_session()
    actor = current_user()
    refusal = account_refusal(db, actor, user)
    if refusal:
        return _refuse(refusal)
    _abort_if_deleted(user)
    if user.id == actor.id:
        return _refuse("Use Sign out to end your own sessions.")
    if user.status != "active":
        abort(400, description="Only an active person has sessions to end.")
    end_sessions(db, user)
    record(
        db,
        user_id=actor.id,
        tracker_id=None,
        action="user_sessions_ended",
        entity="user",
        entity_id=user.id,
        target_user_id=user.id,
    )
    db.commit()
    flash(f"{user.full_name} has been signed out everywhere.", "success")
    return redirect(url_for("admin.access", user_id=user.id))


@bp.post("/users/<int:user_id>/admin")
@admin_required
def set_admin(user_id: int):
    user = _get_user_or_404(user_id)
    _abort_if_deleted(user)
    make_admin = request.form.get("is_admin") == "1"
    actor = current_user()
    if user.id == actor.id and not make_admin:
        return _refuse("You cannot remove your own administrator access.")
    if user.is_admin == make_admin:
        flash(NO_CHANGES_MESSAGE, "info")
        return redirect(_users_url())
    db = get_session()
    if not make_admin:
        refusal = _admin_loss_refusal(db, user)
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
    return redirect(_users_url())


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
    _abort_if_deleted(user)
    if user.auth_source != "local":
        return _refuse(SSO_PASSWORD_MESSAGE)
    if request.method == "GET":
        return _render_password(user, [], 200)
    new_password = request.form.get("password", "")
    error = validate_new_password(new_password)
    if not error and request.form.get("password_confirm", "") != new_password:
        error = PASSWORDS_DIFFER_MESSAGE
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
    if user.id == actor.id:  # the new password ends every other session; this one carries on
        login_user(user)
    flash(f"Set a new password for {user.full_name}. Share it with them securely.", "success")
    return redirect(_users_url())


# --- Switching to Microsoft sign-in ---------------------------------------------------------------------------------


@bp.post("/users/<int:user_id>/sign-in")
@permission_required("manage_users")
def switch_sign_in(user_id: int):
    """Turn a password account into a Microsoft one, with no password and no Microsoft link yet.

    The person's next Microsoft sign-in links the account by its email address (``_resolve_user``). A session already
    signed in is ended, as after a password reset, because the password it was started with is gone. The switch is not
    an administrator loss, so only the last administrator who signs in with a password is guarded, not the last
    administrator.
    """
    user = _get_user_or_404(user_id)
    db = get_session()
    actor = current_user()
    refusal = account_refusal(db, actor, user)
    if refusal:
        return _refuse(refusal)
    if not current_app.config["SSO_ENABLED"]:
        abort(400, description="Microsoft sign-in is not set up.")
    if user.auth_source != "local":
        abort(400, description="This person already signs in with Microsoft.")
    if user.status not in ("active", "disabled"):
        abort(400, description="Only an active or disabled person can be switched to Microsoft sign-in.")
    refusal = last_password_admin_refusal(db, user)
    if refusal:
        return _refuse(refusal)
    user.auth_source = "sso"
    user.password_hash = None
    record(
        db,
        user_id=actor.id,
        tracker_id=None,
        action="sign_in_switched",
        entity="user",
        entity_id=user.id,
        detail=change("local", "sso"),
        target_user_id=user.id,
    )
    db.commit()
    flash(f"{user.full_name} now signs in with Microsoft.", "success")
    return redirect(url_for("admin.access", user_id=user.id))


# --- Deleting a person ----------------------------------------------------------------------------------------------


def _render_delete(user: User, errors: list[str], status: int):
    page = render_template(
        "admin/user_delete.html",
        person=user,
        deletion=deletion_summary(get_session(), user),
        errors=errors,
        page_title=f"Delete {user.full_name}",
        current_page="users",
    )
    return page, status


@bp.route("/users/<int:user_id>/delete", methods=["GET", "POST"])
@admin_required
def delete(user_id: int):
    """Delete a disabled or pending person (``delete_person``), once the administrator has typed their email.

    The POST locks the person (``_get_user_or_404``) and checks the status again, so a person re-enabled since the page
    opened is not deleted. The typed email matches ignoring case and surrounding spaces.
    """
    user = _get_user_or_404(user_id, lock=request.method == "POST")
    db = get_session()
    actor = current_user()
    if user.id == actor.id:
        return _refuse("You cannot delete your own account.")
    if user.status not in ("disabled", "pending"):
        abort(400, description="Only a disabled or pending person can be deleted.")
    refusal = last_admin_refusal(db, user)
    if refusal:
        return _refuse(refusal)
    if request.method == "GET":
        return _render_delete(user, [], 200)
    if request.form.get("confirm_email", "").strip().lower() != user.email:
        return _render_delete(user, [EMAIL_MISMATCH_MESSAGE], 400)
    name, email = user.full_name, user.email
    delete_person(db, actor, user)
    db.commit()
    flash(f"Deleted {name} ({email}).", "success")
    return redirect(url_for("admin.users"))


# --- Effective access -----------------------------------------------------------------------------------------------


def _deleted_note(db, user: User) -> tuple[datetime, str | None] | None:
    """When a deleted person was deleted and by whom, from the latest ``user_deleted`` entry for them.

    The name is None when that entry no longer names the administrator (their account was removed since).
    """
    if user.status != "deleted":
        return None
    row = db.execute(
        select(AuditLog.at, User.full_name)
        .select_from(AuditLog)
        .outerjoin(User, User.id == AuditLog.user_id)
        .where(AuditLog.action == "user_deleted", AuditLog.target_user_id == user.id)
        .order_by(AuditLog.at.desc(), AuditLog.id.desc())
        .limit(1)
    ).first()
    return (row.at, row.full_name) if row else None


@bp.get("/users/<int:user_id>/access")
@permission_required("manage_users")
def access(user_id: int):
    """Every tracker the user reaches and every permission they hold, with where each comes from.

    Tracker names are shown to administrators and ``manage_teams`` holders (spec section 6.2), and otherwise only for
    trackers the viewer can open themselves; the rest are neither named nor counted.
    """
    user = _get_user_or_404(user_id)
    db = get_session()
    viewer = current_user()
    reached = tracker_access_routes(db, user)
    limited = not (viewer.is_admin or has_permission(viewer, "manage_teams"))
    shown = reached
    if limited:
        own = tracker_roles(db, viewer)
        shown = [entry for entry in reached if entry.tracker.id in own]
    regions = db.execute(
        select(Region.id, Region.code, RegionGrant.role)
        .join(RegionGrant, RegionGrant.region_id == Region.id)
        .where(RegionGrant.user_id == user.id)
        .order_by(func.lower(Region.code), Region.code)
    ).all()
    labels = team_labels(load_team_rows(db))
    memberships = db.execute(select(TeamMember.team_id, TeamMember.role).where(TeamMember.user_id == user.id))
    teams = sorted(((labels.get(team_id, ""), team_id, role) for team_id, role in memberships))
    actions = _actions(db, viewer, user)
    return render_template(
        "admin/user_access.html",
        person=user,
        actions=actions,
        deletion=deletion_summary(db, user) if actions["delete"] else None,
        deleted_note=_deleted_note(db, user),
        teams=teams,
        team_labels=labels,
        can_view_teams=has_permission(viewer, "manage_teams"),
        regions=regions,
        can_view_regions=viewer.is_admin,
        held_sets=_held_sets(db, user, labels),
        trackers=shown,
        limited=limited,
        sources=permission_sources(db, user),
        permission_labels={name: label for name, (label, _description) in PERMISSIONS.items()},
        sign_in_labels=SIGN_IN_LABELS,
        sign_in_meanings=SIGN_IN_MEANINGS,
        page_title=f"Effective access: {user.full_name}",
        current_page="users",
    )
