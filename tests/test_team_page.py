"""A team's page: the compact header with edit in place and Delete beside the actions, and the tabs (database)."""

import re

import pytest

from tests.conftest import post
from tests.test_teams import flat, header_of, raw_of, text_of
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
    header = header_of(raw)
    assert re.search(r"<h1[^>]*>\s*Desktops\s*</h1>", header)
    text = flat(header)
    assert "EMEA" in text and "London, United Kingdom" in text
    assert "Under Applications and Windows" in text
    assert "Laptops and desks." in text
    assert len(re.findall(r'href="/admin/teams/\d+"', header)) == 2
    assert f'href="/admin/teams/{desktops.id}?edit=1"' in header and "Edit details" in text
    assert f'href="/admin/teams/{desktops.id}/parents"' in header and "Higher teams" in text
    assert re.search(r'<button[^>]*title="Delete team"', header)
    assert 'id="details"' not in raw and ">Details<" not in raw


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
