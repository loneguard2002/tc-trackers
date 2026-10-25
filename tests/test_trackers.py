"""Trackers, settings, groups, roles and the home page (database required)."""

from datetime import date

from sqlalchemy import select

from tests.conftest import post
from tracker.models import AuditLog, CompletionEntry, Group, Tracker, TrackerRole, Week
from tracker.trackers import load_engine_inputs, tracker_summary

SETTINGS = {
    "name": "Rollout",
    "unit_label": "thin clients",
    "group_label": "Location",
    "description": "",
    "week_ending_weekday": "4",
    "start_date": "2026-09-02",
    "last_week_ending": "2026-12-25",
    "target_completion": "2026-12-18",
    "completed_before_first": "0",
    "moving_average_weeks": "3",
}


def make_group(db, tracker, name="Site A", baseline=40, **kw):
    group = Group(tracker_id=tracker.id, name=name, baseline=baseline, **kw)
    db.add(group)
    db.commit()
    return group


def add_entry(db, tracker, group, entry_date, quantity, week_ending):
    db.add(
        CompletionEntry(
            tracker_id=tracker.id, group_id=group.id, entry_date=entry_date, quantity=quantity, week_ending=week_ending
        )
    )
    db.commit()


def audit_actions(db, tracker_id):
    return [a for a in db.scalars(select(AuditLog).where(AuditLog.tracker_id == tracker_id).order_by(AuditLog.id))]


def test_admin_creates_tracker_and_becomes_owner(client, logged_in_admin, db):
    response = post(client, "/trackers/new", SETTINGS)
    assert response.status_code == 302
    tracker = db.scalars(select(Tracker)).one()
    role = db.get(TrackerRole, (logged_in_admin.id, tracker.id))
    assert role.role == "owner"
    assert any(a.action == "tracker_created" for a in audit_actions(db, tracker.id))


def test_non_admin_cannot_create_tracker(client, logged_in_user):
    assert client.get("/trackers/new").status_code == 403
    assert post(client, "/trackers/new", SETTINGS).status_code == 403


def test_first_week_snaps_to_week_ending_day(client, logged_in_admin, db):
    post(client, "/trackers/new", SETTINGS)  # Wednesday 2 Sep 2026, Friday week-ending
    assert db.scalars(select(Tracker)).one().first_week_ending == date(2026, 9, 4)


def test_last_week_beyond_52_rejected(client, logged_in_admin, db):
    response = post(client, "/trackers/new", {**SETTINGS, "last_week_ending": "2027-12-31"})
    assert response.status_code == 400
    assert b"52 weeks" in response.data
    assert db.scalars(select(Tracker)).first() is None


def test_weekday_change_refused_with_entries(client, logged_in_admin, db, tracker_factory):
    tracker = tracker_factory()
    group = make_group(db, tracker)
    add_entry(db, tracker, group, date(2026, 9, 1), 3, date(2026, 9, 4))
    response = post(client, f"/trackers/{tracker.id}/settings", {**SETTINGS, "week_ending_weekday": "3"})
    assert response.status_code == 400
    assert b"The week-ending day cannot change once entries exist." in response.data
    db.refresh(tracker)
    assert tracker.week_ending_weekday == 4


def test_settings_saved_and_audited(client, logged_in_admin, db, tracker_factory):
    tracker = tracker_factory()
    response = post(client, f"/trackers/{tracker.id}/settings", {**SETTINGS, "name": "Renamed"})
    assert response.status_code == 302
    db.refresh(tracker)
    assert tracker.name == "Renamed"
    assert any(a.action == "settings_updated" and "name" in a.detail for a in audit_actions(db, tracker.id))


def test_settings_refuse_range_excluding_entries(client, logged_in_admin, db, tracker_factory):
    tracker = tracker_factory()
    group = make_group(db, tracker)
    add_entry(db, tracker, group, date(2026, 12, 20), 3, date(2026, 12, 25))
    response = post(client, f"/trackers/{tracker.id}/settings", {**SETTINGS, "last_week_ending": "2026-12-11"})
    assert response.status_code == 400
    assert b"outside the new week range" in response.data


def test_editor_cannot_open_settings(client, logged_in_user, db, tracker_factory, grant):
    tracker = tracker_factory()
    grant(logged_in_user, tracker, "editor")
    assert client.get(f"/trackers/{tracker.id}/settings").status_code == 404


def test_retire_group_with_remaining_refused(client, logged_in_admin, db, tracker_factory):
    tracker = tracker_factory()
    group = make_group(db, tracker, baseline=10)
    post(client, f"/trackers/{tracker.id}/groups", {"action": "retire", "group_id": group.id})
    db.refresh(group)
    assert group.retired is False
    page = client.get(f"/trackers/{tracker.id}/groups")
    assert b"Correct the baseline to the deployed figure before retiring this group." in page.data


def test_retire_group_when_fully_deployed(client, logged_in_admin, db, tracker_factory):
    tracker = tracker_factory()
    group = make_group(db, tracker, baseline=10)
    add_entry(db, tracker, group, date(2026, 9, 1), 10, date(2026, 9, 4))
    post(client, f"/trackers/{tracker.id}/groups", {"action": "retire", "group_id": group.id})
    db.refresh(group)
    assert group.retired is True


def test_baseline_change_audited(client, logged_in_admin, db, tracker_factory):
    tracker = tracker_factory()
    group = make_group(db, tracker, baseline=10)
    post(
        client,
        f"/trackers/{tracker.id}/groups",
        {"action": "update", "group_id": group.id, "name": "Site A", "baseline": "12", "ready_not_complete": "0"},
    )
    db.refresh(group)
    assert group.baseline == 12
    rows = [a for a in audit_actions(db, tracker.id) if a.action == "baseline_changed"]
    assert rows[0].detail == {"baseline": [10, 12]}


def test_create_rename_and_reorder_groups(client, logged_in_admin, db, tracker_factory):
    tracker = tracker_factory()
    url = f"/trackers/{tracker.id}/groups"
    post(client, url, {"action": "create", "name": "Site A", "baseline": "10"})
    post(client, url, {"action": "create", "name": "Site B", "baseline": "20"})
    post(client, url, {"action": "create", "name": "Site B", "baseline": "5"})  # duplicate name refused
    first, second = db.scalars(select(Group).order_by(Group.sort_order, Group.id)).all()
    assert (first.name, second.name) == ("Site A", "Site B")
    post(client, url, {"action": "down", "group_id": first.id})
    db.expire_all()
    assert [g.name for g in db.scalars(select(Group).order_by(Group.sort_order, Group.id))] == ["Site B", "Site A"]
    post(client, url, {"action": "update", "group_id": first.id, "name": "Site C", "baseline": "10"})
    db.refresh(first)
    assert first.name == "Site C"


def test_editor_can_edit_snapshot_not_baseline(client, logged_in_user, db, tracker_factory, grant):
    tracker = tracker_factory()
    grant(logged_in_user, tracker, "editor")
    group = make_group(db, tracker, baseline=10)
    post(
        client,
        f"/trackers/{tracker.id}/groups",
        {
            "action": "update",
            "group_id": group.id,
            "name": "Hacked",
            "baseline": "99",
            "ready_not_complete": "4",
            "planned_completion": "2026-11-06",
            "rag": "Amber",
            "comment": "Stock late",
        },
    )
    db.refresh(group)
    assert (group.baseline, group.name) == (10, "Site A")
    assert (group.ready_not_complete, group.rag, group.comment) == (4, "Amber", "Stock late")
    assert group.planned_completion == date(2026, 11, 6)
    assert post(client, f"/trackers/{tracker.id}/groups", {"action": "retire", "group_id": group.id}).status_code == 403
    assert (
        post(client, f"/trackers/{tracker.id}/groups", {"action": "create", "name": "X", "baseline": "1"}).status_code
        == 403
    )


def test_viewer_cannot_open_groups(client, logged_in_user, db, tracker_factory, grant):
    tracker = tracker_factory()
    grant(logged_in_user, tracker, "viewer")
    assert client.get(f"/trackers/{tracker.id}/groups").status_code == 404


def test_home_lists_only_visible_trackers(client, logged_in_user, tracker_factory, grant):
    mine = tracker_factory(name="Mine tracker")
    tracker_factory(name="Other tracker")
    grant(logged_in_user, mine, "viewer")
    page = client.get("/")
    assert b"Mine tracker" in page.data
    assert b"Other tracker" not in page.data


def test_home_shows_last_entry_date_and_percent(client, logged_in_user, db, tracker_factory, grant):
    tracker = tracker_factory(name="Shown")
    grant(logged_in_user, tracker, "viewer")
    group = make_group(db, tracker, baseline=40)
    add_entry(db, tracker, group, date(2026, 9, 3), 10, date(2026, 9, 4))
    page = client.get("/")
    assert b"03 Sep 2026" in page.data
    assert b"25%" in page.data


def test_archived_tracker_hidden_from_home_but_reachable(client, logged_in_admin, db, tracker_factory):
    tracker = tracker_factory(name="Old tracker")
    assert post(client, f"/trackers/{tracker.id}/archive").status_code == 302
    db.refresh(tracker)
    assert tracker.status == "archived"
    assert b"Old tracker" not in client.get("/").data
    assert b"Old tracker" in client.get("/?archived=1").data
    assert client.get(f"/trackers/{tracker.id}/groups").status_code == 200
    assert client.get(f"/trackers/{tracker.id}/settings").status_code == 200


def test_archive_is_admin_only(client, logged_in_user, tracker_factory, grant):
    tracker = tracker_factory()
    grant(logged_in_user, tracker, "owner")
    assert post(client, f"/trackers/{tracker.id}/archive").status_code == 403


def test_archived_tracker_refuses_changes(client, logged_in_admin, db, tracker_factory, user_factory):
    tracker = tracker_factory(status="archived")
    group = make_group(db, tracker, baseline=10)
    other = user_factory()
    follow = {"follow_redirects": True}
    page = post(client, f"/trackers/{tracker.id}/settings", {**SETTINGS, "name": "Changed"}, **follow)
    assert b"This tracker is archived." in page.data
    page = post(
        client,
        f"/trackers/{tracker.id}/groups",
        {"action": "update", "group_id": group.id, "baseline": "50", "name": "Site A"},
        **follow,
    )
    assert b"This tracker is archived." in page.data
    post(client, f"/trackers/{tracker.id}/groups", {"action": "create", "name": "New", "baseline": "1"})
    page = post(client, f"/trackers/{tracker.id}/roles", {"user_id": other.id, "role": "viewer"}, **follow)
    assert b"This tracker is archived." in page.data
    db.expire_all()
    assert db.get(Tracker, tracker.id).name == "Test tracker"
    assert db.get(Group, group.id).baseline == 10
    assert len(db.scalars(select(Group)).all()) == 1
    assert db.get(TrackerRole, (other.id, tracker.id)) is None


def test_roles_page_admin_only(client, logged_in_user, tracker_factory, grant):
    tracker = tracker_factory()
    grant(logged_in_user, tracker, "owner")
    assert client.get(f"/trackers/{tracker.id}/roles").status_code == 403


def test_admin_sets_and_removes_roles_audited(client, logged_in_admin, db, tracker_factory, user_factory):
    tracker, member = tracker_factory(), user_factory(full_name="Member One")
    url = f"/trackers/{tracker.id}/roles"
    assert b"Member One" in client.get(url).data
    post(client, url, {"user_id": member.id, "role": "viewer"})
    assert db.get(TrackerRole, (member.id, tracker.id)).role == "viewer"
    post(client, url, {"user_id": member.id, "role": "editor"})
    db.expire_all()
    assert db.get(TrackerRole, (member.id, tracker.id)).role == "editor"
    post(client, url, {"user_id": member.id, "role": "remove"})
    db.expire_all()
    assert db.get(TrackerRole, (member.id, tracker.id)) is None
    actions = [a.action for a in audit_actions(db, tracker.id)]
    assert actions == ["role_set", "role_set", "role_removed"]
    assert post(client, url, {"user_id": member.id, "role": "boss"}).status_code == 400


def test_every_role_redirects_to_report(client, logged_in_user, tracker_factory, grant, db):
    tracker = tracker_factory()
    grant(logged_in_user, tracker, "owner")
    assert client.get(f"/trackers/{tracker.id}").headers["Location"].endswith(f"/trackers/{tracker.id}/report")
    role = db.get(TrackerRole, (logged_in_user.id, tracker.id))
    for name in ("viewer", "editor"):
        role.role = name
        db.commit()
        response = client.get(f"/trackers/{tracker.id}")
        assert response.status_code == 302
        assert response.headers["Location"].endswith(f"/trackers/{tracker.id}/report")


# --- Engine data loading -----------------------------------------------------------------------------------------


def test_load_engine_inputs_cuts_off_at_as_of_and_adds_imported(db, tracker_factory):
    tracker = tracker_factory()
    group = make_group(db, tracker, baseline=100, starting_completed=5)
    add_entry(db, tracker, group, date(2026, 9, 1), 3, date(2026, 9, 4))
    add_entry(db, tracker, group, date(2026, 9, 2), 4, date(2026, 9, 4))
    add_entry(db, tracker, group, date(2026, 9, 9), 8, date(2026, 9, 11))
    db.add(Week(tracker_id=tracker.id, week_ending=date(2026, 9, 4), target=10, imported_actual=2))
    db.commit()
    weeks, targets, actuals, groups, totals = load_engine_inputs(db, tracker, date(2026, 9, 4))
    assert weeks[0] == date(2026, 9, 4) and weeks[-1] == date(2026, 12, 25)
    assert targets[date(2026, 9, 4)] == 10
    assert actuals == {date(2026, 9, 4): 3 + 4 + 2}
    assert totals == {group.id: 7}
    assert groups[0].starting_completed == 5
    _, _, later, _, later_totals = load_engine_inputs(db, tracker, date(2026, 9, 11))
    assert later == {date(2026, 9, 4): 9, date(2026, 9, 11): 8}
    assert later_totals == {group.id: 15}


def test_tracker_summary_uses_default_report_week(db, tracker_factory):
    tracker = tracker_factory()
    group = make_group(db, tracker, baseline=100)
    add_entry(db, tracker, group, date(2026, 9, 3), 10, date(2026, 9, 4))
    add_entry(db, tracker, group, date(2026, 9, 10), 20, date(2026, 9, 11))
    # Today is Wed 9 Sep: latest week-ending passed is Fri 4 Sep; the later entry is not counted.
    headline = tracker_summary(db, tracker, date(2026, 9, 9))
    assert headline.report_week == date(2026, 9, 4)
    assert headline.completed == 10
    # Before the first week-ending: the first week is the report week.
    early = tracker_summary(db, tracker, date(2026, 9, 1))
    assert early.report_week == date(2026, 9, 4)
    assert early.completed == 0


def test_schedule_settings_saved_and_audited(client, logged_in_admin, db, tracker_factory):
    from datetime import time

    tracker = tracker_factory()
    data = {**SETTINGS, "schedule_enabled": "1", "send_time": "08:30", "send_timezone": "Europe/Zurich"}
    assert post(client, f"/trackers/{tracker.id}/settings", data).status_code == 302
    db.refresh(tracker)
    assert tracker.schedule_enabled and tracker.send_time == time(8, 30) and tracker.send_timezone == "Europe/Zurich"
    changed = next(a for a in audit_actions(db, tracker.id) if a.action == "settings_updated").detail
    assert {"schedule_enabled", "send_time", "send_timezone"} <= set(changed)


def test_schedule_settings_reject_bad_time_and_zone(client, logged_in_admin, db, tracker_factory):
    tracker = tracker_factory()
    for bad in ({"send_time": "5pm"}, {"send_timezone": "Mars/Olympus"}):
        assert post(client, f"/trackers/{tracker.id}/settings", {**SETTINGS, **bad}).status_code == 400
    db.refresh(tracker)
    assert not tracker.schedule_enabled


def test_schedule_settings_refused_when_archived(client, logged_in_admin, db, tracker_factory):
    tracker = tracker_factory(status="archived")
    post(client, f"/trackers/{tracker.id}/settings", {**SETTINGS, "schedule_enabled": "1"})
    db.refresh(tracker)
    assert not tracker.schedule_enabled
