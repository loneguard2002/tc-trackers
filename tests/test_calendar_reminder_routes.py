"""The calendar reminder switch on the Weekly update tab (database required)."""

from __future__ import annotations

import re
from datetime import datetime, timezone

import pytest
from conftest import post, sign_in

from tracker.formatting import fmt_date
from tracker.mail import smtp
from tracker.models import CalendarReminder

EMAIL = "person@example.com"
COPY = "Remind me at 08:45 on each week-ending day"


@pytest.fixture
def mail(monkeypatch):
    sent: list = []
    monkeypatch.setattr(smtp, "send_message", sent.append)
    return sent


@pytest.fixture
def setup(client, db, tracker_factory, user_factory, grant):
    tracker = tracker_factory(name="Fit-out")
    person = user_factory(email=EMAIL)
    grant(person, tracker, "editor")
    sign_in(client, person)
    return tracker, person


def url(tracker, suffix="") -> str:
    return f"/trackers/{tracker.id}/calendar-reminder{suffix}"


def page_text(client, tracker) -> str:
    return client.get(f"/trackers/{tracker.id}/inputs").get_data(as_text=True)


def method_of(msg) -> str:
    for part in msg.walk():
        if part.get_content_type() == "text/calendar":
            return re.search(r"^METHOD:(.*)$", part.get_content(), flags=re.M).group(1).strip()
    raise AssertionError("no calendar part")


def ics_field(msg, name: str) -> str:
    for part in msg.walk():
        if part.get_content_type() == "text/calendar":
            return re.search(rf"^{name}:(.*)$", part.get_content(), flags=re.M).group(1).strip()
    raise AssertionError("no calendar part")


def flashes(client) -> list[str]:
    with client.session_transaction() as sess:
        return [message for _, message in sess.get("_flashes", [])]


def test_an_editor_sees_the_panel_with_the_switch_off(client, setup):
    tracker, _ = setup
    html = page_text(client, tracker)
    assert COPY in html
    assert 'name="enabled"' in html
    assert re.search(r'name="enabled"[^>]*checked', html) is None
    assert "Send it again" not in html


def test_a_viewer_cannot_reach_either_route(client, db, setup, user_factory, grant):
    tracker, _ = setup
    viewer = user_factory()
    grant(viewer, tracker, "viewer")
    sign_in(client, viewer)
    assert client.get(f"/trackers/{tracker.id}/inputs").status_code == 404
    assert post(client, url(tracker), {"enabled": "on"}).status_code == 404
    assert post(client, url(tracker, "/resend")).status_code == 404
    assert db.get(CalendarReminder, (viewer.id, tracker.id)) is None


def test_an_unknown_tracker_is_404(client, setup):
    assert post(client, "/trackers/999999/calendar-reminder", {"enabled": "on"}).status_code == 404
    assert post(client, "/trackers/999999/calendar-reminder/resend").status_code == 404


def test_switching_on_sends_one_request_and_the_panel_reports_it(client, db, setup, mail):
    tracker, person = setup
    response = post(client, url(tracker), {"enabled": "on"})
    assert response.status_code == 302
    assert response.headers["Location"].endswith(f"/trackers/{tracker.id}/inputs")
    assert len(mail) == 1 and method_of(mail[0]) == "REQUEST"
    assert flashes(client) == [f"Calendar reminder sent to {EMAIL}."]
    html = page_text(client, tracker)
    today = fmt_date(datetime.now(timezone.utc).date())
    assert f"Sent to {EMAIL} on {today}." in html
    assert "Send it again" in html
    assert re.search(r'name="enabled"[^>]*checked', html)


def test_the_week_is_kept_on_the_redirect(client, setup, mail):
    tracker, _ = setup
    response = post(client, url(tracker), {"enabled": "on", "week": "2026-09-11"})
    assert response.headers["Location"].endswith(f"/trackers/{tracker.id}/inputs?week=2026-09-11")
    response = post(client, url(tracker), {"enabled": "on", "week": "rubbish"})
    assert response.headers["Location"].endswith(f"/trackers/{tracker.id}/inputs")


def test_switching_off_sends_one_cancellation(client, db, setup, mail):
    tracker, person = setup
    post(client, url(tracker), {"enabled": "on"})
    client.get(f"/trackers/{tracker.id}/inputs")  # consume the flash
    post(client, url(tracker), {})
    assert [method_of(m) for m in mail] == ["REQUEST", "CANCEL"]
    assert flashes(client)[-1] == f"Calendar reminder switched off. A cancellation was sent to {EMAIL}."
    db.expire_all()
    assert db.get(CalendarReminder, (person.id, tracker.id)).enabled is False
    assert "Send it again" not in page_text(client, tracker)


def test_switching_off_a_reminder_that_was_never_sent_sends_nothing(client, setup, mail):
    tracker, _ = setup
    post(client, url(tracker), {})
    assert mail == []
    assert flashes(client) == ["Calendar reminder is off."]


def test_send_it_again_sends_an_update_with_the_same_uid(client, setup, mail):
    tracker, _ = setup
    post(client, url(tracker), {"enabled": "on"})
    client.get(f"/trackers/{tracker.id}/inputs")
    response = post(client, url(tracker, "/resend"), {"week": "2026-09-11"})
    assert response.headers["Location"].endswith("?week=2026-09-11")
    assert len(mail) == 2
    assert ics_field(mail[1], "UID") == ics_field(mail[0], "UID")
    assert int(ics_field(mail[1], "SEQUENCE")) > int(ics_field(mail[0], "SEQUENCE"))
    assert flashes(client) == [f"Calendar reminder sent again to {EMAIL}."]


def test_send_it_again_without_the_switch_on_sends_nothing(client, setup, mail):
    tracker, _ = setup
    post(client, url(tracker, "/resend"))
    assert mail == []
    assert flashes(client) == ["Switch the calendar reminder on first."]


def test_a_failed_delivery_keeps_the_switch_and_says_so(client, db, setup, monkeypatch):
    tracker, person = setup

    def boom(_msg):
        raise OSError("no route")

    monkeypatch.setattr(smtp, "send_message", boom)
    post(client, url(tracker), {"enabled": "on"})
    assert flashes(client) == ["The calendar reminder could not be sent now. It will be tried again shortly."]
    db.expire_all()
    row = db.get(CalendarReminder, (person.id, tracker.id))
    assert row.enabled is True and row.sent_state == "none"
    html = page_text(client, tracker)
    assert "Not sent yet" in html
    assert re.search(r'name="enabled"[^>]*checked', html)


def test_an_archived_tracker_shows_no_switch_and_refuses_changes(client, db, setup, mail):
    tracker, person = setup
    tracker.status = "archived"
    db.commit()
    html = page_text(client, tracker)
    assert 'name="enabled"' not in html
    post(client, url(tracker), {"enabled": "on"})
    assert mail == []
    assert db.get(CalendarReminder, (person.id, tracker.id)) is None


def test_a_lost_first_insert_race_reads_the_winners_row(client, db, setup, monkeypatch):
    from tracker.entries.views import _reminder_row

    tracker, person = setup
    db.add(CalendarReminder(user_id=person.id, tracker_id=tracker.id, enabled=True))
    db.commit()
    real_get = db.get
    calls = []

    def blind_first(model, key, *a, **kw):
        calls.append(key)
        return None if len(calls) == 1 else real_get(model, key, *a, **kw)

    monkeypatch.setattr(db, "get", blind_first)
    row = _reminder_row(db, person.id, tracker.id)
    assert row is not None and row.enabled is True
