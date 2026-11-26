"""The Teams New view (spec 2026-11-26-teams-new-view-design.md): the switch, the chart, the New team panel, a team's
page with its access map, the Add a member panel and Where it sits (database)."""

from __future__ import annotations

import html as html_lib
import re

import pytest
from conftest import post
from sqlalchemy import select

from tracker.auth.guards import SELF_PROMOTION_MESSAGE, TEAM_WITH_SETS_MESSAGE
from tracker.models import AuditLog, Team, TeamMember, TeamParent
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
    assert shared[0].also_ids == (beta.id,)  # for the dotted line from Beta
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
    html = page(client, "/admin/teams/structure?view=new")
    assert "data-chart" in html and "London Swaps" in html
    assert "2 members · 1 tracker" in html


def test_the_chart_marks_also_under_and_folds(client, logged_in_admin, team_factory):
    alpha, beta = team_factory("Alpha"), team_factory("Beta")
    team_factory("Shared", parents=(alpha, beta))
    html = page(client, "/admin/teams/structure?view=new")
    assert "Also under Beta" in html
    chart_html = html.split("data-chart", 1)[1].split("</section>", 1)[0]
    assert chart_html.count(">Shared<") == 1  # once in the chart (the New team panel lists it too)


def test_the_chart_carries_the_dotted_lines_data(client, logged_in_admin, team_factory):
    alpha, beta = team_factory("Alpha"), team_factory("Beta")
    shared = team_factory("Shared", parents=(alpha, beta))
    html = page(client, "/admin/teams/structure?view=new")
    assert f'data-team-id="{shared.id}" data-also-ids="{beta.id}"' in html  # a dotted line from Beta, the other
    assert f'data-team-id="{alpha.id}">' in html  # no other higher team, no line
    assert "data-chart-links" in html
    assert re.search(r'<label class="org-links-toggle" data-links-toggle hidden>', html)  # shown by the script


def test_an_empty_chart_says_so(client, logged_in_admin):
    assert "No teams yet." in page(client, "/admin/teams/structure?view=new")


# --- The Structure card and the index (simple redesign) -------------------------------------------------------------


def _card(html: str) -> str:
    return re.search(r'<aside class="settings-section structure-card".*?</aside>', html, re.S).group(0)


def test_new_view_index_opens_on_the_first_top_level_team(client, logged_in_admin, team_factory):
    team_factory("Zeta")
    alpha = team_factory("Alpha")
    response = client.get("/admin/teams?view=new")
    assert response.status_code == 302 and response.headers["Location"].endswith(f"/admin/teams/{alpha.id}")


def test_new_view_index_without_teams_offers_the_form(client, logged_in_admin):
    html = page(client, "/admin/teams?view=new")
    assert "No teams yet." in html
    assert re.search(r'<form id="new-team-form"[^>]*>', html) and not re.search(
        r'<form id="new-team-form"[^>]*hidden', html
    )


def test_structure_card_shows_each_team_once(client, logged_in_admin, team_factory):
    alpha, beta = team_factory("Alpha"), team_factory("Beta")
    team_factory("Shared", parents=(alpha, beta))
    card = _card(page(client, f"/admin/teams/{alpha.id}?view=new"))
    assert card.count(">Shared<") == 1
    assert "Also under Beta" in card
    assert "The number is how many people reach a team through teams." in card


def test_structure_card_marks_the_current_team_and_counts_people(
    client, logged_in_admin, team_factory, user_factory, add_member
):
    team = team_factory("Desk")
    add_member(team, user_factory(), "viewer")
    add_member(team, user_factory(status="disabled"), "viewer")
    card = _card(page(client, f"/admin/teams/{team.id}?view=new"))
    node = re.search(r'<a class="structure-node"[^>]*aria-current="page"[^>]*>.*?</a>', card, re.S).group(0)
    assert ">Desk<" in node and "1 person" in node


def test_whole_structure_route_shows_the_chart(client, logged_in_admin, team_factory):
    team_factory("Desk")
    html = page(client, "/admin/teams/structure?view=new")
    assert "data-chart" in html and "Back to teams" in html


def test_whole_structure_needs_manage_teams(client, logged_in_user):
    assert client.get("/admin/teams/structure").status_code == 403


# --- The New team panel ---------------------------------------------------------------------------------------------


def _panel(html: str) -> str:
    return re.search(r'<aside id="new-team-panel".*?</aside>', html, re.S).group(0)


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


def test_the_role_select_posts_to_update_member_and_works_without_javascript(client, logged_in_admin, db, swaps):
    team, ana = swaps["team"], swaps["people"]["Ana Silva"]
    row = _row_of(team_page(client, team), "Ana Silva")
    assert f'action="/admin/teams/{team.id}/members/{ana.id}"' in row and "Set role" in row
    assert re.search(r'<option value="editor"\s+selected', row)
    assert post(client, f"/admin/teams/{team.id}/members/{ana.id}", {"role": "owner"}).status_code == 302
    assert db.get(TeamMember, (team.id, ana.id)).role == "owner"


def test_the_other_tabs_and_edit_details_render_in_the_new_view(client, logged_in_admin, swaps):
    team = swaps["team"]
    assert 'id="trackers-table"' in team_page(client, team, "trackers")
    assert 'action="/admin/teams/%d/rename"' % team.id in page(client, f"/admin/teams/{team.id}?view=new&edit=1")


# --- Add a member ---------------------------------------------------------------------------------------------------


def _add_panel(html: str) -> str:
    return re.search(r'<aside id="add-member".*?</aside>', html, re.S).group(0)


def test_a_refused_add_shows_the_new_view_with_the_message(client, logged_in_admin, swaps):
    team, ana = swaps["team"], swaps["people"]["Ana Silva"]
    team_page(client, team)  # the New view is kept in the session
    response = post(client, f"/admin/teams/{team.id}/members", {"user_id": str(ana.id), "role": "viewer"})
    assert response.status_code == 400
    html = html_lib.unescape(response.get_data(as_text=True))
    assert ALREADY_MEMBER_MESSAGE in html and '<section class="family"' in html and 'id="people-table"' in html


def test_a_team_holding_sets_shows_the_refusal_instead_of_the_panel(client, logged_in_user, give_set, team_factory):
    team = team_factory("Holders")
    give_set(["manage_teams"], user=logged_in_user)
    give_set(["view_activity"], team=team)
    html = team_page(client, team)
    assert TEAM_WITH_SETS_MESSAGE in html and 'action="/admin/teams/%d/members"' % team.id not in html


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
        page(client, f"{url}?view=new&{query}", 302 if url == "/admin/teams" else 200)  # the index opens Desk


# --- The team page (simple redesign, spec 4.4 and 4.5) ---------------------------------------------------------------


def text_of(html: str) -> str:
    return " ".join(re.sub(r"<[^>]+>", " ", html).split())


def _ladder(html: str) -> str:
    return re.search(r'<section class="family".*?</section>', html, re.S).group(0)


def _people(html: str) -> str:
    return re.search(r'<table id="people-table".*?</table>', html, re.S).group(0)


def _row_of(html: str, name: str) -> str:
    return next(row for row in re.findall(r"<tr\b.*?</tr>", _people(html), re.S) if name in row)


def test_team_header_figures(client, logged_in_admin, swaps):
    text = text_of(page(client, f"/admin/teams/{swaps['team'].id}?view=new"))
    assert "4 members" in text and "6 people through teams" in text and "1 tracker" in text


def test_ladder_shows_path_this_team_and_below(client, logged_in_admin, swaps):
    rates = swaps["rates"]
    lad = _ladder(page(client, f"/admin/teams/{rates.id}?view=new"))
    assert (
        text_of(lad).index("Global Markets")
        < text_of(lad).index("EMEA Rates this team")
        < text_of(lad).index("London Swaps")
    )
    assert f'href="/admin/teams/{swaps["top"].id}"' in lad and f'href="/admin/teams/{swaps["team"].id}"' in lad


def test_ladder_of_a_shared_team_has_also_sits_under(client, logged_in_admin, team_factory):
    alpha, beta = team_factory("Alpha"), team_factory("Beta")
    shared = team_factory("Shared", parents=(alpha, beta))
    lad = text_of(_ladder(page(client, f"/admin/teams/{shared.id}?view=new")))
    assert "Also sits under Beta" in lad and "Alpha" in lad


def test_ladder_without_teams_below(client, logged_in_admin, swaps):
    lad = text_of(_ladder(page(client, f"/admin/teams/{swaps['team'].id}?view=new")))
    assert "No teams below" in lad and "Change where it sits" in lad


def test_top_level_ladder_says_so(client, logged_in_admin, swaps):
    assert "this team · top level" in text_of(_ladder(page(client, f"/admin/teams/{swaps['top'].id}?view=new")))


def test_only_two_tabs_and_below_tab_falls_back(client, logged_in_admin, swaps):
    html = page(client, f"/admin/teams/{swaps['team'].id}?view=new")
    tabs = re.search(r'<nav class="tabs team-tabs".*?</nav>', html, re.S).group(0)
    assert "People" in tabs and "Trackers" in tabs and "Teams below" not in tabs
    html = page(client, f"/admin/teams/{swaps['team'].id}?tab=below")
    assert re.search(r'aria-current="page">People', html)


def test_put_an_existing_team_below_uses_indented_options(client, logged_in_admin, swaps):
    html = page(client, f"/admin/teams/{swaps['rates'].id}?view=new")
    form = re.search(
        r'<form class="below-form"[^>]*action="/admin/teams/%d/below".*?</form>' % swaps["rates"].id, html, re.S
    ).group(0)
    assert re.search(
        r'<option value="%d"[^>]*disabled[^>]*>[^<]*London Swaps \(already below\)' % swaps["team"].id, form
    )
    assert re.search(r'<option value="%d"[^>]*disabled[^>]*>[^<]*EMEA Rates \(this team\)' % swaps["rates"].id, form)


def test_people_how_they_get_access(client, logged_in_admin, swaps):
    html = page(client, f"/admin/teams/{swaps['team'].id}?view=new")
    assert "Member of this team" in text_of(_row_of(html, "Ana Silva"))
    priya = _row_of(html, "Priya Nair")
    assert "Through EMEA Rates (Owner)" in text_of(priya) and f'href="/admin/teams/{swaps["rates"].id}"' in priya
    tom = text_of(_row_of(html, "Tom Becker"))
    assert "Member of this team" in tom and "Through EMEA Rates (Editor)" in tom


def test_role_column(client, logged_in_admin, swaps):
    html = page(client, f"/admin/teams/{swaps['team'].id}?view=new")
    tom = _row_of(html, "Tom Becker")
    assert "<select" in tom and "Sees as Editor through a team above" in text_of(tom)
    priya = _row_of(html, "Priya Nair")
    assert "<select" not in priya and "Owner" in text_of(priya) and "Change in EMEA Rates" in text_of(priya)


def test_filters_hide_empty_groups(client, logged_in_admin, team_factory, user_factory, add_member):
    team = team_factory("Solo")
    add_member(team, user_factory(), "viewer")
    tools = re.search(
        r'<div class="list-tools">.*?</div>\s*<div class="section-table',
        page(client, f"/admin/teams/{team.id}?view=new"),
        re.S,
    ).group(0)
    assert "Everyone" in tools and "Members of this team" in tools and "Through a team above" not in tools


def test_people_note_names_what_is_not_listed(client, logged_in_admin, swaps):
    assert (
        "Administrators, people with View all trackers, regional access and roles given on a single tracker are not "
        "listed here." in text_of(page(client, f"/admin/teams/{swaps['team'].id}?view=new"))
    )


def test_inactive_members_listed_not_counted(client, logged_in_admin, swaps, user_factory, add_member):
    team = swaps["team"]
    add_member(team, user_factory(full_name="Old Member", status="disabled"), "viewer")
    html = page(client, f"/admin/teams/{team.id}?view=new")
    assert "Disabled" in text_of(_row_of(html, "Old Member"))
    text = text_of(html)
    assert "4 members" in text and "6 people through teams" in text and "Everyone 6" in text
    node = re.search(r'<a class="structure-node"[^>]*aria-current="page"[^>]*>.*?</a>', html, re.S).group(0)
    assert "6 people" in node


def test_trackers_tab_says_what_members_also_see(client, logged_in_admin, swaps):
    html = page(client, f"/admin/teams/{swaps['top'].id}?view=new&tab=trackers")
    assert "Members also see 2 trackers of the 2 teams below." in text_of(html)


# --- The New team form (simple redesign, spec 4.3) -------------------------------------------------------------------


def _form(html: str) -> str:
    return re.search(r'<form id="new-team-form".*?</form>', html, re.S).group(0)


def _select(form: str, name: str) -> str:
    return re.search(rf'<select id="{name}" name="{name}".*?</select>', form, re.S).group(0)


def _links(db, team_id):
    return sorted(db.scalars(select(TeamParent.parent_id).where(TeamParent.team_id == team_id)))


def test_create_with_also_under_makes_a_shared_team(client, logged_in_admin, db, team_factory, region_factory):
    alpha, beta = team_factory("Alpha"), team_factory("Beta")
    region = region_factory("EMEA")
    page(client, f"/admin/teams/{alpha.id}?view=new")
    response = post(
        client,
        "/admin/teams",
        {"name": "Rates Ops", "parent_id": str(alpha.id), "also_parent_id": str(beta.id), "region_id": str(region.id)},
    )
    assert response.status_code == 302
    team = db.scalar(select(Team).where(Team.name == "Rates Ops"))
    assert _links(db, team.id) == sorted([alpha.id, beta.id])
    entries = {
        (e.action, e.detail.get("parent"))
        for e in db.scalars(select(AuditLog).where(AuditLog.entity_id == str(team.id)))
    }
    assert ("team_created", "Alpha") in entries and ("team_parent_added", "Beta") in entries


def test_also_under_same_as_sits_under_makes_one_link(client, logged_in_admin, db, team_factory, region_factory):
    alpha = team_factory("Alpha")
    region = region_factory("EMEA")
    post(
        client,
        "/admin/teams",
        {"name": "Solo", "parent_id": str(alpha.id), "also_parent_id": str(alpha.id), "region_id": str(region.id)},
    )
    team = db.scalar(select(Team).where(Team.name == "Solo"))
    assert _links(db, team.id) == [alpha.id]
    assert not db.scalar(
        select(AuditLog).where(AuditLog.entity_id == str(team.id), AuditLog.action == "team_parent_added")
    )


def test_refused_create_keeps_what_was_entered(client, logged_in_admin, team_factory, region_factory, location_factory):
    alpha, beta = team_factory("Alpha"), team_factory("Beta")
    region = region_factory("EMEA")
    geneva = location_factory(region, "Geneva", "CH")
    page(client, f"/admin/teams/{alpha.id}?view=new")
    response = post(
        client,
        "/admin/teams",
        {
            "name": "Beta",
            "parent_id": str(alpha.id),
            "also_parent_id": str(beta.id),
            "region_id": str(region.id),
            "location_id": str(geneva.id),
            "description": "Kept",
        },
    )
    assert response.status_code == 400
    form = _form(html_lib.unescape(response.get_data(as_text=True)))
    assert "hidden" not in form.split(">", 1)[0]
    assert 'value="Beta"' in form and ">Kept</textarea>" in form
    assert re.search(rf'<option value="{alpha.id}"[^>]*selected', _select(form, "parent_id"))
    assert re.search(rf'<option value="{beta.id}"[^>]*selected', _select(form, "also_parent_id"))
    assert re.search(rf'<option value="{region.id}"\s+selected', form) and re.search(
        rf'<option value="{geneva.id}"\s+selected', form
    )


def test_sits_under_preselects_the_viewed_team(client, logged_in_admin, swaps):
    form = _form(page(client, f"/admin/teams/{swaps['rates'].id}?view=new&new=1"))
    assert "hidden" not in form.split(">", 1)[0]
    assert re.search(rf'<option value="{swaps["rates"].id}"[^>]*selected', _select(form, "parent_id"))
    assert "No second team" in _select(form, "also_parent_id")
