"""The self-promotion guard (spec section 6.3); database required."""

import pytest
from sqlalchemy import select

from tracker.auth.guards import SELF_PROMOTION_MESSAGE, raises_own_access, snapshot_access
from tracker.models import TeamMember, TrackerRole
from tracker.teams.tree import set_team_parents


def test_message():
    assert SELF_PROMOTION_MESSAGE == (
        "You cannot make a change that gives you more access to a tracker. Ask an administrator."
    )


def test_joining_a_team_with_trackers_raises_own_access(db, user_factory, team_factory, tracker_factory):
    actor = user_factory()
    team = team_factory()
    tracker_factory(team_id=team.id)
    before = snapshot_access(db, actor)
    assert before == {}
    db.add(TeamMember(team_id=team.id, user_id=actor.id, role="viewer"))
    assert raises_own_access(db, actor, before) is True


def test_raising_own_direct_role_raises_own_access(db, user_factory, tracker_factory, grant):
    actor = user_factory()
    tracker = tracker_factory()
    grant(actor, tracker, "viewer")
    before = snapshot_access(db, actor)
    db.scalar(select(TrackerRole).where(TrackerRole.user_id == actor.id)).role = "owner"
    assert raises_own_access(db, actor, before) is True


def test_lowering_own_role_does_not(db, user_factory, tracker_factory, grant):
    actor = user_factory()
    tracker = tracker_factory()
    grant(actor, tracker, "owner")
    before = snapshot_access(db, actor)
    db.scalar(select(TrackerRole).where(TrackerRole.user_id == actor.id)).role = "viewer"
    assert raises_own_access(db, actor, before) is False


def test_moving_a_tracker_into_own_team_raises_own_access(db, user_factory, team_factory, tracker_factory, add_member):
    actor = user_factory()
    own = team_factory()
    add_member(own, actor, "viewer")
    tracker = tracker_factory()
    before = snapshot_access(db, actor)
    tracker.team_id = own.id
    assert raises_own_access(db, actor, before) is True


def test_moving_another_team_under_own_team_raises_own_access(
    db, user_factory, team_factory, tracker_factory, add_member
):
    actor = user_factory()
    own = team_factory("W")
    other = team_factory("X")
    tracker_factory(team_id=other.id)
    add_member(own, actor, "editor")
    before = snapshot_access(db, actor)
    set_team_parents(db, other.id, [own.id])
    assert raises_own_access(db, actor, before) is True


def test_moving_own_team_without_new_trackers_does_not(db, user_factory, team_factory, tracker_factory, add_member):
    actor = user_factory()
    parent = team_factory("P")
    own = team_factory("W", parent=parent)
    tracker = tracker_factory(team_id=own.id)
    add_member(own, actor, "editor")
    before = snapshot_access(db, actor)
    assert before == {tracker.id: "editor"}
    set_team_parents(db, own.id, [])
    assert raises_own_access(db, actor, before) is False


def test_change_for_someone_else_does_not(db, user_factory, team_factory, tracker_factory):
    actor = user_factory()
    someone = user_factory()
    team = team_factory()
    tracker_factory(team_id=team.id)
    before = snapshot_access(db, actor)
    db.add(TeamMember(team_id=team.id, user_id=someone.id, role="owner"))
    assert raises_own_access(db, actor, before) is False


def test_administrator_is_exempt(db, user_factory, tracker_factory):
    admin = user_factory(is_admin=True)
    before = snapshot_access(db, admin)
    assert before is None
    tracker_factory()
    assert raises_own_access(db, admin, before) is False


def test_moving_own_team_under_a_team_where_the_actor_is_owner_raises_own_access(
    db, user_factory, team_factory, tracker_factory, add_member
):
    actor = user_factory()
    parent = team_factory("P")
    own = team_factory("W")
    tracker = tracker_factory(team_id=own.id)
    add_member(own, actor, "viewer")
    add_member(parent, actor, "owner")
    before = snapshot_access(db, actor)
    assert before == {tracker.id: "viewer"}
    set_team_parents(db, own.id, [parent.id])
    assert raises_own_access(db, actor, before) is True


def test_joining_a_team_holding_view_all_trackers_raises_own_access(
    db, user_factory, team_factory, tracker_factory, give_set
):
    actor = user_factory()
    team = team_factory()
    give_set(["view_all_trackers"], team=team)
    tracker_factory()
    before = snapshot_access(db, actor)
    assert before == {}
    db.add(TeamMember(team_id=team.id, user_id=actor.id, role="viewer"))
    assert raises_own_access(db, actor, before) is True


def test_snapshot_after_the_change_is_refused(db, user_factory, team_factory, tracker_factory):
    actor = user_factory()
    team = team_factory()
    tracker_factory(team_id=team.id)
    db.add(TeamMember(team_id=team.id, user_id=actor.id, role="owner"))
    with pytest.raises(RuntimeError, match="snapshot_access must run before the change is made"):
        snapshot_access(db, actor)
