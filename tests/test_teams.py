"""Teams screens: the tree, team pages, members and the guards on them (database required)."""

import html
import re

import pytest
from sqlalchemy import delete, func, select, update

from tests.conftest import post, sign_in
from tracker.auth.accounts import VOUCHED_MESSAGE
from tracker.auth.guards import SELF_PROMOTION_MESSAGE, TEAM_WITH_SETS_MESSAGE, team_holds_sets
from tracker.models import AuditLog, PermissionSet, PermissionSetHolder, Team, TeamMember, TeamParent
from tracker.naming import description_error, name_error
from tracker.teams import views as team_views
from tracker.teams.tree import TEAM_CHOICE_ERROR


def text_of(response) -> str:
    return html.unescape(response.get_data(as_text=True))


def entries(db, action: str | None = None) -> list[AuditLog]:
    query = select(AuditLog).order_by(AuditLog.id)
    if action:
        query = query.where(AuditLog.action == action)
    return list(db.scalars(query))


def member_role(db, team, user) -> str | None:
    return db.scalar(select(TeamMember.role).where(TeamMember.team_id == team.id, TeamMember.user_id == user.id))


def parents_of(db, team) -> set[int]:
    db.expire_all()
    return set(db.scalars(select(TeamParent.parent_id).where(TeamParent.team_id == team.id)))


@pytest.fixture
def place(region_factory, location_factory) -> dict[str, str]:
    """The Region and Location form fields of one region and location, for posts whose point is not the place."""
    region = region_factory("EMEA")
    location = location_factory(region)
    return {"region_id": str(region.id), "location_id": str(location.id)}


PLACE_TEXT = "Geneva, Switzerland (EMEA)"


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


def test_tree_is_nested_with_people_counts(client, logged_in_admin, team_factory, user_factory, add_member):
    infra = team_factory(name="Infrastructure")
    windows = team_factory(name="Windows", parent=infra)
    add_member(windows, user_factory(), "viewer")
    add_member(windows, user_factory(), "owner")
    page = text_of(client.get("/admin/teams"))
    tree = re.search(r'<ul class="team-tree">.*', page, re.S).group(0)
    infra_at = tree.index(">Infrastructure<")
    nested_at = tree.index('<ul class="team-tree-children">', infra_at)
    windows_at = tree.index(">Windows<")
    assert infra_at < nested_at < windows_at
    assert f'href="/admin/teams/{windows.id}"' in tree
    windows_item = tree[windows_at : tree.index("</li>", windows_at)]
    assert "2 people" in windows_item
    infra_item = tree[infra_at:nested_at]
    assert "0 people" in infra_item


def test_create_team_logs_team_created(client, logged_in_admin, db, team_factory, place):
    infra = team_factory(name="Infrastructure")
    response = post(
        client,
        "/admin/teams",
        {"name": "  Windows ", "description": "Desktops", "parent_id": str(infra.id), **place},
    )
    assert response.status_code == 302
    team = db.scalar(select(Team).where(Team.name == "Windows"))
    assert parents_of(db, team) == {infra.id} and team.description == "Desktops"
    [entry] = entries(db, "team_created")
    assert entry.user_id == logged_in_admin.id and entry.entity == "team" and entry.entity_id == str(team.id)
    assert entry.detail == {"name": "Windows", "parent": "Infrastructure", "location": PLACE_TEXT}


def test_create_top_level_team_logs_no_parent(client, logged_in_admin, db, place):
    assert post(client, "/admin/teams", {"name": "Applications", "parent_id": "", **place}).status_code == 302
    [entry] = entries(db, "team_created")
    assert entry.detail == {"name": "Applications", "parent": None, "location": PLACE_TEXT}


def test_create_with_a_malformed_or_missing_parent_is_400(client, logged_in_admin, db, place):
    for parent in ("abc", "99999", "99999999999999999999"):
        page = post(client, "/admin/teams", {"name": "Windows", "parent_id": parent, **place})
        assert page.status_code == 400 and "Choose a team from the list." in text_of(page)
    assert db.scalar(select(func.count()).select_from(Team)) == 0


def test_team_name_unique_ignoring_case_and_spaces(client, logged_in_admin, team_factory, db, place):
    team_factory(name="Windows")
    page = post(client, "/admin/teams", {"name": " windows ", **place})
    assert page.status_code == 400 and "A team with that name already exists." in page.get_data(as_text=True)
    assert db.scalar(select(func.count()).select_from(Team)) == 1


def test_team_name_required_and_at_most_100_characters(client, logged_in_admin, db, place):
    page = post(client, "/admin/teams", {"name": "   ", **place})
    assert page.status_code == 400 and "Enter a team name." in text_of(page)
    page = post(client, "/admin/teams", {"name": "x" * 101, **place})
    assert page.status_code == 400 and "A team name can be at most 100 characters." in text_of(page)
    assert db.scalar(select(func.count()).select_from(Team)) == 0
    assert entries(db) == []


def test_team_description_at_most_500_characters(client, logged_in_admin, db, team_factory, place):
    message = "A description can be at most 500 characters."
    page = post(client, "/admin/teams", {"name": "Windows", "description": "x" * 501, **place})
    assert page.status_code == 400 and message in text_of(page)
    assert db.scalar(select(func.count()).select_from(Team)) == 0
    team = team_factory(name="Linux", location_id=int(place["location_id"]))
    page = post(client, f"/admin/teams/{team.id}/rename", {"name": "Linux", "description": "x" * 501, **place})
    assert page.status_code == 400 and message in text_of(page)
    db.expire_all()
    assert db.get(Team, team.id).description == ""
    assert entries(db) == []


# --- Renaming and moving --------------------------------------------------------------------------------------------


def test_rename_logs_before_and_after(client, logged_in_admin, db, team_factory, place):
    team = team_factory(name="Windows", description="Desktops", location_id=int(place["location_id"]))
    response = post(
        client, f"/admin/teams/{team.id}/rename", {"name": "Windows clients", "description": "Desktops", **place}
    )
    assert response.status_code == 302
    [entry] = entries(db, "team_renamed")
    assert entry.detail == {"team": "Windows", "before": {"name": "Windows"}, "after": {"name": "Windows clients"}}
    assert entry.entity == "team" and entry.entity_id == str(team.id)
    post(client, f"/admin/teams/{team.id}/rename", {"name": "Windows clients", "description": "Laptops", **place})
    assert entries(db, "team_renamed")[-1].detail == {
        "team": "Windows clients",
        "before": {"description": "Desktops"},
        "after": {"description": "Laptops"},
    }


def test_rename_without_changes_logs_nothing(client, logged_in_admin, db, team_factory, place):
    team = team_factory(name="Windows", location_id=int(place["location_id"]))
    data = {"name": " Windows ", "description": "", **place}
    assert post(client, f"/admin/teams/{team.id}/rename", data).status_code == 302
    assert entries(db) == []


def test_rename_to_another_teams_name_refused(client, logged_in_admin, db, team_factory, place):
    team_factory(name="Windows")
    team = team_factory(name="Linux")
    page = post(client, f"/admin/teams/{team.id}/rename", {"name": "WINDOWS", **place})
    assert page.status_code == 400 and "A team with that name already exists." in text_of(page)
    db.expire_all()
    assert db.get(Team, team.id).name == "Linux"


# --- Deleting -------------------------------------------------------------------------------------------------------


def test_delete_refused_with_a_child_team_a_tracker_or_an_archived_tracker(
    client, logged_in_admin, db, team_factory, tracker_factory
):
    parent = team_factory(name="Infrastructure")
    team_factory(name="Windows", parent=parent)
    page = post(client, f"/admin/teams/{parent.id}/delete")
    assert (
        page.status_code == 400
        and "This team has teams below it. Remove them from under it or delete them first." in text_of(page)
    )
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
    assert all(e.detail["team"] == "Windows" for e in logged[:2])
    assert logged[2].detail == {"set": "Auditors", "team": "Windows"}
    assert logged[3].detail == {"name": "Windows", "parents": ["Infrastructure"]}
    assert all(e.user_id == logged_in_admin.id for e in logged)


def test_delete_removes_the_links_and_names_every_higher_team(client, logged_in_admin, db, team_factory):
    infra, apps = team_factory(name="Infrastructure"), team_factory(name="applications")
    desktops = team_factory(name="Desktops", parents=(infra, apps))
    assert post(client, f"/admin/teams/{desktops.id}/delete").status_code == 302
    assert post(client, f"/admin/teams/{apps.id}/delete").status_code == 302
    assert db.scalar(select(func.count()).select_from(TeamParent)) == 0
    assert [e.detail for e in entries(db, "team_deleted")] == [
        {"name": "Desktops", "parents": ["applications", "Infrastructure"]},
        {"name": "applications", "parents": []},
    ]


# --- The layout: tree beside a people-first team page -----------------------------------------------------------------


def raw_of(response) -> str:
    return response.get_data(as_text=True)


def table_rows(page: str) -> list[str]:
    return re.findall(r"<tr data-route.*?</tr>", page, re.S)


def row_for(page: str, name: str) -> str:
    [row] = [row for row in table_rows(page) if name in row]
    return row


def test_index_and_team_page_show_the_tree_with_reach_counts(
    client, logged_in_admin, team_factory, user_factory, add_member
):
    infra = team_factory(name="Infrastructure")
    windows = team_factory(name="Windows", parent=infra)
    patching = team_factory(name="Patching", parent=windows)
    add_member(infra, user_factory(), "owner")
    add_member(windows, user_factory(), "editor")
    add_member(patching, user_factory(), "viewer")
    for url in ("/admin/teams", f"/admin/teams/{windows.id}"):
        raw = raw_of(client.get(url))
        assert 'class="teams-layout"' in raw and "data-tree" in raw
        item = raw[raw.index(">Patching<") : raw.index("</li>", raw.index(">Patching<"))]
        assert "3 people" in item
    assert re.search(r'<a [^>]*aria-current="page"[^>]*>\s*Windows\s*</a>', raw)
    assert not re.search(r'<a [^>]*aria-current="page"[^>]*>\s*Infrastructure\s*</a>', raw)
    index = raw_of(client.get("/admin/teams"))
    assert re.search(r">Infrastructure<.*?1 person<", index, re.S)  # one member, so the singular form


def test_index_right_column_holds_a_prompt_and_the_new_team_form(client, logged_in_admin, team_factory):
    team_factory(name="Infrastructure")
    raw = raw_of(client.get("/admin/teams"))
    assert "Choose a team to see its people and trackers." in raw
    assert 'id="new-team"' in raw and 'id="parent_id"' in raw


def test_team_page_lists_people_from_teams_above(client, logged_in_admin, team_factory, user_factory, add_member):
    infra = team_factory(name="Infrastructure")
    windows = team_factory(name="Windows", parent=infra)
    head = user_factory(full_name="Hana Head")
    mia = user_factory(full_name="Mia Member")
    add_member(infra, head, "owner")
    add_member(windows, mia, "editor")
    raw = raw_of(client.get(f"/admin/teams/{windows.id}"))
    above = row_for(raw, "Hana Head")
    assert 'data-route="inherited"' in above
    assert re.search(rf'From <a href="/admin/teams/{infra.id}">Infrastructure</a>', above)
    assert "<select" not in above and "Remove" not in above and "<form" not in above
    direct = row_for(raw, "Mia Member")
    assert 'data-route="direct"' in direct
    assert re.search(r"<select[^>]*data-autosubmit", direct)
    assert re.search(r"<button[^>]*data-autosubmit-fallback[^>]*>Set role</button>", direct)
    assert "Remove" in direct


def test_direct_member_with_a_higher_inherited_role_gets_a_note(
    client, logged_in_admin, team_factory, user_factory, add_member
):
    infra = team_factory(name="Infrastructure")
    windows = team_factory(name="Windows", parent=infra)
    both, lower = user_factory(full_name="Bea Both"), user_factory(full_name="Lou Lower")
    add_member(infra, both, "owner")
    add_member(windows, both, "viewer")
    add_member(infra, lower, "viewer")
    add_member(windows, lower, "editor")
    raw = raw_of(client.get(f"/admin/teams/{windows.id}"))
    note = row_for(raw, "Bea Both")
    assert 'data-route="direct inherited"' in note and "Owner from Infrastructure" in html.unescape(note)
    assert "<select" in note
    quiet = row_for(raw, "Lou Lower")  # the inherited role is lower than the direct one: nothing to note
    assert 'data-route="direct inherited"' in quiet and " from Infrastructure" not in html.unescape(quiet)


def test_inactive_direct_members_keep_their_row_with_a_status_badge(
    client, logged_in_admin, team_factory, user_factory, add_member
):
    team = team_factory(name="Windows")
    gone = user_factory(full_name="Dora Disabled", status="disabled")
    add_member(team, gone, "viewer")
    row = row_for(raw_of(client.get(f"/admin/teams/{team.id}")), "Dora Disabled")
    assert "Disabled" in row and "<select" in row and "Remove" in row
    assert re.search(r"People\s*<span class=\"tab-count\">1</span>", raw_of(client.get(f"/admin/teams/{team.id}")))


def test_filter_group_counts(client, logged_in_admin, team_factory, user_factory, add_member):
    infra = team_factory(name="Infrastructure")
    windows = team_factory(name="Windows", parent=infra)
    add_member(infra, user_factory(), "owner")
    add_member(windows, user_factory(), "viewer")
    add_member(windows, user_factory(), "viewer")
    text = text_of(client.get(f"/admin/teams/{windows.id}"))
    assert "All (3)" in text and "Direct (2)" in text and "From teams above (1)" in text


def test_people_list_direct_members_before_those_from_teams_above(
    client, logged_in_admin, team_factory, user_factory, add_member
):
    infra = team_factory(name="Infrastructure")
    windows = team_factory(name="Windows", parent=infra)
    add_member(infra, user_factory(full_name="Aaron Above"), "owner")
    add_member(windows, user_factory(full_name="Zoe Direct"), "viewer")
    add_member(infra, user_factory(full_name="Bea Above"), "viewer")
    add_member(windows, user_factory(full_name="Carl Direct"), "viewer")
    page = raw_of(client.get(f"/admin/teams/{windows.id}"))
    order = [n for row in table_rows(page) for n in ("Aaron", "Bea", "Carl", "Zoe") if n in row]
    assert order == ["Carl", "Zoe", "Aaron", "Bea"]


def test_team_page_has_no_details_section_and_edits_in_the_header(client, logged_in_admin, team_factory, place):
    team = team_factory(name="Windows")
    raw = raw_of(client.get(f"/admin/teams/{team.id}"))
    assert "<details" not in raw and 'id="details"' not in raw
    bad = post(client, f"/admin/teams/{team.id}/rename", {"name": "", **place})
    assert bad.status_code == 400 and 'class="team-header team-edit"' in raw_of(bad)
    assert "Edit details" in raw and f"/admin/teams/{team.id}/parents" in raw and "Higher teams" in raw


def test_teams_below_and_new_team_below(client, logged_in_admin, team_factory, user_factory, add_member):
    infra = team_factory(name="Infrastructure")
    windows = team_factory(name="Windows", parent=infra)
    patching = team_factory(name="Patching", parent=windows)
    add_member(windows, user_factory(), "viewer")
    add_member(patching, user_factory(), "viewer")
    raw = raw_of(client.get(f"/admin/teams/{windows.id}?tab=below"))
    below = raw[raw.index('id="teams-below"') :]
    assert "Patching" in below and "2 people" in below
    assert f'href="/admin/teams?parent={windows.id}#new-team"' in raw
    page = raw_of(client.get(f"/admin/teams?parent={windows.id}"))
    select_html = re.search(r'<select id="parent_id".*?</select>', page, re.S).group(0)
    assert re.search(rf'<option value="{windows.id}"\s+selected', select_html)
    for bad in ("abc", "", "9" * 20, "99999"):
        page = raw_of(client.get(f"/admin/teams?parent={bad}"))
        select_html = re.search(r'<select id="parent_id".*?</select>', page, re.S).group(0)
        assert re.search(r'<option value=""\s+selected', select_html), bad
        assert select_html.count("selected") == 1


def test_trackers_link_to_their_access_tab(client, logged_in_admin, team_factory, tracker_factory):
    team = team_factory(name="Windows")
    tracker = tracker_factory(name="Laptop refresh", team_id=team.id)
    raw = raw_of(client.get(f"/admin/teams/{team.id}?tab=trackers"))
    assert f'href="/trackers/{tracker.id}/roles"' in raw


def test_names_with_markup_are_escaped(client, logged_in_admin, team_factory, user_factory, add_member):
    team = team_factory(name="<b>x</b>")
    add_member(team, user_factory(full_name='O"Neil <i>'), "viewer")
    for url in (f"/admin/teams/{team.id}", "/admin/teams"):
        raw = raw_of(client.get(url))
        assert "<b>x</b>" not in raw and "<i>" not in raw and 'O"Neil' not in raw
        assert "&lt;b&gt;x&lt;/b&gt;" in raw
        assert 'data-search="&lt;b&gt;x&lt;/b&gt; o&#34;neil &lt;i&gt;"' in raw


def test_filters_render_hidden_for_no_script(client, logged_in_admin, team_factory, user_factory, add_member):
    team = team_factory(name="Windows")
    add_member(team, user_factory(), "viewer")
    user_factory(full_name="Olly Other")
    raw = raw_of(client.get(f"/admin/teams/{team.id}"))
    for marker in ("data-tree-filter", "data-row-filter=", "data-select-filter="):
        [tag] = re.findall(rf"<[a-z]+[^>]*{marker}[^>]*>", raw)
        assert re.search(r"\bhidden\b", tag), marker
    assert 'src="/static/admin.js' in raw


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
    assert entry.detail == {"team": "Windows", "role": "editor"}
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
    assert changed.detail == {"team": "Windows", "before": "viewer", "after": "owner"}
    assert removed.action == "team_member_removed" and removed.target_user_id == user.id
    assert removed.detail == {"team": "Windows", "role": "owner"}


def test_change_to_an_unknown_role_is_400(client, logged_in_admin, db, team_factory, user_factory, add_member):
    team = team_factory()
    user = user_factory()
    add_member(team, user, "viewer")
    assert post(client, f"/admin/teams/{team.id}/members/{user.id}", {"role": "boss"}).status_code == 400
    assert member_role(db, team, user) == "viewer"


def test_missing_team_or_member_is_404(client, logged_in_admin, team_factory, user_factory):
    assert client.get("/admin/teams/9999").status_code == 404
    assert post(client, "/admin/teams/9999/rename", {"name": "X"}).status_code == 404
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
    page = text_of(client.get(f"/admin/teams/{team.id}?tab=trackers"))
    assert "Secret rollout" in page
    assert re.search(r"Old rollout.*Archived", page, re.S)
    assert client.get(f"/trackers/{tracker.id}").status_code == 404


# --- Final review fixes ---------------------------------------------------------------------------------------------

LONG_ID = "9" * 5000  # int() refuses it, so it must be turned away before any conversion


def vouch(db, actor, target, action="user_created"):
    """Record that ``actor`` created ``target``'s account (or reset its password)."""
    db.add(AuditLog(action=action, entity="user", entity_id=str(target.id), user_id=actor.id, target_user_id=target.id))
    db.commit()


def test_very_long_ids_are_400_not_500(client, logged_in_admin, db, team_factory, place):
    team = team_factory(name="Windows")
    assert post(client, "/admin/teams", {"name": "New", "parent_id": LONG_ID, **place}).status_code == 400
    assert post(client, f"/admin/teams/{team.id}/members", {"user_id": LONG_ID, "role": "viewer"}).status_code == 400
    assert entries(db) == [] and db.scalar(select(func.count()).select_from(Team)) == 1


def test_create_under_a_parent_deleted_at_the_same_moment(
    client, logged_in_admin, db, team_factory, monkeypatch, place
):
    parent = team_factory(name="Going")
    original = team_views.load_team_rows

    def delete_parent_first(session, lock=False):
        if db.get(Team, parent.id) is not None:
            db.delete(db.get(Team, parent.id))
            db.commit()
        return original(session, lock)

    monkeypatch.setattr(team_views, "load_team_rows", delete_parent_first)
    page = post(client, "/admin/teams", {"name": "Child", "parent_id": str(parent.id), **place})
    assert page.status_code == 400 and TEAM_CHOICE_ERROR in text_of(page)
    assert "already exists" not in text_of(page)
    assert db.scalar(select(func.count()).select_from(Team)) == 0 and entries(db) == []


def test_delete_names_the_parent_read_under_the_lock(client, logged_in_admin, db, team_factory, monkeypatch):
    infra, apps = team_factory(name="Infrastructure"), team_factory(name="Applications")
    team = team_factory(name="Windows", parent=infra)
    original = team_views.load_team_rows

    def move_first(session, lock=False):
        if lock:  # another manager moves the team after this request read it, just before the lock
            db.execute(update(TeamParent).where(TeamParent.team_id == team.id).values(parent_id=apps.id))
            db.commit()
        return original(session, lock)

    monkeypatch.setattr(team_views, "load_team_rows", move_first)
    assert post(client, f"/admin/teams/{team.id}/delete").status_code == 302
    [deleted] = entries(db, "team_deleted")
    assert deleted.detail == {"name": "Windows", "parents": ["Applications"]}


def test_removing_a_member_removed_at_the_same_moment(
    client, logged_in_admin, db, team_factory, user_factory, add_member, monkeypatch
):
    team, user = team_factory(name="Windows"), user_factory(full_name="Pat")
    add_member(team, user, "viewer")
    original = team_views._team_path

    def remove_first(t):
        db.execute(delete(TeamMember).where(TeamMember.team_id == team.id))
        db.commit()
        return original(t)

    monkeypatch.setattr(team_views, "_team_path", remove_first)
    response = post(client, f"/admin/teams/{team.id}/members/{user.id}", {"action": "remove"}, follow_redirects=True)
    assert response.status_code == 200 and "Pat is no longer a member of Windows." in text_of(response)
    assert entries(db) == []


def test_holder_cannot_give_a_team_place_to_an_account_they_vouched_for(
    client, db, user_factory, give_set, team_factory, add_member
):
    actor = holder(user_factory, give_set, client)
    team = team_factory(name="Windows")
    created, reset, other = user_factory(), user_factory(), user_factory()
    vouch(db, actor, created)
    vouch(db, actor, reset, action="password_reset")
    url = f"/admin/teams/{team.id}/members"
    for person in (created, reset):
        response = post(client, url, {"user_id": str(person.id), "role": "viewer"}, follow_redirects=True)
        assert VOUCHED_MESSAGE in text_of(response) and member_role(db, team, person) is None
    assert post(client, url, {"user_id": str(other.id), "role": "viewer"}).status_code == 302
    assert member_role(db, team, other) == "viewer"
    add_member(team, created, "viewer")  # placed there by someone else
    response = post(client, f"/admin/teams/{team.id}/members/{created.id}", {"role": "owner"}, follow_redirects=True)
    assert VOUCHED_MESSAGE in text_of(response) and member_role(db, team, created) == "viewer"
    assert post(client, f"/admin/teams/{team.id}/members/{created.id}", {"action": "remove"}).status_code == 302
    assert member_role(db, team, created) is None  # removing lowers access, so it is allowed
    assert [e.target_user_id for e in entries(db, "team_member_added")] == [other.id]
    assert entries(db, "team_member_role_changed") == []


def test_an_administrator_may_give_access_to_an_account_they_created(
    client, logged_in_admin, db, team_factory, user_factory
):
    team, person = team_factory(name="Windows"), user_factory()
    vouch(db, logged_in_admin, person)
    assert (
        post(client, f"/admin/teams/{team.id}/members", {"user_id": str(person.id), "role": "owner"}).status_code == 302
    )
    assert member_role(db, team, person) == "owner"


def test_holder_can_lower_the_role_of_an_account_they_vouched_for(
    client, db, user_factory, give_set, team_factory, add_member
):
    actor = holder(user_factory, give_set, client)
    team = team_factory(name="Windows")
    created = user_factory()
    vouch(db, actor, created)
    add_member(team, created, "editor")
    assert post(client, f"/admin/teams/{team.id}/members/{created.id}", {"role": "viewer"}).status_code == 302
    db.expire_all()
    assert member_role(db, team, created) == "viewer"  # lowering gives nothing, so it is allowed
    assert [e.target_user_id for e in entries(db, "team_member_role_changed")] == [created.id]


def test_delete_message_names_the_team_read_under_the_lock(client, logged_in_admin, db, team_factory, monkeypatch):
    team = team_factory(name="Windows")
    original = team_views.load_team_rows

    def rename_first(session, lock=False):
        if lock:  # another manager renames the team after this request read it, just before the lock
            db.execute(update(Team).where(Team.id == team.id).values(name="Windows Server"))
            db.commit()
        return original(session, lock)

    monkeypatch.setattr(team_views, "load_team_rows", rename_first)
    response = post(client, f"/admin/teams/{team.id}/delete", follow_redirects=True)
    assert "Deleted the team Windows Server." in text_of(response)


# --- The tree and the team page with several higher teams -----------------------------------------------------------


def flat(markup: str) -> str:
    """The text of a piece of markup, tags dropped and white space collapsed."""
    text = " ".join(html.unescape(re.sub(r"<[^>]+>", " ", markup)).split())
    return re.sub(r"\s+([,.])", r"\1", text)


def tree_of(client, url: str = "/admin/teams") -> str:
    raw = raw_of(client.get(url))
    start = raw.index("data-tree>")
    return raw[start : raw.index("</aside>", start)]


def header_of(raw: str) -> str:
    start = raw.index('class="team-header')
    return raw[start : raw.index("</header>", start)]


def test_tree_shows_a_team_under_each_higher_team_with_also_under(client, logged_in_admin, team_factory):
    windows, apps = team_factory(name="Windows"), team_factory(name="Applications")
    desktops = team_factory(name="Desktops", parents=(windows, apps))
    team_factory(name="Laptops", parent=desktops)
    tree = tree_of(client)
    assert tree.count(f'href="/admin/teams/{desktops.id}"') == 2
    assert re.findall(r">(Applications|Windows|Desktops|Laptops)</a>", tree) == [
        "Applications",
        "Desktops",
        "Laptops",
        "Windows",
        "Desktops",
        "Laptops",
    ]
    applications_part, windows_part = tree.split(f'href="/admin/teams/{windows.id}"')
    assert 'class="team-also"' in applications_part and "Also under Windows" in flat(applications_part)
    assert "Also under Applications" in flat(windows_part)
    assert flat(tree).count("Also under") == 2  # Laptops has one higher team and says nothing


def test_also_under_names_two_others_with_and(client, logged_in_admin, team_factory):
    a, b, c = team_factory(name="A"), team_factory(name="B"), team_factory(name="C")
    team_factory(name="Shared", parents=(a, b, c))
    tree = tree_of(client)
    under_a = tree[tree.index(f'href="/admin/teams/{a.id}"') : tree.index(f'href="/admin/teams/{b.id}"')]
    assert "Also under B and C" in flat(under_a)


def test_tree_note_says_a_team_appears_under_each(client, logged_in_admin):
    assert "A team in several groups shows under each, marked “Also under”." in text_of(client.get("/admin/teams"))


def test_team_page_header_names_every_higher_team(client, logged_in_admin, team_factory):
    windows, apps = team_factory(name="Windows"), team_factory(name="Applications")
    desktops = team_factory(name="Desktops", parents=(windows, apps))
    raw = raw_of(client.get(f"/admin/teams/{desktops.id}"))
    header = header_of(raw)
    assert "Under Applications and Windows" in flat(header)
    assert f'href="/admin/teams/{apps.id}"' in header and f'href="/admin/teams/{windows.id}"' in header
    assert "Teams › Desktops" in flat(raw)
    assert tree_of(client, f"/admin/teams/{desktops.id}").count('aria-current="page"') == 2  # every appearance


def test_team_page_header_joins_three_higher_teams(client, logged_in_admin, team_factory):
    a, b, c = team_factory(name="A"), team_factory(name="B"), team_factory(name="C")
    shared = team_factory(name="Shared", parents=(a, b, c))
    assert "Under A, B and C" in flat(header_of(raw_of(client.get(f"/admin/teams/{shared.id}"))))


def test_under_line_follows_the_place_line(client, logged_in_admin, team_factory):
    apps = team_factory(name="Applications")
    desktops = team_factory(name="Desktops", parent=apps)
    header = flat(header_of(raw_of(client.get(f"/admin/teams/{desktops.id}"))))
    assert header.index("Region not set") < header.index("Under Applications")


def test_top_level_team_page_says_top_level(client, logged_in_admin, team_factory):
    team = team_factory(name="Applications")
    raw = raw_of(client.get(f"/admin/teams/{team.id}"))
    assert "Top level" in flat(header_of(raw))


def test_tree_people_count_counts_each_person_once(client, logged_in_admin, team_factory, user_factory, add_member):
    top = team_factory(name="Top")
    left, right = team_factory(name="Left", parent=top), team_factory(name="Right", parent=top)
    desktops = team_factory(name="Desktops", parents=(left, right))
    add_member(top, user_factory(), "viewer")
    tree = tree_of(client)
    first = flat(tree.split(f'href="/admin/teams/{desktops.id}"')[1])
    assert first.startswith(">Desktops") and "1 person" in first[:60] and "2 people" not in first[:60]


def test_new_team_form_offers_a_higher_team(client, logged_in_admin, team_factory):
    team_factory(name="Windows")
    text = text_of(client.get("/admin/teams"))
    assert "Higher team" in text
    assert "Optional. You can add more higher teams from the team's page." in text


def test_a_cycle_in_the_data_does_not_crash_the_tree(client, logged_in_admin, db, team_factory):
    a, b, c = team_factory(name="A"), team_factory(name="B"), team_factory(name="C")
    db.add_all(
        TeamParent(team_id=team_id, parent_id=parent_id)
        for team_id, parent_id in ((b.id, a.id), (b.id, c.id), (c.id, b.id))
    )
    db.commit()
    for url in ("/admin/teams", f"/admin/teams/{c.id}"):
        assert client.get(url).status_code == 200, url
