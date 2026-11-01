"""The tracker Access screen for team managers, and access through teams (database required)."""

import html
import re

from sqlalchemy import select

from tests.conftest import post, sign_in
from tracker.auth.accounts import VOUCHED_MESSAGE
from tracker.auth.guards import SELF_PROMOTION_MESSAGE
from tracker.auth.roles import team_access, tracker_access_list, user_role
from tracker.models import AuditLog, PermissionSetHolder, Tracker, TrackerRole, User
from tracker.trackers.views import INACTIVE_PERSON_MESSAGE


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


def test_administrators_cannot_receive_a_role_and_an_unknown_role_is_refused(
    client, logged_in_user, give_set, tracker_factory, user_factory, db
):
    give_set(["manage_teams"], user=logged_in_user)
    t, admin = tracker_factory(), user_factory(is_admin=True)
    assert post(client, f"/trackers/{t.id}/roles", {"user_id": admin.id, "role": "viewer"}).status_code == 400
    assert post(client, f"/trackers/{t.id}/roles", {"user_id": logged_in_user.id, "role": "boss"}).status_code == 400


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


def test_inactive_team_members_are_left_out_of_the_list(
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
    assert db.get(TrackerRole, (member.id, t.id)) is None and entries(db, "role_set") == []
    assert 'name="team_id"' in page.get_data(as_text=True) and f"/trackers/{t.id}/team" in text_of(page)
    assert post(client, f"/trackers/{t.id}/team", {"team_id": str(team.id), "next": "access"}).status_code == 302
    db.expire_all()
    assert db.get(Tracker, t.id).team_id == team.id
    (moved,) = entries(db, "tracker_team_changed")
    assert moved.detail == {"before": None, "after": "Network"} and moved.tracker_id == t.id


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


# --- Final review fixes ---------------------------------------------------------------------------------------------


def holder_with_tracker(client, logged_in_user, give_set, tracker_factory):
    give_set(["manage_teams"], user=logged_in_user)
    return tracker_factory(name="Rollout", group_label="Location")


def test_setting_the_same_role_or_removing_no_role_changes_nothing(
    client, logged_in_user, give_set, tracker_factory, user_factory, db, grant
):
    t = holder_with_tracker(client, logged_in_user, give_set, tracker_factory)
    member, outsider = user_factory(), user_factory()
    grant(member, t, "editor")
    url = f"/trackers/{t.id}/roles"
    for data in ({"user_id": member.id, "role": "editor"}, {"user_id": outsider.id, "role": "remove"}):
        response = post(client, url, data, follow_redirects=True)
        assert response.status_code == 200 and "No changes to save." in text_of(response)
    assert entries(db, "role_set") == [] and entries(db, "role_removed") == []
    assert db.get(TrackerRole, (member.id, t.id)).role == "editor"


def test_a_direct_role_is_refused_to_a_person_who_is_not_active(
    client, logged_in_user, give_set, tracker_factory, user_factory, db, grant
):
    t = holder_with_tracker(client, logged_in_user, give_set, tracker_factory)
    url = f"/trackers/{t.id}/roles"
    for status in ("disabled", "pending"):
        person = user_factory(status=status)
        response = post(client, url, {"user_id": person.id, "role": "viewer"})
        assert response.status_code == 400 and INACTIVE_PERSON_MESSAGE in text_of(response)
        assert db.get(TrackerRole, (person.id, t.id)) is None
    leaver = user_factory(status="disabled")
    grant(leaver, t, "viewer")
    assert post(client, url, {"user_id": leaver.id, "role": "remove"}).status_code == 302  # removing stays possible
    assert db.get(TrackerRole, (leaver.id, t.id)) is None
    assert entries(db, "role_set") == []


def test_a_direct_role_is_refused_to_an_account_the_holder_vouched_for(
    client, logged_in_user, give_set, tracker_factory, user_factory, db
):
    t = holder_with_tracker(client, logged_in_user, give_set, tracker_factory)
    person, other = user_factory(), user_factory()
    db.add(
        AuditLog(
            action="user_created",
            entity="user",
            entity_id=str(person.id),
            user_id=logged_in_user.id,
            target_user_id=person.id,
        )
    )
    db.commit()
    url = f"/trackers/{t.id}/roles"
    response = post(client, url, {"user_id": person.id, "role": "viewer"}, follow_redirects=True)
    assert VOUCHED_MESSAGE in text_of(response) and db.get(TrackerRole, (person.id, t.id)) is None
    assert post(client, url, {"user_id": other.id, "role": "viewer"}).status_code == 302
    assert [e.target_user_id for e in entries(db, "role_set")] == [other.id]


def test_a_very_long_user_id_is_400(client, logged_in_user, give_set, tracker_factory, db):
    t = holder_with_tracker(client, logged_in_user, give_set, tracker_factory)
    for value in ("9" * 5000, str(2**31)):
        assert post(client, f"/trackers/{t.id}/roles", {"user_id": value, "role": "viewer"}).status_code == 400
    assert entries(db, "role_set") == []


def test_give_form_leaves_out_the_holder_but_not_for_an_administrator(
    client, logged_in_user, give_set, tracker_factory, user_factory
):
    t = holder_with_tracker(client, logged_in_user, give_set, tracker_factory)
    other = user_factory(full_name="Other Person")
    page = client.get(f"/trackers/{t.id}/roles").get_data(as_text=True)
    assert f'value="{other.id}"' in page and f'value="{logged_in_user.id}"' not in page
    admin = user_factory(is_admin=True)
    admin_client = client.application.test_client()
    sign_in(admin_client, admin)
    assert f'value="{logged_in_user.id}"' in admin_client.get(f"/trackers/{t.id}/roles").get_data(as_text=True)


def test_roles_legend_names_groups_generically_for_a_holder_without_a_role(
    client, logged_in_user, give_set, tracker_factory, user_factory, grant
):
    t = holder_with_tracker(client, logged_in_user, give_set, tracker_factory)
    legend = text_of(client.get(f"/trackers/{t.id}/roles")).split('class="role-legend"', 1)[1].split("</dl>", 1)[0]
    assert "targets, groups and risks" in legend and "locations" not in legend
    grant(logged_in_user, t, "viewer")
    legend = text_of(client.get(f"/trackers/{t.id}/roles")).split('class="role-legend"', 1)[1].split("</dl>", 1)[0]
    assert "targets, locations and risks" in legend


def test_a_vouched_account_can_have_its_direct_role_lowered(
    client, logged_in_user, give_set, tracker_factory, user_factory, db, grant
):
    t = holder_with_tracker(client, logged_in_user, give_set, tracker_factory)
    person = user_factory()
    grant(person, t, "editor")
    db.add(
        AuditLog(
            action="user_created",
            entity="user",
            entity_id=str(person.id),
            user_id=logged_in_user.id,
            target_user_id=person.id,
        )
    )
    db.commit()
    url = f"/trackers/{t.id}/roles"
    response = post(client, url, {"user_id": person.id, "role": "owner"}, follow_redirects=True)
    assert VOUCHED_MESSAGE in text_of(response)
    assert post(client, url, {"user_id": person.id, "role": "viewer"}).status_code == 302
    db.expire_all()
    assert db.get(TrackerRole, (person.id, t.id)).role == "viewer"  # lowering gives nothing, so it is allowed
    assert [e.target_user_id for e in entries(db, "role_set")] == [person.id]


def test_give_form_says_a_team_route_already_opens_the_tracker(client, logged_in_user, give_set, tracker_factory):
    t = holder_with_tracker(client, logged_in_user, give_set, tracker_factory)
    page = text_of(client.get(f"/trackers/{t.id}/roles"))
    assert "Give a direct role" in page and "a direct role adds to that" in page
    assert "Add people" not in page and "Access through teams" not in page


def access_fixture(db, tracker_factory, team_factory, add_member, user_factory, give_set):
    top = team_factory(name="Infrastructure")
    win = team_factory(name="Windows", parent=top)
    t = tracker_factory(team_id=win.id)
    admin = user_factory(full_name="Ada Admin", is_admin=True)
    direct = user_factory(full_name="Dina Direct")
    db.add(TrackerRole(user_id=direct.id, tracker_id=t.id, role="editor"))
    both = user_factory(full_name="Bob Both")
    db.add(TrackerRole(user_id=both.id, tracker_id=t.id, role="viewer"))
    add_member(win, both, "owner")
    add_member(top, user_factory(full_name="Tina Team"), "viewer")
    add_member(win, user_factory(full_name="Gone Member", status="disabled"), "owner")
    holder = user_factory(full_name="Pat Pmo")
    pmo = give_set(["view_all_trackers"], name="PMO", user=holder)
    via_team = user_factory(full_name="Vera Viaset")
    pmo_team = team_factory(name="Office")
    add_member(pmo_team, via_team, "viewer")
    db.add(PermissionSetHolder(set_id=pmo.id, team_id=pmo_team.id))
    unrelated = user_factory(full_name="Nina None")
    db.commit()
    return t, admin, unrelated


def test_access_list_agrees_with_user_role(db, tracker_factory, team_factory, add_member, user_factory, give_set):
    t, _admin, unrelated = access_fixture(db, tracker_factory, team_factory, add_member, user_factory, give_set)
    rows = tracker_access_list(db, t)
    assert [r.user.full_name for r in rows] == sorted((r.user.full_name for r in rows), key=lambda n: n.casefold())
    ids = [r.user.id for r in rows]
    assert len(ids) == len(set(ids))
    for row in rows:
        assert row.role == user_role(db, row.user, t.id)
    for user in db.scalars(select(User).where(User.status == "active")):
        assert (user.id in ids) == (user_role(db, user, t.id) is not None)
    by_name = {r.user.full_name: r for r in rows}
    assert unrelated.full_name not in by_name and "Gone Member" not in by_name
    assert by_name["Bob Both"].role == "owner" and by_name["Bob Both"].direct_role == "viewer"
    assert [a.path for a in by_name["Bob Both"].teams] == ["Infrastructure › Windows"]
    assert by_name["Pat Pmo"].view_all_sets == ["PMO"] and by_name["Vera Viaset"].view_all_sets == ["PMO"]
    assert by_name["Ada Admin"].admin and by_name["Ada Admin"].role == "owner"


def test_access_page_is_one_list(
    client, logged_in_admin, db, tracker_factory, team_factory, add_member, user_factory, give_set
):
    t, _admin, _unrelated = access_fixture(db, tracker_factory, team_factory, add_member, user_factory, give_set)
    page = client.get(f"/trackers/{t.id}/roles")
    body = text_of(page)
    assert "Who can open this tracker" in body
    assert "Add people" not in body and "Access through teams" not in body
    html_body = page.get_data(as_text=True)
    table = html_body.split("data-row-filter-target", 1)[1].split("</table>", 1)[0]
    table_rows = re.findall(r"<tr data-route=.*?</tr>", table, re.S)
    names = re.findall(r'member-name">([^<]+)', table)
    assert len(table_rows) == len(names) == len(set(names))
    direct_row = next(r for r in table_rows if "Dina Direct" in r)
    assert "Direct role" in direct_row
    team_row = next(r for r in table_rows if "Bob Both" in r)
    assert "Team Infrastructure › Windows" in html.unescape(team_row) and 'href="/admin/teams/' in team_row
    assert "Permission set PMO: View all trackers" in text_of(page)
    assert "Administrator" in text_of(page)
    assert "data-autosubmit>" in direct_row and "data-autosubmit-fallback>Set role" in direct_row
    assert "Remove access" in direct_row
    other_row = next(r for r in table_rows if "Pat Pmo" in r)
    assert "<select" not in other_row and "<button" not in other_row
    assert 'data-route="direct team"' in table and 'data-route="set"' in table and 'data-route="admin"' in table


def test_give_a_direct_role_form(
    client, logged_in_user, give_set, db, tracker_factory, team_factory, add_member, user_factory
):
    give_set(["manage_teams"], user=logged_in_user)
    t = tracker_factory()
    has_role = user_factory(full_name="Has Role")
    db.add(TrackerRole(user_id=has_role.id, tracker_id=t.id, role="viewer"))
    user_factory(full_name="Ann Admin", is_admin=True)
    user_factory(full_name="Gone Person", status="disabled")
    free = user_factory(full_name="Free Person")
    db.commit()
    page = client.get(f"/trackers/{t.id}/roles").get_data(as_text=True)
    form = page.split('id="section-give"', 1)[1].split("</section>", 1)[0]
    assert form.count("<form") == 1 and f'action="/trackers/{t.id}/roles"' in form
    select = form.split('id="user_id"', 1)[1].split("</select>", 1)[0]
    assert f'value="{free.id}"' in select and "Has Role" not in select and "Ann Admin" not in select
    assert "Gone Person" not in select and f'value="{logged_in_user.id}"' not in select
    assert 'name="role"' in form and "Give access" in form
    assert re.search(r"<input[^>]*data-select-filter=\"user_id\"[^>]*hidden", form)
    response = post(client, f"/trackers/{t.id}/roles", {"user_id": free.id, "role": "viewer"})
    assert response.status_code == 302 and db.get(TrackerRole, (free.id, t.id)).role == "viewer"
