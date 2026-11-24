# Weekly update page layout D Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the Weekly update tab as design D: a slim week bar with the deadline, figure tiles on top, Commentary
and a Calendar reminder card side by side, a Past updates table, an `.ics` download, and a history side panel backed by
an event log.

**Architecture:** Server-rendered Jinja page (`tracker/templates/entries/inputs.html`) with page script
`tracker/static/inputs.js`. A new table `calendar_reminder_events` records what happened to each person's reminder;
`tracker/calendar_invites/service.py` writes it. The history side panel reuses the permission sets drawer
(`dialog.perm-drawer`, `.drawer-head`, `.drawer-body`, `.set-panel`) and fetches an HTML fragment. Both tables use the
standard table toolkit (`tracker/templates/lists/_table.html`, `tracker/static/lists.js`).

**Tech Stack:** Flask, Jinja, SQLAlchemy, Alembic, PostgreSQL, vanilla ES5, CSS; pytest + Playwright.

**Spec:** `docs/superpowers/specs/2026-11-24-weekly-update-layout-design.md` (and, for what the reminder sends,
`docs/superpowers/specs/2026-11-18-calendar-reminders-design.md`). Canvas: https://claude.ai/artifact/8ZzVkrKuQ2oG3YniUeymE3
(artboards `D-page` and `B-history`).

## Global Constraints

- Strict Content Security Policy: no inline script or style, no `style=` attributes. ES5 page scripts. British English,
  no contractions. Copy exactly as in the spec and in this plan.
- Colours, borders and boxes from `docs/design-rules.md` and the tokens in `tracker.css`; reuse existing classes
  (`.access-tiles`/`.access-tile`, `.access-card-head`, `.count-pill`, `.badge`, the drawer classes, the toolkit) before
  adding new ones. Light and dark both work.
- Only editors, owners and the person in charge see the reminder card, the download and the history; a person only
  ever sees their own reminder and events. Nothing goes to the activity log.
- Tables: the toolkit's search, chips with counts, sortable headings, "Showing … of …" footer, paging past 25, cards on a
  phone (`card-rows`), `Clear filters`, the no-match line.
- Tests: browser files start `pytestmark = pytest.mark.browser`, sign in with `browser_sign_in`, add `RECORDER`, end with
  `window.__csp == []` and `window.__errors == []`. Mail is captured with `monkeypatch.setattr(smtp, "send_message",
  sent.append)`, and "email set up" is arranged as in `tests/test_calendar_reminder_routes.py`. Run with
  `M=/mnt/c/Users/AlexKrovina/Documents/GitHub/tc-trackers; $M/.venv/bin/python -m dotenv -f $M/.env run --
  $M/.venv/bin/pytest <tests> -n 6 -q` (Bash sandbox disabled). Per task run that task's tests plus
  `tests/test_templates.py` (7 failures for `mail/access/*.html` exist on main and are not this work).

## Review Focus

- A week whose send already went out, a week far in the future, a week whose send time has passed without a send, and
  a tracker with automatic sending off each show the right deadline text (not a wrong "today").
- The event log never shows another person's events; the panel and the download refuse viewers (404, as every tracker
  route does) and an archived tracker (no card, the routes refuse as the other reminder routes do).
- A failed send, an update with nothing changed ("Email it again") and a cancellation after losing edit rights each
  leave one event with a detail a person understands.
- Opening the history panel twice, or after Remove/Email it again redirects back, sets up its table once and never
  writes to the address.
- The Past updates table with a week that was written without a status, and a week never written, shows each in the
  right chip and with "None" / "–" where the spec says.

Plan rulings:
- **P1:** the toolkit can only mark an ascending default sort, so the History and Past updates rows are rendered newest
  first by the server and their When / Week ending headings carry no default marker (sortable, `aria-sort` none until
  clicked). The spec's "newest first by default" holds for what a person sees.
- **P2:** a week whose send time has passed with no report sent shows "Report was due on Fri 20 Nov at 17:00" (muted).
  The spec does not cover it.
- **P3:** the downloaded file's `ORGANIZER` is the sending address when set, else the person's own address (email may
  not be set up).

---

### Task 1: The event log and the `.ics` download

**Files:** Modify `tracker/models.py`, `tracker/calendar_invites/service.py`, `tracker/calendar_invites/ics.py`,
`tracker/entries/views.py`; create `migrations/versions/0013_calendar_reminder_events.py` (revision `"0013"`, down
`"0012"`); tests `tests/test_calendar_reminders.py`, `tests/test_calendar_reminder_routes.py`,
`tests/test_calendar_ics.py`, new `tests/test_migration_0013.py` (same style as `test_migration_0012.py`).

**Interfaces (produced):**
- Model `CalendarReminderEvent` (`calendar_reminder_events`): `id` identity PK; `user_id` FK users CASCADE; `tracker_id`
  FK trackers CASCADE; `at` timestamptz default now; `kind` text, check in `('switched_on', 'switched_off', 'sent',
  'updated', 'cancelled', 'failed', 'downloaded')`; `detail` text default `''`; index `(user_id, tracker_id, at)`.
- `EVENT_LABELS: dict[str, str]` in `service.py`: switched_on "Switched on", switched_off "Switched off", sent "Invite
  sent", updated "Update sent", cancelled "Cancellation sent", failed "Sending failed", downloaded "Downloaded".
- `EVENT_GROUPS: dict[str, str]`: sent/updated/cancelled → `"sent"`, failed → `"failed"`, downloaded → `"download"`,
  switched_on/switched_off → `"change"`.
- `record_event(session, user_id: int, tracker_id: int, kind: str, detail: str = "") -> None` (adds, does not commit).
- `events_for(session, user_id: int, tracker_id: int) -> list[CalendarReminderEvent]`, newest first.
- `describe_series(series: Series) -> str` in `ics.py`: `"Fridays, 08:45 to 09:00 (London time), 2 Oct – 18 Dec 2026"`
  (weekday plural from `series.weekday`; the place is the time zone's last part with `_` as spaces; dates `d Mon`, the
  year once at the end, or on both when they differ).
- `build_calendar(..., method: Literal["REQUEST", "CANCEL", "PUBLISH"], ...)`: PUBLISH omits `ATTENDEE`, keeps
  `ORGANIZER`, `UID`, `SEQUENCE`, the `VALARM`.
- Route `GET /trackers/<id>/calendar-reminder.ics` (`entries.calendar_reminder_ics`, `require_tracker_role("editor")`,
  refuses an archived tracker like the other reminder routes).

- [ ] Tests first:
  - Events: switching on records `switched_on` "By you"; off records `switched_off` "By you"; a first send records
    `sent` with `describe_series(...)` as detail; a rename then sync records `updated` "Tracker renamed" (dates →
    "Dates changed", weekday → "Week-ending day changed", zone → "Time zone changed", several → joined with "; ",
    `force` with no change → "Sent again"); archiving then sync records `cancelled` "Tracker archived" (lost rights →
    "Edit rights removed", inactive person → "Account not active", switched off → "Switched off"); a failed delivery
    records `failed` with the error text (at most 200 characters); `events_for` returns only that person's events for
    that tracker, newest first.
  - Download: an editor gets 200, `Content-Type` starting `text/calendar`, `Content-Disposition: attachment;
    filename="Laptop refresh reminder.ics"` (characters outside letters, digits, spaces, `-` and `_` removed), body with
    `METHOD:PUBLISH`, the same `UID` as the emailed series and no `ATTENDEE`; it works with email not set up (organizer
    the person's address); it records one `downloaded` event with the file name; a viewer gets 404; an archived
    tracker is refused as the other routes do.
  - `describe_series` for a London tracker over one year and one spanning two years; `build_calendar` with PUBLISH.
  - Migration up and down.
- [ ] Implement; run the four test files plus `tests/test_migration_matches_models.py tests/sched
  tests/test_templates.py`; commit `feat: calendar reminder event log and an .ics download`.

### Task 2: The history side panel

**Files:** Create `tracker/templates/entries/_reminder_history.html` (macro), `tracker/templates/entries/
reminder_history.html` (no-JavaScript page), `tracker/static/reminder-history.js`; modify `tracker/entries/views.py`,
`tracker/static/tracker.css` (only if the drawer classes need a page-neutral alias); tests
`tests/test_calendar_reminder_routes.py`, new `tests/test_reminder_history_browser.py`.

**Interfaces:**
- Consumes: Task 1's `events_for`, `EVENT_LABELS`, `EVENT_GROUPS`, `describe_series`, the download route.
- Produces: `GET /trackers/<id>/calendar-reminder/history` (`entries.calendar_reminder_history`, full page) and
  `GET /trackers/<id>/calendar-reminder/history/panel` (`entries.calendar_reminder_history_panel`, the fragment, no
  base layout); both `require_tracker_role("editor")`. A trigger element `[data-history-url]` on the page opens the
  panel (Task 3 places it).

- [ ] Tests first (server): both routes 404 for a viewer; the panel shows only the person's own events; the summary
  reads "On · up to date" (sent and nothing pending), "On · not sent yet", or "Off", with `describe_series` and "Next:
  Fri 27 Nov 2026" (the next week ending from today, none after the last); the table has one row per event with
  `data-status` = its group, `data-search` = label + detail lowercased, `data-sort-when` = ISO timestamp,
  `data-sort-what` = label, rows newest first (ruling P1), the chips All / Sent / Failed / Downloads with counts, the
  footer "Showing N of N events" (noun "event" for one), "No events match." with Clear filters; in the panel the table
  carries `data-no-address` and `data-state-prefix="history-"`; the full page does not carry `data-no-address`.
- [ ] Tests first (browser, `tests/test_reminder_history_browser.py`): clicking History opens `dialog.perm-drawer` with
  the title "Calendar reminder" and "<tracker> · sent to <email>"; search and chips filter and the count follows;
  When sorts both ways; the address does not change; Escape, ✕ and the backdrop close it and return focus to History;
  opening it twice sets up the table once (`data-table-ready`); the ⋯ menu offers "Download invite (.ics)", "Email it
  again" and "Switch the reminder off…" (the last confirms with "Switch the calendar reminder off? A cancellation is
  sent to Outlook." and posts the existing switch route); without JavaScript History goes to the full page.
- [ ] Implement following `permsets.js` (fetch with `X-Requested-With: fetch`, insert, `window.trackerLists.setUp`,
  focus return) and the holders panel markup; event times shown as `23 Nov 2026, 16:06` in the tracker's time zone.
- [ ] Run `tests/test_calendar_reminder_routes.py tests/test_reminder_history_browser.py tests/test_lists_browser.py
  tests/test_templates.py`; commit `feat: calendar reminder history in a side panel`.

### Task 3: Layout D: week bar, figure tiles, Commentary and the reminder card

**Files:** Create `tracker/entries/week_bar.py`; modify `tracker/entries/views.py` (`_render_inputs`),
`tracker/templates/entries/inputs.html`, `tracker/static/inputs.js`, `tracker/static/tracker.css`; tests
`tests/test_week_bar.py` (no database), `tests/test_calendar_reminder_routes.py`, `tests/test_calendar_reminders_browser.py`,
`tests/test_inputs_targets_browser.py`, `tests/test_entries.py` (where they assert the old markup).

**Interfaces:**
- Consumes: Task 1's download route, Task 2's `[data-history-url]` behaviour.
- Produces: `deadline(tracker: Tracker, week: date, sent_at: datetime | None, now_utc: datetime) -> tuple[str, str]` in
  `week_bar.py` (text, tone `"warning"` or `"muted"`); `week_state(row: ReportInput | None) -> str`.

- [ ] Tests first (`tests/test_week_bar.py`): with sending on and the week's send ahead: "Report goes out today at
  17:00", "Report goes out tomorrow at 17:00", "Report goes out on Fri 27 Nov at 17:00" (tone warning; times in the
  tracker's zone, the send being the week-ending day at `send_time`); with `sent_at`: "Report sent on Fri 20 Nov at
  17:02" (muted); sending off: "Automatic sending is off" (muted); send time passed, nothing sent: "Report was due on
  Fri 20 Nov at 17:00" (muted, ruling P2). `week_state`: "Not written yet", "Written · Amber", "Written · status not set".
  `sent_at` is the latest `ReportSend.sent_at` with `status == "sent"` for that week, scheduled sends only.
- [ ] Tests first (page): the week bar has the week button with `aria-expanded`/`aria-controls`, the state and deadline
  pills, ‹ Latest week ›; without JavaScript the week strip shows; with it the strip starts hidden and the button opens
  it. Six tiles in `.access-tiles` with the labels and values of the spec (Done this week "42" / "of 40 · +2 against
  target"; Completed / "64% · 182 left"; Rate (3 weeks) / "a week · 31 needed"; Forecast / "Target 18 Dec · 7 days
  early"; Next week's target / "Week ending 27 Nov"; Red risks / "1 past its target date", linking to Risks), sub-lines
  `tone-success` / `tone-danger` where ahead or behind, `–` where a figure is missing; the old "This week's figures"
  panel is gone. Commentary and Calendar reminder headings use `.access-card-head`; the preview sits inside the
  Commentary card. The reminder card: pill "On"/"Off", the checkbox `#calendar-reminder` "Email me an Outlook
  reminder" / "08:45 on each week-ending day", "Next: Fri 27 Nov, 08:45" and "Last sent: 23 Nov 2026" (or "Not sent
  yet" / "Email is not set up in this application yet"), Download .ics (link to the Task 1 route), Email it again (only
  when sent), History (`[data-history-url]`); the unsaved-text guard still blocks the checkbox and Email it again; at
  1000 px and wider the two cards sit side by side, narrower they stack; nothing in the layout is sticky except the
  existing Save bar; no sideways scroll at 390 px.
- [ ] Implement; remove the week-header reminder line and its CSS.
- [ ] Run the listed tests plus `tests/test_templates.py`; commit `feat: Weekly update layout D: week bar, figure tiles,
  Commentary and the reminder card`.

### Task 4: Past updates table

**Files:** Modify `tracker/entries/views.py`, `tracker/templates/entries/inputs.html`, `tracker/static/tracker.css`
(only if needed); load `lists.js` on the page; tests `tests/test_entries.py` (server) and a browser test in
`tests/test_inputs_targets_browser.py`.

- [ ] Tests first: under the two cards a card "Past updates" with `.count-pill` = the number of weeks before the shown
  week, note "Each week's commentary as the report showed it."; toolkit search "Search updates", chips All / Green /
  Amber / Red / Not written with counts (`data-status` green/amber/red/unwritten; a week written without a status gets
  `nostatus`, counted only in All); columns Week ending (sortable, date), Status (badge with the RAG dot, "Not written"
  muted, "Status not set" muted), Headline ("–" when not written), Needed from you ("None" when written and blank, "–"
  when not written), Prepared by (full name or "–"), and Open (link to that week); rows newest first (ruling P1); footer
  "Showing N of N weeks" ("week" for one); paging past 25; phone cards; the table id `past-updates` with
  `data-state-prefix="past-"`; the first week of a tracker shows the card with "No earlier weeks yet." instead of a
  table. Browser: search and a chip filter the rows and the count; Clear filters resets; Open goes to that week.
- [ ] Implement; run the listed tests plus `tests/test_lists_browser.py tests/test_templates.py`; commit `feat: Past
  updates table on the Weekly update tab`.

### Finish

- [ ] Full suite once (`-n 6`), ruff; screenshots of the page (light, dark, 390 px) and the panel; push and open the PR.
