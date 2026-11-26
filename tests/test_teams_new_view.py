"""The Teams New view (spec 2026-11-26-teams-new-view-design.md): the switch, the chart, the New team panel, a team's
page with its access map, the Add a member panel and Where it sits (database)."""

from __future__ import annotations

import html as html_lib
import re

import pytest
from conftest import post

from tracker.models import TeamMember
from tracker.teams.overview import FOLD_OVER, chart
from tracker.teams.tree import TeamRow, load_team_rows


def page(client, url: str, status: int = 200) -> str:
    response = client.get(url)
    assert response.status_code == status, url
    return html_lib.unescape(response.get_data(as_text=True))


def walk(nodes):
    for node in nodes:
        yield node
        yield from walk(node.children)


# --- The switch and the chart ---------------------------------------------------------------------------------------


def test_the_switch_keeps_the_choice_and_classic_is_unchanged(client, logged_in_admin):
    assert 'aria-current="page">New view' in page(client, "/admin/teams?view=new")
    assert 'aria-current="page">New view' in page(client, "/admin/teams")  # kept in the session
    html = page(client, "/admin/teams?view=classic")
    assert 'aria-current="page">Classic view' in html and 'class="settings-section teams-tree-card' in html
    assert 'aria-current="page">Classic view' in page(client, "/admin/teams")


def test_the_switch_keeps_the_page_and_its_tab(client, logged_in_admin, team_factory):
    team = team_factory("Desk")
    html = page(client, f"/admin/teams/{team.id}?tab=trackers&view=classic")
    assert f'href="/admin/teams/{team.id}?tab=trackers&view=new"' in html


def test_a_team_under_two_teams_shows_once_with_also_under(db, team_factory):
    alpha, beta = team_factory("Alpha"), team_factory("Beta")
    team_factory("Shared", parents=(beta, alpha))
    shared = [node for node in walk(chart(load_team_rows(db))) if node.row.name == "Shared"]
    assert len(shared) == 1 and shared[0].also_under == ["Beta"]  # under Alpha, the first by name
    alpha_node = next(node for node in chart(load_team_rows(db)) if node.row.name == "Alpha")
    assert [child.row.name for child in alpha_node.children] == ["Shared"]


def test_the_chart_ends_on_a_cycle():
    # Corrupted data: A at the top, B under A and C, C under B; and D and E under each other, out of reach.
    rows = [
        TeamRow(1, "A", ()),
        TeamRow(2, "B", (1, 3)),
        TeamRow(3, "C", (2,)),
        TeamRow(4, "D", (5,)),
        TeamRow(5, "E", (4,)),
    ]
    names = [node.row.name for node in walk(chart(rows))]
    assert names == ["A", "B", "C"]


def test_deep_wide_branches_fold():
    rows = [TeamRow(1, "Top", ()), TeamRow(2, "Mid", (1,)), TeamRow(3, "Deep", (2,)), TeamRow(4, "Narrow", (2,))]
    rows += [TeamRow(10 + i, f"Leaf {i:02}", (3,)) for i in range(FOLD_OVER + 1)]
    rows += [TeamRow(30 + i, f"Twig {i:02}", (4,)) for i in range(FOLD_OVER)]
    nodes = {node.row.name: node for node in walk(chart(rows))}
    assert nodes["Deep"].folded and not nodes["Narrow"].folded
    rows = [TeamRow(1, "Top", ())] + [TeamRow(10 + i, f"Leaf {i:02}", (1,)) for i in range(FOLD_OVER + 5)]
    assert not chart(rows)[0].folded  # the first levels never fold


def test_the_chart_page_shows_each_team_with_its_counts(
    client, logged_in_admin, db, team_factory, user_factory, add_member, tracker_factory
):
    team = team_factory("London Swaps")
    for status in ("active", "active", "disabled"):
        add_member(team, user_factory(status=status), "viewer")
    tracker_factory(name="Live", team_id=team.id)
    tracker_factory(name="Old", team_id=team.id, status="archived")
    html = page(client, "/admin/teams?view=new")
    assert "data-chart" in html and "London Swaps" in html
    assert "2 members · 1 tracker" in html


def test_the_chart_marks_also_under_and_folds(client, logged_in_admin, team_factory):
    alpha, beta = team_factory("Alpha"), team_factory("Beta")
    team_factory("Shared", parents=(alpha, beta))
    html = page(client, "/admin/teams?view=new")
    assert "Also under Beta" in html
    chart_html = html.split("data-chart", 1)[1].split("</section>", 1)[0]
    assert chart_html.count(">Shared<") == 1  # once in the chart (the New team panel lists it too)


def test_an_empty_chart_says_so(client, logged_in_admin):
    assert "No teams yet." in page(client, "/admin/teams?view=new")


# --- The New team panel ---------------------------------------------------------------------------------------------


def _panel(html: str) -> str:
    return re.search(r'<aside id="new-team-panel".*?</aside>', html, re.S).group(0)


def test_the_panel_opens_on_request_and_lists_where_a_team_can_sit(client, logged_in_admin, team_factory):
    top = team_factory("Global Markets")
    rates = team_factory("EMEA Rates", parent=top)
    team_factory("London Swaps", parent=rates)
    team_factory("APAC Desk", parent=top)
    assert re.search(r'<aside id="new-team-panel"[^>]*hidden', page(client, "/admin/teams?view=new"))
    panel = _panel(page(client, "/admin/teams?view=new&new=1"))
    assert "hidden" not in panel.split(">", 1)[0]
    choices = re.findall(r'name="parent_id" value="(\d*)"[^>]*>\s*<span[^>]*>([^<]+)</span>', panel)
    assert [name for _, name in choices] == ["Top level", "Global Markets", "APAC Desk", "EMEA Rates", "London Swaps"]
    assert 'class="sit-choice depth-3"' in panel  # London Swaps, indented two levels
    assert "You can put it under a second team from its Where it sits page." in panel


def test_the_panel_says_who_reaches_the_new_team(client, logged_in_admin, team_factory, user_factory, add_member):
    top = team_factory("Global Markets")
    rates = team_factory("EMEA Rates", parent=top)
    add_member(rates, user_factory(full_name="Priya Nair"), "owner")
    add_member(top, user_factory(full_name="Sam Ortiz"), "viewer")
    add_member(top, user_factory(full_name="Gone Person", status="disabled"), "owner")
    panel = _panel(page(client, "/admin/teams?view=new&new=1"))
    reach = re.search(rf'<ul class="reach-list" data-reach-for="{rates.id}"[^>]*>(.*?)</ul>', panel, re.S).group(1)
    assert re.findall(r"<li>([^<]+)</li>", reach) == [
        "Priya Nair · Owner · EMEA Rates",
        "Sam Ortiz · Viewer · Global Markets",
    ]
    assert 'data-reach-for="">Only the members you add' in panel


def test_the_reach_list_shows_five_then_a_count(client, logged_in_admin, team_factory, user_factory, add_member):
    top = team_factory("Big")
    for n in range(7):
        add_member(top, user_factory(full_name=f"Person {n}"), "viewer")
    panel = _panel(page(client, "/admin/teams?view=new&new=1"))
    reach = re.search(rf'data-reach-for="{top.id}"[^>]*>(.*?)</ul>', panel, re.S).group(1)
    assert reach.count("<li>") == 6 and "and 2 more" in reach


def test_a_refused_create_shows_the_new_view_with_the_panel_open_and_the_input_kept(
    client, logged_in_admin, team_factory, region_factory
):
    team_factory("Desk")
    region = region_factory("EMEA")
    page(client, "/admin/teams?view=new")  # the choice is kept in the session
    response = post(client, "/admin/teams", {"name": "Desk", "parent_id": "", "region_id": str(region.id)})
    assert response.status_code == 400
    html = html_lib.unescape(response.get_data(as_text=True))
    panel = _panel(html)
    assert "hidden" not in panel.split(">", 1)[0] and 'value="Desk"' in panel
    assert "already" in html and "data-chart" in html


def test_the_panel_offers_each_team_s_place_for_filling_in(
    client, logged_in_admin, team_factory, region_factory, location_factory
):
    region = region_factory("EMEA")
    london = location_factory(region, "London", "GB", code="LON")
    rates = team_factory("EMEA Rates", location_id=london.id)
    panel = _panel(page(client, "/admin/teams?view=new&new=1"))
    assert re.search(
        rf'value="{rates.id}" data-team-name="EMEA Rates" '
        rf'data-place-region="{region.id}" data-place-location="{london.id}"',
        panel,
    )


# --- A team's page --------------------------------------------------------------------------------------------------


@pytest.fixture
def swaps(db, team_factory, user_factory, add_member, tracker_factory):
    """Global Markets > EMEA Rates > London Swaps, with the sample people of the design."""
    top = team_factory("Global Markets")
    rates = team_factory("EMEA Rates", parent=top)
    team = team_factory("London Swaps", parent=rates)
    people = {name: user_factory(full_name=name) for name in ("Ana Silva", "Lee Chen", "Mia Rossi", "Tom Becker")}
    people["Priya Nair"] = user_factory(full_name="Priya Nair")
    people["Sam Ortiz"] = user_factory(full_name="Sam Ortiz")
    for name, role in (
        ("Ana Silva", "editor"),
        ("Lee Chen", "viewer"),
        ("Mia Rossi", "viewer"),
        ("Tom Becker", "viewer"),
    ):
        add_member(team, people[name], role)
    add_member(rates, people["Priya Nair"], "owner")
    add_member(rates, people["Tom Becker"], "editor")
    add_member(top, people["Sam Ortiz"], "viewer")
    tracker_factory(name="Swaps desk rollout", team_id=team.id)
    tracker_factory(name="Rates laptop refresh", team_id=rates.id)
    return {"top": top, "rates": rates, "team": team, "people": people}


def team_page(client, team, tab: str | None = None) -> str:
    return page(client, f"/admin/teams/{team.id}?view=new" + (f"&tab={tab}" if tab else ""))


def test_the_map_shows_the_chain_and_this_team(client, logged_in_admin, swaps):
    html = team_page(client, swaps["team"])
    chain = re.search(r'<ol class="access-chain">(.*?)</ol>', html, re.S).group(1)
    assert re.findall(r'class="chain-name">([^<]+)<', chain) == ["Global Markets", "EMEA Rates", "London Swaps"]
    assert "1 person reaches down" in chain and "2 people reach down" in chain
    assert "4 members · 1 tracker" in chain and "Add a team below" in html


def test_a_team_under_two_teams_shows_both_chains(client, logged_in_admin, team_factory):
    left, right = team_factory("Left"), team_factory("Right")
    shared = team_factory("Shared", parents=(left, right))
    html = team_page(client, shared)
    chains = re.findall(r'<ol class="access-chain">(.*?)</ol>', html, re.S)
    assert [re.findall(r'class="chain-name">([^<]+)<', c)[0] for c in chains] == ["Left", "Right"]


def test_people_are_split_into_members_and_from_teams_above(client, logged_in_admin, swaps):
    html = team_page(client, swaps["team"])
    members = re.search(r'<section class="[^"]*team-members".*?</section>', html, re.S).group(0)
    assert "Members of London Swaps" in members
    assert re.findall(r'class="member-name">([^<]+)<', members) == ["Ana Silva", "Lee Chen", "Mia Rossi", "Tom Becker"]
    above = re.search(r'<section class="[^"]*team-from-above".*?</section>', html, re.S).group(0)
    groups = re.findall(r'<h4 class="from-team">([^<]+)</h4>(.*?)(?=<h4|</section>)', above, re.S)
    assert [(title, re.findall(r'class="member-name">([^<]+)<', rows)) for title, rows in groups] == [
        ("From EMEA Rates · team above", ["Priya Nair", "Tom Becker"]),
        ("From Global Markets · 2 levels up", ["Sam Ortiz"]),
    ]


def test_a_member_outranked_from_above_is_told(client, logged_in_admin, swaps):
    assert "Editor counts: Editor of EMEA Rates, above" in team_page(client, swaps["team"])


def test_the_role_switch_posts_to_update_member_and_works_without_javascript(client, logged_in_admin, db, swaps):
    team, ana = swaps["team"], swaps["people"]["Ana Silva"]
    html = team_page(client, team)
    form = re.search(
        rf'<form class="role-switch" method="post" action="/admin/teams/{team.id}/members/{ana.id}">(.*?)</form>',
        html,
        re.S,
    )
    assert (
        form and 'name="role" value="editor" checked data-autosubmit' in form.group(1) and "Set role" in form.group(1)
    )
    assert post(client, f"/admin/teams/{team.id}/members/{ana.id}", {"role": "owner"}).status_code == 302
    assert db.get(TeamMember, (team.id, ana.id)).role == "owner"


def test_the_menu_holds_where_it_sits_and_delete(client, logged_in_admin, swaps, team_factory):
    html = team_page(client, swaps["team"])
    menu = re.search(r'<details class="team-menu">(.*?)</details>', html, re.S).group(1)
    assert f'href="/admin/teams/{swaps["team"].id}/parents"' in menu and "Where it sits" in menu
    assert "This team has trackers" in menu  # it cannot be deleted
    lone = team_factory("Lone")
    menu = re.search(r'<details class="team-menu">(.*?)</details>', team_page(client, lone), re.S).group(1)
    assert f'action="/admin/teams/{lone.id}/delete"' in menu


def test_the_other_tabs_and_edit_details_render_in_the_new_view(client, logged_in_admin, swaps):
    team = swaps["team"]
    assert 'id="below-table"' not in team_page(client, team, "below") and "No teams are below this one." in team_page(
        client, team, "below"
    )
    assert 'id="trackers-table"' in team_page(client, team, "trackers")
    assert 'action="/admin/teams/%d/rename"' % team.id in page(client, f"/admin/teams/{team.id}?view=new&edit=1")
