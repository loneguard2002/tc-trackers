"""The tracker Access screen for team managers, and access through teams (database required)."""

import html

from sqlalchemy import select

from tests.conftest import post
from tracker.auth.guards import SELF_PROMOTION_MESSAGE
from tracker.auth.roles import team_access
from tracker.models import AuditLog, TrackerRole


def text_of(response) -> str:
    return html.unescape(response.get_data(as_text=True))


def entries(db, action):
    db.expire_all()
    return list(db.scalars(select(AuditLog).where(AuditLog.action == action).order_by(AuditLog.id)))


def test_access_screen_opens_for_a_holder_without_a_role(client, logged_in_user, give_set, tracker_factory):
    give_set(["manage_teams"], user=logged_in_user)
    t = tracker_factory(name="Patching")
    page = client.get(f"/trackers/{t.id}/roles")
    body = page.get_data(as_text=True)
    assert page.status_code == 200 and "Patching" in body
    assert f'href="/trackers/{t.id}/report"' not in body
    assert client.get(f"/trackers/{t.id}").status_code == 404


def test_access_screen_for_a_missing_tracker_is_404_for_a_holder(client, logged_in_user, give_set):
    give_set(["manage_teams"], user=logged_in_user)
    assert client.get("/trackers/99999/roles").status_code == 404


def test_access_screen_refuses_a_user_without_manage_teams_before_looking_for_the_tracker(client, logged_in_user):
    assert client.get("/trackers/99999/roles").status_code == 403


def test_role_set_logs_before_after_and_the_affected_user(
    client, logged_in_user, give_set, tracker_factory, user_factory, db
):
    give_set(["manage_teams"], user=logged_in_user)
    t, member = tracker_factory(), user_factory(full_name="Member One")
    url = f"/trackers/{t.id}/roles"
    post(client, url, {"user_id": member.id, "role": "viewer"})
    assert db.get(TrackerRole, (member.id, t.id)).role == "viewer"
    (entry,) = entries(db, "role_set")
    assert entry.detail == {"before": None, "after": "viewer"}
    assert entry.target_user_id == member.id and entry.user_id == logged_in_user.id and entry.tracker_id == t.id
    post(client, url, {"user_id": member.id, "role": "remove"})
    (removed,) = entries(db, "role_removed")
    assert removed.detail == {"before": "viewer", "after": None} and removed.target_user_id == member.id
    assert db.get(TrackerRole, (member.id, t.id)) is None


def test_holder_cannot_give_themselves_a_direct_role(client, logged_in_user, give_set, tracker_factory, db):
    give_set(["manage_teams"], user=logged_in_user)
    t = tracker_factory()
    response = post(client, f"/trackers/{t.id}/roles", {"user_id": logged_in_user.id, "role": "owner"})
    assert response.status_code == 302
    assert SELF_PROMOTION_MESSAGE in text_of(client.get(f"/trackers/{t.id}/roles"))
    assert db.get(TrackerRole, (logged_in_user.id, t.id)) is None and not entries(db, "role_set")


def test_holder_can_give_another_user_a_role_and_administrators_cannot_receive_one(
    client, logged_in_user, give_set, tracker_factory, user_factory, db
):
    give_set(["manage_teams"], user=logged_in_user)
    t, admin = tracker_factory(), user_factory(is_admin=True)
    assert post(client, f"/trackers/{t.id}/roles", {"user_id": admin.id, "role": "viewer"}).status_code == 400
    assert post(client, f"/trackers/{t.id}/roles", {"user_id": logged_in_user.id, "role": "boss"}).status_code == 400


def test_access_through_teams_lists_path_and_role(
    client, logged_in_admin, tracker_factory, team_factory, add_member, user_factory
):
    top = team_factory(name="Infrastructure")
    win = team_factory(name="Windows", parent=top)
    t = tracker_factory(team_id=win.id)
    add_member(win, user_factory(full_name="Wendy Win"), "editor")
    add_member(top, user_factory(full_name="Olly Owner"), "owner")
    body = text_of(client.get(f"/trackers/{t.id}/roles"))
    assert "Access through teams" in body
    assert "Infrastructure › Windows" in body and "Wendy Win" in body and "Olly Owner" in body
    rows = team_rows(body)
    assert any("Wendy Win" in r and "Infrastructure › Windows" in r and "Editor" in r for r in rows)
    assert any("Olly Owner" in r and "Owner" in r and "Windows" not in r for r in rows)


def team_rows(body: str) -> list[str]:
    section = body.split('id="section-team-access"', 1)[1].split("</section>", 1)[0]
    return section.split("<tr>")[1:]


def test_team_access_is_sorted_and_empty_without_a_team(db, tracker_factory, team_factory, add_member, user_factory):
    top = team_factory(name="Top")
    sub = team_factory(name="Sub", parent=top)
    other = team_factory(name="Elsewhere")
    zed, amy = user_factory(full_name="Zed"), user_factory(full_name="Amy")
    add_member(sub, zed, "viewer")
    add_member(top, amy, "owner")
    add_member(sub, amy, "editor")
    add_member(other, user_factory(full_name="Nobody"), "owner")
    t = tracker_factory(team_id=sub.id)
    rows = team_access(db, t)
    assert [(r.user.full_name, r.path, r.role) for r in rows] == [
        ("Amy", "Top", "owner"),
        ("Amy", "Top › Sub", "editor"),
        ("Zed", "Top › Sub", "viewer"),
    ]
    assert team_access(db, tracker_factory()) == []


def test_access_through_teams_leaves_out_inactive_users(
    client, logged_in_admin, tracker_factory, team_factory, add_member, user_factory
):
    team = team_factory(name="Network")
    t = tracker_factory(team_id=team.id)
    add_member(team, user_factory(full_name="Gone Person", status="disabled"), "owner")
    add_member(team, user_factory(full_name="Here Person"), "viewer")
    body = text_of(client.get(f"/trackers/{t.id}/roles"))
    assert "Here Person" in body and "Gone Person" not in body


def test_archived_tracker_refuses_roles_but_offers_the_team_form(
    client, logged_in_user, give_set, tracker_factory, user_factory, team_factory, db
):
    give_set(["manage_teams"], user=logged_in_user)
    team = team_factory(name="Network")
    t, member = tracker_factory(status="archived"), user_factory()
    page = post(client, f"/trackers/{t.id}/roles", {"user_id": member.id, "role": "viewer"}, follow_redirects=True)
    assert "This tracker is archived." in text_of(page)
    assert db.get(TrackerRole, (member.id, t.id)) is None
    assert 'name="team_id"' in page.get_data(as_text=True) and f"/trackers/{t.id}/team" in text_of(page)
    assert post(client, f"/trackers/{t.id}/team", {"team_id": str(team.id), "next": "access"}).status_code == 302


# --- Where a team change returns to --------------------------------------------------------------------------


def test_team_change_with_next_access_returns_an_administrator_to_access(
    client, logged_in_admin, tracker_factory, team_factory
):
    team, t = team_factory(name="Network"), tracker_factory()
    response = post(client, f"/trackers/{t.id}/team", {"team_id": str(team.id), "next": "access"})
    assert response.headers["Location"].endswith(f"/trackers/{t.id}/roles")


def test_team_change_with_next_access_returns_a_team_manager_to_access(
    client, logged_in_user, give_set, tracker_factory, team_factory
):
    give_set(["manage_teams"], user=logged_in_user)
    team, t = team_factory(name="Network"), tracker_factory()
    response = post(client, f"/trackers/{t.id}/team", {"team_id": str(team.id), "next": "access"})
    assert response.headers["Location"].endswith(f"/trackers/{t.id}/roles")


def test_team_change_with_an_unknown_next_goes_home(client, logged_in_admin, tracker_factory, team_factory):
    team, t = team_factory(name="Network"), tracker_factory()
    response = post(client, f"/trackers/{t.id}/team", {"team_id": str(team.id), "next": "elsewhere"})
    assert response.status_code == 302 and response.headers["Location"].endswith("/")
    assert "/roles" not in response.headers["Location"]
