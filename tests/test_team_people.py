from tracker.auth.roles import user_role
from tracker.teams.people import InheritedRole, reach_counts, team_people


def _tree(team_factory):
    infra = team_factory("Infrastructure")
    windows = team_factory("Windows", infra)
    patching = team_factory("Patching", windows)
    return infra, windows, patching


def test_people_include_members_of_teams_above(db, team_factory, user_factory, add_member):
    infra, windows, patching = _tree(team_factory)
    head, lead = user_factory(full_name="Head"), user_factory(full_name="Lead")
    add_member(infra, head, "owner")
    add_member(windows, lead, "editor")

    people = {p.user.id: p for p in team_people(db, patching.id)}

    assert set(people) == {head.id, lead.id}
    assert people[head.id].direct_role is None
    assert people[head.id].inherited == [InheritedRole(infra.id, "Infrastructure", "owner")]
    assert people[head.id].role == "owner"
    assert people[lead.id].inherited == [InheritedRole(windows.id, "Windows", "editor")]


def test_a_person_in_two_teams_of_the_chain_shows_once_with_the_highest_role(
    db, team_factory, user_factory, add_member
):
    infra, windows, _patching = _tree(team_factory)
    pmo = user_factory()
    add_member(windows, pmo, "viewer")
    add_member(infra, pmo, "owner")

    rows = team_people(db, windows.id)

    assert len(rows) == 1
    assert rows[0].direct_role == "viewer"
    assert rows[0].role == "owner"
    assert len(rows[0].inherited) == 1


def test_inactive_people_do_not_reach_but_inactive_members_stay_listed(db, team_factory, user_factory, add_member):
    infra, windows, _patching = _tree(team_factory)
    gone = user_factory(status="disabled")
    pending = user_factory(status="pending")
    add_member(infra, gone, "owner")
    add_member(windows, pending, "viewer")

    assert [p.user.id for p in team_people(db, windows.id)] == [pending.id]


def test_people_are_sorted_by_name_then_id(db, team_factory, user_factory, add_member):
    infra, _windows, _patching = _tree(team_factory)
    zed, bea, amy = user_factory(full_name="zed"), user_factory(full_name="Bea"), user_factory(full_name="amy")
    for user in (zed, bea, amy):
        add_member(infra, user, "viewer")

    assert [p.user.id for p in team_people(db, infra.id)] == [amy.id, bea.id, zed.id]


def test_reach_counts(db, team_factory, user_factory, add_member):
    infra, windows, patching = _tree(team_factory)
    lone = team_factory("Lone")
    head, lead, pmo = user_factory(), user_factory(), user_factory()
    off = user_factory(status="disabled")
    add_member(infra, head, "owner")
    add_member(windows, lead, "editor")
    add_member(windows, pmo, "viewer")
    add_member(windows, off, "viewer")

    assert reach_counts(db) == {infra.id: 1, windows.id: 3, patching.id: 3, lone.id: 0}


def test_diamond_highest_role_wins_and_person_counted_once(db, team_factory, user_factory, tracker_factory, add_member):
    infra, applications = team_factory("Infrastructure"), team_factory("Applications")
    windows = team_factory("Windows", infra)
    desktops = team_factory("Desktops", parents=(windows, applications))
    tracker = tracker_factory(team_id=desktops.id)
    person = user_factory(full_name="Pat")
    add_member(windows, person, "viewer")
    add_member(applications, person, "editor")

    assert user_role(db, person, tracker.id) == "editor"
    assert reach_counts(db)[desktops.id] == 1
    [row] = team_people(db, desktops.id)
    assert row.user.id == person.id and row.direct_role is None and row.role == "editor"
    assert row.inherited == [
        InheritedRole(applications.id, "Applications", "editor"),
        InheritedRole(windows.id, "Windows", "viewer"),
    ]
