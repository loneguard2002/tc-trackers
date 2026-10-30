"""Teams screens (spec sections 6.3, 6.4, 7 and 8.1): the tree, a team's page and its members.

Every change is committed with its activity entries in one transaction, and the entries name teams by their path from
the top of the tree. A change that could raise the actor's own tracker access (moving a team, adding a member,
changing a role) goes through the self-promotion guard of ``tracker/auth/guards.py``: input is validated first, the
access snapshot is taken before any object is touched, and a refused change is rolled back. A non-administrator cannot
give a team place or a member role to an account they created or whose password they reset (``vouched_refusal``).
"""

from __future__ import annotations

from flask import abort, flash, redirect, render_template, request, url_for
from sqlalchemy import delete, exists, func, select
from sqlalchemy.exc import IntegrityError

from ..audit import NO_CHANGES_MESSAGE, change, record
from ..auth import ROLES, current_user, permission_required
from ..auth.accounts import vouched_refusal
from ..auth.guards import (
    SELF_PROMOTION_MESSAGE,
    TEAM_WITH_SETS_MESSAGE,
    raises_own_access,
    snapshot_access,
    team_holds_sets,
)
from ..db import get_session
from ..ids import in_range, parse_id
from ..models import PermissionSet, PermissionSetHolder, Team, TeamMember, Tracker, User
from ..naming import description_error, name_error, name_taken
from . import bp
from .tree import (
    ALREADY_MEMBER_MESSAGE,
    CHOOSE_ROLE_MESSAGE,
    TEAM_CHOICE_ERROR,
    TeamRow,
    children_map,
    descendants,
    load_team_rows,
    order_tree,
    parse_team_id,
    team_choices,
    team_labels,
)

CYCLE_MESSAGE = "A team cannot be moved under itself or under a team below it."
HAS_CHILDREN_MESSAGE = "This team has teams below it. Move or delete them first."
HAS_TRACKERS_MESSAGE = "This team has trackers, including archived ones. Move them to another team first."
CHOOSE_PERSON_MESSAGE = "Choose an active person from the list."
TOP_LEVEL = "Top level"


def _team_or_404(team_id: int) -> Team:
    team = get_session().get(Team, team_id) if in_range(team_id) else None
    if team is None:
        abort(404)
    return team


def _counts(column) -> dict[int, int]:
    return dict(get_session().execute(select(column, func.count()).where(column.is_not(None)).group_by(column)).all())


def _delete_blocker(team_id: int, rows: list[TeamRow]) -> str | None:
    """Why the team cannot be deleted (spec section 6.4), or ``None``."""
    if any(row.parent_id == team_id for row in rows):
        return HAS_CHILDREN_MESSAGE
    if get_session().scalar(select(exists().where(Tracker.team_id == team_id))):
        return HAS_TRACKERS_MESSAGE
    return None


def _to_team(team: Team):
    return redirect(url_for("teams.view", team_id=team.id))


def _refuse(team: Team, message: str):
    """A refusal by a guard: the change is rolled back and the message shown on the team's page."""
    get_session().rollback()
    flash(message, "danger")
    return _to_team(team)


# --- The tree -------------------------------------------------------------------------------------------------------


def _render_index(form, errors: list[str], status: int):
    rows = load_team_rows(get_session())
    page = render_template(
        "teams/index.html",
        children=children_map(rows),
        member_counts=_counts(TeamMember.team_id),
        tracker_counts=_counts(Tracker.team_id),
        choices=team_choices(get_session()),
        form=form,
        errors=errors,
        page_title="Teams",
        current_page="teams",
    )
    return page, status


@bp.get("")
@permission_required("manage_teams")
def index():
    return _render_index({}, [], 200)


@bp.post("")
@permission_required("manage_teams")
def create():
    db = get_session()
    name = request.form.get("name", "").strip()
    description = request.form.get("description", "").strip()
    parent, parent_error = parse_team_id(db, request.form.get("parent_id"))
    errors = [e for e in (name_error(db, Team, name, "team"), description_error(description), parent_error) if e]
    if errors:
        return _render_index(request.form, errors, 400)
    parent_path = team_labels(load_team_rows(db)).get(parent.id, parent.name) if parent else None
    team = Team(name=name, description=description, parent_id=parent.id if parent else None)
    db.add(team)
    try:
        db.flush()
        record(
            db,
            user_id=current_user().id,
            tracker_id=None,
            action="team_created",
            entity="team",
            entity_id=team.id,
            detail={"name": name, "parent": parent_path},
        )
        db.commit()
    except IntegrityError:  # the same name was taken, or the parent deleted, at the same moment
        db.rollback()
        return _render_index(request.form, [name_error(db, Team, name, "team") or TEAM_CHOICE_ERROR], 400)
    flash(f"Created the team {name}.", "success")
    return _to_team(team)


# --- A team's page --------------------------------------------------------------------------------------------------


def _render_team(team: Team, errors: list[str], status: int, form=None):
    db = get_session()
    rows = load_team_rows(db)
    labels = team_labels(rows)
    below = descendants(rows, team.id)
    members = db.execute(
        select(TeamMember.role, User)
        .join(User, User.id == TeamMember.user_id)
        .where(TeamMember.team_id == team.id)
        .order_by(func.lower(User.full_name), User.id)
    ).all()
    member_ids = {user.id for _role, user in members}
    candidates = [
        user
        for user in db.scalars(
            select(User).where(User.status == "active").order_by(func.lower(User.full_name), User.id)
        )
        if user.id not in member_ids
    ]
    trackers = db.scalars(
        select(Tracker).where(Tracker.team_id == team.id).order_by(func.lower(Tracker.name), Tracker.id)
    ).all()
    page = render_template(
        "teams/team.html",
        team=team,
        path=labels.get(team.id, team.name),
        parent_label=labels.get(team.parent_id, TOP_LEVEL) if team.parent_id else TOP_LEVEL,
        parents=[(row.id, labels[row.id]) for row, _depth in order_tree(rows) if row.id not in below],
        members=members,
        candidates=candidates,
        trackers=trackers,
        roles=ROLES,
        can_add=current_user().is_admin or not team_holds_sets(db, team.id),
        add_refusal=TEAM_WITH_SETS_MESSAGE,
        delete_blocker=_delete_blocker(team.id, rows),
        form=form or {"name": team.name, "description": team.description},
        errors=errors,
        page_title=team.name,
        current_page="teams",
    )
    return page, status


@bp.get("/<int:team_id>")
@permission_required("manage_teams")
def view(team_id: int):
    return _render_team(_team_or_404(team_id), [], 200)


@bp.post("/<int:team_id>/rename")
@permission_required("manage_teams")
def rename(team_id: int):
    team = _team_or_404(team_id)
    db = get_session()
    submitted = {
        "name": request.form.get("name", "").strip(),
        "description": request.form.get("description", "").strip(),
    }
    errors = [
        e
        for e in (name_error(db, Team, submitted["name"], "team", team.id), description_error(submitted["description"]))
        if e
    ]
    if errors:
        return _render_team(team, errors, 400, form=submitted)
    before = {field: getattr(team, field) for field, value in submitted.items() if getattr(team, field) != value}
    if not before:
        flash(NO_CHANGES_MESSAGE, "info")
        return _to_team(team)
    after = {field: submitted[field] for field in before}
    path = _team_path(team)  # as it was before the change
    for field, value in after.items():
        setattr(team, field, value)
    record(
        db,
        user_id=current_user().id,
        tracker_id=None,
        action="team_renamed",
        entity="team",
        entity_id=team.id,
        detail={"team": path, **change(before, after)},
    )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return _render_team(team, [name_taken("team")], 400, form=submitted)
    flash("Saved the team details.", "success")
    return _to_team(team)


@bp.post("/<int:team_id>/move")
@permission_required("manage_teams")
def move(team_id: int):
    team = _team_or_404(team_id)
    db = get_session()
    text = request.form.get("parent_id", "").strip()
    new_parent_id = parse_id(text) if text else None
    if text and new_parent_id is None:
        return _render_team(team, [TEAM_CHOICE_ERROR], 400)
    rows = load_team_rows(db, lock=True)  # held until commit or rollback, so a concurrent move cannot form a cycle
    current = {row.id: row for row in rows}
    if team.id not in current:
        db.rollback()
        abort(404)
    if new_parent_id is not None and new_parent_id not in current:
        db.rollback()
        return _render_team(team, [TEAM_CHOICE_ERROR], 400)
    if new_parent_id is not None and new_parent_id in descendants(rows, team.id):
        db.rollback()
        return _render_team(team, [CYCLE_MESSAGE], 400)
    old_parent_id = current[team.id].parent_id
    if new_parent_id == old_parent_id:
        db.rollback()
        flash(NO_CHANGES_MESSAGE, "info")
        return _to_team(team)
    actor = current_user()
    before = snapshot_access(db, actor)
    team.parent_id = new_parent_id
    if raises_own_access(db, actor, before):
        return _refuse(team, SELF_PROMOTION_MESSAGE)
    labels = team_labels(rows)  # read before the move: the team's path is the one it had
    old_path = labels.get(old_parent_id) if old_parent_id else None
    new_path = labels.get(new_parent_id) if new_parent_id else None
    record(
        db,
        user_id=actor.id,
        tracker_id=None,
        action="team_moved",
        entity="team",
        entity_id=team.id,
        detail={"team": labels[team.id], **change(old_path, new_path)},
    )
    db.commit()
    flash(f"Moved {team.name} to {new_path or 'the top level'}.", "success")
    return _to_team(team)


@bp.post("/<int:team_id>/delete", endpoint="delete")
@permission_required("manage_teams")
def delete_team(team_id: int):
    team = _team_or_404(team_id)
    db = get_session()
    rows = load_team_rows(db, lock=True)  # a team or tracker cannot be put under it until this commits
    current = {row.id: row for row in rows}
    if team.id not in current:
        db.rollback()
        abort(404)
    blocker = _delete_blocker(team.id, rows)
    if blocker:
        db.rollback()
        return _render_team(team, [blocker], 400)
    labels = team_labels(rows)
    path = labels[team.id]
    parent_id = current[team.id].parent_id  # from the locked row: a move just committed has changed it
    actor_id = current_user().id
    memberships = db.execute(
        select(TeamMember.user_id, TeamMember.role).where(TeamMember.team_id == team.id).order_by(TeamMember.user_id)
    ).all()
    for user_id, role in memberships:
        record(
            db,
            user_id=actor_id,
            tracker_id=None,
            action="team_member_removed",
            entity="team",
            entity_id=team.id,
            detail={"team": path, "role": role},
            target_user_id=user_id,
        )
    holdings = db.execute(
        select(PermissionSet.id, PermissionSet.name)
        .join(PermissionSetHolder, PermissionSetHolder.set_id == PermissionSet.id)
        .where(PermissionSetHolder.team_id == team.id)
        .order_by(func.lower(PermissionSet.name), PermissionSet.id)
    ).all()
    for set_id, set_name in holdings:
        record(
            db,
            user_id=actor_id,
            tracker_id=None,
            action="permission_set_holder_removed",
            entity="permission_set",
            entity_id=set_id,
            detail={"set": set_name, "team": path},
        )
    record(
        db,
        user_id=actor_id,
        tracker_id=None,
        action="team_deleted",
        entity="team",
        entity_id=team.id,
        detail={"name": current[team.id].name, "parent": labels.get(parent_id) if parent_id else None},
    )
    db.execute(delete(TeamMember).where(TeamMember.team_id == team.id))
    db.execute(delete(PermissionSetHolder).where(PermissionSetHolder.team_id == team.id))
    db.delete(team)
    db.commit()
    flash(f"Deleted the team {team.name}.", "success")
    return redirect(url_for("teams.index"))


# --- Members --------------------------------------------------------------------------------------------------------


def _team_path(team: Team) -> str:
    return team_labels(load_team_rows(get_session())).get(team.id, team.name)


@bp.post("/<int:team_id>/members")
@permission_required("manage_teams")
def add_member(team_id: int):
    team = _team_or_404(team_id)
    db = get_session()
    actor = current_user()
    if not actor.is_admin and team_holds_sets(db, team.id):
        return _refuse(team, TEAM_WITH_SETS_MESSAGE)
    user_id = parse_id(request.form.get("user_id"))
    user = db.get(User, user_id) if user_id else None
    if user is None or user.status != "active":
        return _render_team(team, [CHOOSE_PERSON_MESSAGE], 400)
    role = request.form.get("role", "")
    if role not in ROLES:
        return _render_team(team, [CHOOSE_ROLE_MESSAGE], 400)
    if db.get(TeamMember, (team.id, user.id)) is not None:
        return _render_team(team, [ALREADY_MEMBER_MESSAGE], 400)
    refusal = vouched_refusal(db, actor, user)
    if refusal:
        return _refuse(team, refusal)
    path = _team_path(team)
    before = snapshot_access(db, actor)
    db.add(TeamMember(team_id=team.id, user_id=user.id, role=role))
    try:
        if raises_own_access(db, actor, before):
            return _refuse(team, SELF_PROMOTION_MESSAGE)
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
        db.commit()
    except IntegrityError:  # added at the same moment by someone else
        db.rollback()
        return _render_team(team, [ALREADY_MEMBER_MESSAGE], 400)
    flash(f"Added {user.full_name} to {team.name} as {role}.", "success")
    return _to_team(team)


@bp.post("/<int:team_id>/members/<int:user_id>")
@permission_required("manage_teams")
def update_member(team_id: int, user_id: int):
    team = _team_or_404(team_id)
    db = get_session()
    membership = db.get(TeamMember, (team.id, user_id)) if in_range(user_id) else None
    if membership is None:
        abort(404)
    user = db.get(User, user_id)
    path = _team_path(team)
    actor = current_user()
    if request.form.get("action") == "remove":
        role = membership.role
        removed = db.execute(
            delete(TeamMember).where(TeamMember.team_id == team.id, TeamMember.user_id == user.id)
        ).rowcount
        if not removed:  # removed by someone else at the same moment
            db.rollback()
            flash(f"{user.full_name} is no longer a member of {team.name}.", "info")
            return _to_team(team)
        record(
            db,
            user_id=actor.id,
            tracker_id=None,
            action="team_member_removed",
            entity="team",
            entity_id=team.id,
            detail={"team": path, "role": role},
            target_user_id=user.id,
        )
        db.commit()
        flash(f"Removed {user.full_name} from {team.name}.", "success")
        return _to_team(team)
    role = request.form.get("role", "")
    if role not in ROLES:
        return _render_team(team, [CHOOSE_ROLE_MESSAGE], 400)
    old = membership.role
    if role == old:
        flash(NO_CHANGES_MESSAGE, "info")
        return _to_team(team)
    refusal = vouched_refusal(db, actor, user)
    if refusal:
        return _refuse(team, refusal)
    before = snapshot_access(db, actor)
    membership.role = role
    if raises_own_access(db, actor, before):
        return _refuse(team, SELF_PROMOTION_MESSAGE)
    record(
        db,
        user_id=actor.id,
        tracker_id=None,
        action="team_member_role_changed",
        entity="team",
        entity_id=team.id,
        detail={"team": path, **change(old, role)},
        target_user_id=user.id,
    )
    db.commit()
    flash(f"{user.full_name} is now {role} in {team.name}.", "success")
    return _to_team(team)
