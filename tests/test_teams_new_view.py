"""The Teams New view (spec 2026-11-26-teams-new-view-design.md): the switch, the chart, the New team panel, a team's
page with its access map, the Add a member panel and Where it sits (database)."""

from __future__ import annotations

import html as html_lib

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
    assert html.count(">Shared<") == 1


def test_an_empty_chart_says_so(client, logged_in_admin):
    assert "No teams yet." in page(client, "/admin/teams?view=new")
