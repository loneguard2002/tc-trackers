# Calendar reminders to write the weekly update

Agreed with the owner on 18 Nov 2026.

## Why

The weekly update (the "Weekly update" tab: headline, decisions needed, status) has to be written before the report
goes out on the week-ending day. Today the only prompt is an email to the person in charge 24 hours before an
automatic send, and only while automatic sending is on. The owner wants the reminder in people's own Outlook
calendars: on each week-ending day of a tracker, at 08:45, a calendar reminder to write that week's update. The
reminders must keep themselves up to date when the tracker changes.

## Goals

1. **The person chooses the trackers.** Each tracker has a "Remind me" switch for that person. Only the trackers they
   switched on reach their calendar, never all of them.
2. **Only people who can write the update.** The switch is offered to editors, owners and the person in charge
   (`g.role in ('editor', 'owner')`). Viewers do not get it.
3. **Delivered as calendar invitations by email.** Switching a tracker on sends the person an email carrying a calendar
   invitation: a weekly series on the tracker's week-ending day, from its first to its last week ending, 08:45 to 09:00
   in the tracker's time zone (`send_timezone`), with a pop-up reminder at 08:45. Outlook adds it to the person's own
   calendar, so it shows in Outlook on the desktop, on the web and on phones.
4. **Kept up to date by the application.** When the tracker's name, first or last week ending, week-ending day or time
   zone changes, the application sends an update to the same series, which Outlook moves in place. When the series
   should no longer exist, the application sends a cancellation, which removes it: the person switches it off, the
   tracker is archived or deleted, the person loses edit rights, or the person's account is deactivated. Restoring
   or regaining does not resubscribe on its own; the switch stays as the person left it and an invitation is sent
   again only while the switch is on and the person can edit.
5. **Link to the update.** The invitation's description and URL link to the tracker's Weekly update page
   (`entries.inputs` without `week=`, which opens the latest week ending on or before today, so on the reminder day it
   opens that week).

## Non-goals

- No subscribed calendar link (the application runs on an internal server, which Outlook on the web and the new
  Outlook cannot reach) and no Microsoft 365 calendar permissions.
- No change to the existing email reminder (24 hours before an automatic send); the two live side by side.
- The calendar does not know whether the update is written; the reminder appears every week.
- No one else can switch on someone's reminders; administrators do not manage them.

## Anti-goals

- Duplicate series in someone's calendar (an update or resend must replace, never add).
- A series that stays in a calendar after the person switched it off, lost edit rights or the tracker was archived or
  deleted.

## Constraints

- The application already sends email (reports and reminders) through its configured SMTP account; invitations use
  the same account and sender address.
- The people who use it run classic desktop Outlook 2016 and Outlook 2021; both handle email calendar invitations,
  updates and cancellations natively.
- **Before the build**, one test invitation is sent to the owner and checked in Outlook 2016 and Outlook 2021 (and on
  the web or phone where used): the
  series appears on the right days at 08:45, the reminder pops up, an update moves it in place, and a cancellation
  removes it. If any of these fails, the owner decides before any build.
- Strict Content Security Policy, ES5, British English without contractions, as elsewhere in the app.

## Approaches

- **Chosen: calendar invitations by email, kept up to date by the application.** Works in every Outlook, needs
  nothing from IT and nothing reachable from outside, and reuses the email the reports already use.
- Rejected: a subscribed calendar link. Outlook on the web, the new Outlook and phones fetch subscriptions from
  Microsoft's servers, which cannot reach the internal server; classic desktop Outlook might, but recent versions can
  hand subscriptions to the cloud too.
- Rejected: writing events through Microsoft 365. IT would have to grant the application permission to change
  people's calendars.
- Rejected earlier: a downloaded .ics file (goes stale) and one calendar per tracker (repeated Outlook steps).

## How it behaves (decided)

- **Where the switch lives:** on the tracker's Weekly update tab (the page the reminder links to), a small panel
  "Calendar reminder" with the switch "Remind me at 08:45 on each week-ending day", the state ("Sent to <email> on
  <date>") and "Send it again" (for someone who deleted the series by mistake; it resends the same series, so it
  replaces rather than duplicates).
- **Without JavaScript:** the switch is a small form that posts and returns to the Weekly update tab.
- **The invitation:** an email to the person ("Calendar reminder: <tracker name>") with a `text/calendar;
  method=REQUEST` part. One `VEVENT` per tracker and person with a stable `UID` (built from the tracker and the
  person), `RRULE:FREQ=WEEKLY` ending at the last week ending, `DTSTART` 08:45 with the tracker's `TZID` and a matching
  `VTIMEZONE` so summer time is right, 15 minutes long, `TRANSP:TRANSPARENT` (does not block the diary), a `VALARM`
  (`ACTION:DISPLAY`, `TRIGGER:PT0M`), the sending address as `ORGANIZER` and the person as the only `ATTENDEE` with
  `RSVP=FALSE` so Outlook does not ask for a reply.
- **Updates and cancellations:** each sent series is remembered with its `SEQUENCE` and what it was built from (name,
  first and last week ending, weekday, time zone). An update is the same `UID` with a higher `SEQUENCE`; a cancellation
  is `METHOD:CANCEL` with the same `UID` and a higher `SEQUENCE`.
- **When they are sent:** switching on or off sends at once (a failure shows a message and leaves the work for the
  scheduler). Everything else is found by the existing scheduler cycle (`run_scheduler_cycle`), which compares each
  remembered series with the tracker and the person's current rights and sends what is needed. A delivery failure is
  retried at the next cycle; nothing is lost.
- **A deleted tracker:** its cancellations still go out, so the remembered series must survive the tracker's deletion
  long enough to send them (builder's choice how).
- **Past weeks:** the series starts at the first week ending even when switched on mid-run; past occurrences are
  harmless and keep the series simple.
- **Activity log:** nothing is logged. The reminders are a personal choice that changes nothing about the tracker, and
  the activity log is visible to everyone who may view activity.

## Left to the builder

- Table names and shape (for example a `calendar_reminders` row per person and tracker with the switch, the `UID`,
  the `SEQUENCE`, what the last sent series was built from, and its state: sent, update pending, cancel pending), and
  the migration.
- Whether to hand-write the iCalendar text or add a small library (prefer no new dependency if the text stays simple
  and is tested against the iCalendar rules: CRLF line endings, line folding at 75 octets, escaping of commas,
  semicolons and backslashes in the tracker name).
- How the `VTIMEZONE` is produced for the tracker's zone.
- Where replies land if a person replies anyway (the sending mailbox); no handling is needed.
