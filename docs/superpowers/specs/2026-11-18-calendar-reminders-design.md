# Calendar reminders to write the weekly update

Agreed with the owner on 18 Nov 2026.

## Why

The weekly update (the "Weekly update" tab: headline, decisions needed, status) has to be written before the report
goes out on the week-ending day. Today the only prompt is an email to the person in charge 24 hours before an
automatic send, and only while automatic sending is on. The owner wants the reminder in people's own calendars: on
each week-ending day of a tracker, at 08:45, a calendar reminder to write that week's update.

## Goals

1. **One personal calendar link per person.** A person subscribes to it once in Outlook (or any calendar that takes an
   internet calendar link). The link is secret and personal, because a calendar cannot sign in.
2. **The person chooses the trackers.** Each tracker has a "Remind me" switch for that person. Only the trackers they
   switched on appear in their calendar, never all of them.
3. **Only people who can write the update.** The switch is offered to editors, owners and the person in charge
   (`g.role in ('editor', 'owner')`). Viewers do not get it. If a person later loses edit rights, that tracker's events
   leave their calendar at the next refresh; their switch is kept but has no effect while they cannot edit.
4. **The events.** For each switched-on tracker, one event on every week-ending day from `first_week_ending` to
   `last_week_ending`, starting at 08:45 in the tracker's time zone (`send_timezone`), with an alarm at the start.
   Title "Write the weekly update: <tracker name>"; the description and URL link to that week's Weekly update page
   (`entries.inputs` with `week=`).
5. **Always current.** The calendar is built by the application each time the calendar program asks for it, so a
   change to a tracker's dates, name, time zone or week-ending day, a switch turned on or off, or archiving the tracker
   (its events disappear) shows at the calendar program's next refresh.
6. **Reset the link.** A person can reset their link; the old one stops working at once (404) and they subscribe again
   with the new one.

## Non-goals

- No emailed invitations and no meeting requests.
- No change to the existing email reminder (24 hours before an automatic send); the two live side by side.
- The calendar does not know whether the update is written; the reminder appears every week.
- No one else can see or switch on someone's reminders; administrators do not manage them.

## Anti-goals

- A link that still works after the person lost access or reset it.
- A link that reveals other trackers, other people's data, or anything beyond the tracker names, dates and links.

## Constraints

- The calendar link must be reachable from the internet for Outlook on the web and the new Outlook, because
  Microsoft's servers fetch subscribed calendars, not the person's PC. Classic desktop Outlook fetches from the PC.
- Calendar programs refresh subscribed calendars on their own schedule (often every few hours); changes are not
  instant.
- Not every Outlook version is known to fire the alarm of a subscribed calendar. **Before the build, a throwaway test
  link is checked in the owner's Outlook (web and desktop)**: the event shows at 08:45 and the reminder pops up. If
  the reminder does not pop up, the owner decides whether to continue (events without pop-ups) before any build.
- Strict Content Security Policy, ES5, British English without contractions, as elsewhere in the app.

## Approaches

- **Chosen: one personal link, trackers chosen in the app.** One subscription in Outlook, one "Tracker reminders"
  calendar; switching a tracker on or off happens in the app. Losing edit rights removes that tracker's events; one
  reset covers everything.
- Rejected: one link per tracker. Every tracker becomes a separate calendar in Outlook and the Outlook steps are
  repeated for each tracker.
- Rejected: a downloaded .ics file. It goes stale when the tracker's dates, name or access change.

## How it behaves (decided)

- **Where the switch lives:** on the tracker's Weekly update tab (the page the reminder links to), a small panel
  "Calendar reminder" with the switch "Remind me at 08:45 on each week-ending day" and, once the person has a link,
  "Copy my calendar link", a short "How to add it to Outlook" note, and "Reset my link".
- **The link:** `https://<app>/calendar/<token>.ics`, the token a long random secret (at least 32 bytes, URL-safe).
  *(Call made after the builder check.)* The token itself is stored, so the person can copy their link again on any
  visit to any tracker's Weekly update tab; it only reveals tracker names, week-ending dates and links. Switching the
  first tracker on creates the link; there is no separate "Create" step. "Reset my link" replaces the token, and the
  old link answers 404 at once.
- **No sign-in for the feed:** the route takes no session or cookies, answers `text/calendar; charset=utf-8`, and
  returns 404 for an unknown or reset token (never a hint whether the token ever existed).
- **The calendar file:** a `VCALENDAR` named "Tracker reminders" (`X-WR-CALNAME`). *(Call made after the builder
  check.)* One `VEVENT` per tracker and week ending (at most 52 per tracker), not a repeating series, so each event links
  to its own week (`entries.inputs` with `week=`). Each event's start is 08:45 in the tracker's time zone converted to
  UTC for that date (so summer time is right without a `VTIMEZONE`), lasting 15 minutes, marked free
  (`TRANSP:TRANSPARENT`) so it does not block the diary, with a `VALARM` (`ACTION:DISPLAY`, `TRIGGER:PT0M`). Each event
  has a stable `UID` built from the tracker id and the week ending, so a refresh updates events instead of duplicating
  them. Past weeks stay in the calendar; an archived tracker's events all disappear.
- **Activity log:** *(call made after the builder check)* nothing is logged. The reminders are a personal choice that
  changes nothing about the tracker, and the activity log is visible to everyone who may view activity, which would
  show other people's personal choices.
- **Without JavaScript:** the switch is a small form that posts and returns to the Weekly update tab; the link is shown
  in a read-only field to copy by hand.

## Left to the builder

- Table names and shape (for example a `calendar_feeds` row per person with the token hash, and a
  `calendar_subscriptions` row per person and tracker), the migration, and whether to hand-write the iCalendar text or
  add a small library (prefer no new dependency if the text stays simple and is tested against the iCalendar rules:
  CRLF line endings, line folding at 75 octets, escaping of commas, semicolons and backslashes in the tracker name).
- How the `VTIMEZONE` is produced for the tracker's zone.
- Rate limiting of the feed route, if the app already has a pattern for it.
