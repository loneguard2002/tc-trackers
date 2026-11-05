"""Teams screens (spec sections 6.3, 6.4, 7 and 8.1): the tree, a team's page and its members.

Every change is committed with its activity entries in one transaction, and the entries name teams by their names. A
change that could raise the actor's own tracker access (moving a team, adding a member, changing a role) goes through
the self-promotion guard of ``tracker/auth/guards.py``: input is validated first, the access snapshot is taken before
any object is touched, and a refused change is rolled back. A non-administrator cannot give a team place or a member
role to an account they created or whose password they reset (``vouched_refusal``).
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import NamedTuple

from flask import abort, flash, redirect, render_template, request, url_for
from sqlalchemy import delete, exists, func, insert, select
from sqlalchemy.exc import IntegrityError

from ..audit import NO_CHANGES_MESSAGE, change, record
from ..auth import ROLE_ORDER, ROLES, current_user, permission_required
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
from ..lists.catalogue import location_choices, location_label, parse_location, team_places
from ..models import Location, PermissionSet, PermissionSetHolder, Region, Team, TeamMember, TeamParent, Tracker, User
from ..naming import description_error, name_error, name_taken
from . import bp
from .impact import move_impact
from .people import TeamPerson, reach_counts, team_people
from .tree import (
    ALREADY_MEMBER_MESSAGE,
    CHOOSE_ROLE_MESSAGE,
    TEAM_CHOICE_ERROR,
    TeamRow,
    children_map,
    descendants,
    load_team_rows,
    parse_team_id,
    sorted_by_name,
    team_choices,
    team_labels,
)

CYCLE_MESSAGE = "A team cannot be placed under itself or under a team below it."
ALREADY_UNDER = "{team} is already under {parent}."
NOT_UNDER = "{team} is not under {parent}."
HAS_CHILDREN_MESSAGE = "This team has teams below it. Move or delete them first."
HAS_TRACKERS_MESSAGE = "This team has trackers, including archived ones. Move them to another team first."
CHOOSE_PERSON_MESSAGE = "Choose an active person from the list."
TOP_LEVEL = "Top level"


def _team_or_404(team_id: int) -> Team:
    team = get_session().get(Team, team_id) if in_range(team_id) else None
    if team is None:
        abort(404)
    return team


def _delete_blocker(team_id: int, rows: list[TeamRow]) -> str | None:
    """Why the team cannot be deleted (spec section 6.4), or ``None``."""
    if any(team_id in row.parent_ids for row in rows):
        return HAS_CHILDREN_MESSAGE
    if get_session().scalar(select(exists().where(Tracker.team_id == team_id))):
        return HAS_TRACKERS_MESSAGE
    return None


def _row(rows: list[TeamRow], team: Team) -> TeamRow:
    """The team's row, or an empty top-level row for a team deleted at the same moment."""
    return next((row for row in rows if row.id == team.id), TeamRow(team.id, team.name, ()))


def _higher_team_names(labels: dict[int, str], parent_ids: Iterable[int]) -> list[str]:
    """The names of the higher teams, sorted by name ignoring case."""
    return sorted((labels[parent_id] for parent_id in parent_ids), key=lambda name: (name.casefold(), name))


def _higher_teams_text(labels: dict[int, str], parent_ids: Iterable[int]) -> str | None:
    """The higher teams named in a sentence, "Applications and Infrastructure", or ``None`` for the top level."""
    return " and ".join(_higher_team_names(labels, parent_ids)) or None


def _to_team(team: Team):
    return redirect(url_for("teams.view", team_id=team.id))


def _place_text(location: Location | None) -> str | None:
    """A location as the Activity names it, "Geneva, Switzerland (EMEA)", or ``None`` when unset."""
    if location is None:
        return None
    region = get_session().get(Region, location.region_id)
    return f"{location_label(location.city, location.country_code)} ({region.code})"


def _place_form(team: Team) -> dict[str, str]:
    """The Region and Location choices to preselect for a team: its own, or none when unset."""
    location = get_session().get(Location, team.location_id) if team.location_id else None
    if location is None:
        return {"region_id": "", "location_id": ""}
    return {"region_id": str(location.region_id), "location_id": str(location.id)}


def _refuse(team: Team, message: str):
    """A refusal by a guard: the change is rolled back and the message shown on the team's page."""
    get_session().rollback()
    flash(message, "danger")
    return _to_team(team)


# --- The tree -------------------------------------------------------------------------------------------------------


def _tree_context(rows: list[TeamRow], current_id: int | None) -> dict:
    """What the shared tree partial needs: the children, who reaches each team, and each team's search text."""
    db = get_session()
    names: dict[int, list[str]] = {}
    for team_id, full_name in db.execute(
        select(TeamMember.team_id, User.full_name)
        .join(User, User.id == TeamMember.user_id)
        .order_by(func.lower(User.full_name), User.id)
    ):
        names.setdefault(team_id, []).append(full_name)
    return {
        "children": children_map(rows),
        "reach": reach_counts(db),
        "search": {row.id: " ".join([row.name, *names.get(row.id, [])]).lower() for row in rows},
        "current_id": current_id,
        "places": team_places(db),
    }


def _parent_choice(rows: list[TeamRow], text: str | None) -> str:
    """The id (as text) of the parent to preselect, or an empty string for the top level."""
    parent_id = parse_id(text)
    return str(parent_id) if parent_id is not None and parent_id in {row.id for row in rows} else ""


def _render_index(form, errors: list[str], status: int):
    rows = load_team_rows(get_session())
    page = render_template(
        "teams/index.html",
        **_tree_context(rows, None),
        choices=team_choices(get_session()),
        place_choices=location_choices(get_session()),
        selected_parent=form.get("parent_id", "") if form else _parent_choice(rows, request.args.get("parent")),
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
    location, location_error = parse_location(db, request.form.get("region_id"), request.form.get("location_id"), None)
    errors = [
        e
        for e in (name_error(db, Team, name, "team"), description_error(description), parent_error, location_error)
        if e
    ]
    if errors:
        return _render_index(request.form, errors, 400)
    parent_path = team_labels(load_team_rows(db)).get(parent.id, parent.name) if parent else None
    place = _place_text(location)
    team = Team(name=name, description=description, location_id=location.id)
    db.add(team)
    try:
        db.flush()
        if parent:
            db.add(TeamParent(team_id=team.id, parent_id=parent.id))
            db.flush()
        record(
            db,
            user_id=current_user().id,
            tracker_id=None,
            action="team_created",
            entity="team",
            entity_id=team.id,
            detail={"name": name, "parent": parent_path, "location": place},
        )
        db.commit()
    except IntegrityError:  # the same name was taken, or the parent or location deleted, at the same moment
        db.rollback()
        error = (
            name_error(db, Team, name, "team")
            or parse_location(db, request.form.get("region_id"), request.form.get("location_id"), None)[1]
            or TEAM_CHOICE_ERROR
        )
        return _render_index(request.form, [error], 400)
    flash(f"Created the team {name}.", "success")
    return _to_team(team)


# --- A team's page --------------------------------------------------------------------------------------------------


class PersonRow(NamedTuple):
    """One line of the People table."""

    person: TeamPerson
    route: str  # "direct", "inherited" or "direct inherited": what the row filter matches
    note: str | None  # "Owner from Infrastructure", for a direct member whose inherited role is higher


def _person_row(person: TeamPerson) -> PersonRow:
    route = " ".join(r for r, present in (("direct", person.direct_role), ("inherited", person.inherited)) if present)
    note = None
    if person.direct_role is not None and person.inherited:
        top = max(person.inherited, key=lambda inherit: ROLE_ORDER[inherit.role])  # the nearest team on a tie
        if ROLE_ORDER[top.role] > ROLE_ORDER[person.direct_role]:
            note = f"{top.role.title()} from {top.team_name}"
    return PersonRow(person, route, note)


def _render_team(team: Team, errors: list[str], status: int, form=None, open_details: bool = False):
    db = get_session()
    rows = load_team_rows(db)
    labels = team_labels(rows)
    people = [_person_row(person) for person in team_people(db, team.id)]
    people.sort(key=lambda row: row.person.direct_role is None)  # direct members first; the order by name is kept
    direct_ids = {row.person.user.id for row in people if row.person.direct_role is not None}
    candidates = [
        user
        for user in db.scalars(
            select(User).where(User.status == "active").order_by(func.lower(User.full_name), User.id)
        )
        if user.id not in direct_ids
    ]
    trackers = db.scalars(
        select(Tracker).where(Tracker.team_id == team.id).order_by(func.lower(Tracker.name), Tracker.id)
    ).all()
    context = _tree_context(rows, team.id)
    page = render_template(
        "teams/team.html",
        **context,
        team=team,
        path=labels.get(team.id, team.name),
        parent_label=_higher_teams_text(labels, _row(rows, team).parent_ids) or TOP_LEVEL,
        people=people,
        direct_count=sum(1 for row in people if row.person.direct_role is not None),
        inherited_count=sum(1 for row in people if row.person.inherited),
        below=context["children"].get(team.id, []),
        candidates=candidates,
        trackers=trackers,
        roles=ROLES,
        can_add=current_user().is_admin or not team_holds_sets(db, team.id),
        add_refusal=TEAM_WITH_SETS_MESSAGE,
        delete_blocker=_delete_blocker(team.id, rows),
        place_choices=location_choices(db, team.location_id),
        place=context["places"].get(team.id),
        form=form or {"name": team.name, "description": team.description, **_place_form(team)},
        errors=errors,
        open_details=open_details,
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
    region_text, location_text = request.form.get("region_id", ""), request.form.get("location_id", "")
    form = {**submitted, "region_id": region_text.strip(), "location_id": location_text.strip()}
    location, location_error = parse_location(db, region_text, location_text, team.location_id)
    errors = [
        e
        for e in (
            name_error(db, Team, submitted["name"], "team", team.id),
            description_error(submitted["description"]),
            location_error,
        )
        if e
    ]
    if errors:
        return _render_team(team, errors, 400, form=form, open_details=True)
    before = {field: getattr(team, field) for field, value in submitted.items() if getattr(team, field) != value}
    after = {field: submitted[field] for field in before}
    if location.id != team.location_id:
        before["location"] = _place_text(db.get(Location, team.location_id) if team.location_id else None)
        after["location"] = _place_text(location)
    if not before:
        flash(NO_CHANGES_MESSAGE, "info")
        return _to_team(team)
    path = _team_path(team)  # as it was before the change
    for field, value in submitted.items():
        setattr(team, field, value)
    team.location_id = location.id
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
    except IntegrityError:  # the same name was taken, or the location deleted, at the same moment
        db.rollback()
        error = parse_location(db, region_text, location_text, team.location_id)[1] or name_taken("team")
        return _render_team(team, [error], 400, form=form, open_details=True)
    flash("Saved the team details.", "success")
    return _to_team(team)


def _judge_change(rows: list[TeamRow], team: Team, action: str, text: str) -> tuple[int | None, str | None, str | None]:
    """Check one change to the team's higher teams: ``(parent id, error, notice)``.

    An error is a refusal (status 400); a notice says the change would do nothing.
    """
    parent_id = parse_id(text)
    labels = team_labels(rows)
    if parent_id is None or parent_id not in labels:
        return None, TEAM_CHOICE_ERROR, None
    current = _row(rows, team).parent_ids
    names = {"team": team.name, "parent": labels[parent_id]}
    if action == "add":
        if parent_id in descendants(rows, team.id):
            return parent_id, CYCLE_MESSAGE, None
        if parent_id in current:
            return parent_id, None, ALREADY_UNDER.format(**names)
    elif parent_id not in current:
        return parent_id, None, NOT_UNDER.format(**names)
    return parent_id, None, None


def _render_parents(
    team: Team,
    errors: list[str],
    status: int,
    change_to: tuple[str, int] | None = None,
    notice: str | None = None,
):
    """The Higher teams page: the current higher teams, the teams that could be added and, for a valid ``change_to``
    (``("add" | "remove", parent id)``), what that one change would alter."""
    db = get_session()
    rows = load_team_rows(db)
    labels = team_labels(rows)
    current = frozenset(_row(rows, team).parent_ids)
    below = descendants(rows, team.id)
    impact = None
    if change_to is not None and not errors and notice is None:
        action, parent_id = change_to
        impact = move_impact(db, team, current | {parent_id} if action == "add" else current - {parent_id})
    page = render_template(
        "teams/parents.html",
        team=team,
        higher=[(row.id, row.name) for row in sorted_by_name(row for row in rows if row.id in current)],
        choices=[(row.id, row.name) for row in sorted_by_name(rows) if row.id not in below | current],
        change_to=change_to,
        target=labels.get(change_to[1]) if change_to else None,
        impact=impact,
        notice=notice,
        errors=errors,
        page_title=f"Higher teams for {team.name}",
        current_page="teams",
    )
    return page, status


@bp.get("/<int:team_id>/parents")
@permission_required("manage_teams")
def parents(team_id: int):
    team = _team_or_404(team_id)
    action = "add" if "add" in request.args else "remove" if "remove" in request.args else None
    if action is None:
        return _render_parents(team, [], 200)
    parent_id, error, notice = _judge_change(load_team_rows(get_session()), team, action, request.args[action].strip())
    if error:
        return _render_parents(team, [error], 400)
    return _render_parents(team, [], 200, (action, parent_id), notice)


@bp.post("/<int:team_id>/parents")
@permission_required("manage_teams")
def change_parents(team_id: int):
    team = _team_or_404(team_id)
    db = get_session()
    action = request.form.get("action", "")
    if action not in ("add", "remove"):
        abort(400)
    rows = load_team_rows(db, lock=True)  # held until commit or rollback, so a concurrent change cannot form a cycle
    if team.id not in {row.id for row in rows}:
        db.rollback()
        abort(404)
    parent_id, error, notice = _judge_change(rows, team, action, request.form.get("parent_id", "").strip())
    if error or notice:
        db.rollback()
        if error:
            return _render_parents(team, [error], 400)
        flash(notice, "info")
        return redirect(url_for("teams.parents", team_id=team.id))
    actor = current_user()
    before = snapshot_access(db, actor)
    if action == "add":
        db.execute(insert(TeamParent).values(team_id=team.id, parent_id=parent_id))
    else:
        db.execute(delete(TeamParent).where(TeamParent.team_id == team.id, TeamParent.parent_id == parent_id))
    if raises_own_access(db, actor, before):
        return _refuse(team, SELF_PROMOTION_MESSAGE)
    labels = team_labels(rows)
    record(
        db,
        user_id=actor.id,
        tracker_id=None,
        action="team_parent_added" if action == "add" else "team_parent_removed",
        entity="team",
        entity_id=team.id,
        detail={"team": labels[team.id], "parent": labels[parent_id]},
    )
    db.commit()
    if action == "add":
        flash(f"Added {team.name} under {labels[parent_id]}.", "success")
    else:
        message = f"Removed {team.name} from under {labels[parent_id]}."
        if set(_row(rows, team).parent_ids) == {parent_id}:
            message += " It is now at the top level."
        flash(message, "success")
    return redirect(url_for("teams.parents", team_id=team.id))


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
        return _render_team(team, [blocker], 400, open_details=True)
    labels = team_labels(rows)
    path = labels[team.id]
    parent_ids = current[team.id].parent_ids  # read under the lock: a move just committed has changed them
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
        detail={"name": current[team.id].name, "parents": _higher_team_names(labels, parent_ids)},
    )
    db.execute(delete(TeamMember).where(TeamMember.team_id == team.id))
    db.execute(delete(PermissionSetHolder).where(PermissionSetHolder.team_id == team.id))
    name = current[team.id].name  # from the locked row: a rename just committed has changed it
    db.delete(team)
    db.commit()
    flash(f"Deleted the team {name}.", "success")
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
    # Lowering a member's role gives nothing, so only a higher role is refused.
    refusal = vouched_refusal(db, actor, user) if ROLE_ORDER[role] > ROLE_ORDER[old] else None
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
