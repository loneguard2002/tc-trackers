"""The Users screen for manage_users holders: guards, password reset, re-enable, approval and effective access."""

import html
import re
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from tests.conftest import post, sign_in
from tracker.auth.accounts import (
    ELEVATED_MESSAGE,
    LAST_ADMIN_MESSAGE,
    OWN_ACCOUNT_MESSAGE,
    VOUCHED_MESSAGE,
    last_admin_refusal,
    vouched_refusal,
)
from tracker.auth.guards import TEAM_WITH_SETS_MESSAGE
from tracker.auth.passwords import verify_password
from tracker.auth.permissions import permission_sources
from tracker.auth.roles import tracker_access_routes, tracker_roles
from tracker.models import AuditLog, TeamMember, TrackerRegion, User

SSO_MESSAGE = "This person signs in with Microsoft and has no password here."
NEW_PASSWORD = "new-password-456"


def text_of(response) -> str:
    return html.unescape(response.get_data(as_text=True))


def entries(db, action: str) -> list[AuditLog]:
    return list(db.scalars(select(AuditLog).where(AuditLog.action == action).order_by(AuditLog.id)))


def reloaded(db, user: User) -> User:
    db.expire_all()
    return db.get(User, user.id)


@pytest.fixture
def user_manager(client, user_factory, give_set):
    actor = user_factory(full_name="Manager")
    give_set(["manage_users"], user=actor)
    sign_in(client, actor)
    return actor


# --- Opening the screen and creating users --------------------------------------------------------------------------


def test_holder_opens_users_and_creates_a_local_user(client, user_manager, db):
    assert client.get("/admin/users").status_code == 200
    assert client.get("/admin/users/new").status_code == 200
    response = post(
        client, "/admin/users", {"email": "new@example.com", "full_name": "New Person", "password": "a long password"}
    )
    assert response.status_code == 302
    created = db.scalars(select(User).where(User.email == "new@example.com")).one()
    assert created.status == "active" and not created.is_admin
    (row,) = entries(db, "user_created")
    assert row.user_id == user_manager.id and row.target_user_id == created.id


def test_users_screen_refused_without_manage_users(client, logged_in_user, user_factory):
    other = user_factory(status="disabled")
    assert client.get("/admin/users").status_code == 403
    assert post(client, f"/admin/users/{other.id}/enable").status_code == 403
    assert client.get(f"/admin/users/{other.id}/password").status_code == 403


def test_administrator_flag_stays_administrator_only(client, user_manager, user_factory, db):
    other = user_factory()
    assert post(client, f"/admin/users/{other.id}/admin", {"is_admin": "1"}).status_code == 403
    assert reloaded(db, other).is_admin is False
    assert "Make administrator" not in text_of(client.get("/admin/users"))


# --- Guards on elevated users and one's own account -----------------------------------------------------------------

STATUS_FOR_ACTION = {"password": "active", "disable": "active", "enable": "disabled", "approve": "pending"}


@pytest.mark.parametrize("action", ["password", "disable", "enable", "approve"])
@pytest.mark.parametrize("kind", ["admin", "direct_set", "team_set", "self", "disabled_former_admin"])
def test_holder_refused_on_elevated_users_and_own_account(
    client, user_manager, user_factory, team_factory, add_member, give_set, db, action, kind
):
    status = STATUS_FOR_ACTION[action]
    if kind == "self":
        target = user_manager
    elif kind == "admin":
        target = user_factory(is_admin=True, status=status)
    elif kind == "disabled_former_admin":
        target = user_factory(is_admin=True, status="disabled")
    elif kind == "direct_set":
        target = user_factory(status=status)
        give_set(["view_activity"], user=target)
    else:
        target = user_factory(status=status)
        team = team_factory(name="Auditors")
        add_member(team, target, "viewer")
        give_set(["view_activity"], team=team)
    before = (target.status, target.password_hash, target.is_admin)
    data = {"password": NEW_PASSWORD} if action == "password" else {}
    response = post(client, f"/admin/users/{target.id}/{action}", data, follow_redirects=True)
    assert response.status_code == 200
    assert (OWN_ACCOUNT_MESSAGE if kind == "self" else ELEVATED_MESSAGE) in text_of(response)
    after = reloaded(db, target)
    assert (after.status, after.password_hash, after.is_admin) == before
    assert db.scalars(select(AuditLog).where(AuditLog.target_user_id == target.id)).first() is None


def test_holder_sees_only_the_actions_they_may_take(client, user_manager, user_factory, give_set):
    plain = user_factory(full_name="Plain Person")
    elevated = user_factory(full_name="Elevated Person")
    give_set(["view_activity"], user=elevated)
    disabled = user_factory(full_name="Disabled Person", status="disabled")
    page = text_of(client.get("/admin/users"))
    assert f'action="/admin/users/{plain.id}/disable"' in page
    assert f'href="/admin/users/{plain.id}/password"' in page
    assert f'action="/admin/users/{disabled.id}/enable"' in page
    for user in (elevated, user_manager):
        assert f"/admin/users/{user.id}/disable" not in page
        assert f"/admin/users/{user.id}/password" not in page
        assert f'href="/admin/users/{user.id}/access"' in page
    assert f"/admin/users/{plain.id}/admin" not in page and "Make administrator" not in page


# --- Password reset -------------------------------------------------------------------------------------------------


def test_holder_resets_a_local_password_and_it_is_logged_without_secrets(client, user_manager, user_factory, db):
    target = user_factory(full_name="Target")
    page = client.get(f"/admin/users/{target.id}/password")
    assert page.status_code == 200 and 'name="password"' in text_of(page)
    assert "At least 12 characters" in text_of(page)
    response = post(client, f"/admin/users/{target.id}/password", {"password": NEW_PASSWORD})
    assert response.status_code == 302 and response.headers["Location"] == "/admin/users"
    assert verify_password(NEW_PASSWORD, reloaded(db, target).password_hash)
    (row,) = entries(db, "password_reset")
    assert row.user_id == user_manager.id and row.target_user_id == target.id
    assert row.detail == {"source": "web"}
    assert NEW_PASSWORD not in str(row.detail) and "$2b$" not in str(row.detail)


def test_reset_password_rules_and_microsoft_accounts(client, user_manager, user_factory, db):
    target = user_factory()
    short = post(client, f"/admin/users/{target.id}/password", {"password": "x" * 11})
    assert short.status_code == 400 and "at least 12 characters" in text_of(short)
    assert reloaded(db, target).password_hash == target.password_hash
    sso = user_factory(auth_source="sso", password_hash=None, sso_subject="subject-1")
    refused = post(client, f"/admin/users/{sso.id}/password", {"password": NEW_PASSWORD}, follow_redirects=True)
    assert SSO_MESSAGE in text_of(refused)
    assert reloaded(db, sso).password_hash is None
    assert SSO_MESSAGE in text_of(client.get(f"/admin/users/{sso.id}/password", follow_redirects=True))
    assert f"/admin/users/{sso.id}/password" not in text_of(client.get("/admin/users"))
    assert entries(db, "password_reset") == []


def test_reset_password_for_a_missing_user_is_404(client, logged_in_admin):
    assert client.get("/admin/users/999999/password").status_code == 404
    assert client.get(f"/admin/users/{2**31}/access").status_code == 404


# --- Re-enable, disable and approve ---------------------------------------------------------------------------------


def test_reenable_logs_user_enabled(client, user_manager, user_factory, db):
    target = user_factory(status="disabled")
    response = post(client, f"/admin/users/{target.id}/enable")
    assert response.status_code == 302
    assert reloaded(db, target).status == "active"
    (row,) = entries(db, "user_enabled")
    assert row.user_id == user_manager.id and row.target_user_id == target.id
    assert row.detail == {"before": "disabled", "after": "active"}
    assert post(client, f"/admin/users/{target.id}/enable").status_code == 400
    assert len(entries(db, "user_enabled")) == 1


def test_user_entries_name_the_affected_user(client, logged_in_admin, user_factory, db):
    post(client, "/admin/users", {"email": "made@example.com", "full_name": "Made", "password": "a long password"})
    made = db.scalars(select(User).where(User.email == "made@example.com")).one()
    (created,) = entries(db, "user_created")
    assert created.target_user_id == made.id
    other = user_factory()
    post(client, f"/admin/users/{other.id}/disable")
    (disabled,) = entries(db, "user_disabled")
    assert disabled.target_user_id == other.id and disabled.detail == {"before": "active", "after": "disabled"}
    assert post(client, f"/admin/users/{other.id}/disable").status_code == 400


def test_approve_only_pending_users(client, user_manager, user_factory, db):
    active = user_factory()
    disabled = user_factory(status="disabled")
    assert post(client, f"/admin/users/{active.id}/approve").status_code == 400
    assert post(client, f"/admin/users/{disabled.id}/approve").status_code == 400
    assert reloaded(db, disabled).status == "disabled"
    pending = user_factory(status="pending")
    assert post(client, f"/admin/users/{pending.id}/approve").status_code == 302
    assert reloaded(db, pending).status == "active"
    (row,) = entries(db, "user_approved")
    assert row.target_user_id == pending.id and row.detail == {"before": "pending", "after": "active"}


def test_last_admin_refusal(db, user_factory):
    only = user_factory(is_admin=True)
    assert last_admin_refusal(db, only) == LAST_ADMIN_MESSAGE
    user_factory(is_admin=True)
    assert last_admin_refusal(db, only) is None
    db.rollback()
    assert last_admin_refusal(db, user_factory()) is None
    assert last_admin_refusal(db, user_factory(is_admin=True, status="disabled")) is None


def test_user_admin_changed_logs_before_after_and_affected_user(client, logged_in_admin, user_factory, db):
    other = user_factory()
    post(client, f"/admin/users/{other.id}/admin", {"is_admin": "1"})
    post(client, f"/admin/users/{other.id}/admin", {"is_admin": "1"})  # no change, no entry
    post(client, f"/admin/users/{other.id}/admin", {"is_admin": "0"})
    rows = entries(db, "user_admin_changed")
    assert [(row.detail, row.target_user_id) for row in rows] == [
        ({"before": False, "after": True}, other.id),
        ({"before": True, "after": False}, other.id),
    ]


# --- Team places at approval ----------------------------------------------------------------------------------------


def test_approval_with_a_team_place(client, logged_in_admin, user_factory, team_factory, db):
    windows = team_factory(name="Windows", parent=team_factory(name="Infrastructure"))
    pending = user_factory(status="pending", auth_source="sso", password_hash=None, sso_subject="s-1")
    page = text_of(client.get("/admin/users"))
    assert 'name="team_id"' in page and f'<option value="{windows.id}">Windows</option>' in page
    response = post(client, f"/admin/users/{pending.id}/approve", {"team_id": str(windows.id), "team_role": "editor"})
    assert response.status_code == 302
    assert reloaded(db, pending).status == "active"
    assert db.get(TeamMember, (windows.id, pending.id)).role == "editor"
    (approved,) = entries(db, "user_approved")
    (added,) = entries(db, "team_member_added")
    assert approved.target_user_id == pending.id and added.target_user_id == pending.id
    assert added.detail == {"team": "Windows", "role": "editor"}
    assert added.entity == "team" and added.entity_id == str(windows.id)
    flashed = text_of(client.get("/admin/users"))
    assert f"{pending.full_name} is now active, as editor in Windows." in flashed


def test_team_place_refused_for_a_holder_without_manage_teams(client, user_manager, user_factory, team_factory, db):
    team = team_factory(name="Windows")
    pending = user_factory(status="pending")
    assert 'name="team_id"' not in text_of(client.get("/admin/users"))
    response = post(client, f"/admin/users/{pending.id}/approve", {"team_id": str(team.id), "team_role": "viewer"})
    assert response.status_code == 403
    assert reloaded(db, pending).status == "pending"
    assert db.get(TeamMember, (team.id, pending.id)) is None
    assert entries(db, "user_approved") == []


def test_team_place_in_a_team_holding_a_set_refused_for_non_admins(client, user_factory, team_factory, give_set, db):
    actor = user_factory(full_name="Both")
    give_set(["manage_users", "manage_teams"], user=actor)
    sign_in(client, actor)
    plain = team_factory(name="Plain")
    holding = team_factory(name="Holding")
    give_set(["view_activity"], team=holding)
    pending = user_factory(status="pending")
    page = text_of(client.get("/admin/users")).split('id="section-users"')[0]  # the filters list every team
    assert f'<option value="{plain.id}"' in page and f'<option value="{holding.id}"' not in page
    data = {"team_id": str(holding.id), "team_role": "viewer"}
    response = post(client, f"/admin/users/{pending.id}/approve", data, follow_redirects=True)
    assert TEAM_WITH_SETS_MESSAGE in text_of(response)
    assert reloaded(db, pending).status == "pending"
    assert db.get(TeamMember, (holding.id, pending.id)) is None
    assert entries(db, "user_approved") == []
    response = post(client, f"/admin/users/{pending.id}/approve", {"team_id": str(plain.id), "team_role": "owner"})
    assert response.status_code == 302
    assert db.get(TeamMember, (plain.id, pending.id)).role == "owner"


def test_administrator_places_in_a_team_holding_a_set(
    client, logged_in_admin, user_factory, team_factory, give_set, db
):
    holding = team_factory(name="Holding")
    give_set(["view_activity"], team=holding)
    pending = user_factory(status="pending")
    post(client, f"/admin/users/{pending.id}/approve", {"team_id": str(holding.id), "team_role": "viewer"})
    assert reloaded(db, pending).status == "active"
    assert db.get(TeamMember, (holding.id, pending.id)).role == "viewer"


def test_approval_with_a_deleted_team_is_400_and_the_user_stays_pending(
    client, logged_in_admin, user_factory, team_factory, db
):
    team = team_factory(name="Gone")
    kept = team_factory(name="Kept")
    gone_id = team.id
    db.delete(team)
    db.commit()
    pending = user_factory(status="pending")
    for data in (
        {"team_id": str(gone_id), "team_role": "viewer"},
        {"team_id": "abc", "team_role": "viewer"},
        {"team_id": str(kept.id), "team_role": "admin"},
        {"team_id": str(kept.id)},
    ):
        assert post(client, f"/admin/users/{pending.id}/approve", data).status_code == 400
    assert reloaded(db, pending).status == "pending"
    assert db.scalars(select(TeamMember)).first() is None
    assert entries(db, "user_approved") == []


# --- Rows and effective access --------------------------------------------------------------------------------------


def test_rows_show_teams_sets_and_the_effective_access_link(
    client, logged_in_admin, user_factory, team_factory, add_member, give_set
):
    person = user_factory(full_name="Team Person")
    office = team_factory(name="PMO Office")
    add_member(office, person, "editor")
    give_set(["view_activity"], team=office, name="PMO")
    give_set(["view_all_trackers"], user=person, name="Auditors")
    page = text_of(client.get("/admin/users"))
    assert "PMO Office · Editor" in page
    assert "PMO (through PMO Office)" in page and "Auditors" in page
    assert f'href="/admin/users/{person.id}/access"' in page


def test_effective_access_lists_routes_and_permission_sources(
    client, logged_in_admin, user_factory, team_factory, add_member, give_set, grant, tracker_factory, db
):
    person = user_factory(full_name="Routed Person")
    windows = team_factory(name="Windows", parent=team_factory(name="Infrastructure"))
    office = team_factory(name="PMO Office")
    add_member(windows, person, "editor")
    add_member(office, person, "viewer")
    give_set(["view_all_trackers"], team=office, name="PMO")
    give_set(["view_activity"], user=person, name="Readers")
    tracker_factory(name="Servers", team_id=windows.id)
    laptops = tracker_factory(name="Laptops")
    grant(person, laptops, "viewer")
    routes = {a.tracker.name: (a.role, [r.text for r in a.routes]) for a in tracker_access_routes(db, person)}
    assert routes == {
        "Laptops": ("viewer", ["Direct role: Viewer", "View all trackers: Viewer"]),
        "Servers": ("editor", ["Team Windows: Editor", "View all trackers: Viewer"]),
    }
    assert {a.tracker.id: a.role for a in tracker_access_routes(db, person)} == tracker_roles(db, person)
    assert permission_sources(db, person) == {
        "view_all_trackers": ["Set PMO, held by team PMO Office"],
        "view_activity": ["Set Readers, held directly"],
    }
    page = text_of(client.get(f"/admin/users/{person.id}/access"))
    for text in (
        "Servers",
        "Laptops",
        "Team Windows: Editor",
        "Direct role: Viewer",
        "View all trackers: Viewer",
        "Set PMO, held by team PMO Office",
        "Set Readers, held directly",
    ):
        assert text in page
    assert "Only trackers you can open are listed." not in page


def test_effective_access_of_an_administrator_and_of_an_inactive_user(
    client, logged_in_admin, user_factory, tracker_factory, grant, db
):
    tracker = tracker_factory(name="Anything")
    (row,) = tracker_access_routes(db, logged_in_admin)
    assert (row.tracker.id, row.role, [r.text for r in row.routes]) == (tracker.id, "owner", ["Administrator"])
    assert all(sources == ["Administrator"] for sources in permission_sources(db, logged_in_admin).values())
    disabled = user_factory(status="disabled")
    grant(disabled, tracker, "owner")
    assert tracker_access_routes(db, disabled) == [] and permission_sources(db, disabled) == {}
    page = text_of(client.get(f"/admin/users/{disabled.id}/access"))
    assert page.count("Anything") == 0 and "not active" in page


def test_effective_access_hides_names_the_holder_cannot_open(
    client, user_manager, user_factory, tracker_factory, grant, give_set, db
):
    person = user_factory(full_name="Watched Person")
    secret = tracker_factory(name="Secret Plans")
    shared = tracker_factory(name="Shared Work")
    grant(person, secret, "owner")
    grant(person, shared, "viewer")
    grant(user_manager, shared, "viewer")
    page = text_of(client.get(f"/admin/users/{person.id}/access"))
    assert "Shared Work" in page and "Secret Plans" not in page
    assert "Only trackers you can open are listed." in page and "you cannot open" not in page  # nothing is counted
    another = tracker_factory(name="Other Secret")
    grant(person, another, "editor")
    assert "Only trackers you can open are listed." in text_of(client.get(f"/admin/users/{person.id}/access"))
    give_set(["manage_teams"], user=user_manager)
    page = text_of(client.get(f"/admin/users/{person.id}/access"))
    assert "Secret Plans" in page and "Other Secret" in page and "Only trackers you can open" not in page


def test_effective_access_refused_without_manage_users(client, logged_in_user, user_factory):
    other = user_factory()
    assert client.get(f"/admin/users/{other.id}/access").status_code == 403


# --- Final review fixes ---------------------------------------------------------------------------------------------


def test_a_holder_disables_a_plain_user(client, user_manager, user_factory, db):
    target = user_factory(full_name="Plain Person")
    response = post(client, f"/admin/users/{target.id}/disable", follow_redirects=True)
    assert response.status_code == 200 and "Plain Person has been disabled." in text_of(response)
    assert reloaded(db, target).status == "disabled"
    (row,) = entries(db, "user_disabled")
    assert row.user_id == user_manager.id and row.target_user_id == target.id


def test_pending_copy_says_waiting_for_approval(client, logged_in_admin, user_factory):
    user_factory(status="pending", auth_source="sso", password_hash=None)
    assert "People who signed in with Microsoft and are waiting for approval" in text_of(client.get("/admin/users"))


def test_vouched_refusal_reads_the_activity_log(db, user_factory):
    actor, created, reset, other = (user_factory() for _ in range(4))
    admin = user_factory(is_admin=True)
    for action, target in (("user_created", created), ("password_reset", reset), ("user_disabled", other)):
        db.add(
            AuditLog(action=action, entity="user", entity_id=str(target.id), user_id=actor.id, target_user_id=target.id)
        )
    db.commit()
    assert vouched_refusal(db, actor, created) == VOUCHED_MESSAGE
    assert vouched_refusal(db, actor, reset) == VOUCHED_MESSAGE
    assert vouched_refusal(db, actor, other) is None
    assert vouched_refusal(db, admin, created) is None
    assert VOUCHED_MESSAGE == "You created this account or set its password, so another person must give it access."


def test_holder_cannot_place_an_account_they_vouched_for_at_approval(client, user_factory, team_factory, give_set, db):
    actor = user_factory(full_name="Both")
    give_set(["manage_users", "manage_teams"], user=actor)
    sign_in(client, actor)
    team = team_factory(name="Plain")
    pending = user_factory(status="pending")
    db.add(
        AuditLog(
            action="password_reset",
            entity="user",
            entity_id=str(pending.id),
            user_id=actor.id,
            target_user_id=pending.id,
        )
    )
    db.commit()
    data = {"team_id": str(team.id), "team_role": "viewer"}
    response = post(client, f"/admin/users/{pending.id}/approve", data, follow_redirects=True)
    assert VOUCHED_MESSAGE in text_of(response)
    assert reloaded(db, pending).status == "pending" and db.get(TeamMember, (team.id, pending.id)) is None
    assert entries(db, "user_approved") == []
    assert post(client, f"/admin/users/{pending.id}/approve").status_code == 302  # approval alone gives no access
    assert reloaded(db, pending).status == "active"


def test_approval_with_a_very_long_team_id_is_400(client, logged_in_admin, user_factory, db):
    pending = user_factory(status="pending")
    response = post(client, f"/admin/users/{pending.id}/approve", {"team_id": "9" * 5000, "team_role": "viewer"})
    assert response.status_code == 400 and reloaded(db, pending).status == "pending"


# --- The list: filters and the actions menu -------------------------------------------------------------------------


def people_rows(response) -> dict[str, str]:
    """Name to the HTML of its row in the People table."""
    body = text_of(response)
    table = body.split('id="section-users"', 1)[1]
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", table, flags=re.S)[1:]
    return {re.search(r'class="member-name">([^<]*)', row).group(1).strip(): row for row in rows}


@pytest.fixture
def filter_people(client, user_manager, user_factory, team_factory, add_member, give_set):
    """Manager plus four people: Ada (Platform, direct set), Bo (Platform), Cy (Ops, set through Ops), Di (disabled)."""
    platform, ops = team_factory(name="Platform"), team_factory(name="Ops")
    ada = user_factory(full_name="Ada Lovelace", email="ada@example.com")
    bo = user_factory(full_name="Bo Peep", email="bo@example.org")
    cy = user_factory(full_name="Cy Young", email="cy_young@example.com")
    user_factory(full_name="Di Gone", email="di@example.com", status="disabled")
    add_member(platform, ada, "viewer")
    add_member(platform, bo, "viewer")
    add_member(ops, cy, "viewer")
    direct = give_set(["view_activity"], user=ada, name="Auditors")
    through = give_set(["view_activity"], team=ops, name="Operators")
    names = SimpleNamespace(platform=platform, ops=ops, direct=direct, through=through)
    return names


def listed(client, query: str = "") -> list[str]:
    return [name for name in people_rows(client.get(f"/admin/users{query}")) if name != "Manager"]


def test_users_filters(client, filter_people):
    everyone = ["Ada Lovelace", "Bo Peep", "Cy Young", "Di Gone"]
    assert sorted(listed(client)) == sorted(everyone)
    assert "Showing" not in text_of(client.get("/admin/users"))
    assert listed(client, "?q=LOVELACE") == ["Ada Lovelace"]
    assert listed(client, "?q=example.org") == ["Bo Peep"]
    assert listed(client, "?q=cy_") == ["Cy Young"]  # an underscore is literal, not a wildcard
    assert listed(client, "?q=c_y") == []
    assert listed(client, "?status=disabled") == ["Di Gone"]
    assert sorted(listed(client, "?status=active")) == ["Ada Lovelace", "Bo Peep", "Cy Young"]
    assert sorted(listed(client, f"?team={filter_people.platform.id}")) == ["Ada Lovelace", "Bo Peep"]
    assert listed(client, f"?set={filter_people.direct.id}") == ["Ada Lovelace"]
    assert listed(client, f"?set={filter_people.through.id}") == ["Cy Young"]
    assert listed(client, f"?team={filter_people.platform.id}&q=peep") == ["Bo Peep"]
    assert listed(client, f"?team={filter_people.platform.id}&status=disabled") == []
    response = client.get(f"/admin/users?team={filter_people.platform.id}")
    assert "Showing 2 of 5 people." in text_of(response)
    assert f'<option value="{filter_people.platform.id}" selected' in text_of(response)


def test_users_list_shows_and_filters_how_each_person_signs_in(client, user_manager, user_factory):
    user_factory(full_name="Sso Person", auth_source="sso", password_hash=None)
    user_factory(full_name="Local Person", is_admin=True)
    response = client.get("/admin/users")
    body = text_of(response)
    headings = re.findall(r'data-sort="([^"]+)"', body.split("<thead>", 1)[1].split("</thead>", 1)[0])
    assert headings == ["name", "status", "admin", "sign-in", "teams", "sets"]
    rows = people_rows(response)

    def cells(name: str) -> list[str]:
        """The Status, Administrator and Sign-in cells of a row, as the reader sees them."""
        found = re.findall(r'<td class="user-badge">(.*?)</td>', rows[name], flags=re.S)
        return [re.sub(r"<[^>]+>", "", cell).strip() for cell in found]

    assert cells("Sso Person") == ["Active", "Not an administrator", "SSO"]
    assert cells("Local Person") == ["Active", "Administrator", "Local"]
    assert 'title="SSO: signs in with a Microsoft work account (single sign-on)"' in rows["Sso Person"]
    sso_row = body.split('data-sort-name="Sso Person"', 1)[1].split(">", 1)[0]
    assert 'data-sort-status="active"' in sso_row and 'data-sort-admin=""' in sso_row
    assert 'data-sort-sign-in="SSO"' in sso_row
    legend = re.sub(r"<[^>]+>", "", body.split('class="section-foot-note sign-in-legend">', 1)[1].split("</p>", 1)[0])
    assert " ".join(legend.split()) == (
        "Sign-in: Local signs in with an email address and a password set in this app; "
        "SSO signs in with a Microsoft work account (single sign-on)."
    )
    assert listed(client, "?sign_in=sso") == ["Sso Person"]
    assert listed(client, "?sign_in=local") == ["Local Person"]
    assert listed(client, "?sign_in=local&q=sso") == []
    response = client.get("/admin/users?sign_in=sso")
    assert "Showing 1 of 3 people." in text_of(response)
    assert '<option value="sso" selected>SSO</option>' in text_of(response)


def test_users_filters_ignore_bad_values(client, filter_people):
    for query in (
        "?status=bogus",
        "?sign_in=bogus",
        "?team=abc",
        "?team=" + "9" * 20,
        "?set=-1",
        "?team=999999",
        "?q=",
    ):
        response = client.get(f"/admin/users{query}")
        assert response.status_code == 200
        assert len(people_rows(response)) == 5, query
        assert "Showing" not in text_of(response)


def test_empty_filtered_list_says_so(client, filter_people):
    body = text_of(client.get("/admin/users?q=nobody"))
    assert "No one matches these filters." in body and "Showing 0 of 5 people." in body
    assert 'role="search"' in body and ">Clear<" in body


def test_awaiting_approval_ignores_filters(client, user_manager, user_factory):
    user_factory(full_name="Pat Pending", status="pending")
    body = text_of(client.get("/admin/users?q=zzz"))
    assert "Awaiting approval" in body.split('id="section-users"')[0]
    assert "Pat Pending" in body.split('id="section-users"')[0]
    assert "Pat Pending" not in body.split('id="section-users"')[1]


def test_row_actions_sit_in_a_more_menu(client, logged_in_admin, user_factory):
    plain = user_factory(full_name="Plain Person")
    boss = user_factory(full_name="Boss Person", is_admin=True)
    off = user_factory(full_name="Off Person", status="disabled")
    sso = user_factory(full_name="Sso Person", auth_source="sso")
    response = client.get("/admin/users")
    body = text_of(response)
    assert "Sign-in</th>" not in body and ">Role</th>" not in body
    rows = people_rows(response)
    for user in (plain, boss, off, sso):
        row = rows[user.full_name]
        assert f'href="/admin/users/{user.id}/access">Access<' in row
        assert '<details class="row-menu">' in row
        assert f'More<span class="sr-only"> actions for {user.full_name}</span>' in row
    assert f'action="/admin/users/{plain.id}/disable"' in rows["Plain Person"]
    assert f'href="/admin/users/{plain.id}/password"' in rows["Plain Person"]
    assert "Make administrator" in rows["Plain Person"] and "Remove administrator" in rows["Boss Person"]
    assert f'action="/admin/users/{off.id}/enable"' in rows["Off Person"]
    assert "/password" not in rows["Sso Person"]
    assert re.search(
        r"badge-success[^<]*>Active</span></td>\s*<td[^>]*><span[^>]*badge-info[^>]*>Administrator<",
        rows["Boss Person"],
    )
    assert "Administrator" not in rows["Plain Person"].replace("Make administrator", "")
    # the signed-in administrator's own row offers neither Disable nor an administrator change
    own = rows[logged_in_admin.full_name]
    assert "/disable" not in own and "administrator</button>" not in own


def _visible(client, person) -> str:
    """The access page as the reader sees it: tags dropped, whitespace collapsed."""
    raw = re.sub(r"<[^>]+>", " ", _access_html(client, person))
    return re.sub(r"\s+", " ", html.unescape(raw))


def _access_html(client, person) -> str:
    return client.get(f"/admin/users/{person.id}/access").get_data(as_text=True)


def test_access_page_marks_the_route_that_sets_the_role(
    client, user_manager, user_factory, team_factory, add_member, give_set, tracker_factory, grant
):
    person = user_factory(full_name="Marked Person")
    windows = team_factory(name="Windows")
    add_member(windows, person, "editor")
    give_set(["view_all_trackers"], user=person)
    tracker_factory(name="Servers", team_id=windows.id)
    give_set(["manage_teams"], user=user_manager)
    page = _visible(client, person)
    assert "Team Windows: Editor Sets the role" in page
    assert "View all trackers: Viewer Sets the role" not in page and page.count("Sets the role") == 1
    both = tracker_factory(name="Both Viewer")
    grant(person, both, "viewer")
    page = _visible(client, person)
    assert "Direct role: Viewer Sets the role" in page and "View all trackers: Viewer Sets the role" in page


def test_access_page_header_and_sections(client, user_manager, user_factory, team_factory, add_member, give_set, db):
    local = user_factory(full_name="Local Person")
    admin = user_factory(full_name="Admin Person", is_admin=True)
    assert "Administrator" in _visible(client, admin) and "Administrator" not in _visible(client, local)
    sso = user_factory(full_name="Sso Person", auth_source="sso", password_hash=None)
    page = _visible(client, local)
    assert f"{local.email} · Signs in with a password" in page
    assert "Reset password" in page and "Disable" in page and "Make administrator" not in page  # manager is no admin
    assert "Signs in with Microsoft" in _visible(client, sso)
    assert "Reset password" not in _visible(client, sso)
    assert "Not a member of any team." in page and "Holds no permission sets." in page
    person = user_factory(full_name="Member Person")
    windows = team_factory(name="Windows", parent=team_factory(name="Infrastructure"))
    add_member(windows, person, "editor")
    give_set(["view_activity"], user=person, name="Readers")
    give_set(["view_all_trackers"], team=windows, name="PMO")
    raw = _access_html(client, person)
    page = _visible(client, person)
    for text in (
        "Teams",
        "Windows · Editor",
        "Permission sets",
        "Readers, held directly",
        "PMO, held by team Windows",
    ):
        assert text in page
    assert page.index("Teams") < page.index("Permission sets")
    assert f'href="/admin/teams/{windows.id}"' not in raw  # manage_users alone does not link teams
    give_set(["manage_teams"], user=user_manager)
    assert f'href="/admin/teams/{windows.id}"' in _access_html(client, person)
    pending = user_factory(status="pending")
    assert "Approve" in _visible(client, pending)


def test_access_page_lists_region_grants_of_active_and_disabled_people(
    client, logged_in_admin, user_factory, region_factory, region_grant, tracker_factory, db
):
    emea = region_factory("EMEA")
    region_factory("APAC")
    tracker = tracker_factory(name="Covered")
    db.add(TrackerRegion(tracker_id=tracker.id, region_id=emea.id))
    db.commit()
    holder = user_factory(full_name="Active Holder")
    region_grant(emea, holder, "viewer")
    raw = _access_html(client, holder)
    page = _visible(client, holder)
    assert "Region EMEA: Viewer" in page
    assert page.index("Regions") > page.index("Teams") and "EMEA · Viewer" in page[page.index("Regions") :]
    assert f'href="/admin/regions/{emea.id}/access">EMEA</a>' in raw
    gone = user_factory(full_name="Gone Holder", status="disabled")
    uncovered = region_factory("AMER")
    region_grant(uncovered, gone, "owner")
    page = _visible(client, gone)
    assert "AMER · Owner" in page[page.index("Regions") :]
    assert "Any teams, region access and permission sets it keeps apply again once it is active." in page
    assert "Has no region access." in _visible(client, user_factory(full_name="No Region"))
