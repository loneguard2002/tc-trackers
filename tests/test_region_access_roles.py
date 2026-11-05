"""Access through a region grant: it reaches every tracker covering the region (database required)."""

from tracker.auth.roles import (
    RegionAccess,
    Route,
    tracker_access_list,
    tracker_access_routes,
    tracker_roles,
    user_role,
    visible_trackers,
)
from tracker.models import Team, TrackerRegion


def _cover(db, tracker, *regions) -> None:
    db.add_all(TrackerRegion(tracker_id=tracker.id, region_id=region.id) for region in regions)
    db.commit()


def test_region_grant_reaches_trackers_covering_the_region(
    db, user_factory, tracker_factory, region_factory, region_grant
):
    emea, apac = region_factory("EMEA"), region_factory("APAC")
    covered, other = tracker_factory(name="Covered"), tracker_factory(name="Other")
    _cover(db, covered, emea)
    _cover(db, other, apac)
    user = user_factory()
    region_grant(emea, user, "viewer")
    assert user_role(db, user, covered.id) == "viewer"
    assert user_role(db, user, other.id) is None
    assert [t.id for t in visible_trackers(db, user)] == [covered.id]


def test_highest_role_wins_across_routes(
    db, user_factory, tracker_factory, region_factory, region_grant, grant, team_factory, add_member
):
    emea, apac = region_factory("EMEA"), region_factory("APAC")
    user = user_factory()
    direct = tracker_factory(name="Direct")
    _cover(db, direct, emea)
    region_grant(emea, user, "editor")
    grant(user, direct, "viewer")
    assert user_role(db, user, direct.id) == "editor"

    team = team_factory("Windows")
    via_team = tracker_factory(name="Via team", team_id=team.id)
    _cover(db, via_team, emea)
    add_member(team, user, "owner")
    assert user_role(db, user, via_team.id) == "owner"

    both = tracker_factory(name="Both")
    _cover(db, both, emea, apac)
    other = user_factory()
    region_grant(emea, other, "viewer")
    region_grant(apac, other, "editor")
    assert user_role(db, other, both.id) == "editor"


def test_region_route_follows_the_tracker_regions(db, user_factory, tracker_factory, region_factory, region_grant):
    emea = region_factory("EMEA")
    tracker, bare = tracker_factory(name="Covered"), tracker_factory(name="Bare")
    _cover(db, tracker, emea)
    user = user_factory()
    region_grant(emea, user, "viewer")
    assert user_role(db, user, tracker.id) == "viewer"
    assert user_role(db, user, bare.id) is None
    db.query(TrackerRegion).filter_by(tracker_id=tracker.id, region_id=emea.id).delete()
    db.commit()
    assert user_role(db, user, tracker.id) is None


def test_inactive_person_reaches_nothing_by_region(db, user_factory, tracker_factory, region_factory, region_grant):
    emea = region_factory("EMEA")
    tracker = tracker_factory()
    _cover(db, tracker, emea)
    user = user_factory()
    region_grant(emea, user, "editor")
    user.status = "disabled"
    db.commit()
    assert tracker_roles(db, user) == {}
    user.status = "active"
    db.commit()
    assert tracker_roles(db, user) == {tracker.id: "editor"}


def test_retired_region_grant_keeps_working(db, user_factory, tracker_factory, region_factory, region_grant):
    emea = region_factory("EMEA")
    tracker = tracker_factory()
    _cover(db, tracker, emea)
    user = user_factory()
    region_grant(emea, user, "viewer")
    emea.retired = True
    db.commit()
    assert user_role(db, user, tracker.id) == "viewer"


def test_team_region_grants_nothing(db, user_factory, tracker_factory, region_factory, region_grant, location_factory):
    emea, apac = region_factory("EMEA"), region_factory("APAC")
    team = Team(name="Located", location_id=location_factory(emea).id, region_id=emea.id)
    db.add(team)
    db.commit()
    tracker = tracker_factory(team_id=team.id)
    _cover(db, tracker, apac)
    user = user_factory()
    region_grant(emea, user, "owner")
    assert user_role(db, user, tracker.id) is None


def test_effective_access_lists_the_region_route(db, user_factory, tracker_factory, region_factory, region_grant):
    emea = region_factory("EMEA")
    tracker = tracker_factory()
    _cover(db, tracker, emea)
    user = user_factory()
    region_grant(emea, user, "viewer")
    [access] = tracker_access_routes(db, user)
    assert access.tracker.id == tracker.id and access.role == "viewer"
    assert Route("Region EMEA: Viewer", "viewer") in access.routes


def test_access_list_shows_region_route_once_per_region(
    db, user_factory, tracker_factory, region_factory, region_grant
):
    emea = region_factory("EMEA")
    tracker = tracker_factory()
    _cover(db, tracker, emea)
    holder, gone = user_factory(), user_factory()
    region_grant(emea, holder, "viewer")
    region_grant(emea, gone, "owner")
    gone.status = "disabled"
    db.commit()
    rows = tracker_access_list(db, tracker)
    assert [r.user.id for r in rows] == [holder.id]
    assert rows[0].regions == [RegionAccess(emea.id, "EMEA", "viewer")]
    assert rows[0].role == "viewer"
