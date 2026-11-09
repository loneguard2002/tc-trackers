"""The person in charge of a tracker: set at creation, chosen on Settings, flagged when missing (database)."""

from sqlalchemy import select

from tests.conftest import post, sign_in
from tests.test_trackers import SETTINGS
from tracker.auth.roles import lead_candidates, lead_in_charge
from tracker.models import AuditLog, Tracker


def test_the_creator_is_put_in_charge_of_a_new_tracker(client, logged_in_admin, db, labels_form):
    assert post(client, "/trackers/new", {**SETTINGS, **labels_form}).status_code == 302
    tracker = db.scalars(select(Tracker)).one()
    assert tracker.lead_user_id == logged_in_admin.id


def test_candidates_are_editors_and_owners_by_any_route(db, tracker_factory, user_factory, grant):
    tracker = tracker_factory()
    owner, editor, viewer = user_factory(full_name="Ann"), user_factory(full_name="Bob"), user_factory(full_name="Cy")
    disabled = user_factory(full_name="Dee", status="disabled")
    grant(owner, tracker, "owner")
    grant(editor, tracker, "editor")
    grant(viewer, tracker, "viewer")
    grant(disabled, tracker, "owner")
    assert [u.full_name for u in lead_candidates(db, tracker)] == ["Ann", "Bob"]
    tracker.lead_user_id = disabled.id
    assert lead_in_charge(db, tracker) is None
    tracker.lead_user_id = editor.id
    assert lead_in_charge(db, tracker) == editor


def test_settings_choose_the_person_in_charge_and_audit_it(
    client, db, tracker_factory, user_factory, grant, labels_form
):
    tracker = tracker_factory()
    owner, editor = user_factory(full_name="Ann"), user_factory(full_name="Bob")
    grant(owner, tracker, "owner")
    grant(editor, tracker, "editor")
    sign_in(client, owner)
    page = client.get(f"/trackers/{tracker.id}/settings").get_data(as_text=True)
    assert 'id="lead-missing"' in page and '<option value="' + str(editor.id) + '">Bob</option>' in page
    url = f"/trackers/{tracker.id}/settings"
    response = post(client, url, {**SETTINGS, **labels_form, "lead_user_id": str(editor.id)})
    assert response.status_code == 302
    db.refresh(tracker)
    assert tracker.lead_user_id == editor.id
    entry = db.scalars(select(AuditLog).where(AuditLog.action == "settings_updated")).one()
    assert entry.detail["lead"] == [None, "Bob"]
    assert 'id="lead-missing"' not in client.get(url).get_data(as_text=True)


def test_settings_refuse_an_empty_or_unqualified_choice_and_keep_it_when_absent(
    client, db, tracker_factory, user_factory, grant, labels_form
):
    tracker = tracker_factory()
    owner, viewer = user_factory(full_name="Ann"), user_factory(full_name="Cy")
    grant(owner, tracker, "owner")
    grant(viewer, tracker, "viewer")
    tracker.lead_user_id = owner.id
    db.commit()
    sign_in(client, owner)
    url = f"/trackers/{tracker.id}/settings"
    empty = post(client, url, {**SETTINGS, **labels_form, "lead_user_id": ""})
    assert empty.status_code == 400 and "Choose the person in charge." in empty.get_data(as_text=True)
    viewer_choice = post(client, url, {**SETTINGS, **labels_form, "lead_user_id": str(viewer.id)})
    assert viewer_choice.status_code == 400 and "Editor or Owner" in viewer_choice.get_data(as_text=True)
    assert post(client, url, {**SETTINGS, **labels_form}).status_code == 302
    db.refresh(tracker)
    assert tracker.lead_user_id == owner.id


def test_email_page_flags_a_tracker_with_nobody_in_charge(client, db, tracker_factory, user_factory, grant):
    tracker, owner = tracker_factory(), user_factory()
    grant(owner, tracker, "owner")
    sign_in(client, owner)
    assert "nobody in charge" in client.get(f"/trackers/{tracker.id}/mail").get_data(as_text=True)
    tracker.lead_user_id = owner.id
    db.commit()
    assert "nobody in charge" not in client.get(f"/trackers/{tracker.id}/mail").get_data(as_text=True)
