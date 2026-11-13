"""A team's page: the compact header with edit in place and Delete beside the actions, and the tabs (database)."""

import re

import pytest

from tests.conftest import post
from tests.test_teams import entries, flat, header_of, parents_of, raw_of, text_of
from tracker.teams.tree import TEAM_CHOICE_ERROR
from tracker.teams.views import HAS_CHILDREN_MESSAGE


@pytest.fixture
def desktops(team_factory, region_factory, location_factory):
    emea = region_factory("EMEA")
    london = location_factory(emea, city="London", country_code="GB")
    windows, apps = team_factory(name="Windows"), team_factory(name="Applications")
    return team_factory(
        name="Desktops", parents=(windows, apps), location_id=london.id, description="Laptops and desks."
    )


def test_header_shows_place_under_and_description_and_actions(client, logged_in_admin, desktops):
    raw = raw_of(client.get(f"/admin/teams/{desktops.id}"))
    # the page title leads back to Teams ("Teams › Desktops"); the team's description sits under it, once
    title = (
        '<h1 class="title-crumb"><a href="/admin/teams">Teams</a>'
        '<span class="title-crumb-sep" aria-hidden="true">›</span>Desktops</h1>'
    )
    assert title in raw and raw.count("<h1") == 1
    assert '<p class="page-lede">Laptops and desks.</p>' in raw and raw.count("Laptops and desks.") == 1
    header = header_of(raw)
    text = flat(header)
    assert "EMEA" in text and "London, United Kingdom" in text
    assert "Under Applications and Windows" in text
    assert len(re.findall(r'href="/admin/teams/\d+"', header)) == 2
    assert f'href="/admin/teams/{desktops.id}?edit=1"' in header and "Edit details" in text
    assert f'href="/admin/teams/{desktops.id}/parents"' in header and "Higher teams" in text
    assert re.search(r'<button[^>]*title="Delete team"', header)
    assert 'id="details"' not in raw and ">Details<" not in raw


def test_teams_pages_open_with_a_title_and_a_description(client, logged_in_admin, desktops, team_factory):
    """Teams carries its count; a team without a description says what a team does; its sub-pages lead back."""
    index = raw_of(client.get("/admin/teams"))
    assert '<h1>Teams <span class="count-pill title-count">3<span class="sr-only"> teams</span>' in index
    plain = team_factory(name="Plain")
    page = raw_of(client.get(f"/admin/teams/{plain.id}"))
    assert (
        '<p class="page-lede">People in this team reach its trackers, and the trackers of every team below it.</p>'
        in page
    )
    crumbs = '<a href="/admin/teams">Teams</a><span class="title-crumb-sep" aria-hidden="true">›</span>'
    parents = raw_of(client.get(f"/admin/teams/{desktops.id}/parents"))
    assert f'{crumbs}<a href="/admin/teams/{desktops.id}">Desktops</a>' in parents
    assert '<span class="title-crumb-sep" aria-hidden="true">›</span>Higher teams</h1>' in parents
    assert "The teams Desktops sits under." in parents and parents.count("<h1") == 1


def test_header_shows_the_region_alone_without_a_location(client, logged_in_admin, team_factory, region_factory):
    world = region_factory("GLOBAL")
    team = team_factory(name="Group risk", region_id=world.id)
    header = flat(header_of(raw_of(client.get(f"/admin/teams/{team.id}"))))
    assert "GLOBAL" in header and "·" not in header


def test_tabs_link_with_counts_and_mark_the_current_one(
    client, logged_in_admin, team_factory, user_factory, add_member, tracker_factory
):
    infra = team_factory(name="Infrastructure")
    team_factory(name="Windows", parent=infra)
    team_factory(name="Patching", parent=infra)
    add_member(infra, user_factory(), "viewer")
    tracker_factory(team_id=infra.id)
    base = f"/admin/teams/{infra.id}"
    for tab, current in (("people", "People 1"), ("below", "Teams below 2"), ("trackers", "Trackers 1")):
        raw = raw_of(client.get(f"{base}?tab={tab}"))
        links = re.findall(r'<a class="tab[^"]*" href="([^"]*)"([^>]*)>(.*?)</a>', raw, re.S)
        assert [(href, flat(label)) for href, _, label in links] == [
            (f"{base}?tab=people", "People 1"),
            (f"{base}?tab=below", "Teams below 2"),
            (f"{base}?tab=trackers", "Trackers 1"),
        ]
        assert [flat(label) for _, extra, label in links if 'aria-current="page"' in extra] == [current]
        assert [f'id="tab-{t}"' in raw for t in ("people", "below", "trackers")] == [
            t == tab for t in ("people", "below", "trackers")
        ]


def test_people_tab_count_leaves_out_people_who_are_not_active(
    client, logged_in_admin, team_factory, user_factory, add_member
):
    infra = team_factory(name="Infrastructure")
    add_member(infra, user_factory(), "viewer")
    add_member(infra, user_factory(status="disabled"), "editor")
    raw = raw_of(client.get(f"/admin/teams/{infra.id}"))
    links = re.findall(r'<a class="tab[^"]*" href="[^"]*"[^>]*>(.*?)</a>', raw, re.S)
    assert flat(links[0]) == "People 1"
    assert "Disabled" in raw  # the disabled member is still listed, so it can be removed


def test_unknown_tab_shows_people(client, logged_in_admin, team_factory):
    team = team_factory(name="Windows")
    response = client.get(f"/admin/teams/{team.id}?tab=nonsense")
    raw = raw_of(response)
    assert response.status_code == 200 and 'id="tab-people"' in raw and 'id="tab-below"' not in raw
    assert re.findall(r'aria-current="page">People', raw)


def test_edit_mode_shows_the_form_in_the_header(client, logged_in_admin, desktops):
    raw = raw_of(client.get(f"/admin/teams/{desktops.id}?edit=1"))
    header = header_of(raw)
    assert f'action="/admin/teams/{desktops.id}/rename"' in header
    for label in ("Name", "Region", "Location", "Description"):
        assert f">{label}</label>" in header
    assert re.search(r'<option value=""[^>]*>No specific location</option>\s*<optgroup', header)
    assert "Save details" in header
    assert re.search(rf'<a[^>]*href="/admin/teams/{desktops.id}"[^>]*>Cancel</a>', header)
    assert 'href="/admin/teams/%d?edit=1"' % desktops.id not in raw
    assert "Higher teams" not in header and 'title="Delete team"' not in header
    assert 'id="details"' not in raw


def test_failed_save_keeps_edit_mode_and_values(client, logged_in_admin, desktops):
    page = post(
        client,
        f"/admin/teams/{desktops.id}/rename",
        {"name": "", "description": "Typed text kept.", "region_id": "", "location_id": ""},
    )
    assert page.status_code == 400
    raw = raw_of(page)
    header = header_of(raw)
    assert "Typed text kept." in header and "Save details" in header
    assert "Please correct the following" in header
    assert 'id="details"' not in raw


def test_delete_is_disabled_with_the_reason_when_teams_are_below(
    client, logged_in_admin, team_factory, tracker_factory
):
    parent = team_factory(name="Infrastructure")
    child = team_factory(name="Windows", parent=parent)
    header = header_of(raw_of(client.get(f"/admin/teams/{parent.id}")))
    [button] = re.findall(r"<button[^>]*\bdisabled\b[^>]*>.*?</button>", header, re.S)
    assert f'title="{HAS_CHILDREN_MESSAGE}"' in button and HAS_CHILDREN_MESSAGE in flat(button)
    assert f"/admin/teams/{parent.id}/delete" not in header
    header = header_of(raw_of(client.get(f"/admin/teams/{child.id}")))
    assert f'method="post" action="/admin/teams/{child.id}/delete"' in header
    assert "data-inline-confirm" in header and "Delete Windows" in flat(header) and 'name="csrf_token"' in header
    assert not re.search(r"<button[^>]*\bdisabled\b", header)


def test_a_refused_delete_shows_the_reason_in_the_header(client, logged_in_admin, team_factory):
    parent = team_factory(name="Infrastructure")
    team_factory(name="Windows", parent=parent)
    page = post(client, f"/admin/teams/{parent.id}/delete")
    assert page.status_code == 400 and HAS_CHILDREN_MESSAGE in flat(header_of(raw_of(page)))


def test_tree_help_sits_beside_the_title(client, logged_in_admin, team_factory):
    team_factory(name="Windows")
    raw = raw_of(client.get("/admin/teams"))
    head = re.search(r'<header class="[^"]*team-tree-head[^"]*">(.*?)</header>', raw, re.S).group(1)
    assert re.search(r"<h2[^>]*>Teams</h2>", head)
    assert (
        "A team in several groups shows under each, marked “Also under”. Numbers count the people who reach a team."
        in text_of(client.get("/admin/teams")).replace("\n", " ")
    )
    assert "The number beside a team" not in raw


def test_people_table_columns_filters_and_add_form_on_top(
    client, logged_in_admin, team_factory, user_factory, add_member
):
    infra = team_factory(name="Infrastructure")
    windows = team_factory(name="Windows", parent=infra)
    mia = user_factory(full_name="Mia Member")
    add_member(windows, mia, "viewer")
    add_member(infra, user_factory(full_name="Hana Head"), "owner")
    user_factory(full_name="Pat Possible")
    raw = raw_of(client.get(f"/admin/teams/{windows.id}"))
    assert raw.index(f'action="/admin/teams/{windows.id}/members"') < raw.index('data-search-for="people-table"')
    assert "team-add-panel" in raw and 'data-select-filter="user_id"' in raw
    assert 'src="/static/lists.js' in raw
    headings = re.findall(r'<th scope="col"[^>]*>.*?</th>', raw[raw.index('id="people-table"') :], re.S)
    assert [flat(h) for h in headings[:3]] == ["Person Person", "Route Route", "Role Role"]
    group = raw[raw.index('data-status-for="people-table"') :]
    group = group[group.index(">") + 1 : group.index("</div>")]
    assert re.findall(r'data-status="(\w+)"', group) == ["all", "direct", "inherited"]
    assert flat(group) == "All 2 Direct 1 From teams above 1"
    assert re.search(r'data-pager-for="people-table"[^>]*\bhidden\b', raw)
    direct = row_of(raw, "Mia Member")
    assert 'data-status="direct"' in direct and "<select" in direct and "Mia Member" in direct
    assert re.search(
        r'<button[^>]*class="tool-button[^"]*"[^>]*title="Remove Mia Member from Windows"[^>]*>\s*<svg.*?</svg>'
        r'\s*<span class="sr-only">Remove Mia Member from Windows</span>',
        direct,
        re.S,
    )
    assert ">Remove<" not in direct
    inherited = row_of(raw, "Hana Head")
    assert 'data-status="inherited"' in inherited
    assert "<select" not in inherited and "<form" not in inherited


def row_of(raw: str, name: str) -> str:
    [row] = [r for r in re.findall(r"<tr data-route.*?</tr>", raw, re.S) if name in r]
    return row


def test_teams_below_and_trackers_tables_columns(
    client, logged_in_admin, team_factory, tracker_factory, region_factory, business_line_factory, db
):
    from tracker.models import TrackerRegion

    infra = team_factory(name="Infrastructure")
    windows = team_factory(name="Windows", parent=infra)
    tracker_factory(name="Patch cycle", team_id=windows.id)
    emea = region_factory("EMEA")
    line = business_line_factory("Rates")
    live = tracker_factory(name="Laptop refresh", team_id=infra.id, business_line_id=line.id)
    old = tracker_factory(name="Old rollout", team_id=infra.id, status="archived")
    db.add(TrackerRegion(tracker_id=live.id, region_id=emea.id))
    db.commit()
    raw = raw_of(client.get(f"/admin/teams/{infra.id}?tab=below"))
    table = raw[raw.index('id="below-table"') : raw.index("</table>", raw.index('id="below-table"'))]
    assert [flat(h) for h in re.findall(r"<th scope=\"col\"[^>]*>.*?</th>", table, re.S)] == [
        "Team Team",
        "Place Place",
        "People People",
        "Trackers Trackers",
        "Actions",
    ]
    assert re.search(r"<tr[^>]*data-search=\"windows[^\"]*\"", table) and 'data-sort-trackers="1"' in table
    assert 'data-search-for="below-table"' in raw and 'data-pager-for="below-table"' in raw
    raw = raw_of(client.get(f"/admin/teams/{infra.id}?tab=trackers"))
    table = raw[raw.index('id="trackers-table"') : raw.index("</table>", raw.index('id="trackers-table"'))]
    assert [flat(h) for h in re.findall(r"<th scope=\"col\"[^>]*>.*?</th>", table, re.S)] == [
        "Tracker Tracker",
        "Business line Business line",
        "Regions Regions",
        "Status Status",
        "Actions",
    ]
    rows = re.findall(r"<tr[^>]*data-search.*?</tr>", table, re.S)
    assert len(rows) == 2
    live_row = next(r for r in rows if "Laptop refresh" in r)
    assert 'data-status="active"' in live_row and "Rates" in live_row and "EMEA" in live_row
    assert "Active" in flat(live_row) and f'href="/trackers/{live.id}/roles"' in live_row
    old_row = next(r for r in rows if "Old rollout" in r)
    assert 'data-status="archived"' in old_row and "Archived" in flat(old_row)
    assert f'href="/trackers/{old.id}/roles"' in old_row
    group = raw[raw.index('data-status-for="trackers-table"') :]
    assert flat(group[group.index(">") + 1 : group.index("</div>")]) == "All 2 Active 1 Archived 1"


@pytest.fixture
def estate(team_factory):
    """Top above Infra above Windows above Patching; Infra also has Apps below it; Other and Solo stand apart."""
    top = team_factory(name="Top")
    infra = team_factory(name="Infra", parent=top)
    windows = team_factory(name="Windows", parent=infra)
    patching = team_factory(name="Patching", parent=windows)
    apps = team_factory(name="Apps", parent=infra)
    other = team_factory(name="Other")
    solo = team_factory(name="Solo")
    return {
        "top": top,
        "infra": infra,
        "windows": windows,
        "patching": patching,
        "apps": apps,
        "other": other,
        "solo": solo,
    }


def below_url(team, **query) -> str:
    extra = "".join(f"&{key}={value}" for key, value in query.items())
    return f"/admin/teams/{team.id}?tab=below{extra}"


def test_top_panel_offers_existing_teams_without_loops(client, logged_in_admin, estate):
    raw = raw_of(client.get(below_url(estate["infra"])))
    panel = raw[raw.index('id="tab-below"') : raw.index('id="below-table"')]
    assert panel.index("team-add-panel") < panel.index("list-tools")
    text = flat(panel)
    assert "Existing team" in text and "Add selected team" in text and " or " in text and "New team" in text
    assert text.index("Add selected team") < text.index("New team")
    select = re.search(r'<select id="below_team_id" name="team_id".*?</select>', panel, re.S).group(0)
    names = re.findall(r"<option[^>]*>([^<]*)</option>", select)
    assert [n.strip() for n in names] == ["Other", "Patching", "Solo"]  # not Infra, Top (higher), Windows, Apps (below)
    assert f'action="/admin/teams/{estate["infra"].id}/below"' in panel and 'method="get"' in panel
    assert f"parent={estate['infra'].id}" in panel


def test_add_selected_team_previews_then_returns_to_the_tab(client, logged_in_admin, db, estate):
    infra, solo = estate["infra"], estate["solo"]
    response = client.get(f"/admin/teams/{infra.id}/below?team_id={solo.id}")
    assert response.status_code == 302
    preview = f"/admin/teams/{solo.id}/parents?add={infra.id}&back={infra.id}"
    assert response.headers["Location"].endswith(preview)
    page = client.get(preview)
    raw = raw_of(page)
    assert "Adding Solo under Infra" in text_of(page)
    assert f'name="back" value="{infra.id}"' in raw
    assert f'href="/admin/teams/{infra.id}?tab=below"' in raw  # Cancel
    done = post(
        client, f"/admin/teams/{solo.id}/parents", {"action": "add", "parent_id": str(infra.id), "back": str(infra.id)}
    )
    assert done.status_code == 302 and done.headers["Location"].endswith(f"/admin/teams/{infra.id}?tab=below")
    assert parents_of(db, solo) == {infra.id}
    assert len(entries(db, "team_parent_added")) == 1


def test_a_team_placed_below_at_the_same_moment_returns_to_the_tab(client, logged_in_admin, db, estate):
    """Someone else places Solo under Infra between the choice and the confirm: back to the tab, with a notice."""
    infra, solo = estate["infra"], estate["solo"]
    preview = f"/admin/teams/{solo.id}/parents?add={infra.id}&back={infra.id}"
    assert "Adding Solo under Infra" in text_of(client.get(preview))
    post(client, f"/admin/teams/{solo.id}/parents", {"action": "add", "parent_id": str(infra.id)})
    done = post(
        client, f"/admin/teams/{solo.id}/parents", {"action": "add", "parent_id": str(infra.id), "back": str(infra.id)}
    )
    assert done.status_code == 302 and done.headers["Location"].endswith(f"/admin/teams/{infra.id}?tab=below")
    assert "Solo is already under Infra." in text_of(client.get(done.headers["Location"]))
    again = client.get(preview)  # the preview link itself, followed late
    assert again.status_code == 302 and again.headers["Location"].endswith(f"/admin/teams/{infra.id}?tab=below")
    assert len(entries(db, "team_parent_added")) == 1


def test_an_error_on_higher_teams_offers_the_way_back_to_the_tab(client, logged_in_admin, estate):
    infra, top = estate["infra"], estate["top"]
    response = client.get(f"/admin/teams/{top.id}/parents?add={infra.id}&back={infra.id}")  # would form a cycle
    assert response.status_code == 400
    assert f'href="/admin/teams/{infra.id}?tab=below"' in raw_of(response)
    assert "Back to the teams below Infra" in text_of(response)


@pytest.mark.parametrize("value", ["", "x", "999999"])
def test_add_selected_team_without_a_real_team_is_refused(client, logged_in_admin, estate, value):
    response = client.get(f"/admin/teams/{estate['infra'].id}/below?team_id={value}")
    assert response.status_code == 400
    assert TEAM_CHOICE_ERROR in text_of(response) and 'id="tab-below"' in raw_of(response)


def test_row_remove_previews_then_returns(client, logged_in_admin, db, estate):
    infra, apps = estate["infra"], estate["apps"]
    raw = raw_of(client.get(below_url(infra)))
    row = next(r for r in re.findall(r"<tr[^>]*data-search.*?</tr>", raw, re.S) if "Apps" in r)
    link = re.search(r'<a class="tool-button[^"]*" href="([^"]*)" title="([^"]*)">(.*?)</a>', row, re.S)
    assert link.group(1).replace("&amp;", "&") == f"/admin/teams/{apps.id}/parents?remove={infra.id}&back={infra.id}"
    assert link.group(2) == "Remove Apps from under Infra"
    assert "Remove Apps from under Infra" in link.group(3) and "sr-only" in link.group(3)
    assert "Removing Apps from under Infra" in text_of(client.get(link.group(1).replace("&amp;", "&")))
    done = post(
        client,
        f"/admin/teams/{apps.id}/parents",
        {"action": "remove", "parent_id": str(infra.id), "back": str(infra.id)},
    )
    assert done.headers["Location"].endswith(f"/admin/teams/{infra.id}?tab=below")
    assert parents_of(db, apps) == set()
    assert len(entries(db, "team_parent_removed")) == 1


@pytest.mark.parametrize("back", ["999999", "abc", ""])
def test_back_to_an_unknown_team_is_ignored(client, logged_in_admin, db, estate, back):
    solo, infra = estate["solo"], estate["infra"]
    page = raw_of(client.get(f"/admin/teams/{solo.id}/parents?add={infra.id}&back={back}"))
    assert 'name="back"' not in page and f'href="/admin/teams/{solo.id}/parents"' in page
    done = post(client, f"/admin/teams/{solo.id}/parents", {"action": "add", "parent_id": str(infra.id), "back": back})
    assert done.headers["Location"].endswith(f"/admin/teams/{solo.id}/parents")


def test_blocked_delete_shows_its_reason_as_visible_text_beside_the_button(client, logged_in_admin, team_factory):
    parent = team_factory(name="Infrastructure")
    team_factory(name="Windows", parent=parent)
    header = header_of(raw_of(client.get(f"/admin/teams/{parent.id}")))
    outside = re.sub(r"<button[^>]*\bdisabled\b[^>]*>.*?</button>", "", header, flags=re.S)
    note = re.search(r'<(\w+)[^>]*class="[^"]*team-delete-note[^"]*"[^>]*>(.*?)</\1>', outside, re.S)
    assert note and HAS_CHILDREN_MESSAGE in flat(note.group(2))
    assert re.search(r"<button[^>]*\bdisabled\b[^>]*>.*?</button>", header, re.S)


def test_edit_details_keeps_the_current_tab(client, logged_in_admin, desktops):
    base = f"/admin/teams/{desktops.id}"
    header = header_of(raw_of(client.get(f"{base}?tab=trackers")))
    assert f'href="{base}?edit=1&amp;tab=trackers"' in header
    header = header_of(raw_of(client.get(f"{base}?edit=1&tab=trackers")))
    assert f'href="{base}?tab=trackers"' in header and 'name="tab" value="trackers"' in header
    page = post(
        client, f"{base}/rename", {"name": "", "description": "", "region_id": "", "location_id": "", "tab": "trackers"}
    )
    header = header_of(raw_of(page))
    assert (
        page.status_code == 400 and 'name="tab" value="trackers"' in header and f'href="{base}?tab=trackers"' in header
    )


def test_saving_details_returns_to_the_tab(client, logged_in_admin, desktops):
    base = f"/admin/teams/{desktops.id}"
    form = {
        "name": "Desktops 2",
        "description": "",
        "region_id": str(desktops.region_id),
        "location_id": str(desktops.location_id),
    }
    assert (
        post(client, f"{base}/rename", {**form, "tab": "trackers"}).headers["Location"].endswith(f"{base}?tab=trackers")
    )
    form["name"] = "Desktops 3"
    assert post(client, f"{base}/rename", {**form, "tab": "bogus"}).headers["Location"].endswith(base)


def test_pager_uses_the_singular_noun_for_one_row(client, logged_in_admin, team_factory, tracker_factory):
    team = team_factory(name="Infrastructure")
    tracker_factory(team_id=team.id)
    raw = raw_of(client.get(f"/admin/teams/{team.id}?tab=trackers"))
    assert 'data-noun-one="tracker"' in raw and 'data-noun-many="trackers"' in raw


def test_the_or_between_the_two_ways_to_add_a_team_below_has_its_own_style(client, logged_in_admin, estate):
    raw = raw_of(client.get(below_url(estate["infra"])))
    assert '<span class="team-add-or">or</span>' in raw and 'class="role-note">or<' not in raw
