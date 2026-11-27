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
from sqlalchemy import delete, exists, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError
from werkzeug.datastructures import MultiDict

from ..audit import NO_CHANGES_MESSAGE, change, record
from ..auth import ROLE_ORDER, ROLES, current_user, has_permission, permission_required
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
from ..lists.catalogue import location_choices, location_label, parse_place, team_places
from ..lists.views import can_manage_lists
from ..models import (
    BusinessLine,
    Location,
    PermissionSet,
    PermissionSetHolder,
    Region,
    Team,
    TeamMember,
    Tracker,
    TrackerRegion,
    User,
)
from ..naming import description_error, name_error, name_taken
from . import bp
from .impact import move_impact
from .layout import ladder, main_parent_ids, tree_options
from .overview import chart, structure_items
from .people import TeamPerson, reach_counts, team_people
from .person import check_answer, first_name, person_rights, person_teams, person_trackers
from .sits import CYCLE_MESSAGE, Draft, Preview, add_reason, draft_errors, preview, read_draft
from .tracker_moves import (
    TEAM_DELETED_MESSAGE,
    TRACKERS_CHANGED_MESSAGE,
    archive_trackers,
    moving_trackers,
    parse_trackers,
    picker_trackers,
    retired_team_region,
    team_region,
    tracker_move_impact,
)
from .tracker_moves import move_trackers as apply_tracker_moves
from .tree import (
    ALREADY_MEMBER_MESSAGE,
    CHOOSE_ROLE_MESSAGE,
    TEAM_CHOICE_ERROR,
    TeamRow,
    ancestors,
    children_map,
    descendants,
    load_team_rows,
    parse_team_id,
    set_team_parents,
    sorted_by_name,
    team_choices,
    team_labels,
)
from .view_choice import chosen_view, switch_urls

ALREADY_UNDER = "{team} is already under {parent}."
NOT_UNDER = "{team} is not under {parent}."
HAS_CHILDREN_MESSAGE = "This team has teams below it. Remove them from under it or delete them first."
HAS_TRACKERS_MESSAGE = "This team has trackers, including archived ones. Move them to another team first."
CHOOSE_PERSON_MESSAGE = "Choose an active person from the list."
TEAM_TABS = ("people", "below", "trackers")


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


def _higher_teams(labels: dict[int, str], parent_ids: Iterable[int]) -> list[tuple[int, str]]:
    """The higher teams as ``(id, name)``, sorted by name ignoring case."""
    return sorted(((i, labels[i]) for i in parent_ids if i in labels), key=lambda item: (item[1].casefold(), item[1]))


def _to_team(team: Team, tab: str = "people"):
    """Back to the team's page, on ``tab`` unless that is the first tab (the address then stays short)."""
    return redirect(url_for("teams.view", team_id=team.id, tab=tab if tab in TEAM_TABS and tab != "people" else None))


def _place_text(region: Region | None, location: Location | None) -> str | None:
    """A place as the Activity names it, "Geneva, Switzerland (EMEA)" or "EMEA" alone, or ``None`` when unset."""
    if region is None:
        return None
    if location is None:
        return region.code
    return f"{location_label(location.city, location.country_code)} ({region.code})"


def _place_form(team: Team) -> dict[str, str]:
    """The Region and Location choices to preselect for a team: its own, or none when unset."""
    return {"region_id": str(team.region_id or ""), "location_id": str(team.location_id or "")}


def _refuse(team: Team, message: str, back: int | None = None):
    """A refusal by a guard: the change is rolled back and the message shown on the team's page, or on the Teams
    below tab of ``back`` when the change was started there."""
    get_session().rollback()
    flash(message, "danger")
    if back is not None:
        return redirect(url_for("teams.view", team_id=back, tab="below"))
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
    labels = team_labels(rows)
    return {
        "children": children_map(rows),
        "higher": {row.id: _higher_teams(labels, row.parent_ids) for row in rows if len(row.parent_ids) > 1},
        "reach": reach_counts(db),
        "search": {row.id: " ".join([row.name, *names.get(row.id, [])]).lower() for row in rows},
        "current_id": current_id,
        "places": team_places(db),
    }


def _structure_context(
    db, rows: list[TeamRow], current_id: int | None, new_open: bool = False, tree: dict | None = None
) -> dict:
    """What the New view's Structure card and Whole structure layer need beyond ``_tree_context`` (reach, places,
    search, current_id), which every Teams page passes too (spec 2026-11-26-teams-simple-redesign-design.md 4.2, 4.3
    and 4.9). ``tree`` is the caller's ``_tree_context`` result, reused for its reach and places."""
    reach = tree["reach"] if tree is not None else reach_counts(db)
    places = tree["places"] if tree is not None else team_places(db)
    items = structure_items(rows, places, reach)
    for item in items:
        item["url"] = url_for("teams.view", team_id=item["id"])
    # The people the Structure card's search offers (4.2): every active user, so someone in no team can be looked up.
    people = [
        {"name": name, "email": email, "url": url_for("teams.person", user_id=user_id)}
        for user_id, name, email in db.execute(
            select(User.id, User.full_name, User.email)
            .where(User.status == "active")
            .order_by(func.lower(User.full_name), User.id)
        )
    ]
    return {
        "people_items": people,
        "nodes": chart(rows),
        "team_options": tree_options(rows),
        "team_names": team_labels(rows),
        "new_open": new_open,
        "structure_items": items,
    }


def _parent_choice(rows: list[TeamRow], text: str | None) -> str:
    """The id (as text) of the parent to preselect, or an empty string for the top level."""
    parent_id = parse_id(text)
    return str(parent_id) if parent_id is not None and parent_id in {row.id for row in rows} else ""


def _render_index(form, errors: list[str], status: int):
    db = get_session()
    rows = load_team_rows(db)
    view = chosen_view()
    tree = _tree_context(rows, None)
    page = render_template(
        "teams/index_new.html" if view == "new" else "teams/index.html",
        **tree,
        **(_structure_context(db, rows, None, new_open=True, tree=tree) if view == "new" else {}),
        view_urls=switch_urls("teams.index"),
        active_view=view,
        choices=team_choices(get_session()),
        place_choices=location_choices(get_session()),
        selected_parent=form.get("parent_id", "") if form else _parent_choice(rows, request.args.get("parent")),
        form=form,
        new_form=form or {},
        new_errors=errors,
        errors=errors,
        team_total=len(rows),
        page_title="Teams",
        current_page="teams",
    )
    return page, status


@bp.get("")
@permission_required("manage_teams")
def index():
    if chosen_view() == "new":  # the New view opens on the first top-level team; with none, the empty page
        tops = sorted_by_name(row for row in load_team_rows(get_session()) if not row.parent_ids)
        if tops:
            return redirect(
                url_for("teams.view", team_id=tops[0].id, new="1" if request.args.get("new") == "1" else None)
            )
    return _render_index({}, [], 200)


@bp.get("/structure")
@permission_required("manage_teams")
def structure():
    """The old Whole structure address: the structure is now a layer on every New view Teams page (spec 4.9)."""
    return redirect(url_for("teams.index", _anchor="whole-structure"))


@bp.post("")
@permission_required("manage_teams")
def create():
    db = get_session()
    name = request.form.get("name", "").strip()
    description = request.form.get("description", "").strip()
    parent, parent_error = parse_team_id(db, request.form.get("parent_id"))
    also, also_error = parse_team_id(db, request.form.get("also_parent_id"))  # the New view's Also under
    if also is not None and parent is None:
        parent, also = also, None  # Top level with Also under X: it sits under X
    if also is not None and also.id == parent.id:
        also = None  # the same team twice is one link
    region, location, place_error = parse_place(
        db, request.form.get("region_id"), request.form.get("location_id"), None, None
    )
    errors = [
        e
        for e in (
            name_error(db, Team, name, "team"),
            description_error(description),
            parent_error,
            also_error,
            place_error,
        )
        if e
    ]
    if errors:
        return _refuse_create(parent, errors)
    actor = current_user()
    before = snapshot_access(db, actor) if also is not None else None
    parent_path = team_labels(load_team_rows(db)).get(parent.id, parent.name) if parent else None
    place = _place_text(region, location)
    team = Team(name=name, description=description, region_id=region.id, location_id=location.id if location else None)
    db.add(team)
    try:
        db.flush()
        if parent:  # the Sits under team is the main one
            set_team_parents(db, team.id, [parent.id, *([also.id] if also else [])], main_id=parent.id)
            db.flush()
        if also is not None:
            if raises_own_access(db, actor, before):  # a new team has no trackers, so this holds; checked all the same
                db.rollback()
                return _refuse_create(parent, [SELF_PROMOTION_MESSAGE])
        record(
            db,
            user_id=actor.id,
            tracker_id=None,
            action="team_created",
            entity="team",
            entity_id=team.id,
            detail={"name": name, "parent": parent_path, "location": place},
        )
        if also is not None:
            record(
                db,
                user_id=actor.id,
                tracker_id=None,
                action="team_parent_added",
                entity="team",
                entity_id=team.id,
                detail={"team": name, "parent": also.name},
            )
        db.commit()
    except IntegrityError:  # the same name was taken, or the parent, region or location deleted, at the same moment
        db.rollback()
        error = (
            name_error(db, Team, name, "team")
            or parse_place(db, request.form.get("region_id"), request.form.get("location_id"), None, None)[2]
            or TEAM_CHOICE_ERROR
        )
        return _refuse_create(parse_team_id(db, request.form.get("parent_id"))[0], [error])
    flash(f"Created the team {name}.", "success")
    return _to_team(team)


def _refuse_create(parent: Team | None, errors: list[str]):
    """A refused create, shown again with what was typed: in the New view on the Sits under team's page (else the
    first top-level team's) with the New team form open; in Classic, or with no team at all, on the index."""
    if chosen_view() == "new":
        team = parent
        if team is None:
            tops = sorted_by_name(row for row in load_team_rows(get_session()) if not row.parent_ids)
            team = get_session().get(Team, tops[0].id) if tops else None
        if team is not None:
            return _render_team(team, [], 400, form=request.form, new_form=request.form, new_errors=errors)
    return _render_index(request.form, errors, 400)


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


class TrackerRow(NamedTuple):
    tracker: Tracker
    business_line: str
    regions: list[str]


def _tracker_rows(db, team_id: int) -> list[TrackerRow]:
    """The team's trackers by name, each with its business line and its region codes."""
    found = db.execute(
        select(Tracker, BusinessLine.name)
        .outerjoin(BusinessLine, Tracker.business_line_id == BusinessLine.id)
        .where(Tracker.team_id == team_id)
        .order_by(func.lower(Tracker.name), Tracker.id)
    ).all()
    codes: dict[int, list[str]] = {}
    for tracker_id, code in db.execute(
        select(TrackerRegion.tracker_id, Region.code)
        .join(Region, Region.id == TrackerRegion.region_id)
        .where(TrackerRegion.tracker_id.in_([tracker.id for tracker, _ in found]))
        .order_by(func.lower(Region.code), Region.id)
    ):
        codes.setdefault(tracker_id, []).append(code)
    return [TrackerRow(tracker, line or "", codes.get(tracker.id, [])) for tracker, line in found]


def _simple_team_context(db, rows: list[TeamRow], team: Team) -> dict:
    """What a team's page needs in the New view (spec 2026-11-26-teams-simple-redesign-design.md 4.4 and 4.5): the
    Where it sits ladder, the teams that may be put below it, and what its members also see in the teams below."""
    lad = ladder(rows, team.id)
    directly_below = {below.row.id for below in lad.below}
    above = set(ancestors(rows, team.id))

    def reason(team_id: int) -> str | None:
        if team_id == team.id:
            return "this team"
        if team_id in directly_below:
            return "already below"
        if team_id in above:
            return "above this team, would make a loop"
        return None

    lower = descendants(rows, team.id) - {team.id}
    lower_trackers = db.scalar(
        select(func.count()).select_from(Tracker).where(Tracker.team_id.in_(lower), Tracker.status != "archived")
    )
    return {
        "ladder": lad,
        "below_options": tree_options(rows, reason),
        "below_trackers": (lower_trackers or 0, len(lower)),
    }


def _sits_context(
    db, rows: list[TeamRow], team: Team, draft: Draft, errors: list[str] | None, back: int | None
) -> dict:
    """What the Where it sits editor needs (spec 4.6): the teams that may be added above, with the reason for those
    that may not, and who the whole draft would give or take access, against what is saved now."""
    saved = set(_row(rows, team).parent_ids)
    unchanged = set(draft.above) == saved  # the same higher teams (perhaps another main): no one's access changes
    return {
        "sits_options": tree_options(rows, add_reason(rows, team.id, draft)),
        "sits_preview": Preview([], [], []) if unchanged else preview(move_impact(db, team, frozenset(draft.above))),
        "sits_errors": errors or [],
        "sits_back": back,
    }


def _render_team(
    team: Team,
    errors: list[str],
    status: int,
    form=None,
    editing: bool = False,
    tab: str = "people",
    picking: bool = False,
    picked: frozenset[int] = frozenset(),
    new_form=None,
    new_errors: list[str] | None = None,
    sits: Draft | None = None,
    sits_errors: list[str] | None = None,
    sits_back: int | None = None,
):
    """The team's page with one tab open; ``picking`` opens the Trackers tab's picker, whose ``picked`` boxes are
    ticked, and shows ``errors`` there instead of in the header."""
    db = get_session()
    rows = load_team_rows(db)
    labels = team_labels(rows)
    people = [_person_row(person) for person in team_people(db, team.id)]
    people.sort(key=lambda row: row.person.direct_role is None)  # direct members first; the order by name is kept
    direct_ids = {row.person.user.id for row in people if row.person.direct_role is not None}
    counted = [row for row in people if row.person.user.status == "active"]  # the counts leave out inactive people
    candidates = [
        user
        for user in db.scalars(
            select(User).where(User.status == "active").order_by(func.lower(User.full_name), User.id)
        )
        if user.id not in direct_ids
    ]
    trackers = _tracker_rows(db, team.id)
    context = _tree_context(rows, team.id)
    below = context["children"].get(team.id, [])
    tracker_counts = dict(
        db.execute(
            select(Tracker.team_id, func.count())
            .where(Tracker.team_id.in_([r.id for r in below]))
            .group_by(Tracker.team_id)
        ).all()
    )
    excluded = {team.id, *(row.id for row in below), *ancestors(rows, team.id)}  # itself, direct lower, all higher
    view = chosen_view()
    if view == "new" and tab == "below":  # the New view has no Teams below tab: the ladder shows them
        tab = "people"
    page = render_template(
        "teams/team_new.html" if view == "new" else "teams/team.html",
        **(_simple_team_context(db, rows, team) if view == "new" else {}),
        **(_sits_context(db, rows, team, sits, sits_errors, sits_back) if view == "new" and sits is not None else {}),
        sits=sits if view == "new" else None,
        **(
            _structure_context(
                db, rows, team.id, new_open=new_form is not None or request.args.get("new") == "1", tree=context
            )
            if view == "new"
            else {}
        ),
        new_form=new_form or {},
        new_errors=new_errors or [],
        selected_parent=new_form.get("parent_id", "") if new_form is not None else str(team.id),
        team_total=len(rows),
        **context,
        view_urls=switch_urls("teams.view", team_id=team.id, tab=tab if tab in TEAM_TABS and tab != "people" else None),
        active_view=view,
        existing_teams=[(row.id, row.name) for row in sorted_by_name(rows) if row.id not in excluded],
        team=team,
        under=_higher_teams(labels, _row(rows, team).parent_ids),
        people=people,
        active_people=len(counted),
        direct_count=sum(1 for row in counted if row.person.direct_role is not None),
        inherited_count=sum(1 for row in counted if row.person.inherited),
        below=below,
        tracker_counts=tracker_counts,
        candidates=candidates,
        trackers=trackers,
        active_trackers=sum(1 for row in trackers if row.tracker.status != "archived"),
        roles=ROLES,
        can_add=current_user().is_admin or not team_holds_sets(db, team.id),
        add_refusal=TEAM_WITH_SETS_MESSAGE,
        delete_blocker=_delete_blocker(team.id, rows),
        # Edit details keeps the team's own retired region and location; the New team form offers none retired
        place_choices=location_choices(db, team.region_id, team.location_id) if editing else location_choices(db),
        place=context["places"].get(team.id),
        form=form or {"name": team.name, "description": team.description, **_place_form(team)},
        errors=errors,
        editing=editing,
        tab=tab if tab in TEAM_TABS else "people",
        picking=picking,
        pick=picker_trackers(db, team) if picking else [],
        pick_region=getattr(team_region(db, team), "code", None) if picking else None,
        picked=picked,
        page_title=team.name,
        current_page="teams",
    )
    return page, status


@bp.get("/people/<int:user_id>")
@permission_required("manage_teams")
def person(user_id: int):
    """One person's teams, trackers and rights (spec 2026-11-26-teams-simple-redesign-design.md 4.8), beside the
    Structure card marking their teams. It has no Classic version (plan PR 4, R1)."""
    db = get_session()
    user = db.get(User, user_id) if in_range(user_id) else None
    if user is None or user.status == "deleted":
        abort(404)
    rows = load_team_rows(db)
    tree = _tree_context(rows, None)
    teams = person_teams(db, rows, user)
    actor = current_user()
    show_rights = actor.is_admin or has_permission(actor, "manage_users")
    trackers = db.scalars(select(Tracker).order_by(func.lower(Tracker.name), Tracker.id)).all()
    check_id = parse_id(request.args.get("check"))
    checked = next((tracker for tracker in trackers if tracker.id == check_id), None)
    page = render_template(
        "teams/person_new.html",
        **tree,
        **_structure_context(db, rows, None, tree=tree),
        view_urls=switch_urls("teams.index"),
        active_view="new",
        team_total=len(rows),
        place_choices=location_choices(db),
        selected_parent="",
        form={},
        new_form={},
        new_errors=[],
        person=user,
        first=first_name(user),
        teams=teams,
        person_marks={
            line.team.id: ("member", f"Member · {line.role.title()}") if line.member else ("through", line.how)
            for line in teams
        },
        seen=person_trackers(db, rows, user),
        show_rights=show_rights,
        rights=person_rights(db, user) if show_rights else [],
        can_open_users=has_permission(actor, "manage_users"),
        all_trackers=trackers,
        check_id=checked.id if checked else None,
        answer=check_answer(db, rows, user, checked) if checked else None,
        page_title=user.full_name,
        current_page="teams",
    )
    return page, 200


@bp.get("/<int:team_id>/below")
@permission_required("manage_teams")
def add_below(team_id: int):
    """Place an existing team under this one: on to that team's Higher teams preview, which returns to this tab."""
    team = _team_or_404(team_id)
    child, error = parse_team_id(get_session(), request.args.get("team_id"))
    if child is None:
        return _render_team(team, [error or TEAM_CHOICE_ERROR], 400, tab="below")
    if chosen_view() == "new":  # the Where it sits editor of the team being placed, with this team added
        return redirect(url_for("teams.sits", team_id=child.id, add=team.id, back=team.id))
    return redirect(url_for("teams.parents", team_id=child.id, add=team.id, back=team.id))


@bp.get("/<int:team_id>")
@permission_required("manage_teams")
def view(team_id: int):
    tab = request.args.get("tab", "")
    return _render_team(
        _team_or_404(team_id),
        [],
        200,
        editing=request.args.get("edit") == "1",
        tab=tab,
        picking=tab == "trackers" and request.args.get("add") == "1",
    )


# --- Trackers moved into the team -----------------------------------------------------------------------------------


def _chosen_trackers(team: Team, texts: list[str]):
    """``(trackers, None)`` for a valid choice, else ``(None, response)``: the picker again, with the error."""
    trackers, error = parse_trackers(get_session(), team, texts)
    if error:
        picked = frozenset(i for i in map(parse_id, texts) if i is not None)
        return None, _render_team(team, [error], 400, tab="trackers", picking=True, picked=picked)
    return trackers, None


def _move_race(team_id: int):
    """After a move failed because someone changed the trackers or deleted the team at the same moment: roll back and
    say which, on the picker again or, when the team is gone, on the Teams page."""
    db = get_session()
    db.rollback()
    if db.scalar(select(Team.id).where(Team.id == team_id)) is None:
        flash(TEAM_DELETED_MESSAGE, "danger")
        return redirect(url_for("teams.index"))
    flash(TRACKERS_CHANGED_MESSAGE, "danger")
    return redirect(url_for("teams.view", team_id=team_id, tab="trackers", add=1))


def _asks_to_archive(team: Team, trackers: list[Tracker]) -> bool:
    """Whether moving the trackers asks to archive them: the team's region is retired, so they gain no region, and
    the actor may retire regions (the owner's rule) and is moving at least one active tracker."""
    return (
        can_manage_lists(current_user())
        and retired_team_region(get_session(), team) is not None
        and any(tracker.status != "archived" for tracker in trackers)
    )


@bp.get("/<int:team_id>/trackers", endpoint="move_trackers")
@permission_required("manage_teams")
def preview_tracker_moves(team_id: int):
    """What moving the chosen trackers into the team would change, with the button that does it."""
    team = _team_or_404(team_id)
    trackers, refusal = _chosen_trackers(team, request.args.getlist("tracker_id"))
    if refusal:
        return refusal
    db = get_session()
    region = team_region(db, team)
    try:  # the preview makes the move in a savepoint, which fails like the move itself
        impact = tracker_move_impact(db, team, trackers)
    except (IntegrityError, StaleDataError):
        return _move_race(team_id)  # not team.id: the failed flush leaves the session to be rolled back first
    retired = retired_team_region(db, team)
    ids = [tracker.id for tracker in trackers]
    asks = _asks_to_archive(team, trackers)
    page = render_template(
        "teams/move_trackers.html",
        team=team,
        moving=moving_trackers(db, team, trackers),
        region=region.code if region else None,
        retired=retired.code if retired else None,
        asks=asks,
        asking=asks and request.args.get("ask") == "1",
        to_archive=sum(1 for tracker in trackers if tracker.status != "archived"),
        preview_url=url_for("teams.move_trackers", team_id=team.id, tracker_id=ids),
        ask_url=url_for("teams.move_trackers", team_id=team.id, tracker_id=ids, ask=1),
        impact=impact,
        page_title=f"Move trackers to {team.name}",
        current_page="teams",
    )
    return page, 200


@bp.post("/<int:team_id>/trackers", endpoint="confirm_move_trackers")
@permission_required("manage_teams")
def confirm_tracker_moves(team_id: int):
    team = _team_or_404(team_id)
    trackers, refusal = _chosen_trackers(team, request.form.getlist("tracker_id"))
    if refusal:
        return refusal
    db = get_session()
    actor = current_user()
    back = redirect(url_for("teams.view", team_id=team.id, tab="trackers"))
    names, team_name = [tracker.name for tracker in trackers], team.name
    archive = request.form.get("archive") == "yes" and _asks_to_archive(team, trackers)
    before = snapshot_access(db, actor)
    try:  # flushed by the guard's query, so a change made at the same moment fails there or on commit
        apply_tracker_moves(db, actor, team, trackers)
        if archive:
            archive_trackers(db, actor, trackers)
        if raises_own_access(db, actor, before):
            db.rollback()
            flash(SELF_PROMOTION_MESSAGE, "danger")
            return back
        db.commit()
    except (IntegrityError, StaleDataError):  # the team or a tracker was deleted, or a region added, at that moment
        return _move_race(team_id)  # not team.id: the failed flush leaves the session to be rolled back first
    moved = names[0] if len(names) == 1 else f"{len(names)} trackers"
    archived = f" and archived {'it' if len(names) == 1 else 'them'}" if archive else ""
    flash(f"Moved {moved} to {team_name}{archived}.", "success")
    return back


@bp.post("/<int:team_id>/rename")
@permission_required("manage_teams")
def rename(team_id: int):
    team = _team_or_404(team_id)
    db = get_session()
    tab = request.form.get("tab", "")
    submitted = {
        "name": request.form.get("name", "").strip(),
        "description": request.form.get("description", "").strip(),
    }
    region_text, location_text = request.form.get("region_id", ""), request.form.get("location_id", "")
    form = {**submitted, "region_id": region_text.strip(), "location_id": location_text.strip()}
    region, location, place_error = parse_place(db, region_text, location_text, team.region_id, team.location_id)
    location_id = location.id if location else None
    errors = [
        e
        for e in (
            name_error(db, Team, submitted["name"], "team", team.id),
            description_error(submitted["description"]),
            place_error,
        )
        if e
    ]
    if errors:
        return _render_team(team, errors, 400, form=form, editing=True, tab=tab)
    before = {field: getattr(team, field) for field, value in submitted.items() if getattr(team, field) != value}
    after = {field: submitted[field] for field in before}
    if (region.id, location_id) != (team.region_id, team.location_id):
        before["location"] = _place_text(
            db.get(Region, team.region_id) if team.region_id else None,
            db.get(Location, team.location_id) if team.location_id else None,
        )
        after["location"] = _place_text(region, location)
    if not before:
        flash(NO_CHANGES_MESSAGE, "info")
        return _to_team(team, tab)
    path = _team_path(team)  # as it was before the change
    for field, value in submitted.items():
        setattr(team, field, value)
    team.region_id, team.location_id = region.id, location_id
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
    except IntegrityError:  # the same name was taken, or the region or location deleted, at the same moment
        db.rollback()
        error = parse_place(db, region_text, location_text, team.region_id, team.location_id)[2] or name_taken("team")
        return _render_team(team, [error], 400, form=form, editing=True, tab=tab)
    flash("Saved the team details.", "success")
    return _to_team(team, tab)


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
    if action in ("add", "move"):  # move: the chosen team becomes its only higher team
        if parent_id in descendants(rows, team.id):
            return parent_id, CYCLE_MESSAGE, None
        if parent_id in current if action == "add" else current == (parent_id,):
            return parent_id, None, ALREADY_UNDER.format(**names)
    elif parent_id not in current:
        return parent_id, None, NOT_UNDER.format(**names)
    return parent_id, None, None


def _back_team(text: str | None) -> int | None:
    """The team a Higher teams change returns to: ``text`` when it names an existing team, else None."""
    team_id = parse_id(text)
    return team_id if team_id is not None and get_session().get(Team, team_id) is not None else None


def _render_parents(
    team: Team,
    errors: list[str],
    status: int,
    change_to: tuple[str, int] | None = None,
    notice: str | None = None,
    back: int | None = None,
):
    """The Higher teams page: the current higher teams, the teams that could be added and, for a valid ``change_to``
    (``("add" | "remove", parent id)``), what that one change would alter."""
    db = get_session()
    rows = load_team_rows(db)
    labels = team_labels(rows)
    current = frozenset(_row(rows, team).parent_ids)
    below = descendants(rows, team.id)
    impact = None
    after = None
    if change_to is not None and not errors and notice is None:
        action, parent_id = change_to
        after = {"add": current | {parent_id}, "move": frozenset({parent_id})}.get(action, current - {parent_id})
        impact = move_impact(db, team, after)
    view = chosen_view()
    page = render_template(
        "teams/parents.html",
        view_urls=switch_urls("teams.parents", team_id=team.id),
        active_view=view,
        team=team,
        higher=[(row.id, row.name) for row in sorted_by_name(row for row in rows if row.id in current)],
        choices=[(row.id, row.name) for row in sorted_by_name(rows) if row.id not in below | current],
        change_to=change_to,
        target=labels.get(change_to[1]) if change_to else None,
        impact=impact,
        notice=notice,
        back=back,
        back_name=next((row.name for row in rows if row.id == back), None),
        errors=errors,
        page_title=f"Higher teams for {team.name}",
        current_page="teams",
    )
    return page, status


@bp.get("/<int:team_id>/parents")
@permission_required("manage_teams")
def parents(team_id: int):
    team = _team_or_404(team_id)
    if chosen_view() == "new":  # the New view changes where a team sits in its editor
        return redirect(
            url_for("teams.sits", team_id=team.id, add=request.args.get("add"), back=request.args.get("back"))
        )
    action = next((key for key in ("add", "remove", "move") if key in request.args), None)
    text = request.args.get(action, "") if action else ""
    if action is None and "to" in request.args:  # the New view's form: a team, and whether to keep the others
        action = "move" if request.args.get("how") == "move" else "add"
        text = request.args["to"]
    back = _back_team(request.args.get("back"))
    if action is None:
        return _render_parents(team, [], 200, back=back)
    parent_id, error, notice = _judge_change(load_team_rows(get_session()), team, action, text.strip())
    if error:
        return _render_parents(team, [error], 400, back=back)
    if notice and back is not None:  # someone made or undid the change already: nothing to confirm
        flash(notice, "info")
        return redirect(url_for("teams.view", team_id=back, tab="below"))
    return _render_parents(team, [], 200, (action, parent_id), notice, back)


@bp.post("/<int:team_id>/parents")
@permission_required("manage_teams")
def change_parents(team_id: int):
    team = _team_or_404(team_id)
    db = get_session()
    action = request.form.get("action", "")
    if action not in ("add", "remove", "move"):
        abort(400)
    rows = load_team_rows(db, lock=True)  # held until commit or rollback, so a concurrent change cannot form a cycle
    if team.id not in {row.id for row in rows}:
        db.rollback()
        abort(404)
    parent_id, error, notice = _judge_change(rows, team, action, request.form.get("parent_id", "").strip())
    back = _back_team(request.form.get("back"))
    if error or notice:
        db.rollback()
        if error:
            return _render_parents(team, [error], 400, back=back)
        flash(notice, "info")
        if back is not None:
            return redirect(url_for("teams.view", team_id=back, tab="below"))
        return redirect(url_for("teams.parents", team_id=team.id))
    actor = current_user()
    before = snapshot_access(db, actor)
    current = set(_row(rows, team).parent_ids)
    if action == "add":  # set_team_parents keeps the main: the current one, or this one for a top-level team
        set_team_parents(db, team.id, current | {parent_id})
        changes = [("team_parent_added", parent_id)]
    elif action == "remove":  # taking out the main passes it to the next by name
        set_team_parents(db, team.id, current - {parent_id})
        changes = [("team_parent_removed", parent_id)]
    else:  # move: the chosen team becomes the only higher team
        set_team_parents(db, team.id, [parent_id])
        changes = [("team_parent_removed", dropped) for dropped in sorted(current - {parent_id})]
        changes += [("team_parent_added", parent_id)] if parent_id not in current else []
    if raises_own_access(db, actor, before):
        return _refuse(team, SELF_PROMOTION_MESSAGE, back)
    labels = team_labels(rows)
    for logged_action, changed_id in changes:
        record(
            db,
            user_id=actor.id,
            tracker_id=None,
            action=logged_action,
            entity="team",
            entity_id=team.id,
            detail={"team": labels[team.id], "parent": labels[changed_id]},
        )
    db.commit()
    if action == "move":
        flash(f"Moved {team.name} under {labels[parent_id]}.", "success")
    elif action == "add":
        flash(f"Added {team.name} under {labels[parent_id]}.", "success")
    else:
        message = f"Removed {team.name} from under {labels[parent_id]}."
        if set(_row(rows, team).parent_ids) == {parent_id}:
            message += " It is now at the top level."
        flash(message, "success")
    if back is not None:
        return redirect(url_for("teams.view", team_id=back, tab="below"))
    return redirect(url_for("teams.parents", team_id=team.id))


# --- Where it sits, the New view's editor (spec 4.6) ----------------------------------------------------------------


@bp.get("/<int:team_id>/sits")
@permission_required("manage_teams")
def sits(team_id: int):
    """The Where it sits editor: the draft in the address, changed by Add, Make main and Take out, then one Save."""
    team = _team_or_404(team_id)
    if chosen_view() != "new":
        return redirect(url_for("teams.parents", team_id=team.id))
    draft = read_draft(load_team_rows(get_session()), team.id, request.args)
    return _render_team(team, [], 200, sits=draft, sits_back=_back_team(request.args.get("back")))


@bp.post("/<int:team_id>/sits")
@permission_required("manage_teams")
def save_sits(team_id: int):
    """Save the whole draft at once: every link added or taken out and the main team, under the lock and one
    self-promotion check over the combined change."""
    team = _team_or_404(team_id)
    db = get_session()
    rows = load_team_rows(db, lock=True)  # held until commit or rollback, so a concurrent change cannot form a cycle
    if team.id not in {row.id for row in rows}:
        db.rollback()
        abort(404)
    back = _back_team(request.form.get("back"))
    above, main = request.form.getlist("above"), request.form.get("main", "")
    draft, errors = draft_errors(rows, team.id, above, main)
    if errors:
        db.rollback()
        posted = read_draft(
            load_team_rows(db), team.id, MultiDict([("draft", "1"), ("main", main), *(("above", a) for a in above)])
        )
        return _render_team(team, [], 400, sits=posted, sits_errors=errors, sits_back=back)
    current = set(_row(rows, team).parent_ids)
    current_main = main_parent_ids(rows).get(team.id)
    target = back if back is not None else team.id
    if set(draft.above) == current and draft.main == current_main:
        db.rollback()
        flash(NO_CHANGES_MESSAGE, "info")
        return redirect(url_for("teams.view", team_id=target))
    actor = current_user()
    before = snapshot_access(db, actor)
    set_team_parents(db, team.id, draft.above, main_id=draft.main)
    if set(draft.above) != current and raises_own_access(db, actor, before):  # the main alone changes no access
        db.rollback()  # the editor again, with the draft kept and the reason inside it
        return _render_team(team, [], 400, sits=draft, sits_errors=[SELF_PROMOTION_MESSAGE], sits_back=back)
    labels = team_labels(rows)
    changes = [("team_parent_removed", dropped) for dropped in sorted(current - set(draft.above))]
    changes += [("team_parent_added", added) for added in sorted(set(draft.above) - current)]
    for logged_action, changed_id in changes:
        record(
            db,
            user_id=actor.id,
            tracker_id=None,
            action=logged_action,
            entity="team",
            entity_id=team.id,
            detail={"team": labels[team.id], "parent": labels[changed_id]},
        )
    if current_main is not None and draft.main is not None and draft.main != current_main:
        record(
            db,
            user_id=actor.id,
            tracker_id=None,
            action="team_main_set",
            entity="team",
            entity_id=team.id,
            detail={"team": labels[team.id], "before": labels[current_main], "after": labels[draft.main]},
        )
    db.commit()
    flash(f"Saved where {team.name} sits.", "success")
    return redirect(url_for("teams.view", team_id=target))


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
