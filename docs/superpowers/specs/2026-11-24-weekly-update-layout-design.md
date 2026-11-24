# Weekly update page: layout, calendar reminder card and its history

Agreed with the owner on 24 Nov 2026 from the "Weekly update: calendar invite" canvas
(https://claude.ai/artifact/8ZzVkrKuQ2oG3YniUeymE3): layout from design C, history side panel from design B.
Builds on `docs/superpowers/specs/2026-11-18-calendar-reminders-design.md` (what the reminder sends) and
`docs/design-rules.md`.

## Why

The page has one job: write this week's update (status, headline, decisions) before the report goes out. Today the
week header and week strip take the top third of the screen, the page never says when the report goes out, the report
preview sits away from the boxes it previews, and the calendar reminder is a single line with no way to download the
invite or see what was sent.

## Goals

1. **A slim week bar.** One card, one line: a week button "Week ending 20 Nov 2026 ▾", this week's state, the deadline,
   and ‹ Latest week ›. The week button opens the week strip underneath (closed when the page opens; without
   JavaScript the strip shows, as today).
   - **State:** "Not written yet", or "Written · Amber" (the saved status, "Written · status not set" without one).
   - **Deadline:** with automatic sending on and the shown week's send still to come: "Report goes out today at 17:00",
     "… tomorrow at 17:00" or "… on Fri 27 Nov at 17:00", in the tracker's time zone, amber. Once that week was sent:
     "Report sent on Fri 20 Nov at 17:02" (muted). Automatic sending off: "Automatic sending is off" (muted). Times
     come from the existing schedule (`next_send`, `send_time`, `send_timezone`) and the report sends.
2. **Writing on the left, facts on the right.** From 1000 px wide: the Commentary card on the left (about 60%), the
   figures and the reminder on the right (about 40%). The right column stays in view while the page scrolls (sticky,
   under the top bar and section links). Narrower: one column in this order: week bar, Commentary (with its preview),
   figures, reminder.
3. **The preview belongs to the form.** "Preview: top of the report" moves into the Commentary card, under the boxes,
   as a tinted strip (design rule 3: no box inside a box). It updates as you type, as today. "Use last week's text"
   stays above it.
4. **The figures first.** The right column starts with "This week's figures" as today (the four figures with their
   comparisons, next week's target, last week's status), then the verdict line and the Red and overdue risk counts with
   "Open risks".
5. **Calendar reminder card** under the figures, for editors, owners and the person in charge (not on an archived
   tracker):
   - The checkbox "Email me an Outlook reminder", with "08:45 on each week-ending day" under it. Ticking and
     unticking behave as today, including "Save your weekly update first." while the update has unsaved changes.
   - A status line: "Next: Fri 27 Nov · sent 23 Nov", "Not sent yet", "Email is not set up in this application yet",
     or nothing while it is off.
   - Two icon buttons with labels for screen readers and a tooltip: **Download the invite (.ics)** and **Email the
     invite again** (today's "Send again"; shown only when a series was sent).
   - **History**, which opens the history side panel.
6. **Download the invite.** `GET /trackers/<id>/calendar-reminder.ics` returns the person's series as a file
   (`<tracker name> reminder.ics`): the same series, UID and time zone as the email, `METHOD:PUBLISH`, so opening it
   adds the series to Outlook. It works whether or not the box is ticked and without email set up. Each download is
   recorded in the history.
7. **History side panel.** The same right-hand panel as permission set holders (`dialog.perm-drawer`: full height,
   560 px, frosted header, backdrop per design rule 1). Header: "Calendar reminder", "<tracker> · sent to <email>", a ⋯
   menu (Download invite, Email it again, Switch the reminder off… in red) and ✕.
   - **In your calendar:** status ("On · up to date", "On · not sent yet", "Off"), when ("Fridays, 08:45 to 09:00
     (London time)"), from – to, next date; Download .ics and Email it again.
   - **History:** a standard table (the toolkit in `lists/_table.html` and `lists.js`): a search box, chips All /
     Sent / Failed / Downloads with counts, columns When (sortable, newest first by default) / What (sortable) /
     Detail, "No events match." with Clear filters, the footer "Showing 6 of 6 events" and paging past 25. The panel's
     table does not write to the address (`data-no-address`), like the holders panel.
   - Without JavaScript, History links to a plain page with the same two sections.
8. **An event log** so the history exists: one row per event for a person and tracker, with when it happened, what
   (switched on, switched off, invite sent, update sent, cancellation sent, sending failed, downloaded) and a short
   detail ("Tracker renamed", "The mail server did not answer"). Written where these happen today (the switch, "Email
   it again", the scheduler sync, the download). History starts when this ships; earlier sends are not shown.

## Non-goals

- No change to what the invitation contains or when it is sent.
- Nobody sees another person's reminder or history; administrators do not get a view of them.
- Nothing goes to the activity log (as in the reminders design).

## Approaches

- **Chosen: C with B's history panel.** The slim week bar puts writing near the top, the figures stay in view, and the
  reminder becomes a small card with a clear label.
- Considered: A (the reminder as a line in the week header, history in a centred pop-up): smallest change, but keeps
  the tall header and mixes the reminder with the week.
- Considered: B alone (the reminder card above the figures): pushes the figures down, though they are read every week
  and the reminder is set once.

## Calls made (the owner may change these)

- The week strip starts closed and does not remember being opened.
- The downloaded file uses `METHOD:PUBLISH` with the same UID as the emailed series. Whether Outlook 2016 and 2021 then
  apply later emailed updates and cancellations to a downloaded copy is not known; check before release.
- Events are kept for the life of the tracker (removed with it); no separate clean-up.
- The deadline pill counts only automatic sending; a manual send does not change it.

## Left to the builder

Markup and class names, the event table's name and shape, the route for the no-JavaScript history page, and how the
sticky right column clears the top bar, as long as the behaviour above holds, the page passes the Content Security
Policy, and every new string is British English without contractions.
