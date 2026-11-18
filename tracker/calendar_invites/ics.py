"""Builds the calendar invitation for one person and tracker: the iCalendar text and the email that carries it.

The invitation is a weekly series on the tracker's week-ending day, 08:45 to 09:00 in the tracker's time zone, from the
first to the last week ending. It is delivered as an email whose ``text/calendar; method=<METHOD>`` part sits beside the
text and HTML bodies (which Outlook 2016 and 2021 process as a meeting item) and is also attached as ``invite.ics``. An
update or a cancellation is the same ``UID`` with a higher ``SEQUENCE``. Nothing here touches the database.
"""

from __future__ import annotations

import html
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from email.message import EmailMessage
from typing import Literal
from zoneinfo import ZoneInfo

from flask import current_app

START = time(8, 45)
DURATION = timedelta(minutes=15)
PRODID = "-//Tradition//tc-trackers calendar reminders//EN"
METHODS = ("REQUEST", "CANCEL")
LINE_OCTETS = 75
EXPLANATION = "Outlook adds this to your calendar; it is updated or removed automatically."


@dataclass(frozen=True)
class Series:
    """What one person's reminder series is made of; the ids give it a stable ``uid``."""

    tracker_id: int
    user_id: int
    name: str
    weekday: int
    first: date
    last: date
    tz: str
    url: str

    @property
    def uid(self) -> str:
        return f"tracker-{self.tracker_id}-user-{self.user_id}@tc-trackers"


def inputs_url(tracker_id: int) -> str:
    """The absolute Weekly update page of a tracker, from the configured ``APP_URL`` (never from request headers)."""
    return f"{current_app.config['APP_URL'].rstrip('/')}/trackers/{tracker_id}/inputs"


def series_for(tracker, user, url: str) -> Series:
    return Series(
        tracker_id=tracker.id,
        user_id=user.id,
        name=tracker.name,
        weekday=tracker.week_ending_weekday,
        first=tracker.first_week_ending,
        last=tracker.last_week_ending,
        tz=tracker.send_timezone,
        url=url,
    )


def fingerprint(series: Series) -> dict:
    """The parts of a series whose change means the invitation must be sent again."""
    return {
        "name": series.name,
        "weekday": series.weekday,
        "first": series.first.isoformat(),
        "last": series.last.isoformat(),
        "tz": series.tz,
    }


# --- iCalendar text ------------------------------------------------------------------------------------------


def _escape(value: str) -> str:
    """Escape a text value: backslash, semicolon, comma and line breaks."""
    value = value.replace("\\", "\\\\").replace(";", r"\;").replace(",", "\\,")
    return value.replace("\r\n", "\\n").replace("\r", "\\n").replace("\n", "\\n")


def _fold(line: str) -> str:
    """Fold a content line at 75 octets, never inside a UTF-8 character; a continuation starts with one space."""
    parts: list[str] = []
    current, size, limit = "", 0, LINE_OCTETS
    for char in line:
        width = len(char.encode("utf-8"))
        if size + width > limit:
            parts.append(current)
            current, size, limit = " ", 1, LINE_OCTETS
        current += char
        size += width
    parts.append(current)
    return "\r\n".join(parts)


def _utc_stamp(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _local_stamp(moment: datetime) -> str:
    return moment.strftime("%Y%m%dT%H%M%S")


def _offset_text(offset: timedelta) -> str:
    minutes = int(offset.total_seconds() // 60)
    sign = "+" if minutes >= 0 else "-"
    return f"{sign}{abs(minutes) // 60:02d}{abs(minutes) % 60:02d}"


def _offset_at(zone: ZoneInfo, moment: datetime) -> timedelta:
    return moment.astimezone(zone).utcoffset()


def _changes(zone: ZoneInfo, start: datetime, end: datetime) -> list[datetime]:
    """The UTC instants, to the minute, at which the zone's offset changes between ``start`` and ``end``."""
    found = []
    previous = start
    while previous < end:
        following = min(previous + timedelta(days=1), end)
        if _offset_at(zone, following) != _offset_at(zone, previous):
            low, high = previous, following  # the offset differs at ``high`` and not at ``low``
            while high - low > timedelta(minutes=1):
                middle = low + (high - low) / 2
                middle -= timedelta(seconds=middle.second, microseconds=middle.microsecond)
                if _offset_at(zone, middle) == _offset_at(zone, low):
                    low = middle
                else:
                    high = middle
            found.append(high)
        previous = following
    return found


def _timezone_component(
    kind: str, local_start: datetime, before: timedelta, moment: datetime, zone: ZoneInfo
) -> list[str]:
    local = moment.astimezone(zone)
    return [
        f"BEGIN:{kind}",
        f"DTSTART:{_local_stamp(local_start)}",
        f"TZOFFSETFROM:{_offset_text(before)}",
        f"TZOFFSETTO:{_offset_text(local.utcoffset())}",
        f"TZNAME:{local.tzname()}",
        f"END:{kind}",
    ]


def _kind(moment: datetime, zone: ZoneInfo) -> str:
    return "DAYLIGHT" if moment.astimezone(zone).dst() else "STANDARD"


def _vtimezone(tz: str, first_year: int, last_year: int) -> list[str]:
    """A ``VTIMEZONE`` that lists the zone's offset changes from 1 January of the first year to 31 December of the
    last, plus the offset in force at the start. It has no recurrence rule, so every reader gets the same answer."""
    zone = ZoneInfo(tz)
    start = datetime(first_year, 1, 1, tzinfo=timezone.utc)
    end = datetime(last_year, 12, 31, 23, 59, tzinfo=timezone.utc)
    initial = _offset_at(zone, start)
    lines = ["BEGIN:VTIMEZONE", f"TZID:{tz}"]
    lines += _timezone_component(_kind(start, zone), datetime(first_year, 1, 1), initial, start, zone)
    for moment in _changes(zone, start, end):
        before = _offset_at(zone, moment - timedelta(minutes=1))
        wall_before = (moment + before).replace(tzinfo=None)
        lines += _timezone_component(_kind(moment, zone), wall_before, before, moment, zone)
    lines.append("END:VTIMEZONE")
    return lines


def build_calendar(
    series: Series,
    organizer: str,
    attendee: str,
    method: Literal["REQUEST", "CANCEL"],
    sequence: int,
    now_utc: datetime,
) -> str:
    """The complete ``VCALENDAR`` text, with CRLF line endings, folded and escaped."""
    if method not in METHODS:
        raise ValueError(f"The method must be one of {', '.join(METHODS)}, not {method!r}.")
    zone = ZoneInfo(series.tz)
    start = datetime.combine(series.first, START)
    until = datetime.combine(series.last, START, tzinfo=zone)
    cancelled = method == "CANCEL"
    description = f"Write the weekly update for {series.name}.\n{series.url}"
    event = [
        "BEGIN:VEVENT",
        f"UID:{series.uid}",
        f"DTSTAMP:{_utc_stamp(now_utc)}",
        f"DTSTART;TZID={series.tz}:{_local_stamp(start)}",
        f"DTEND;TZID={series.tz}:{_local_stamp(start + DURATION)}",
        f"RRULE:FREQ=WEEKLY;UNTIL={_utc_stamp(until)}",
        f"SEQUENCE:{sequence}",
        f"SUMMARY:{_escape(f'Write the weekly update: {series.name}')}",
        f"DESCRIPTION:{_escape(description)}",
        f"URL:{series.url}",
        f"ORGANIZER:mailto:{organizer}",
        f"ATTENDEE;RSVP=FALSE;PARTSTAT=NEEDS-ACTION;ROLE=REQ-PARTICIPANT:mailto:{attendee}",
        f"STATUS:{'CANCELLED' if cancelled else 'CONFIRMED'}",
        "TRANSP:TRANSPARENT",
    ]
    if not cancelled:
        event += [
            "BEGIN:VALARM",
            "ACTION:DISPLAY",
            "TRIGGER:PT0M",
            f"DESCRIPTION:{_escape(f'Write the weekly update: {series.name}')}",
            "END:VALARM",
        ]
    event.append("END:VEVENT")
    lines = [
        "BEGIN:VCALENDAR",
        f"PRODID:{PRODID}",
        "VERSION:2.0",
        "CALSCALE:GREGORIAN",
        f"METHOD:{method}",
        *_vtimezone(series.tz, series.first.year, series.last.year),
        *event,
        "END:VCALENDAR",
    ]
    return "".join(_fold(line) + "\r\n" for line in lines)


# --- The email -----------------------------------------------------------------------------------------------


def build_invite_email(
    series: Series,
    organizer: str,
    attendee: str,
    method: Literal["REQUEST", "CANCEL"],
    sequence: int,
    now_utc: datetime,
) -> EmailMessage:
    """The invitation email: text and HTML bodies and the calendar as an alternative (the part Outlook turns into a
    meeting item), also attached as ``invite.ics``."""
    calendar = build_calendar(series, organizer, attendee, method, sequence, now_utc)
    name = " ".join(series.name.split())
    if method == "CANCEL":
        subject = f"Calendar reminder cancelled: {name}"
        lead = f"The weekly reminder to write the update for {name} has been cancelled."
        note = "Outlook removes it from your calendar."
    else:
        subject = f"Calendar reminder: {name}"
        lead = f"A weekly reminder to write the update for {name} is in your calendar."
        note = EXPLANATION
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = organizer
    msg["To"] = attendee
    msg.set_content(f"{lead}\n\nWeekly update page: {series.url}\n\n{note}\n")
    link = html.escape(series.url, quote=True)
    msg.add_alternative(
        f'<p>{html.escape(lead)}</p><p><a href="{link}">Open the Weekly update page</a></p><p>{html.escape(note)}</p>',
        subtype="html",
    )
    # base64, so no hop needs 8BITMIME and the CRLF line endings arrive as written
    msg.add_alternative(calendar, subtype="calendar", charset="utf-8", cte="base64", params={"method": method})
    msg.add_attachment(calendar.encode("utf-8"), maintype="application", subtype="ics", filename="invite.ics")
    msg["Content-Class"] = "urn:content-classes:calendarmessage"  # set last: adding parts moves Content-* headers
    return msg
