"""The Teams New view (spec 2026-11-26-teams-new-view-design.md): the switch, the chart, the New team panel, a team's
page with its access map, the Add a member panel and Where it sits (database)."""

from __future__ import annotations

import html as html_lib
import re

from conftest import post

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
