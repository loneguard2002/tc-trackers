"""A tracker's team, the creator becoming owner, and moving a tracker between teams (database required)."""

import html
import re
from datetime import date
from io import BytesIO

from sqlalchemy import select

from tests.conftest import post, sign_in
from tests.importer.build_fixture import workbook_bytes
from tracker.auth.guards import SELF_PROMOTION_MESSAGE
from tracker.models import AuditLog, Team, Tracker, TrackerRole

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
CHOICE_ERROR = "Choose a team from the list."


def text_of(response) -> str:
    return html.unescape(response.get_data(as_text=True))


def entries(db, action):
    db.expire_all()
    return list(db.scalars(select(AuditLog).where(AuditLog.action == action).order_by(AuditLog.id)))


def team_of(db, tracker):
    db.expire_all()
    return db.get(Tracker, tracker.id).team_id


def holder(user_factory, give_set, client):
    user = user_factory(full_name="Holder")
    give_set(["manage_teams"], user=user)
    sign_in(client, user)
    return user


def test_creator_without_admin_becomes_owner_and_it_is_logged(client, logged_in_user, give_set, db):
    give_set(["create_trackers"], user=logged_in_user)
    post(client, "/trackers/new", SETTINGS)
    tracker = db.scalars(select(Tracker)).one()
    assert db.get(TrackerRole, (logged_in_user.id, tracker.id)).role == "owner"
    entry = db.scalars(select(AuditLog).where(AuditLog.action == "role_set")).one()
    assert entry.detail == {"before": None, "after": "owner"} and entry.target_user_id == logged_in_user.id
    logged = db.scalars(select(AuditLog.action).where(AuditLog.tracker_id == tracker.id).order_by(AuditLog.id)).all()
    assert logged == ["tracker_created", "role_set"]


def test_new_tracker_in_a_team_or_none(client, logged_in_admin, team_factory, db):
    parent = team_factory(name="Infrastructure")
    child = team_factory(name="Windows", parent=parent)
    assert post(client, "/trackers/new", {**SETTINGS, "team_id": str(child.id)}).status_code == 302
    assert post(client, "/trackers/new", {**SETTINGS, "name": "Other", "team_id": ""}).status_code == 302
    first, second = db.scalars(select(Tracker).order_by(Tracker.id)).all()
    assert first.team_id == child.id and second.team_id is None
    created = entries(db, "tracker_created")
    assert created[0].detail["team"] == "Infrastructure › Windows" and created[1].detail["team"] is None
    assert 'name="team_id"' in client.get("/trackers/new").get_data(as_text=True)


def test_new_tracker_with_an_unknown_team_is_refused(client, logged_in_admin, db):
    for value in ("9999", "abc"):
        response = post(client, "/trackers/new", {**SETTINGS, "team_id": value})
        assert response.status_code == 400 and CHOICE_ERROR in text_of(response)
    assert db.scalars(select(Tracker)).first() is None


def confirm_page(client) -> str:
    return post(
        client,
        "/import",
        {"weekday": "4", "workbook": (BytesIO(workbook_bytes()), "book.xlsx")},
        content_type="multipart/form-data",
    ).get_data(as_text=True)


def test_import_confirmation_sets_team_and_owner(client, user_factory, give_set, team_factory, db):
    team = team_factory(name="Network")
    user = user_factory()
    give_set(["import_workbooks"], user=user)
    sign_in(client, user)

    def confirm(**extra):
        page = post(
            client,
            "/import",
            {"weekday": "4", "workbook": (BytesIO(workbook_bytes()), "book.xlsx")},
            content_type="multipart/form-data",
        )
        token = page.get_data(as_text=True).split('name="payload" value="')[1].split('"')[0]
        return post(client, "/import/confirm", {"payload": token, "name": "Rollout", **extra})

    page = html.unescape(confirm_page(client))
    assert 'name="team_id"' in page and "You become its owner." in page and "As an administrator" not in page
    assert confirm(team_id=str(team.id)).status_code == 302
    tracker = db.scalars(select(Tracker)).one()
    assert tracker.team_id == team.id and db.get(TrackerRole, (user.id, tracker.id)).role == "owner"
    logged = db.scalars(select(AuditLog.action).where(AuditLog.tracker_id == tracker.id).order_by(AuditLog.id)).all()
    assert logged == ["tracker_imported", "role_set"]
    bad = confirm(team_id="9999")
    assert bad.status_code == 400 and CHOICE_ERROR in text_of(bad)
    assert db.scalars(select(Tracker)).all() == [tracker]


def test_import_confirmation_by_an_administrator_gives_no_role(client, logged_in_admin, db):
    page = post(
        client,
        "/import",
        {"weekday": "4", "workbook": (BytesIO(workbook_bytes()), "book.xlsx")},
        content_type="multipart/form-data",
    )
    assert "As an administrator, you can already open every tracker." in text_of(page)
    assert "You become its owner." not in text_of(page)
    token = page.get_data(as_text=True).split('name="payload" value="')[1].split('"')[0]
    assert post(client, "/import/confirm", {"payload": token, "name": "Rollout"}).status_code == 302
    tracker = db.scalars(select(Tracker)).one()
    assert db.get(TrackerRole, (logged_in_admin.id, tracker.id)) is None


def test_set_team_requires_manage_teams(client, logged_in_user, tracker_factory, team_factory, grant, db):
    tracker = tracker_factory()
    grant(logged_in_user, tracker, "owner")
    team = team_factory()
    response = post(client, f"/trackers/{tracker.id}/team", {"team_id": str(team.id), "next": "settings"})
    assert response.status_code == 403 and team_of(db, tracker) is None


def test_set_team_for_a_missing_tracker_is_404(client, logged_in_admin):
    assert post(client, "/trackers/9999/team", {"team_id": ""}).status_code == 404


def test_set_team_logs_before_and_after_and_works_when_archived(
    client, logged_in_admin, tracker_factory, team_factory, db
):
    windows = team_factory(name="Windows", parent=team_factory(name="Infrastructure"))
    network = team_factory(name="Network")
    tracker = tracker_factory(team_id=windows.id, status="archived")
    response = post(client, f"/trackers/{tracker.id}/team", {"team_id": str(network.id), "next": "settings"})
    assert response.status_code == 302 and response.headers["Location"].endswith(f"/trackers/{tracker.id}/settings")
    assert team_of(db, tracker) == network.id
    entry = entries(db, "tracker_team_changed")[0]
    assert entry.detail == {"before": "Infrastructure › Windows", "after": "Network"} and entry.tracker_id == tracker.id
    post(client, f"/trackers/{tracker.id}/team", {"team_id": "", "next": "access"})
    assert team_of(db, tracker) is None
    assert entries(db, "tracker_team_changed")[1].detail == {"before": "Network", "after": None}


def test_set_team_with_an_unknown_team_changes_nothing(client, logged_in_admin, tracker_factory, db):
    tracker = tracker_factory()
    for value in ("9999", "abc"):
        response = post(client, f"/trackers/{tracker.id}/team", {"team_id": value, "next": "settings"})
        assert response.status_code == 400
    assert team_of(db, tracker) is None and not entries(db, "tracker_team_changed")


def test_set_team_to_the_same_team_writes_nothing(client, logged_in_admin, tracker_factory, team_factory, db):
    team = team_factory()
    tracker = tracker_factory(team_id=team.id)
    response = post(client, f"/trackers/{tracker.id}/team", {"team_id": str(team.id), "next": "settings"})
    assert response.status_code == 302
    assert not entries(db, "tracker_team_changed")


def test_holder_cannot_move_a_tracker_into_their_own_team(
    client, user_factory, give_set, tracker_factory, team_factory, add_member, db
):
    user = holder(user_factory, give_set, client)
    mine = team_factory(name="Mine")
    add_member(mine, user, "owner")
    tracker = tracker_factory()
    response = post(client, f"/trackers/{tracker.id}/team", {"team_id": str(mine.id), "next": "access"})
    assert response.status_code == 302
    assert SELF_PROMOTION_MESSAGE in text_of(client.get("/"))
    assert team_of(db, tracker) is None and not entries(db, "tracker_team_changed")


def test_holder_moving_a_tracker_that_does_not_raise_their_access_is_allowed(
    client, user_factory, give_set, tracker_factory, team_factory, add_member, db
):
    user = holder(user_factory, give_set, client)
    mine, other = team_factory(name="Mine"), team_factory(name="Other")
    add_member(mine, user, "owner")
    tracker = tracker_factory(team_id=mine.id)
    response = post(client, f"/trackers/{tracker.id}/team", {"team_id": str(other.id), "next": "access"})
    assert response.status_code == 302 and team_of(db, tracker) == other.id


def test_settings_team_section_only_for_team_managers(
    client, user_factory, give_set, tracker_factory, team_factory, grant, db
):
    team = team_factory(name="Network")
    tracker = tracker_factory(team_id=team.id)
    owner = user_factory()
    grant(owner, tracker, "owner")
    sign_in(client, owner)
    page = client.get(f"/trackers/{tracker.id}/settings").get_data(as_text=True)
    assert 'id="team"' not in page and 'href="#team"' not in page
    give_set(["manage_teams"], user=owner)
    page = client.get(f"/trackers/{tracker.id}/settings").get_data(as_text=True)
    assert 'id="team"' in page and 'href="#team"' in page and 'name="team_id"' in page and "data-confirm-source" in page
    plain = re.sub(r"<[^>]+>", "", html.unescape(page))
    assert "Move Test tracker from Network to" in plain
    assert "People's access to this tracker will change." in plain
    assert "data-confirm=\"Move Test tracker to the chosen team? People's access" in html.unescape(page)


def test_settings_team_section_for_an_administrator(client, logged_in_admin, tracker_factory):
    tracker = tracker_factory()
    page = client.get(f"/trackers/{tracker.id}/settings").get_data(as_text=True)
    assert 'id="team"' in page and 'href="#team"' in page and "No team" in page


def test_home_card_shows_the_team_name(client, logged_in_admin, tracker_factory, team_factory):
    team = team_factory(name="Network")
    tracker_factory(name="With team", team_id=team.id, first_week_ending=date(2026, 9, 4))
    assert '<p class="tracker-card-team">Network</p>' in client.get("/").get_data(as_text=True)


# --- Final review fixes ---------------------------------------------------------------------------------------------


def test_a_very_long_team_id_is_400(client, logged_in_admin, tracker_factory, db):
    response = post(client, "/trackers/new", {**SETTINGS, "team_id": "9" * 5000})
    assert response.status_code == 400 and CHOICE_ERROR in text_of(response)
    t = tracker_factory()
    assert post(client, f"/trackers/{t.id}/team", {"team_id": "9" * 5000}).status_code == 400
    assert db.scalars(select(Tracker)).all() == [t] and entries(db, "tracker_team_changed") == []


def delete_team_on_first_read(monkeypatch, module, db, team):
    """Delete ``team`` from another session the first time the view reads the team tree."""
    original = module.load_team_rows

    def delete_first(session, lock=False):
        if db.get(Team, team.id) is not None:
            db.delete(db.get(Team, team.id))
            db.commit()
        return original(session, lock)

    monkeypatch.setattr(module, "load_team_rows", delete_first)


def test_a_tracker_created_in_a_team_deleted_at_the_same_moment(client, logged_in_admin, team_factory, db, monkeypatch):
    from tracker.trackers import views as tracker_views

    team = team_factory(name="Going")
    delete_team_on_first_read(monkeypatch, tracker_views, db, team)
    response = post(client, "/trackers/new", {**SETTINGS, "team_id": str(team.id)})
    assert response.status_code == 400 and CHOICE_ERROR in text_of(response)
    assert db.scalars(select(Tracker)).first() is None and entries(db, "tracker_created") == []


def test_a_tracker_moved_into_a_team_deleted_at_the_same_moment(
    client, logged_in_admin, team_factory, tracker_factory, db, monkeypatch
):
    from tracker.trackers import views as tracker_views

    team, t = team_factory(name="Going"), tracker_factory()
    delete_team_on_first_read(monkeypatch, tracker_views, db, team)
    response = post(client, f"/trackers/{t.id}/team", {"team_id": str(team.id)}, follow_redirects=True)
    assert response.status_code == 200 and CHOICE_ERROR in text_of(response)
    assert team_of(db, t) is None and entries(db, "tracker_team_changed") == []


def test_a_workbook_imported_into_a_team_deleted_at_the_same_moment(
    client, logged_in_admin, team_factory, db, monkeypatch
):
    from tracker.importer import views as importer_views

    team = team_factory(name="Going")
    page = post(
        client,
        "/import",
        {"weekday": "4", "workbook": (BytesIO(workbook_bytes()), "book.xlsx")},
        content_type="multipart/form-data",
    )
    token = page.get_data(as_text=True).split('name="payload" value="')[1].split('"')[0]
    original = importer_views.parse_team_id

    def delete_after_parsing(session, value):
        found = original(session, value)
        db.delete(db.get(Team, team.id))
        db.commit()
        return found

    monkeypatch.setattr(importer_views, "parse_team_id", delete_after_parsing)
    response = post(client, "/import/confirm", {"payload": token, "name": "Rollout", "team_id": str(team.id)})
    assert response.status_code == 400 and CHOICE_ERROR in text_of(response)
    assert db.scalars(select(Tracker)).first() is None
