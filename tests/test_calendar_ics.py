"""The calendar invitation builder: the iCalendar text and the email that carries it (no database)."""

from __future__ import annotations

import re
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from tracker.calendar_invites.ics import (
    Series,
    build_calendar,
    build_invite_email,
    describe_series,
    fingerprint,
    series_for,
)

NOW = datetime(2026, 11, 18, 9, 30, 15, tzinfo=timezone.utc)
ORGANIZER = "reports@example.com"
ATTENDEE = "person@example.com"
URL = "https://trackers.example.com/trackers/7/inputs"


def make_series(**changes) -> Series:
    values = {
        "tracker_id": 7, "user_id": 12, "name": "Weekly returns", "weekday": 4, "first": date(2026, 10, 16),
        "last": date(2026, 11, 27), "tz": "Europe/London", "url": URL,
    }  # fmt: skip
    return Series(**{**values, **changes})


def calendar(series: Series | None = None, method: str = "REQUEST", sequence: int = 0) -> str:
    return build_calendar(series or make_series(), ORGANIZER, ATTENDEE, method, sequence, NOW)


def unfold(text: str) -> list[str]:
    return text.replace("\r\n ", "").split("\r\n")


def lines_of(text: str) -> list[str]:
    return [line for line in unfold(text) if line]


def prop(text: str, name: str) -> str:
    """The first unfolded content line that starts with ``name``."""
    return next(line for line in lines_of(text) if line.startswith(name))


def zone_offset_at(text: str, local: datetime) -> str:
    """The offset the VTIMEZONE gives at a local wall-clock time: the latest component starting at or before it."""
    block = text.split("BEGIN:VTIMEZONE\r\n", 1)[1].split("END:VTIMEZONE", 1)[0]
    components = []
    for part in re.findall(r"BEGIN:(?:STANDARD|DAYLIGHT)\r\n(.*?)END:(?:STANDARD|DAYLIGHT)", block, re.S):
        fields = dict(line.split(":", 1) for line in part.split("\r\n") if line)
        components.append((datetime.strptime(fields["DTSTART"], "%Y%m%dT%H%M%S"), fields["TZOFFSETTO"]))
    assert "RRULE" not in block
    started = [c for c in components if c[0] <= local]
    return max(started, key=lambda c: c[0])[1]


def test_lines_end_in_crlf_only():
    text = calendar()
    assert text.endswith("END:VCALENDAR\r\n")
    assert "\n" not in text.replace("\r\n", "")
    assert "\r" not in text.replace("\r\n", "")


def test_no_line_exceeds_75_octets_and_unfolding_restores_the_name():
    name = ("Évaluation — résumé " * 8)[:120]
    assert len(name) == 120
    text = calendar(make_series(name=name))
    assert all(len(line.encode()) <= 75 for line in text.split("\r\n"))
    assert any(line.startswith(" ") for line in text.split("\r\n"))
    for line in text.split("\r\n"):
        line.encode().decode()  # every physical line is whole UTF-8: no character is split
    assert prop(text, "SUMMARY:") == f"SUMMARY:Write the weekly update: {name}"
    assert f"Write the weekly update for {name}." in prop(text, "DESCRIPTION:")


def test_text_values_are_escaped():
    text = calendar(make_series(name="A, B; C\\ D"))
    assert prop(text, "SUMMARY:") == "SUMMARY:Write the weekly update: A\\, B\\; C\\\\ D"


def test_newlines_in_text_values_are_escaped():
    text = calendar(make_series(name="A\r\nB\nC"))
    assert prop(text, "SUMMARY:") == "SUMMARY:Write the weekly update: A\\nB\\nC"


def test_start_and_end_are_in_the_trackers_time_zone():
    text = calendar()
    assert "DTSTART;TZID=Europe/London:20261016T084500" in lines_of(text)
    assert "DTEND;TZID=Europe/London:20261016T090000" in lines_of(text)


def test_the_series_runs_weekly_until_the_last_week_ending_in_utc():
    summer = calendar(make_series(last=date(2026, 10, 23)))
    assert "RRULE:FREQ=WEEKLY;UNTIL=20261023T074500Z" in lines_of(summer)  # 08:45 BST
    winter = calendar()
    assert "RRULE:FREQ=WEEKLY;UNTIL=20261127T084500Z" in lines_of(winter)  # 08:45 GMT


def test_london_timezone_gives_summer_time_before_25_october_and_winter_time_after():
    text = calendar(make_series(first=date(2026, 10, 2), last=date(2026, 11, 27)))
    assert "BEGIN:VTIMEZONE" in text and "TZID:Europe/London" in lines_of(text)
    assert zone_offset_at(text, datetime(2026, 1, 5, 8, 45)) == "+0000"
    assert zone_offset_at(text, datetime(2026, 10, 2, 8, 45)) == "+0100"
    assert zone_offset_at(text, datetime(2026, 10, 23, 8, 45)) == "+0100"
    assert zone_offset_at(text, datetime(2026, 10, 30, 8, 45)) == "+0000"
    assert zone_offset_at(text, datetime(2026, 11, 27, 8, 45)) == "+0000"


def test_timezone_components_carry_the_offset_they_change_from_and_a_matching_kind():
    text = calendar(make_series(first=date(2026, 10, 2), last=date(2026, 11, 27)))
    block = text.split("BEGIN:VTIMEZONE\r\n", 1)[1].split("END:VTIMEZONE", 1)[0]
    assert "BEGIN:DAYLIGHT\r\nDTSTART:20260329T010000\r\nTZOFFSETFROM:+0000\r\nTZOFFSETTO:+0100\r\n" in block
    assert "BEGIN:STANDARD\r\nDTSTART:20261025T020000\r\nTZOFFSETFROM:+0100\r\nTZOFFSETTO:+0000\r\n" in block


def test_sydney_timezone_gives_winter_time_before_4_october_and_summer_time_after():
    series = make_series(first=date(2026, 10, 2), last=date(2026, 11, 27), tz="Australia/Sydney")
    text = calendar(series)
    assert "TZID:Australia/Sydney" in lines_of(text)
    assert "DTSTART;TZID=Australia/Sydney:20261002T084500" in lines_of(text)
    assert zone_offset_at(text, datetime(2026, 1, 5, 8, 45)) == "+1100"
    assert zone_offset_at(text, datetime(2026, 6, 5, 8, 45)) == "+1000"
    assert zone_offset_at(text, datetime(2026, 10, 2, 8, 45)) == "+1000"
    assert zone_offset_at(text, datetime(2026, 10, 9, 8, 45)) == "+1100"
    assert zone_offset_at(text, datetime(2026, 11, 27, 8, 45)) == "+1100"
    until = datetime(2026, 11, 27, 8, 45, tzinfo=ZoneInfo("Australia/Sydney")).astimezone(timezone.utc)
    assert f"UNTIL={until:%Y%m%dT%H%M%SZ}" in prop(text, "RRULE:")


def test_a_span_over_two_calendar_years_lists_the_changes_in_both():
    text = calendar(make_series(first=date(2026, 12, 4), last=date(2027, 4, 2)))
    assert zone_offset_at(text, datetime(2026, 12, 4, 8, 45)) == "+0000"
    assert zone_offset_at(text, datetime(2027, 3, 26, 8, 45)) == "+0000"
    assert zone_offset_at(text, datetime(2027, 4, 2, 8, 45)) == "+0100"


def test_a_zone_without_summer_time_has_one_component():
    text = calendar(make_series(tz="Asia/Singapore"))
    assert text.count("BEGIN:STANDARD") == 1 and "BEGIN:DAYLIGHT" not in text
    assert zone_offset_at(text, datetime(2026, 10, 16, 8, 45)) == "+0800"


def test_the_event_does_not_block_the_diary_and_alerts_at_the_start():
    text = calendar()
    assert "TRANSP:TRANSPARENT" in lines_of(text)
    alarm = text.split("BEGIN:VALARM\r\n", 1)[1].split("END:VALARM", 1)[0]
    assert "ACTION:DISPLAY" in alarm and "TRIGGER:PT0M" in alarm


def test_attendee_and_organizer():
    text = calendar()
    attendee = prop(text, "ATTENDEE")
    assert attendee.startswith("ATTENDEE;") and "RSVP=FALSE" in attendee and attendee.endswith(f":mailto:{ATTENDEE}")
    assert text.count("ATTENDEE") == 1
    assert f"ORGANIZER:mailto:{ORGANIZER}" in lines_of(text)


def test_organizer_is_the_bare_address_when_the_sender_has_a_display_name():
    text = build_calendar(make_series(), "Reports <reports@example.com>", ATTENDEE, "REQUEST", 0, NOW)
    assert "ORGANIZER:mailto:reports@example.com" in lines_of(text)
    msg = build_invite_email(make_series(), "Reports <reports@example.com>", ATTENDEE, "REQUEST", 0, NOW)
    assert msg["From"] == "Reports <reports@example.com>"


def test_request_header_properties():
    text = calendar(sequence=3)
    lines = lines_of(text)
    assert lines[0] == "BEGIN:VCALENDAR"
    for expected in ("VERSION:2.0", "METHOD:REQUEST", "SEQUENCE:3", "STATUS:CONFIRMED", "DTSTAMP:20261118T093015Z"):
        assert expected in lines
    assert prop(text, "PRODID:").startswith("PRODID:-//")
    assert "STATUS:CANCELLED" not in text


def test_cancellation():
    text = calendar(method="CANCEL", sequence=4)
    lines = lines_of(text)
    assert "METHOD:CANCEL" in lines and "STATUS:CANCELLED" in lines and "SEQUENCE:4" in lines
    assert "METHOD:REQUEST" not in lines
    assert f"UID:{make_series().uid}" in lines


def test_uid_has_the_stable_format():
    assert make_series().uid == "tracker-7-user-12@tc-trackers"
    assert "UID:tracker-7-user-12@tc-trackers" in lines_of(calendar())


def test_the_link_is_the_url_and_is_in_the_description():
    text = calendar()
    assert f"URL:{URL}" in lines_of(text)
    assert URL in prop(text, "DESCRIPTION:")
    assert "week=" not in text


def test_series_for_takes_the_trackers_and_the_persons_ids():
    class Row:
        def __init__(self, **kw):
            self.__dict__.update(kw)

    tracker = Row(id=7, name="Returns", week_ending_weekday=4, first_week_ending=date(2026, 10, 16),
                  last_week_ending=date(2026, 11, 27), send_timezone="Europe/London")  # fmt: skip
    series = series_for(tracker, Row(id=12), URL)
    assert series == make_series(name="Returns")


def test_fingerprint_follows_the_name_dates_weekday_and_zone_only():
    base = fingerprint(make_series())
    assert base == {
        "name": "Weekly returns", "weekday": 4, "first": "2026-10-16", "last": "2026-11-27", "tz": "Europe/London",
    }  # fmt: skip
    for change in (
        {"name": "Other"}, {"first": date(2026, 10, 9)}, {"last": date(2026, 12, 4)}, {"weekday": 3},
        {"tz": "Europe/Paris"},
    ):  # fmt: skip
        assert fingerprint(make_series(**change)) != base
    assert fingerprint(make_series(url="https://other.example.com/x", user_id=99, tracker_id=8)) == base


def test_email_carries_the_calendar_as_an_alternative_and_as_invite_ics():
    msg = build_invite_email(make_series(), ORGANIZER, ATTENDEE, "REQUEST", 2, NOW)
    assert msg["To"] == ATTENDEE
    assert msg["Subject"] == "Calendar reminder: Weekly returns"
    alternative = next(p for p in msg.walk() if p.get_content_type() == "multipart/alternative")
    kinds = [p.get_content_type() for p in alternative.iter_parts()]
    assert kinds == ["text/plain", "text/html", "text/calendar"]
    part = list(alternative.iter_parts())[2]
    assert part.get_param("method") == "REQUEST" and part.get_content_charset().lower() == "utf-8"
    assert part.get_content().replace("\r\n", "\n") == calendar(sequence=2).replace("\r\n", "\n")
    attached = [p for p in msg.walk() if p.get_filename() == "invite.ics"]
    assert len(attached) == 1
    assert attached[0].get_content().decode() == calendar(sequence=2)  # the attachment keeps the CRLF endings


def test_email_bodies_link_to_the_page_and_explain_the_calendar():
    msg = build_invite_email(make_series(name="A & B <C>"), ORGANIZER, ATTENDEE, "REQUEST", 0, NOW)
    text = msg.get_body(("plain",)).get_content()
    page = msg.get_body(("html",)).get_content()
    assert URL in text and URL in page
    assert "Outlook adds this to your calendar; it is updated or removed automatically." in text
    assert "Outlook adds this to your calendar; it is updated or removed automatically." in page
    assert "A &amp; B &lt;C&gt;" in page and "<C>" not in page


def test_cancellation_email():
    msg = build_invite_email(make_series(), ORGANIZER, ATTENDEE, "CANCEL", 5, NOW)
    assert msg["Subject"] == "Calendar reminder cancelled: Weekly returns"
    part = next(p for p in msg.walk() if p.get_content_type() == "text/calendar")
    assert part.get_param("method") == "CANCEL"
    assert "STATUS:CANCELLED" in part.get_content()
    assert "Outlook removes it, or offers to remove it, from your calendar." in msg.get_body(("plain",)).get_content()


def test_a_long_name_with_other_characters_survives_in_the_subject():
    name = "Évaluation — " * 10
    msg = build_invite_email(make_series(name=name), ORGANIZER, ATTENDEE, "REQUEST", 0, NOW)
    assert str(msg["Subject"]) == f"Calendar reminder: {name.strip()}"


def test_unknown_method_is_refused():
    with pytest.raises(ValueError):
        calendar(method="BOGUS")


def test_the_calendar_part_has_a_transfer_encoding_that_survives_a_hop_without_8bitmime():
    for name in ("Weekly returns", "Évaluation — résumé"):
        msg = build_invite_email(make_series(name=name), ORGANIZER, ATTENDEE, "REQUEST", 0, NOW)
        part = next(p for p in msg.walk() if p.get_content_type() == "text/calendar")
        assert part["Content-Transfer-Encoding"] in ("base64", "quoted-printable")
        assert msg.as_bytes().isascii()
        assert part.get_content().replace("\r\n", "\n") == calendar(make_series(name=name)).replace("\r\n", "\n")


def test_the_email_is_marked_as_a_calendar_message():
    msg = build_invite_email(make_series(), ORGANIZER, ATTENDEE, "REQUEST", 0, NOW)
    assert msg["Content-Class"] == "urn:content-classes:calendarmessage"


def test_describe_series_within_one_year():
    series = make_series(weekday=4, first=date(2026, 10, 2), last=date(2026, 12, 18))
    assert describe_series(series) == "Fridays, 08:45 to 09:00 (London time), 2 Oct \u2013 18 Dec 2026"


def test_describe_series_across_two_years_and_a_multi_word_place():
    series = make_series(weekday=0, first=date(2026, 12, 7), last=date(2027, 1, 18), tz="America/New_York")
    assert describe_series(series) == "Mondays, 08:45 to 09:00 (New York time), 7 Dec 2026 \u2013 18 Jan 2027"


def test_a_publish_calendar_has_no_attendee_but_keeps_the_rest():
    text = build_calendar(make_series(), ORGANIZER, ATTENDEE, "PUBLISH", 2, NOW)
    lines = lines_of(text)
    assert "METHOD:PUBLISH" in lines and "SEQUENCE:2" in lines
    assert "ATTENDEE" not in text
    assert f"ORGANIZER:mailto:{ORGANIZER}" in lines
    assert any(line.startswith("UID:tracker-7-user-12@") for line in lines)
    assert "BEGIN:VALARM" in lines
