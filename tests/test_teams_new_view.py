"""The Teams New view (spec 2026-11-26-teams-new-view-design.md): the switch, the chart, the New team panel, a team's
page with its access map, the Add a member panel and Where it sits (database)."""

from __future__ import annotations

import html as html_lib
import re

import pytest
from conftest import post
from sqlalchemy import select

from tracker.auth.guards import SELF_PROMOTION_MESSAGE, TEAM_WITH_SETS_MESSAGE
from tracker.models import AuditLog, TeamMember
from tracker.teams.overview import FOLD_OVER, chart
from tracker.teams.tree import ALREADY_MEMBER_MESSAGE, TeamRow, load_team_rows
from tracker.teams.views import CYCLE_MESSAGE


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
        form and 'name="role" value="editor" checked data-role-choice' in form.group(1) and "Set role" in form.group(1)
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


# --- Add a member ---------------------------------------------------------------------------------------------------


def _add_panel(html: str) -> str:
    return re.search(r'<aside id="add-member".*?</aside>', html, re.S).group(0)


def test_the_panel_explains_each_role(client, logged_in_admin, swaps):
    panel = _add_panel(team_page(client, swaps["team"]))
    cards = re.findall(
        r'name="role" value="(\w+)"[^>]*>\s*<span class="role-card-text"><strong>(\w+)</strong><span>([^<]+)</span>',
        panel,
    )
    assert cards == [
        ("viewer", "Viewer", "Opens the report and downloads it."),
        ("editor", "Editor", "Also records entries, writes the weekly update, keeps risks and targets."),
        ("owner", "Owner", "Also changes locations, settings and sends the report email."),
    ]
    assert 'value="viewer" checked' in panel  # the least access to start with


def test_the_preview_names_the_trackers(client, logged_in_admin, swaps, tracker_factory):
    tracker_factory(name="Old rollout", team_id=swaps["team"].id, status="archived")
    panel = _add_panel(team_page(client, swaps["rates"]))
    text = re.sub(r"<[^>]+>", "", re.search(r'<p class="add-preview".*?</p>', panel, re.S).group(0))
    assert (
        re.sub(r"\s+", " ", text)
        .strip()
        .endswith("will be a Viewer on 2 trackers: Rates laptop refresh, Swaps desk rollout.")
    )
    assert f'action="/admin/teams/{swaps["rates"].id}/members"' in panel


def test_the_preview_counts_past_three(client, logged_in_admin, team_factory, tracker_factory):
    team = team_factory("Many")
    for name in ("A", "B", "C", "D", "E"):
        tracker_factory(name=f"Tracker {name}", team_id=team.id)
    panel = _add_panel(team_page(client, team))
    assert "Tracker A, Tracker B, Tracker C and 2 more" in re.sub(r"<[^>]+>", "", panel)


def test_a_refused_add_shows_the_new_view_with_the_message(client, logged_in_admin, swaps):
    team, ana = swaps["team"], swaps["people"]["Ana Silva"]
    team_page(client, team)  # the New view is kept in the session
    response = post(client, f"/admin/teams/{team.id}/members", {"user_id": str(ana.id), "role": "viewer"})
    assert response.status_code == 400
    html = html_lib.unescape(response.get_data(as_text=True))
    assert ALREADY_MEMBER_MESSAGE in html and '<aside id="add-member"' in html and "access-chain" in html


def test_a_team_holding_sets_shows_the_refusal_instead_of_the_panel(client, logged_in_user, give_set, team_factory):
    team = team_factory("Holders")
    give_set(["manage_teams"], user=logged_in_user)
    give_set(["view_activity"], team=team)
    panel = _add_panel(team_page(client, team))
    assert TEAM_WITH_SETS_MESSAGE in panel and "<form" not in panel


# --- Where it sits --------------------------------------------------------------------------------------------------


def test_keep_shows_both_chains_after(client, logged_in_admin, swaps, team_factory, user_factory, add_member):
    apac = team_factory("APAC Desk", parent=swaps["top"])
    add_member(apac, user_factory(full_name="Kai Wong"), "editor")
    html = page(client, f"/admin/teams/{swaps['team'].id}/parents?view=new&to={apac.id}&how=add")
    now = re.search(r'<figure class="sits-now">(.*?)</figure>', html, re.S).group(1)
    after = re.search(r'<figure class="sits-after">(.*?)</figure>', html, re.S).group(1)
    assert now.count('class="access-chain') == 1 and after.count('class="access-chain') == 2
    assert re.search(r'<li class="is-new">.*?APAC Desk', after, re.S)
    assert "Kai Wong gains Editor on Swaps desk rollout." in html
    assert "Put London Swaps under APAC Desk too" in html


def test_move_replaces_every_higher_team(
    client, logged_in_admin, db, team_factory, user_factory, add_member, tracker_factory
):
    a, b, c = team_factory("A"), team_factory("B"), team_factory("C")
    team = team_factory("Moving", parents=(a, b))
    add_member(a, user_factory(full_name="Ann Above"), "viewer")
    tracker_factory(name="Their tracker", team_id=team.id)
    preview = page(client, f"/admin/teams/{team.id}/parents?view=new&to={c.id}&how=move")
    assert "Ann Above loses Viewer on Their tracker." in preview and "Move Moving under C" in preview
    response = post(client, f"/admin/teams/{team.id}/parents", {"action": "move", "parent_id": str(c.id)})
    assert response.status_code == 302
    assert load_team_rows(db) and next(r for r in load_team_rows(db) if r.id == team.id).parent_ids == (c.id,)
    actions = sorted(e.action for e in db.scalars(select(AuditLog).where(AuditLog.entity_id == str(team.id))))
    assert actions == ["team_parent_added", "team_parent_removed", "team_parent_removed"]


def test_move_to_the_only_higher_team_is_a_notice(client, logged_in_admin, team_factory):
    a = team_factory("A")
    team = team_factory("Under A", parent=a)
    html = page(client, f"/admin/teams/{team.id}/parents?view=new&to={a.id}&how=move")
    assert "Under A is already under A." in html and "move-confirm" not in html


def test_move_into_a_team_below_is_a_cycle(client, logged_in_admin, team_factory):
    team = team_factory("Top")
    below = team_factory("Below", parent=team)
    response = post(client, f"/admin/teams/{team.id}/parents", {"action": "move", "parent_id": str(below.id)})
    assert response.status_code == 400 and CYCLE_MESSAGE in html_lib.unescape(response.get_data(as_text=True))


def test_move_is_refused_when_it_would_raise_own_access(
    client, logged_in_user, db, give_set, team_factory, add_member, tracker_factory
):
    give_set(["manage_teams"], user=logged_in_user)
    mine, other = team_factory("Mine"), team_factory("Other")
    add_member(mine, logged_in_user, "owner")
    team = team_factory("Target", parent=other)
    tracker_factory(name="Target tracker", team_id=team.id)
    response = post(client, f"/admin/teams/{team.id}/parents", {"action": "move", "parent_id": str(mine.id)})
    assert response.status_code == 302
    assert next(r for r in load_team_rows(db) if r.id == team.id).parent_ids == (other.id,)
    follow = page(client, response.headers["Location"])
    assert SELF_PROMOTION_MESSAGE in follow


def test_the_classic_page_is_unchanged_by_the_new_params(client, logged_in_admin, team_factory):
    a, b = team_factory("A"), team_factory("B")
    team = team_factory("T", parent=a)
    html = page(client, f"/admin/teams/{team.id}/parents?view=classic&add={b.id}")
    assert "Add under B" in html and "sits-after" not in html


# --- Final review fixes ---------------------------------------------------------------------------------------------


def test_classic_shows_a_move_preview_as_a_move(client, logged_in_admin, team_factory):
    a, b, c = team_factory("A"), team_factory("B"), team_factory("C")
    team = team_factory("T", parents=(a, b))
    html = page(client, f"/admin/teams/{team.id}/parents?view=classic&to={c.id}&how=move")
    assert "Moving T under C" in html and "Move under C" in html and "Remove from C" not in html


@pytest.mark.parametrize("query", ["endpoint=x", "_method=DELETE", "_external=1", "_anchor=x"])
def test_odd_query_keys_do_not_break_the_switch(client, logged_in_admin, team_factory, query):
    team = team_factory("Desk")
    for url in ("/admin/teams", f"/admin/teams/{team.id}", f"/admin/teams/{team.id}/parents"):
        page(client, f"{url}?view=new&{query}")
