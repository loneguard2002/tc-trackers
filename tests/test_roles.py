"""Per-tracker roles (database required)."""

from sqlalchemy import event, select

from tests.conftest import post
from tracker.auth.roles import ROLE_ORDER, tracker_roles, user_role, visible_trackers
from tracker.models import CompletionEntry, Group


def test_role_order():
    assert ROLE_ORDER == {"viewer": 1, "editor": 2, "owner": 3}


def test_require_tracker_role_hides_tracker(client, logged_in_user, tracker_factory):
    t = tracker_factory()
    assert client.get(f"/trackers/{t.id}").status_code == 404


def test_missing_tracker_is_404_for_everyone(client, logged_in_admin):
    assert client.get("/trackers/9999").status_code == 404


def test_viewer_can_view(client, logged_in_user, tracker_factory, grant):
    t = tracker_factory()
    grant(logged_in_user, t, "viewer")
    page = client.get(f"/trackers/{t.id}", follow_redirects=True)
    assert page.status_code == 200 and page.request.path == f"/trackers/{t.id}/report"


def test_viewer_cannot_reach_editor_route(client, logged_in_user, tracker_factory, grant):
    t = tracker_factory()
    grant(logged_in_user, t, "viewer")
    assert client.get(f"/trackers/{t.id}/entries/new").status_code == 404


def test_editor_reaches_editor_route(client, logged_in_user, tracker_factory, grant):
    t = tracker_factory()
    grant(logged_in_user, t, "editor")
    assert client.get(f"/trackers/{t.id}/entries/new").status_code == 200


def test_admin_is_owner_everywhere(client, logged_in_admin, tracker_factory, db):
    t = tracker_factory()
    assert client.get(f"/trackers/{t.id}/entries/new").status_code == 200
    assert user_role(db, logged_in_admin, t.id) == "owner"


def test_user_role_none_without_grant(db, user_factory, tracker_factory):
    assert user_role(db, user_factory(), tracker_factory().id) is None


def test_visible_trackers_only_with_role(db, user_factory, tracker_factory, grant):
    user, admin = user_factory(), user_factory(is_admin=True)
    mine, other = tracker_factory(name="Mine"), tracker_factory(name="Other")
    grant(user, mine, "viewer")
    assert [t.id for t in visible_trackers(db, user)] == [mine.id]
    assert {t.id for t in visible_trackers(db, admin)} == {mine.id, other.id}


# --- Roles through teams and the view_all_trackers permission (spec section 6.1) ----------------------------------


def test_team_role_alone(db, user_factory, tracker_factory, team_factory, add_member):
    team, user = team_factory(name="Windows"), user_factory()
    t = tracker_factory(team_id=team.id)
    add_member(team, user, "editor")
    assert user_role(db, user, t.id) == "editor"
    assert tracker_roles(db, user) == {t.id: "editor"}


def test_team_role_flows_down_several_levels(db, user_factory, tracker_factory, team_factory, add_member):
    a = team_factory(name="A")
    b = team_factory(name="B", parent=a)
    c = team_factory(name="C", parent=b)
    user = user_factory()
    add_member(a, user, "editor")
    t = tracker_factory(team_id=c.id)
    assert user_role(db, user, t.id) == "editor"
    assert [x.id for x in visible_trackers(db, user)] == [t.id]


def test_team_role_not_sideways_or_upwards(db, user_factory, tracker_factory, team_factory, add_member):
    a = team_factory(name="A")
    b = team_factory(name="B", parent=a)
    b2 = team_factory(name="B2", parent=a)
    user = user_factory()
    add_member(b, user, "owner")
    in_a, in_b2 = tracker_factory(team_id=a.id), tracker_factory(team_id=b2.id)
    assert user_role(db, user, in_a.id) is None
    assert user_role(db, user, in_b2.id) is None
    assert visible_trackers(db, user) == []
    assert tracker_roles(db, user) == {}


def test_highest_route_wins(db, user_factory, tracker_factory, team_factory, add_member, grant, give_set):
    team = team_factory(name="Team")
    t = tracker_factory(team_id=team.id)

    direct_viewer_team_owner = user_factory()
    grant(direct_viewer_team_owner, t, "viewer")
    add_member(team, direct_viewer_team_owner, "owner")
    assert user_role(db, direct_viewer_team_owner, t.id) == "owner"

    direct_owner_team_viewer = user_factory()
    grant(direct_owner_team_viewer, t, "owner")
    add_member(team, direct_owner_team_viewer, "viewer")
    assert user_role(db, direct_owner_team_viewer, t.id) == "owner"

    a = team_factory(name="A")
    b = team_factory(name="B", parent=a)
    in_b = tracker_factory(team_id=b.id)
    two_memberships = user_factory()
    add_member(a, two_memberships, "viewer")
    add_member(b, two_memberships, "editor")
    assert user_role(db, two_memberships, in_b.id) == "editor"
    assert tracker_roles(db, two_memberships) == {in_b.id: "editor"}

    view_all_and_editor = user_factory()
    give_set(["view_all_trackers"], user=view_all_and_editor)
    grant(view_all_and_editor, t, "editor")
    assert user_role(db, view_all_and_editor, t.id) == "editor"
    assert tracker_roles(db, view_all_and_editor) == {t.id: "editor", in_b.id: "viewer"}


def test_view_all_trackers_gives_viewer_everywhere(
    db, user_factory, tracker_factory, team_factory, add_member, give_set
):
    pmo, other = team_factory(name="PMO"), team_factory(name="Other")
    in_other, no_team = tracker_factory(name="In other", team_id=other.id), tracker_factory(name="No team")
    expected = {in_other.id: "viewer", no_team.id: "viewer"}

    holder = user_factory()
    give_set(["view_all_trackers"], user=holder)
    assert tracker_roles(db, holder) == expected

    member = user_factory()
    add_member(pmo, member, "viewer")
    give_set(["view_all_trackers"], team=pmo)
    assert tracker_roles(db, member) == expected
    assert [t.id for t in visible_trackers(db, member)] == [in_other.id, no_team.id]


def test_view_all_held_by_team_above_or_below_does_not_apply(
    db, user_factory, tracker_factory, team_factory, add_member, give_set
):
    a = team_factory(name="A")
    b = team_factory(name="B", parent=a)
    c = team_factory(name="C", parent=b)
    give_set(["view_all_trackers"], team=b)
    t = tracker_factory()
    above, below = user_factory(), user_factory()
    add_member(a, above, "viewer")
    add_member(c, below, "viewer")
    assert user_role(db, above, t.id) is None
    assert user_role(db, below, t.id) is None


def test_other_permissions_do_not_give_viewer(db, user_factory, tracker_factory, give_set):
    user = user_factory()
    give_set(["create_trackers", "view_activity"], user=user)
    assert user_role(db, user, tracker_factory().id) is None


def test_tracker_without_team_is_reached_only_directly_by_admin_or_view_all(
    db, user_factory, tracker_factory, team_factory, add_member, grant, give_set
):
    team = team_factory(name="Team")
    t = tracker_factory()
    member, direct, admin, view_all = user_factory(), user_factory(), user_factory(is_admin=True), user_factory()
    add_member(team, member, "owner")
    grant(direct, t, "editor")
    give_set(["view_all_trackers"], user=view_all)
    assert user_role(db, member, t.id) is None
    assert user_role(db, direct, t.id) == "editor"
    assert user_role(db, admin, t.id) == "owner"
    assert tracker_roles(db, admin) == {t.id: "owner"}
    assert user_role(db, view_all, t.id) == "viewer"


def test_pending_and_disabled_users_have_no_access(
    db, user_factory, tracker_factory, team_factory, add_member, grant, give_set
):
    team = team_factory(name="Team")
    t = tracker_factory(team_id=team.id)
    for status in ("pending", "disabled"):
        u = user_factory(status=status)
        grant(u, t, "owner")
        add_member(team, u, "owner")
        give_set(["view_all_trackers"], user=u)
        assert user_role(db, u, t.id) is None and visible_trackers(db, u) == [] and tracker_roles(db, u) == {}


def test_team_member_opens_tracker_and_others_get_404(
    client, logged_in_user, tracker_factory, team_factory, add_member
):
    parent = team_factory(name="Infrastructure")
    windows, network = team_factory(name="Windows", parent=parent), team_factory(name="Network", parent=parent)
    add_member(windows, logged_in_user, "viewer")
    mine, sibling = tracker_factory(team_id=windows.id), tracker_factory(team_id=network.id)
    page = client.get(f"/trackers/{mine.id}", follow_redirects=True)
    assert page.status_code == 200 and page.request.path == f"/trackers/{mine.id}/report"
    assert client.get(f"/trackers/{sibling.id}").status_code == 404


def test_visible_trackers_is_one_statement(
    db, user_factory, tracker_factory, team_factory, add_member, grant, give_set
):
    a = team_factory(name="A")
    b = team_factory(name="B", parent=a)
    user = user_factory()
    add_member(a, user, "editor")
    give_set(["view_all_trackers"], team=b)
    grant(user, tracker_factory(name="Direct"), "owner")
    tracker_factory(name="Team", team_id=b.id)
    engine = db.get_bind()
    statements = []

    def count(*args):
        statements.append(args[2])

    event.listen(engine, "before_cursor_execute", count)
    try:
        trackers = visible_trackers(db, user)
    finally:
        event.remove(engine, "before_cursor_execute", count)
    assert [t.name for t in trackers] == ["Direct", "Team"]
    assert len(statements) == 1


def test_archived_tracker_reached_through_team_is_read_only(
    client, db, logged_in_user, tracker_factory, team_factory, add_member
):
    team = team_factory(name="Team")
    add_member(team, logged_in_user, "editor")
    tracker = tracker_factory(team_id=team.id, status="archived")
    group = Group(tracker_id=tracker.id, name="Site A", baseline=50)
    db.add(group)
    db.commit()
    form = {"group_id": str(group.id), "entry_date": "2026-10-14", "quantity": "5", "note": ""}
    page = post(client, f"/trackers/{tracker.id}/entries/new", form, follow_redirects=True)
    assert page.status_code == 200
    assert b"This tracker is archived." in page.data
    assert db.scalars(select(CompletionEntry)).all() == []


def test_home_lists_team_trackers_with_their_role(client, logged_in_user, tracker_factory, team_factory, add_member):
    parent = team_factory(name="Infrastructure")
    windows, network = team_factory(name="Windows", parent=parent), team_factory(name="Network", parent=parent)
    add_member(parent, logged_in_user, "editor")
    tracker_factory(name="Patching tracker", team_id=windows.id)
    tracker_factory(name="Firewall tracker", team_id=network.id)
    tracker_factory(name="Unrelated tracker")
    page = client.get("/")
    assert b"Patching tracker" in page.data and b"Firewall tracker" in page.data
    assert b"Unrelated tracker" not in page.data
    assert page.data.count(b'<span class="role-tag">Editor</span>') == 2


def test_an_inactive_administrator_has_no_role(db, user_factory, tracker_factory):
    t = tracker_factory()
    for status in ("pending", "disabled"):
        admin = user_factory(is_admin=True, status=status)
        assert user_role(db, admin, t.id) is None
        assert tracker_roles(db, admin) == {} and visible_trackers(db, admin) == []
