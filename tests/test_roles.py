"""Per-tracker roles (database required)."""

from tracker.auth.roles import ROLE_ORDER, user_role, visible_trackers


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
    assert client.get(f"/trackers/{t.id}").status_code == 200


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
