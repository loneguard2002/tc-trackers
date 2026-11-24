"""The calendar reminder switch on the Weekly update tab (database required)."""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from conftest import post, sign_in

from tracker.calendar_invites import service
from tracker.mail import smtp
from tracker.models import CalendarReminder

EMAIL = "person@example.com"
COPY = "Email me an Outlook reminder"


@pytest.fixture(autouse=True)
def email_set_up(monkeypatch):
    monkeypatch.setattr(
        smtp, "get_smtp_config", lambda session=None: {"host": "smtp.example.com", "from_": "reports@example.com"}
    )


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
    assert COPY in html and "08:45 on each week-ending day" in html
    assert 'name="enabled"' in html
    assert re.search(r'name="enabled"[^>]*checked', html) is None
    assert "Email it again" not in html
    # The card sits beside the Commentary card (it covers every week), after the week bar.
    assert 'role="switch"' not in html
    assert html.index("week-bar") < html.index("data-inputs-form") < html.index("data-reminder-form")
    assert "week-picker" not in html and 'class="reminder-line"' not in html


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
    today = datetime.now(timezone.utc).date()
    assert f"Last sent: {today.day} {today:%b %Y}" in html
    assert "Email it again" in html
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
    assert "Email it again" not in page_text(client, tracker)


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


NOT_SET_UP = "Email is not set up in this application yet. The reminder will be sent once it is."


def test_without_email_set_up_the_switch_saves_and_says_so(client, db, setup, mail, monkeypatch):
    tracker, person = setup
    monkeypatch.setattr(smtp, "get_smtp_config", lambda session=None: {"host": "smtp.example.com", "from_": ""})
    post(client, url(tracker), {"enabled": "on"})
    assert flashes(client) == [NOT_SET_UP]
    assert mail == []
    db.expire_all()
    row = db.get(CalendarReminder, (person.id, tracker.id))
    assert row.enabled is True and row.last_error is None
    html = page_text(client, tracker)
    assert "Email is not set up in this application yet" in html and "Not sent yet" not in html


def test_the_sent_date_is_the_trackers_local_date(client, db, setup, mail):
    tracker, person = setup
    tracker.send_timezone = "Pacific/Auckland"
    db.commit()
    post(client, url(tracker), {"enabled": "on"})
    row = db.get(CalendarReminder, (person.id, tracker.id))
    row.sent_at = datetime(2026, 10, 1, 12, 30, tzinfo=timezone.utc)  # 01:30 on 2 October in Auckland (UTC+13)
    db.commit()
    assert "Last sent: 2 Oct 2026" in page_text(client, tracker)


def event_list(db, tracker, person):
    db.expire_all()
    return [(e.kind, e.detail) for e in reversed(service.events_for(db, person.id, tracker.id))]


def test_switching_on_and_off_records_events_by_you(client, db, setup, mail):
    tracker, person = setup
    post(client, url(tracker), {"enabled": "on"})
    post(client, url(tracker), {})
    kinds = [kind for kind, _ in event_list(db, tracker, person)]
    assert kinds[0] == "switched_on" and "switched_off" in kinds
    assert dict(event_list(db, tracker, person))["switched_on"] == "By you"
    assert dict(event_list(db, tracker, person))["switched_off"] == "By you"


def ics_url(tracker) -> str:
    return f"/trackers/{tracker.id}/calendar-reminder.ics"


def test_an_editor_downloads_the_calendar_file(client, db, setup, mail):
    tracker, person = setup
    tracker.name = "Laptop refresh!/"
    db.commit()
    post(client, url(tracker), {"enabled": "on"})
    response = client.get(ics_url(tracker))
    assert response.status_code == 200
    assert response.headers["Content-Type"].startswith("text/calendar")
    assert response.headers["Content-Disposition"] == 'attachment; filename="Laptop refresh reminder.ics"'
    body = response.get_data(as_text=True)
    assert "METHOD:PUBLISH" in body and "ATTENDEE" not in body
    assert "ORGANIZER:mailto:reports@example.com" in body
    assert "SEQUENCE:0" in body
    assert re.search(r"^UID:(.*)$", body, flags=re.M).group(1).strip() == ics_field(mail[0], "UID")
    assert event_list(db, tracker, person)[-1] == ("downloaded", "Laptop refresh reminder.ics")


def test_the_download_uses_the_current_sequence_once_a_series_was_sent(client, db, setup, mail):
    tracker, _ = setup
    post(client, url(tracker), {"enabled": "on"})
    post(client, url(tracker, "/resend"))
    assert "SEQUENCE:1" in client.get(ics_url(tracker)).get_data(as_text=True)


def test_the_download_works_without_email_set_up(client, db, setup, monkeypatch):
    tracker, person = setup
    monkeypatch.setattr(smtp, "get_smtp_config", lambda session=None: {})
    response = client.get(ics_url(tracker))
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert f"ORGANIZER:mailto:{EMAIL}" in body and "SEQUENCE:0" in body
    assert [kind for kind, _ in event_list(db, tracker, person)] == ["downloaded"]


def test_a_viewer_cannot_download(client, db, setup, user_factory, grant):
    tracker, _ = setup
    viewer = user_factory()
    grant(viewer, tracker, "viewer")
    sign_in(client, viewer)
    assert client.get(ics_url(tracker)).status_code == 404
    assert service.events_for(db, viewer.id, tracker.id) == []


def test_an_archived_tracker_refuses_the_download(client, db, setup):
    tracker, person = setup
    tracker.status = "archived"
    db.commit()
    response = client.get(ics_url(tracker))
    assert response.status_code == 302
    assert event_list(db, tracker, person) == []


def test_accented_letters_are_transliterated_in_the_file_name(client, db, setup):
    tracker, _ = setup
    tracker.name = "Évaluation Zoë"
    db.commit()
    response = client.get(ics_url(tracker))
    assert response.headers["Content-Disposition"] == 'attachment; filename="Evaluation Zoe reminder.ics"'


def test_a_name_that_sanitises_to_nothing_gives_a_bare_file_name(client, db, setup):
    tracker, _ = setup
    tracker.name = "!!!/"
    db.commit()
    response = client.get(ics_url(tracker))
    assert response.headers["Content-Disposition"] == 'attachment; filename="reminder.ics"'


def test_a_first_off_submit_on_a_new_row_records_nothing(client, db, setup, mail):
    tracker, person = setup
    post(client, url(tracker), {})
    assert event_list(db, tracker, person) == []


def test_letters_without_a_decomposition_are_mapped_in_the_file_name(client, db, setup):
    tracker, _ = setup
    tracker.name = "Straße Ø"
    db.commit()
    response = client.get(ics_url(tracker))
    assert response.headers["Content-Disposition"] == 'attachment; filename="Strasse O reminder.ics"'


def history_url(tracker, panel=False) -> str:
    return url(tracker, "/history/panel" if panel else "/history")


def next_friday(tracker) -> date:
    today = datetime.now(ZoneInfo(tracker.send_timezone)).date()
    return today + timedelta(days=(4 - today.weekday()) % 7)


def row_attributes(html: str) -> list[dict]:
    return [dict(re.findall(r'(data-[a-z-]+)="([^"]*)"', tag)) for tag in re.findall(r"<tr data-status[^>]*>", html)]


def test_a_viewer_cannot_reach_either_history_route(client, db, setup, user_factory, grant):
    tracker, _ = setup
    viewer = user_factory()
    grant(viewer, tracker, "viewer")
    sign_in(client, viewer)
    assert client.get(history_url(tracker)).status_code == 404
    assert client.get(history_url(tracker, panel=True)).status_code == 404


def test_an_archived_tracker_refuses_the_history(client, db, setup):
    tracker, _ = setup
    tracker.status = "archived"
    db.commit()
    assert client.get(history_url(tracker)).status_code == 302
    assert client.get(history_url(tracker, panel=True)).status_code == 302


def test_the_panel_lists_only_the_persons_own_events_newest_first(client, db, setup, mail, user_factory, grant):
    tracker, person = setup
    other = user_factory()
    grant(other, tracker, "editor")
    service.record_event(db, other.id, tracker.id, "failed", "Somebody else's trouble")
    db.commit()
    post(client, url(tracker), {"enabled": "on"})
    post(client, url(tracker, "/resend"))
    client.get(ics_url(tracker))
    html = client.get(history_url(tracker, panel=True)).get_data(as_text=True)
    assert "Somebody else" not in html
    assert "<html" not in html and "data-panel-history" in html
    rows = row_attributes(html)
    assert [r["data-sort-what"] for r in rows] == ["Downloaded", "Update sent", "Invite sent", "Switched on"]
    assert [r["data-status"] for r in rows] == ["download", "sent", "sent", "change"]
    assert all(re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{12}", r["data-sort-when"]) for r in rows)
    assert rows[0]["data-search"] == "downloaded fit-out reminder.ics"
    assert re.search(r"<td>\d{1,2} [A-Z][a-z]{2} \d{4}, \d\d:\d\d</td>", html)
    assert 'aria-sort="ascending"' not in html and "data-sort-default" not in html


def test_the_panel_table_keeps_out_of_the_address_and_the_page_does_not(client, setup, mail):
    tracker, _ = setup
    post(client, url(tracker), {"enabled": "on"})
    panel = client.get(history_url(tracker, panel=True)).get_data(as_text=True)
    assert "data-no-address" in panel and 'data-state-prefix="history-"' in panel
    page = client.get(history_url(tracker)).get_data(as_text=True)
    assert "data-no-address" not in page and "Switch the reminder off" not in page
    assert "<html" in page and 'id="history-table"' in page


def test_the_panel_has_chips_with_counts_and_a_footer(client, db, setup, mail):
    tracker, person = setup
    post(client, url(tracker), {"enabled": "on"})
    service.record_event(db, person.id, tracker.id, "failed", "Mail host refused")
    db.commit()
    client.get(ics_url(tracker))
    html = client.get(history_url(tracker, panel=True)).get_data(as_text=True)
    chips = re.findall(r'data-status="(\w+)" aria-pressed="\w+">(\w+) <span class="chip-count"[^>]*>(\d+)', html)
    assert chips == [
        ("all", "All", "4"),
        ("sent", "Sent", "1"),
        ("failed", "Failed", "1"),
        ("download", "Downloads", "1"),
    ]
    assert "Showing 4 of 4 events" in html
    assert "No events match." in html and "Clear filters" in html


def test_the_footer_says_event_for_one(client, db, setup):
    tracker, person = setup
    service.record_event(db, person.id, tracker.id, "downloaded", "Fit-out reminder.ics")
    db.commit()
    html = client.get(history_url(tracker, panel=True)).get_data(as_text=True)
    assert "Showing 1 of 1 event" in html and "Showing 1 of 1 events" not in html


def summary_of(html: str) -> str:
    return re.sub(r"\s+", " ", re.search(r'<p class="history-state">(.*?)</p>', html, flags=re.S).group(1))


def test_the_summary_follows_the_reminder(client, db, setup, mail):
    tracker, person = setup
    off = client.get(history_url(tracker, panel=True)).get_data(as_text=True)
    assert "<strong>Off</strong>" in summary_of(off) and "Next:" not in off
    assert "Nothing has happened to this reminder yet." in off
    post(client, url(tracker), {"enabled": "on"})
    on = client.get(history_url(tracker, panel=True)).get_data(as_text=True)
    assert "On \u00b7 up to date" in summary_of(on)
    assert "Fridays, 08:45 to 09:00" in on


def test_the_summary_says_not_sent_yet_without_email(client, db, setup, monkeypatch):
    tracker, _ = setup
    monkeypatch.setattr(smtp, "get_smtp_config", lambda session=None: {})
    post(client, url(tracker), {"enabled": "on"})
    html = client.get(history_url(tracker, panel=True)).get_data(as_text=True)
    assert "On \u00b7 not sent yet" in summary_of(html)


def test_the_summary_names_the_next_week_ending_and_none_after_the_last(client, db, setup, mail):
    tracker, _ = setup
    friday = next_friday(tracker)
    tracker.first_week_ending, tracker.last_week_ending = friday - timedelta(days=14), friday + timedelta(days=14)
    db.commit()
    post(client, url(tracker), {"enabled": "on"})
    html = client.get(history_url(tracker, panel=True)).get_data(as_text=True)
    assert f"Next: Fri {friday.day} {friday:%b %Y}" in html
    tracker.first_week_ending, tracker.last_week_ending = friday - timedelta(days=28), friday - timedelta(days=7)
    db.commit()
    assert "Next:" not in client.get(history_url(tracker, panel=True)).get_data(as_text=True)


def test_the_inputs_page_links_to_the_history(client, setup):
    tracker, _ = setup
    html = page_text(client, tracker)
    week = re.search(r'name="week" value="([\d-]+)"', html).group(1)
    assert (
        f'href="{history_url(tracker)}?week={week}" data-history-url="{history_url(tracker, panel=True)}?week={week}"'
        in html
    )
    assert 'id="history-panel"' in html and "reminder-history.js" in html and "lists.js" in html


def test_a_sent_series_with_an_update_waiting_says_so(client, db, setup, mail):
    tracker, _ = setup
    post(client, url(tracker), {"enabled": "on"})
    assert "On · up to date" in summary_of(client.get(history_url(tracker, panel=True)).get_data(as_text=True))
    tracker.last_week_ending = tracker.last_week_ending - timedelta(days=7)
    db.commit()
    html = client.get(history_url(tracker, panel=True)).get_data(as_text=True)
    assert "On · update not sent yet" in summary_of(html)
    assert "not sent yet" in summary_of(html) and "On · not sent yet" not in summary_of(html)


def card_of(html: str) -> str:
    return html[
        html.index('class="settings-section reminder-card"') : html.index("</section>", html.index("reminder-card"))
    ]


def test_the_card_shows_off_and_nothing_under_the_switch(client, setup):
    tracker, _ = setup
    card = card_of(page_text(client, tracker))
    assert re.search(r'badge-muted">Off</span>', card)
    assert "Next:" not in card and "Last sent:" not in card and "Not sent yet" not in card
    assert f'href="/trackers/{tracker.id}/calendar-reminder.ics"' in card and "Download .ics" in card
    assert "Email it again" not in card
    assert "data-history-url" in card and ">History</a>" in card
    assert "Save your weekly update first." in card and "data-reminder-guard" in card


def test_the_card_shows_on_next_and_last_sent(client, db, setup, mail):
    tracker, _ = setup
    friday = date.today()
    while friday.weekday() != 4:
        friday += timedelta(days=1)
    tracker.first_week_ending, tracker.last_week_ending = friday - timedelta(days=14), friday + timedelta(days=14)
    db.commit()
    post(client, url(tracker), {"enabled": "on"})
    card = card_of(page_text(client, tracker))
    assert re.search(r'badge-success">On</span>', card)
    assert f"Next: Fri {friday.day} {friday:%b}, 08:45" in card
    today = datetime.now(timezone.utc).date()
    assert f"Last sent: {today.day} {today:%b %Y}" in card
    assert "Email it again" in card


def test_the_card_says_when_email_is_not_set_up(client, setup, mail, monkeypatch):
    tracker, _ = setup
    monkeypatch.setattr(smtp, "get_smtp_config", lambda session=None: {})
    post(client, url(tracker), {"enabled": "on"})
    card = card_of(page_text(client, tracker))
    assert "Email is not set up in this application yet" in card and "Last sent:" not in card


def test_the_card_names_no_next_date_after_the_last_week(client, db, setup, mail):
    tracker, _ = setup
    tracker.first_week_ending, tracker.last_week_ending = date(2026, 1, 2), date(2026, 3, 27)
    db.commit()
    post(client, url(tracker), {"enabled": "on"})
    assert "Next:" not in card_of(page_text(client, tracker))


def test_the_history_next_date_skips_a_reminder_that_has_gone(client, db, setup, mail, monkeypatch):
    from tracker.entries import views

    tracker, _ = setup
    tracker.first_week_ending, tracker.last_week_ending = date(2026, 11, 6), date(2026, 11, 27)
    db.commit()
    post(client, url(tracker), {"enabled": "on"})
    for moment, expected in (
        (datetime(2026, 11, 20, 8, 44, tzinfo=timezone.utc), "Fri 20 Nov"),
        (datetime(2026, 11, 20, 8, 45, tzinfo=timezone.utc), "Fri 27 Nov"),
    ):
        monkeypatch.setattr(
            views, "datetime", type("D", (datetime,), {"now": classmethod(lambda cls, tz=None: moment)})
        )
        assert f"Next: {expected}" in client.get(f"/trackers/{tracker.id}/calendar-reminder/history").get_data(
            as_text=True
        )
        assert f"Next: {expected}, 08:45" in page_text(client, tracker)


def enabled_unsent(db, person, tracker):
    db.add(CalendarReminder(user_id=person.id, tracker_id=tracker.id, enabled=True, sequence=0, sent_state="none"))
    db.commit()


def test_email_it_again_is_offered_only_once_a_series_was_sent(client, db, setup, mail):
    tracker, person = setup
    enabled_unsent(db, person, tracker)
    panel = client.get(history_url(tracker, panel=True)).get_data(as_text=True)
    page = client.get(history_url(tracker)).get_data(as_text=True)
    assert "Email it again" not in panel and "Email it again" not in page
    assert "Switch the reminder off" in panel and "Download .ics" in panel and "Download .ics" in page
    post(client, url(tracker, "/resend"))  # sends the first request (nothing sent yet)
    row = db.get(CalendarReminder, (person.id, tracker.id))
    db.refresh(row)
    assert row.sent_state == "sent"
    panel = client.get(history_url(tracker, panel=True)).get_data(as_text=True)
    page = client.get(history_url(tracker)).get_data(as_text=True)
    assert panel.count("Email it again") == 2  # the menu and the calendar section
    assert page.count("Email it again") == 1


def test_the_calendar_section_has_the_download_and_a_plain_resend_form(client, db, setup, mail):
    tracker, _ = setup
    post(client, url(tracker), {"enabled": "on"})
    page = client.get(history_url(tracker)).get_data(as_text=True)
    section = page[
        page.index('aria-labelledby="history-reminder-title"') : page.index('aria-labelledby="history-events-title"')
    ]
    assert f'href="{ics_url(tracker)}"' in section and "Download .ics" in section
    assert f'action="{url(tracker, "/resend")}"' in section and "data-history-form" not in section
    assert 'name="csrf_token"' in section
    panel = client.get(history_url(tracker, panel=True)).get_data(as_text=True)
    assert "Switch the reminder off" in panel and "Switch the reminder off" not in page


def test_the_panel_forms_carry_the_week_being_viewed(client, setup, mail):
    tracker, _ = setup
    post(client, url(tracker), {"enabled": "on"})
    panel = client.get(history_url(tracker, panel=True) + "?week=2026-09-11").get_data(as_text=True)
    assert panel.count('name="week" value="2026-09-11"') == 3  # Email it again, Switch off, and the section's form
    for bad in ("", "?week=rubbish"):
        plain = client.get(history_url(tracker, panel=True) + bad).get_data(as_text=True)
        assert 'name="week"' not in plain
    response = post(client, url(tracker, "/resend"), {"week": "2026-09-11"})
    assert response.headers["Location"].endswith(f"/trackers/{tracker.id}/inputs?week=2026-09-11")
    inputs = client.get(f"/trackers/{tracker.id}/inputs?week=2026-09-18").get_data(as_text=True)
    assert f'data-history-url="{history_url(tracker, panel=True)}?week=2026-09-18"' in inputs
