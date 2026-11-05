"""The move preview: who loses, gains or changes access before a team is moved (database required)."""

import re

import pytest
from sqlalchemy import select

from tests.conftest import post, sign_in
from tests.test_teams import entries, parents_of, text_of
from tracker.models import TeamParent
from tracker.teams.impact import move_impact
from tracker.teams.tree import TEAM_CHOICE_ERROR
from tracker.teams.views import CYCLE_MESSAGE


@pytest.fixture
def tree(team_factory, tracker_factory):
    infra = team_factory(name="Infrastructure")
    windows = team_factory(name="Windows", parent=infra)
    apps = team_factory(name="Applications")
    laptops = tracker_factory(name="Laptop refresh", team_id=windows.id)
    return infra, windows, apps, laptops


def preview(client, windows, apps):
    return client.get(f"/admin/teams/{windows.id}/move?parent_id={apps.id}")


def test_preview_lists_who_loses_and_gains(client, logged_in_admin, user_factory, add_member, tree):
    infra, windows, apps, _laptops = tree
    head = user_factory(full_name="Head of Infrastructure")
    lead = user_factory(full_name="Apps Lead")
    add_member(infra, head, "owner")
    add_member(apps, lead, "editor")
    page = text_of(preview(client, windows, apps))
    assert "Head of Infrastructure loses Owner on Laptop refresh." in page
    assert "Apps Lead gains Editor on Laptop refresh." in page
    assert "No one loses access." not in page and "No one gains access." not in page
    assert "No roles change." in page


def test_preview_lists_role_changes(client, logged_in_admin, user_factory, add_member, tree):
    infra, windows, apps, _laptops = tree
    person = user_factory(full_name="Dual Member")
    add_member(infra, person, "owner")
    add_member(apps, person, "viewer")
    page = text_of(preview(client, windows, apps))
    assert "Dual Member goes from Owner to Viewer on Laptop refresh." in page
    assert "No one loses access." in page and "No one gains access." in page


def test_people_whose_access_does_not_change_are_not_listed(
    client, logged_in_admin, user_factory, add_member, grant, tree
):
    infra, windows, apps, laptops = tree
    person = user_factory(full_name="Steady Owner")
    add_member(infra, person, "owner")
    grant(person, laptops, "owner")
    page = text_of(preview(client, windows, apps))
    assert "Steady Owner" not in page
    assert "No one loses access." in page and "No roles change." in page


def test_administrators_and_inactive_people_are_left_out(client, logged_in_admin, user_factory, add_member, tree):
    infra, windows, apps, _laptops = tree
    boss = user_factory(full_name="Boss Admin", is_admin=True)  # owner everywhere, so never changes
    gone = user_factory(full_name="Gone Person", status="disabled")
    waiting = user_factory(full_name="Waiting Person", status="pending")
    for person in (boss, gone, waiting):
        add_member(infra, person, "owner")
    page = text_of(preview(client, windows, apps))
    for name in ("Boss Admin", "Gone Person", "Waiting Person"):
        assert name not in page


def test_preview_changes_nothing(client, logged_in_admin, db, user_factory, add_member, tree):
    infra, windows, apps, _laptops = tree
    add_member(infra, user_factory(full_name="Head"), "owner")
    assert preview(client, windows, apps).status_code == 200
    assert parents_of(db, windows) == {infra.id}
    assert entries(db) == []
    assert post(client, f"/admin/teams/{windows.id}/move", {"parent_id": str(apps.id)}).status_code == 302
    assert parents_of(db, windows) == {apps.id}


def test_move_impact_leaves_the_session_clean(db, user_factory, add_member, tree):
    infra, windows, apps, _laptops = tree
    add_member(infra, user_factory(full_name="Head"), "owner")
    impact = move_impact(db, windows, frozenset({apps.id}))
    assert [c.user.full_name for c in impact.losses] == ["Head"]
    assert [t.name for t in impact.trackers] == ["Laptop refresh"]
    assert not db.dirty and not db.in_nested_transaction()
    assert set(db.scalars(select(TeamParent.parent_id).where(TeamParent.team_id == windows.id))) == {infra.id}


def test_bad_destinations(client, logged_in_admin, db, team_factory, user_factory, give_set, tree):
    infra, windows, apps, _laptops = tree
    servers = team_factory(name="Servers", parent=windows)
    for value in ("abc", "9" * 20):
        response = client.get(f"/admin/teams/{windows.id}/move?parent_id={value}")
        assert response.status_code == 400 and TEAM_CHOICE_ERROR in text_of(response)
    for target in (windows, servers):
        response = client.get(f"/admin/teams/{windows.id}/move?parent_id={target.id}")
        assert response.status_code == 400 and CYCLE_MESSAGE in text_of(response)
    same = client.get(f"/admin/teams/{windows.id}/move?parent_id={infra.id}")
    assert same.status_code == 200
    assert "Windows is already below Infrastructure." in text_of(same)
    assert 'method="post"' not in same.get_data(as_text=True).split("<main", 1)[1]
    assert client.get("/admin/teams/99999/move").status_code == 404
    outsider = user_factory(full_name="Outsider")
    sign_in(client, outsider)
    assert client.get(f"/admin/teams/{windows.id}/move").status_code == 403


def test_already_at_the_top_level(client, logged_in_admin, team_factory):
    top = team_factory(name="Windows")
    page = text_of(client.get(f"/admin/teams/{top.id}/move?parent_id="))
    assert "Windows is already at the top level." in page


def test_page_without_a_choice_offers_every_valid_place(client, logged_in_admin, team_factory):
    infra = team_factory(name="Infrastructure")
    windows = team_factory(name="Windows", parent=infra)
    servers = team_factory(name="Servers", parent=windows)
    apps = team_factory(name="Applications")
    page = client.get(f"/admin/teams/{windows.id}/move").get_data(as_text=True)
    select_html = re.search(r'<select id="parent_id" name="parent_id".*?</select>', page, re.S).group(0)
    assert re.findall(r'<option value="(\d*)"', select_html) == ["", str(apps.id), str(infra.id)]
    assert str(servers.id) not in select_html
    assert "Lose access" not in page
