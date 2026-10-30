"""Teams screens: the tree, team pages, members and the guards on them (database required)."""

import html
import re

from sqlalchemy import func, select

from tests.conftest import post, sign_in
from tracker.auth.guards import SELF_PROMOTION_MESSAGE, TEAM_WITH_SETS_MESSAGE, team_holds_sets
from tracker.models import AuditLog, PermissionSet, PermissionSetHolder, Team, TeamMember
from tracker.naming import description_error, name_error
from tracker.teams.views import CYCLE_MESSAGE


def text_of(response) -> str:
    return html.unescape(response.get_data(as_text=True))


def entries(db, action: str | None = None) -> list[AuditLog]:
    query = select(AuditLog).order_by(AuditLog.id)
    if action:
        query = query.where(AuditLog.action == action)
    return list(db.scalars(query))


def member_role(db, team, user) -> str | None:
    return db.scalar(select(TeamMember.role).where(TeamMember.team_id == team.id, TeamMember.user_id == user.id))


def parent_of(db, team) -> int | None:
    db.expire_all()
    return db.scalar(select(Team.parent_id).where(Team.id == team.id))


def move_options(page: str) -> list[str]:
    select_html = re.search(r'<select id="parent_id-move".*?</select>', page, re.S).group(0)
    return re.findall(r'<option value="(\d*)"', select_html)


def holder(user_factory, give_set, client):
    """A non-administrator who holds manage_teams, signed in."""
    user = user_factory(full_name="Holder")
    give_set(["manage_teams"], user=user)
    sign_in(client, user)
    return user


# --- Shared naming checks -------------------------------------------------------------------------------------------


def test_name_error_messages_and_exclusion(db, team_factory):
    team = team_factory(name="Windows")
    assert name_error(db, Team, "", "team") == "Enter a team name."
    assert name_error(db, Team, "x" * 101, "team") == "A team name can be at most 100 characters."
    assert name_error(db, Team, "x" * 100, "team") is None
    assert name_error(db, Team, "WINDOWS", "team") == "A team with that name already exists."
    assert name_error(db, Team, "Windows", "team", exclude_id=team.id) is None
    assert name_error(db, PermissionSet, "Windows", "permission set") is None


def test_description_error():
    assert description_error("x" * 500) is None
    assert description_error("x" * 501) == "A description can be at most 500 characters."


def test_team_holds_sets(db, team_factory, give_set):
    plain, holding = team_factory(), team_factory()
    give_set(["view_activity"], team=holding)
    assert team_holds_sets(db, holding.id) is True
    assert team_holds_sets(db, plain.id) is False
    assert TEAM_WITH_SETS_MESSAGE == "This team holds permission sets, so only an administrator can add people to it."


# --- Access ---------------------------------------------------------------------------------------------------------


def test_teams_screens_refused_without_manage_teams(client, logged_in_user, team_factory):
    team = team_factory()
    assert client.get("/admin/teams").status_code == 403
    assert client.get(f"/admin/teams/{team.id}").status_code == 403
    assert post(client, "/admin/teams", {"name": "X"}).status_code == 403
    assert post(client, f"/admin/teams/{team.id}/rename", {"name": "Y"}).status_code == 403
    assert post(client, f"/admin/teams/{team.id}/delete").status_code == 403


def test_holder_of_manage_teams_opens_the_screens(client, user_factory, give_set, team_factory):
    holder(user_factory, give_set, client)
    team = team_factory(name="Infrastructure")
    assert client.get("/admin/teams").status_code == 200
    assert client.get(f"/admin/teams/{team.id}").status_code == 200


# --- The tree and creating teams ------------------------------------------------------------------------------------


def test_tree_is_nested_with_member_and_tracker_counts(
    client, logged_in_admin, team_factory, user_factory, add_member, tracker_factory
):
    infra = team_factory(name="Infrastructure")
    windows = team_factory(name="Windows", parent=infra)
    add_member(windows, user_factory(), "viewer")
    add_member(windows, user_factory(), "owner")
    tracker_factory(team_id=windows.id)
    page = text_of(client.get("/admin/teams"))
    tree = re.search(r'<ul class="team-tree">.*', page, re.S).group(0)
    infra_at = tree.index(">Infrastructure<")
    nested_at = tree.index('<ul class="team-tree-children">', infra_at)
    windows_at = tree.index(">Windows<")
    assert infra_at < nested_at < windows_at
    assert f'href="/admin/teams/{windows.id}"' in tree
    windows_item = tree[windows_at : tree.index("</li>", windows_at)]
    assert "2 members" in windows_item and "1 tracker" in windows_item
    infra_item = tree[infra_at:nested_at]
    assert "0 members" in infra_item and "0 trackers" in infra_item


def test_create_team_logs_team_created(client, logged_in_admin, db, team_factory):
    infra = team_factory(name="Infrastructure")
    response = post(
        client, "/admin/teams", {"name": "  Windows ", "description": "Desktops", "parent_id": str(infra.id)}
    )
    assert response.status_code == 302
    team = db.scalar(select(Team).where(Team.name == "Windows"))
    assert team.parent_id == infra.id and team.description == "Desktops"
    [entry] = entries(db, "team_created")
    assert entry.user_id == logged_in_admin.id and entry.entity == "team" and entry.entity_id == str(team.id)
    assert entry.detail == {"name": "Windows", "parent": "Infrastructure"}


def test_create_top_level_team_logs_no_parent(client, logged_in_admin, db):
    assert post(client, "/admin/teams", {"name": "Applications", "parent_id": ""}).status_code == 302
    [entry] = entries(db, "team_created")
    assert entry.detail == {"name": "Applications", "parent": None}


def test_create_with_a_malformed_or_missing_parent_is_400(client, logged_in_admin, db):
    for parent in ("abc", "99999", "99999999999999999999"):
        page = post(client, "/admin/teams", {"name": "Windows", "parent_id": parent})
        assert page.status_code == 400 and "Choose a team from the list." in text_of(page)
    assert db.scalar(select(func.count()).select_from(Team)) == 0


def test_team_name_unique_ignoring_case_and_spaces(client, logged_in_admin, team_factory, db):
    team_factory(name="Windows")
    page = post(client, "/admin/teams", {"name": " windows "})
    assert page.status_code == 400 and "A team with that name already exists." in page.get_data(as_text=True)
    assert db.scalar(select(func.count()).select_from(Team)) == 1


def test_team_name_required_and_at_most_100_characters(client, logged_in_admin, db):
    page = post(client, "/admin/teams", {"name": "   "})
    assert page.status_code == 400 and "Enter a team name." in text_of(page)
    page = post(client, "/admin/teams", {"name": "x" * 101})
    assert page.status_code == 400 and "A team name can be at most 100 characters." in text_of(page)
    assert db.scalar(select(func.count()).select_from(Team)) == 0
    assert entries(db) == []


def test_team_description_at_most_500_characters(client, logged_in_admin, db, team_factory):
    message = "A description can be at most 500 characters."
    page = post(client, "/admin/teams", {"name": "Windows", "description": "x" * 501})
    assert page.status_code == 400 and message in text_of(page)
    assert db.scalar(select(func.count()).select_from(Team)) == 0
    team = team_factory(name="Linux")
    page = post(client, f"/admin/teams/{team.id}/rename", {"name": "Linux", "description": "x" * 501})
    assert page.status_code == 400 and message in text_of(page)
    db.expire_all()
    assert db.get(Team, team.id).description == ""
    assert entries(db) == []


# --- Renaming and moving --------------------------------------------------------------------------------------------


def test_rename_logs_before_and_after(client, logged_in_admin, db, team_factory):
    team = team_factory(name="Windows", description="Desktops")
    response = post(client, f"/admin/teams/{team.id}/rename", {"name": "Windows clients", "description": "Desktops"})
    assert response.status_code == 302
    [entry] = entries(db, "team_renamed")
    assert entry.detail == {"before": {"name": "Windows"}, "after": {"name": "Windows clients"}}
    assert entry.entity == "team" and entry.entity_id == str(team.id)
    post(client, f"/admin/teams/{team.id}/rename", {"name": "Windows clients", "description": "Laptops"})
    assert entries(db, "team_renamed")[-1].detail == {
        "before": {"description": "Desktops"},
        "after": {"description": "Laptops"},
    }


def test_rename_without_changes_logs_nothing(client, logged_in_admin, db, team_factory):
    team = team_factory(name="Windows")
    assert post(client, f"/admin/teams/{team.id}/rename", {"name": " Windows ", "description": ""}).status_code == 302
    assert entries(db) == []


def test_rename_to_another_teams_name_refused(client, logged_in_admin, db, team_factory):
    team_factory(name="Windows")
    team = team_factory(name="Linux")
    page = post(client, f"/admin/teams/{team.id}/rename", {"name": "WINDOWS"})
    assert page.status_code == 400 and "A team with that name already exists." in text_of(page)
    db.expire_all()
    assert db.get(Team, team.id).name == "Linux"


def test_move_form_offers_only_valid_parents(client, logged_in_admin, team_factory):
    infra = team_factory(name="Infrastructure")
    windows = team_factory(name="Windows", parent=infra)
    servers = team_factory(name="Servers", parent=windows)
    apps = team_factory(name="Applications")
    page = text_of(client.get(f"/admin/teams/{windows.id}"))
    options = move_options(page)
    assert "" in options and str(infra.id) in options and str(apps.id) in options
    assert str(windows.id) not in options and str(servers.id) not in options


def test_move_under_itself_or_below_refused_on_the_server(client, logged_in_admin, db, team_factory):
    infra = team_factory(name="Infrastructure")
    windows = team_factory(name="Windows", parent=infra)
    servers = team_factory(name="Servers", parent=windows)
    for target in (windows, servers):
        page = post(client, f"/admin/teams/{windows.id}/move", {"parent_id": str(target.id)})
        assert page.status_code == 400 and CYCLE_MESSAGE in text_of(page)
        assert parent_of(db, windows) == infra.id
    assert CYCLE_MESSAGE == "A team cannot be moved under itself or under a team below it."
    assert entries(db, "team_moved") == []


def test_move_logs_parent_before_and_after(client, logged_in_admin, db, team_factory):
    infra = team_factory(name="Infrastructure")
    apps = team_factory(name="Applications")
    windows = team_factory(name="Windows", parent=infra)
    assert post(client, f"/admin/teams/{windows.id}/move", {"parent_id": ""}).status_code == 302
    assert parent_of(db, windows) is None
    assert post(client, f"/admin/teams/{windows.id}/move", {"parent_id": str(apps.id)}).status_code == 302
    assert parent_of(db, windows) == apps.id
    moves = entries(db, "team_moved")
    assert [m.detail for m in moves] == [
        {"before": "Infrastructure", "after": None},
        {"before": None, "after": "Applications"},
    ]
    assert moves[0].entity == "team" and moves[0].entity_id == str(windows.id)


def test_move_names_parents_by_their_paths(client, logged_in_admin, db, team_factory):
    infra = team_factory(name="Infrastructure")
    windows = team_factory(name="Windows", parent=infra)
    laptops = team_factory(name="Laptops")
    assert post(client, f"/admin/teams/{laptops.id}/move", {"parent_id": str(windows.id)}).status_code == 302
    [entry] = entries(db, "team_moved")
    assert entry.detail == {"before": None, "after": "Infrastructure › Windows"}


def test_move_to_the_same_parent_logs_nothing(client, logged_in_admin, db, team_factory):
    infra = team_factory(name="Infrastructure")
    windows = team_factory(name="Windows", parent=infra)
    assert post(client, f"/admin/teams/{windows.id}/move", {"parent_id": str(infra.id)}).status_code == 302
    assert entries(db) == []


def test_move_with_a_malformed_parent_is_400(client, logged_in_admin, db, team_factory):
    infra = team_factory(name="Infrastructure")
    windows = team_factory(name="Windows", parent=infra)
    for parent in ("abc", "1.5", "99999"):
        assert post(client, f"/admin/teams/{windows.id}/move", {"parent_id": parent}).status_code == 400
    assert parent_of(db, windows) == infra.id
    assert entries(db) == []


# --- Deleting -------------------------------------------------------------------------------------------------------


def test_delete_refused_with_a_child_team_a_tracker_or_an_archived_tracker(
    client, logged_in_admin, db, team_factory, tracker_factory
):
    parent = team_factory(name="Infrastructure")
    team_factory(name="Windows", parent=parent)
    page = post(client, f"/admin/teams/{parent.id}/delete")
    assert page.status_code == 400 and "This team has teams below it. Move or delete them first." in text_of(page)
    trackers_message = "This team has trackers, including archived ones. Move them to another team first."
    with_tracker = team_factory(name="Linux")
    tracker_factory(team_id=with_tracker.id)
    page = post(client, f"/admin/teams/{with_tracker.id}/delete")
    assert page.status_code == 400 and trackers_message in text_of(page)
    with_archived = team_factory(name="Mac")
    tracker_factory(team_id=with_archived.id, status="archived")
    page = post(client, f"/admin/teams/{with_archived.id}/delete")
    assert page.status_code == 400 and trackers_message in text_of(page)
    assert db.scalar(select(func.count()).select_from(Team)) == 4
    assert entries(db) == []


def test_delete_shown_only_when_allowed(client, logged_in_admin, team_factory):
    parent = team_factory(name="Infrastructure")
    child = team_factory(name="Windows", parent=parent)
    assert f'action="/admin/teams/{parent.id}/delete"' not in client.get(f"/admin/teams/{parent.id}").get_data(
        as_text=True
    )
    assert f'action="/admin/teams/{child.id}/delete"' in client.get(f"/admin/teams/{child.id}").get_data(as_text=True)


def test_delete_removes_and_logs_memberships_and_holdings(
    client, logged_in_admin, db, team_factory, user_factory, add_member, give_set
):
    infra = team_factory(name="Infrastructure")
    team = team_factory(name="Windows", parent=infra)
    first, second = user_factory(), user_factory()
    add_member(team, first, "viewer")
    add_member(team, second, "owner")
    permission_set = give_set(["view_activity"], team=team, name="Auditors")
    response = post(client, f"/admin/teams/{team.id}/delete")
    assert response.status_code == 302
    assert db.scalar(select(Team.id).where(Team.id == team.id)) is None
    assert db.scalar(select(func.count()).select_from(TeamMember)) == 0
    assert db.scalar(select(func.count()).select_from(PermissionSetHolder)) == 0
    assert db.get(PermissionSet, permission_set.id) is not None
    logged = entries(db)
    assert [e.action for e in logged] == [
        "team_member_removed",
        "team_member_removed",
        "permission_set_holder_removed",
        "team_deleted",
    ]
    assert {e.target_user_id for e in logged[:2]} == {first.id, second.id}
    assert {e.detail["role"] for e in logged[:2]} == {"viewer", "owner"}
    assert all(e.detail["team"] == "Infrastructure › Windows" for e in logged[:2])
    assert logged[2].detail == {"set": "Auditors", "team": "Infrastructure › Windows"}
    assert logged[3].detail == {"name": "Windows", "parent": "Infrastructure"}
    assert all(e.user_id == logged_in_admin.id for e in logged)


# --- Members --------------------------------------------------------------------------------------------------------


def test_team_page_lists_members_and_offers_only_active_non_members(
    client, logged_in_admin, team_factory, user_factory, add_member
):
    team = team_factory(name="Windows")
    member = user_factory(full_name="Mia Member")
    add_member(team, member, "editor")
    user_factory(full_name="Olly Other")
    user_factory(full_name="Dora Disabled", status="disabled")
    user_factory(full_name="Pat Pending", status="pending")
    page = text_of(client.get(f"/admin/teams/{team.id}"))
    assert "Mia Member" in page
    add_form = re.search(r'<select id="user_id".*?</select>', page, re.S).group(0)
    assert "Olly Other" in add_form
    assert "Mia Member" not in add_form and "Dora Disabled" not in add_form and "Pat Pending" not in add_form


def test_add_member_logs_with_the_affected_user(client, logged_in_admin, db, team_factory, user_factory):
    infra = team_factory(name="Infrastructure")
    team = team_factory(name="Windows", parent=infra)
    user = user_factory()
    response = post(client, f"/admin/teams/{team.id}/members", {"user_id": str(user.id), "role": "editor"})
    assert response.status_code == 302
    assert member_role(db, team, user) == "editor"
    [entry] = entries(db, "team_member_added")
    assert entry.target_user_id == user.id and entry.user_id == logged_in_admin.id
    assert entry.detail == {"team": "Infrastructure › Windows", "role": "editor"}
    assert entry.entity == "team" and entry.entity_id == str(team.id)


def test_add_member_refuses_users_who_are_not_active(client, logged_in_admin, db, team_factory, user_factory):
    team = team_factory()
    for status in ("disabled", "pending"):
        user = user_factory(status=status)
        response = post(client, f"/admin/teams/{team.id}/members", {"user_id": str(user.id), "role": "viewer"})
        assert response.status_code == 400
    for bad in ("abc", "99999", ""):
        assert post(client, f"/admin/teams/{team.id}/members", {"user_id": bad, "role": "viewer"}).status_code == 400
    assert db.scalar(select(func.count()).select_from(TeamMember)) == 0
    assert entries(db) == []


def test_add_member_refuses_an_unknown_role_and_an_existing_member(
    client, logged_in_admin, db, team_factory, user_factory, add_member
):
    team = team_factory()
    user = user_factory()
    assert post(client, f"/admin/teams/{team.id}/members", {"user_id": str(user.id), "role": "boss"}).status_code == 400
    add_member(team, user, "viewer")
    page = post(client, f"/admin/teams/{team.id}/members", {"user_id": str(user.id), "role": "owner"})
    assert page.status_code == 400 and "That person is already a member of this team." in text_of(page)
    assert member_role(db, team, user) == "viewer"
    assert entries(db) == []


def test_change_role_and_remove_member_log_before_and_after(
    client, logged_in_admin, db, team_factory, user_factory, add_member
):
    infra = team_factory(name="Infrastructure")
    team = team_factory(name="Windows", parent=infra)
    user = user_factory()
    add_member(team, user, "viewer")
    url = f"/admin/teams/{team.id}/members/{user.id}"
    assert post(client, url, {"role": "owner"}).status_code == 302
    assert member_role(db, team, user) == "owner"
    assert post(client, url, {"role": "owner"}).status_code == 302  # unchanged: no entry
    assert post(client, url, {"action": "remove"}).status_code == 302
    assert member_role(db, team, user) is None
    changed, removed = entries(db)
    assert changed.action == "team_member_role_changed" and changed.target_user_id == user.id
    assert changed.detail == {"team": "Infrastructure › Windows", "before": "viewer", "after": "owner"}
    assert removed.action == "team_member_removed" and removed.target_user_id == user.id
    assert removed.detail == {"team": "Infrastructure › Windows", "role": "owner"}


def test_change_to_an_unknown_role_is_400(client, logged_in_admin, db, team_factory, user_factory, add_member):
    team = team_factory()
    user = user_factory()
    add_member(team, user, "viewer")
    assert post(client, f"/admin/teams/{team.id}/members/{user.id}", {"role": "boss"}).status_code == 400
    assert member_role(db, team, user) == "viewer"


def test_missing_team_or_member_is_404(client, logged_in_admin, team_factory, user_factory):
    assert client.get("/admin/teams/9999").status_code == 404
    assert post(client, "/admin/teams/9999/rename", {"name": "X"}).status_code == 404
    assert post(client, "/admin/teams/9999/move", {"parent_id": ""}).status_code == 404
    assert post(client, "/admin/teams/9999/delete").status_code == 404
    assert post(client, "/admin/teams/9999/members", {"user_id": "1", "role": "viewer"}).status_code == 404
    team = team_factory()
    stranger = user_factory()
    assert post(client, f"/admin/teams/{team.id}/members/{stranger.id}", {"role": "owner"}).status_code == 404
    assert post(client, f"/admin/teams/{team.id}/members/{stranger.id}", {"action": "remove"}).status_code == 404


# --- Guards for holders who are not administrators ------------------------------------------------------------------


def test_holder_cannot_add_self_to_a_team_with_trackers(
    client, db, user_factory, give_set, team_factory, tracker_factory
):
    actor = holder(user_factory, give_set, client)
    team = team_factory()
    tracker_factory(team_id=team.id)
    response = post(
        client, f"/admin/teams/{team.id}/members", {"user_id": str(actor.id), "role": "viewer"}, follow_redirects=True
    )
    assert SELF_PROMOTION_MESSAGE in text_of(response)
    assert member_role(db, team, actor) is None
    assert entries(db) == []


def test_holder_can_add_someone_else(client, db, user_factory, give_set, team_factory, tracker_factory):
    holder(user_factory, give_set, client)
    team = team_factory()
    tracker_factory(team_id=team.id)
    other = user_factory()
    assert (
        post(client, f"/admin/teams/{team.id}/members", {"user_id": str(other.id), "role": "owner"}).status_code == 302
    )
    assert member_role(db, team, other) == "owner"


def test_holder_cannot_raise_own_team_role_but_can_lower_it(
    client, db, user_factory, give_set, team_factory, tracker_factory, add_member
):
    actor = holder(user_factory, give_set, client)
    team = team_factory()
    tracker_factory(team_id=team.id)
    add_member(team, actor, "editor")
    url = f"/admin/teams/{team.id}/members/{actor.id}"
    response = post(client, url, {"role": "owner"}, follow_redirects=True)
    assert SELF_PROMOTION_MESSAGE in text_of(response)
    assert member_role(db, team, actor) == "editor"
    assert entries(db) == []
    assert post(client, url, {"role": "viewer"}).status_code == 302
    assert member_role(db, team, actor) == "viewer"
    [entry] = entries(db, "team_member_role_changed")
    assert entry.detail["before"] == "editor" and entry.detail["after"] == "viewer"


def test_holder_cannot_move_a_team_under_their_own_team(
    client, db, user_factory, give_set, team_factory, tracker_factory, add_member
):
    actor = holder(user_factory, give_set, client)
    own = team_factory(name="Own")
    add_member(own, actor, "owner")
    other = team_factory(name="Other")
    tracker_factory(team_id=other.id)
    response = post(client, f"/admin/teams/{other.id}/move", {"parent_id": str(own.id)}, follow_redirects=True)
    assert SELF_PROMOTION_MESSAGE in text_of(response)
    assert parent_of(db, other) is None
    assert entries(db) == []


def test_non_admin_cannot_add_members_to_a_team_holding_a_set(
    client, db, user_factory, give_set, team_factory, logged_in_admin
):
    team = team_factory()
    give_set(["view_activity"], team=team)
    other = user_factory()
    holder(user_factory, give_set, client)
    url = f"/admin/teams/{team.id}/members"
    response = post(client, url, {"user_id": str(other.id), "role": "viewer"}, follow_redirects=True)
    assert TEAM_WITH_SETS_MESSAGE in text_of(response)
    assert member_role(db, team, other) is None
    sign_in(client, logged_in_admin)
    assert post(client, url, {"user_id": str(other.id), "role": "viewer"}).status_code == 302
    assert member_role(db, team, other) == "viewer"


def test_team_page_names_trackers_the_holder_cannot_open(client, user_factory, give_set, team_factory, tracker_factory):
    holder(user_factory, give_set, client)
    team = team_factory()
    tracker = tracker_factory(name="Secret rollout", team_id=team.id)
    tracker_factory(name="Old rollout", team_id=team.id, status="archived")
    page = text_of(client.get(f"/admin/teams/{team.id}"))
    assert "Secret rollout" in page
    assert re.search(r"Old rollout.*Archived", page, re.S)
    assert client.get(f"/trackers/{tracker.id}").status_code == 404
