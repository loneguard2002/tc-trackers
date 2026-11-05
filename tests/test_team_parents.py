"""The Higher teams screen: adding or removing one higher team, with a preview of who gains or loses access."""

import re

import pytest
from sqlalchemy import select

from tests.conftest import post, sign_in
from tests.test_teams import entries, flat, holder, parents_of, text_of
from tracker.auth.guards import SELF_PROMOTION_MESSAGE
from tracker.ids import MAX_ID
from tracker.models import Team, TeamParent
from tracker.teams.impact import move_impact
from tracker.teams.tree import TEAM_CHOICE_ERROR
from tracker.teams.views import ALREADY_UNDER, CYCLE_MESSAGE, NOT_UNDER


@pytest.fixture
def tree(team_factory, tracker_factory):
    """Windows under Infrastructure, Desktops under Windows, Applications at the top; a tracker in Desktops."""
    infra = team_factory(name="Infrastructure")
    windows = team_factory(name="Windows", parent=infra)
    desktops = team_factory(name="Desktops", parent=windows)
    apps = team_factory(name="Applications")
    laptops = tracker_factory(name="Laptop refresh", team_id=desktops.id)
    return infra, windows, desktops, apps, laptops


def screen(team) -> str:
    return f"/admin/teams/{team.id}/parents"


def add_options(page: str) -> list[str]:
    select_html = re.search(r'<select id="add" name="add".*?</select>', page, re.S).group(0)
    return re.findall(r'<option value="(\d+)"', select_html)


def test_screen_lists_higher_teams_and_offers_only_valid_ones(client, logged_in_admin, team_factory, tree):
    infra, windows, desktops, apps, _laptops = tree
    laptops_team = team_factory(name="Laptops", parent=desktops)
    raw = client.get(screen(desktops)).get_data(as_text=True)
    page = text_of(client.get(screen(desktops)))
    assert "Higher teams for Desktops" in page
    assert f'href="{screen(desktops)}?remove={windows.id}"' in raw and "Remove…" in page
    assert "Windows" in page and "Desktops is at the top level." not in page
    assert add_options(raw) == [str(apps.id), str(infra.id)]
    for excluded in (desktops, windows, laptops_team):
        assert str(excluded.id) not in add_options(raw)


def test_top_level_team_says_so_and_nothing_to_add(client, logged_in_admin, team_factory):
    only = team_factory(name="Only")
    page = text_of(client.get(screen(only)))
    assert "Only is at the top level." in page
    assert "No other team can take Only." in page
    assert 'name="add"' not in page


def test_preview_add_lists_gains(client, logged_in_admin, user_factory, add_member, tree):
    _infra, _windows, desktops, apps, _laptops = tree
    lead = user_factory(full_name="Apps Lead")
    add_member(apps, lead, "editor")
    page = text_of(client.get(f"{screen(desktops)}?add={apps.id}"))
    assert "Adding Desktops under Applications" in page
    assert "Apps Lead gains Editor on Laptop refresh." in page
    assert "No one loses access." in page and "No roles change." in page
    assert "Add under Applications" in page


def test_preview_remove_lists_losses(client, logged_in_admin, user_factory, add_member, tree):
    infra, windows, desktops, _apps, _laptops = tree
    head = user_factory(full_name="Head of Infrastructure")
    add_member(infra, head, "owner")
    page = text_of(client.get(f"{screen(desktops)}?remove={windows.id}"))
    assert "Removing Desktops from under Windows" in page
    assert "Head of Infrastructure loses Owner on Laptop refresh." in page
    assert "Remove from Windows" in page


def test_preview_remove_keeps_access_through_the_other_path(
    client, logged_in_admin, team_factory, tracker_factory, user_factory, add_member
):
    windows, apps = team_factory(name="Windows"), team_factory(name="Applications")
    desktops = team_factory(name="Desktops", parents=(windows, apps))
    tracker_factory(name="Laptop refresh", team_id=desktops.id)
    person = user_factory(full_name="Both Paths")
    add_member(windows, person, "editor")
    add_member(apps, person, "editor")
    page = text_of(client.get(f"{screen(desktops)}?remove={windows.id}"))
    assert "No one loses access." in page and "No roles change." in page
    assert "Both Paths" not in page


def test_preview_lists_role_changes_when_the_stronger_path_goes(
    client, logged_in_admin, team_factory, tracker_factory, user_factory, add_member
):
    strong, weak = team_factory(name="Strong"), team_factory(name="Weak")
    below = team_factory(name="Below", parents=(strong, weak))
    tracker_factory(name="Laptop refresh", team_id=below.id)
    person = user_factory(full_name="Dual Member")
    add_member(strong, person, "owner")
    add_member(weak, person, "viewer")
    page = text_of(client.get(f"{screen(below)}?remove={strong.id}"))
    assert "Dual Member goes from Owner to Viewer on Laptop refresh." in page


def test_people_whose_access_does_not_change_are_not_listed(
    client, logged_in_admin, user_factory, add_member, grant, tree
):
    infra, _windows, desktops, apps, laptops = tree
    person = user_factory(full_name="Steady Owner")
    add_member(infra, person, "owner")
    grant(person, laptops, "owner")
    page = text_of(client.get(f"{screen(desktops)}?add={apps.id}"))
    assert "Steady Owner" not in page


def test_administrators_and_inactive_people_are_left_out(client, logged_in_admin, user_factory, add_member, tree):
    _infra, _windows, desktops, apps, _laptops = tree
    boss = user_factory(full_name="Boss Admin", is_admin=True)
    gone = user_factory(full_name="Gone Person", status="disabled")
    waiting = user_factory(full_name="Waiting Person", status="pending")
    for person in (boss, gone, waiting):
        add_member(apps, person, "owner")
    page = text_of(client.get(f"{screen(desktops)}?add={apps.id}"))
    for name in ("Boss Admin", "Gone Person", "Waiting Person"):
        assert name not in page


def test_preview_changes_nothing(client, logged_in_admin, db, user_factory, add_member, tree):
    _infra, windows, desktops, apps, _laptops = tree
    add_member(apps, user_factory(full_name="Head"), "owner")
    assert client.get(f"{screen(desktops)}?add={apps.id}").status_code == 200
    assert parents_of(db, desktops) == {windows.id}
    assert entries(db) == []


def test_move_impact_leaves_the_session_clean(db, user_factory, add_member, tree):
    infra, windows, desktops, _apps, _laptops = tree
    add_member(infra, user_factory(full_name="Head"), "owner")
    impact = move_impact(db, desktops, frozenset())
    assert [c.user.full_name for c in impact.losses] == ["Head"]
    assert [t.name for t in impact.trackers] == ["Laptop refresh"]
    assert not db.dirty and not db.in_nested_transaction()
    assert set(db.scalars(select(TeamParent.parent_id).where(TeamParent.team_id == desktops.id))) == {windows.id}


def test_add_logs_and_links(client, logged_in_admin, db, tree):
    _infra, windows, desktops, apps, _laptops = tree
    response = post(client, screen(desktops), {"action": "add", "parent_id": str(apps.id)}, follow_redirects=True)
    assert "Added Desktops under Applications." in text_of(response)
    assert parents_of(db, desktops) == {windows.id, apps.id}
    [entry] = entries(db, "team_parent_added")
    assert entry.detail == {"team": "Desktops", "parent": "Applications"}
    assert entry.entity == "team" and entry.entity_id == str(desktops.id)


def test_remove_logs_and_unlinks(client, logged_in_admin, db, team_factory):
    one, two = team_factory(name="One"), team_factory(name="Two")
    team = team_factory(name="Team", parents=(one, two))
    response = post(client, screen(team), {"action": "remove", "parent_id": str(one.id)}, follow_redirects=True)
    text = text_of(response)
    assert "Removed Team from under One." in text and "It is now at the top level." not in text
    assert parents_of(db, team) == {two.id}
    [entry] = entries(db, "team_parent_removed")
    assert entry.detail == {"team": "Team", "parent": "One"}


def test_remove_last_link_makes_top_level(client, logged_in_admin, db, tree):
    _infra, windows, desktops, _apps, _laptops = tree
    response = post(client, screen(desktops), {"action": "remove", "parent_id": str(windows.id)}, follow_redirects=True)
    assert "Removed Desktops from under Windows. It is now at the top level." in text_of(response)
    assert parents_of(db, desktops) == set()
    [entry] = entries(db, "team_parent_removed")
    assert entry.detail == {"team": "Desktops", "parent": "Windows"}


def test_add_under_a_team_below_by_another_path_is_refused(client, logged_in_admin, db, team_factory):
    a, b = team_factory(name="A"), team_factory(name="B")
    c = team_factory(name="C", parents=(a, b))
    d = team_factory(name="D", parent=c)
    for team, parent in ((a, c), (b, d), (a, a)):
        page = post(client, screen(team), {"action": "add", "parent_id": str(parent.id)})
        assert page.status_code == 400 and CYCLE_MESSAGE in text_of(page)
        response = client.get(f"{screen(team)}?add={parent.id}")
        assert response.status_code == 400 and CYCLE_MESSAGE in text_of(response)
    assert parents_of(db, a) == set() and parents_of(db, b) == set()
    assert entries(db) == []
    assert CYCLE_MESSAGE == "A team cannot be placed under itself or under a team below it."


def test_adding_an_existing_link_is_a_notice(client, logged_in_admin, db, tree):
    _infra, windows, desktops, _apps, _laptops = tree
    message = ALREADY_UNDER.format(team="Desktops", parent="Windows")
    assert message == "Desktops is already under Windows."
    page = client.get(f"{screen(desktops)}?add={windows.id}")
    assert page.status_code == 200 and message in text_of(page)
    assert 'method="post"' not in page.get_data(as_text=True).split("<main", 1)[1]
    response = post(client, screen(desktops), {"action": "add", "parent_id": str(windows.id)})
    assert response.status_code == 302
    assert message in text_of(client.get(screen(desktops)))
    assert parents_of(db, desktops) == {windows.id}
    assert entries(db) == []


def test_removing_a_missing_link_is_a_notice(client, logged_in_admin, db, tree):
    _infra, windows, desktops, apps, _laptops = tree
    message = NOT_UNDER.format(team="Desktops", parent="Applications")
    assert message == "Desktops is not under Applications."
    page = client.get(f"{screen(desktops)}?remove={apps.id}")
    assert page.status_code == 200 and message in text_of(page)
    response = post(client, screen(desktops), {"action": "remove", "parent_id": str(apps.id)})
    assert response.status_code == 302
    assert message in text_of(client.get(screen(desktops)))
    assert parents_of(db, desktops) == {windows.id}
    assert entries(db) == []


def test_malformed_or_unknown_parent_is_400(client, logged_in_admin, db, team_factory, tree):
    _infra, windows, desktops, _apps, _laptops = tree
    gone = team_factory(name="Gone")
    gone_id = gone.id
    db.delete(db.get(Team, gone_id))
    db.commit()
    for value in ("abc", "1.5", "", "9" * 5000, str(MAX_ID + 1), str(gone_id)):
        for key in ("add", "remove"):
            response = client.get(f"{screen(desktops)}?{key}={value}")
            assert response.status_code == 400 and TEAM_CHOICE_ERROR in text_of(response)
            response = post(client, screen(desktops), {"action": key, "parent_id": value})
            assert response.status_code == 400 and TEAM_CHOICE_ERROR in text_of(response)
    assert post(client, screen(desktops), {"action": "swap", "parent_id": str(windows.id)}).status_code == 400
    assert parents_of(db, desktops) == {windows.id}
    assert entries(db) == []


def test_unknown_team_is_404(client, logged_in_admin):
    assert client.get("/admin/teams/99999/parents").status_code == 404
    assert post(client, "/admin/teams/99999/parents", {"action": "add", "parent_id": "1"}).status_code == 404


def test_holder_cannot_add_a_team_under_their_own_team(
    client, db, user_factory, give_set, team_factory, tracker_factory, add_member
):
    actor = holder(user_factory, give_set, client)
    own = team_factory(name="Own")
    add_member(own, actor, "owner")
    other = team_factory(name="Other")
    tracker_factory(team_id=other.id)
    response = post(client, screen(other), {"action": "add", "parent_id": str(own.id)}, follow_redirects=True)
    assert SELF_PROMOTION_MESSAGE in text_of(response)
    assert parents_of(db, other) == set()
    assert entries(db) == []


def test_old_move_address_is_gone(client, logged_in_admin, team_factory):
    team = team_factory(name="Windows")
    assert client.get(f"/admin/teams/{team.id}/move").status_code == 404
    assert post(client, f"/admin/teams/{team.id}/move", {"parent_id": ""}).status_code == 404


def test_team_page_links_to_higher_teams(client, logged_in_admin, team_factory):
    team = team_factory(name="Windows")
    raw = client.get(f"/admin/teams/{team.id}").get_data(as_text=True)
    assert f'href="/admin/teams/{team.id}/parents"' in raw and "Higher teams…" in raw
    assert "Move…" not in raw


def test_parents_requires_manage_teams(client, user_factory, team_factory):
    team = team_factory(name="Windows")
    sign_in(client, user_factory(full_name="Outsider"))
    assert client.get(screen(team)).status_code == 403
    assert post(client, screen(team), {"action": "add", "parent_id": "1"}).status_code == 403


def test_notices_sit_in_the_section_they_belong_to(client, logged_in_admin, tree):
    _infra, windows, desktops, apps, _laptops = tree
    removed = client.get(f"{screen(desktops)}?remove={apps.id}").get_data(as_text=True)
    now, add = removed.split('id="section-add"')
    assert "Desktops is not under Applications." in flat(now.split('id="section-now"')[1])
    assert "Desktops is not under" not in flat(add)
    added = client.get(f"{screen(desktops)}?add={windows.id}").get_data(as_text=True)
    now, add = added.split('id="section-add"')
    assert "Desktops is already under Windows." in flat(add)
    assert "Desktops is already under" not in flat(now)
