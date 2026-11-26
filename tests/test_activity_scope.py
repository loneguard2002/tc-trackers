"""Activity shows each person only the entries for what they manage (the owner's rule, 26 Nov 2026) (database)."""

from __future__ import annotations

import re
from datetime import date

import pytest

from tracker.activity.labels import ACTION_LABELS
from tracker.activity.scope import ACTION_AREAS
from tracker.models import AuditLog


def test_every_action_belongs_to_an_area():
    assert set(ACTION_AREAS) == set(ACTION_LABELS)


@pytest.fixture
def log(db, tracker_factory, user_factory):
    """Two trackers, another person, and one entry of each kind the scope tells apart."""
    mine = tracker_factory(name="Mine", first_week_ending=date(2026, 9, 4), last_week_ending=date(2026, 12, 25))
    theirs = tracker_factory(name="Theirs", first_week_ending=date(2026, 9, 4), last_week_ending=date(2026, 12, 25))
    other = user_factory(full_name="Other Person")
    rows = {
        "entry_mine": AuditLog(
            user_id=other.id, tracker_id=mine.id, action="entry_created", entity="entry", entity_id="1"
        ),
        "entry_theirs": AuditLog(
            user_id=other.id, tracker_id=theirs.id, action="entry_created", entity="entry", entity_id="2"
        ),
        "role_theirs": AuditLog(
            user_id=other.id, tracker_id=theirs.id, action="role_set", entity="tracker", entity_id="3"
        ),
        "user_created": AuditLog(user_id=other.id, action="user_created", entity="user", entity_id="4"),
        "team_created": AuditLog(user_id=other.id, action="team_created", entity="team", entity_id="5"),
        "set_created": AuditLog(
            user_id=other.id, action="permission_set_created", entity="permission_set", entity_id="6"
        ),
    }
    db.add_all(rows.values())
    db.commit()
    return mine, theirs, rows


def shown_ids(client) -> set[str]:
    html = client.get("/admin/activity?size=100").get_data(as_text=True)
    return set(re.findall(r'data-entry="(\d+)"', html))


def ids(rows, *names) -> set[str]:
    return {str(rows[name].id) for name in names}


def test_a_viewer_sees_their_trackers_and_their_own_actions_only(client, db, logged_in_user, give_set, grant, log):
    mine, _theirs, rows = log
    give_set(["view_activity"], user=logged_in_user)
    grant(logged_in_user, mine, "viewer")
    own = AuditLog(user_id=logged_in_user.id, action="login", entity="user", entity_id=str(logged_in_user.id))
    db.add(own)
    db.commit()
    seen = shown_ids(client)
    assert ids(rows, "entry_mine") <= seen and str(own.id) in seen
    assert not seen & ids(rows, "entry_theirs", "role_theirs", "user_created", "team_created", "set_created")


@pytest.mark.parametrize(
    ("permission", "expected"),
    [("manage_users", "user_created"), ("manage_teams", "team_created")],
)
def test_each_area_shows_to_those_who_manage_it(client, logged_in_user, give_set, log, permission, expected):
    _mine, _theirs, rows = log
    give_set(["view_activity", permission], user=logged_in_user)
    seen = shown_ids(client)
    assert ids(rows, expected) <= seen
    assert not seen & ids(rows, "set_created", "entry_theirs")


def test_role_changes_show_only_to_the_trackers_own_people(client, logged_in_user, give_set, grant, log):
    _mine, theirs, rows = log
    give_set(["view_activity", "manage_teams"], user=logged_in_user)  # hands out roles, but has none on Theirs
    assert str(rows["role_theirs"].id) not in shown_ids(client)
    grant(logged_in_user, theirs, "viewer")
    assert str(rows["role_theirs"].id) in shown_ids(client)


def test_their_own_action_on_a_tracker_they_cannot_open_shows_without_its_details(
    client, db, logged_in_user, give_set, log
):
    _mine, theirs, _rows = log
    give_set(["view_activity"], user=logged_in_user)
    own = AuditLog(user_id=logged_in_user.id, tracker_id=theirs.id, action="role_set", entity="tracker", entity_id="7")
    db.add(own)
    db.commit()
    html = client.get("/admin/activity?size=100").get_data(as_text=True)
    assert str(own.id) in set(re.findall(r'data-entry="(\d+)"', html))
    assert "Details hidden: you cannot open this tracker." in html


def test_administrators_see_everything(client, logged_in_admin, log):
    _mine, _theirs, rows = log
    assert ids(rows, *rows) <= shown_ids(client)


def test_the_counts_and_the_action_filter_follow_the_scope(client, db, logged_in_user, give_set, grant, log):
    mine, _theirs, _rows = log
    give_set(["view_activity"], user=logged_in_user)
    grant(logged_in_user, mine, "viewer")
    html = client.get("/admin/activity").get_data(as_text=True)
    assert "Showing 1 of 1 entry" in html  # the one entry about Mine
    options = set(re.findall(r'<option value="([a-z_]+)"', html))
    assert "entry_created" in options and "permission_set_created" not in options and "user_created" not in options


def test_the_person_filter_names_only_people_in_entries_the_viewer_may_see(
    client, db, logged_in_user, give_set, grant, log, user_factory
):
    mine, _theirs, _rows = log
    stranger = user_factory(full_name="Hidden Stranger")
    db.add(AuditLog(user_id=stranger.id, action="team_created", entity="team", entity_id="9"))
    db.commit()
    give_set(["view_activity"], user=logged_in_user)
    grant(logged_in_user, mine, "viewer")
    html = client.get("/admin/activity").get_data(as_text=True)
    assert "Other Person (" in html  # recorded an entry on their tracker
    assert "Hidden Stranger" not in html
