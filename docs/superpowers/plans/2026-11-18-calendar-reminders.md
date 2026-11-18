# Calendar reminders by email invitation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A person who can write a tracker's weekly update can switch on a calendar reminder; the application emails
them a calendar invitation for a weekly 08:45 series and keeps it up to date (updates and cancellations).

**Architecture:** A pure iCalendar builder (`tracker/calendar_invites/ics.py`) makes the invitation text and email; a
table `calendar_reminders` remembers each person's switch and what was last sent; a sync service
(`tracker/calendar_invites/service.py`) compares that with the tracker and the person's rights and sends a request,
update or cancellation; it runs when the switch changes and in every scheduler cycle. The switch lives on the
Weekly update tab.

**Tech Stack:** Flask, Jinja, SQLAlchemy, Alembic, PostgreSQL, Python `email` and `zoneinfo`; pytest + Playwright. No new
dependency.

**Spec:** `docs/superpowers/specs/2026-11-18-calendar-reminders-design.md`

## Global Constraints

- Series: weekly on the tracker's week-ending day, from `first_week_ending` to `last_week_ending`, 08:45 to 09:00 in
  `tracker.send_timezone`, `TRANSP:TRANSPARENT`, `VALARM` `ACTION:DISPLAY` `TRIGGER:PT0M`, `ORGANIZER` = the configured
  sender address (`get_smtp_config()["from_"]`), one `ATTENDEE` = the person with `RSVP=FALSE`.
- Title (`SUMMARY`): `Write the weekly update: <tracker name>`. Email subject: `Calendar reminder: <tracker name>`
  (request and update) and `Calendar reminder cancelled: <tracker name>` (cancellation).
- Link (`URL` and in `DESCRIPTION`): the absolute URL of `entries.inputs` for the tracker, without `week=`.
- `UID`: `tracker-<tracker id>-user-<user id>@tc-trackers`, stable for the life of the row. An update or a cancellation
  is the same `UID` with a higher `SEQUENCE`. `SEQUENCE` rises only after a successful delivery.
- iCalendar text: CRLF line endings, lines folded at 75 octets (UTF-8 safe), `\`, `;`, `,` and newlines escaped in
  text values. `UNTIL` in UTC (`Z`).
- Only people with `user_role(session, user, tracker_id) in ('editor', 'owner')` may switch it on and receive it; an
  archived tracker or a person whose status is not `active` receives a cancellation.
- Nothing is written to the activity log.
- Strict CSP (no inline script or style, no `style=`), ES5, British English, no contractions.
- Tests: browser files start `pytestmark = pytest.mark.browser`, sign in with `browser_sign_in`, add `RECORDER`, end with
  `window.__csp == []` and `window.__errors == []`. Mail is captured with
  `monkeypatch.setattr(smtp, "send_message", sent.append)` as in `tests/sched/test_reminders.py`. Run with
  `M=/mnt/c/Users/AlexKrovina/Documents/GitHub/tc-trackers; $M/.venv/bin/python -m dotenv -f $M/.env run --
  $M/.venv/bin/pytest <tests> -n 6 -q` (Bash sandbox disabled). Per task run only that task's tests plus
  `tests/test_templates.py`.

## Review Focus

- Switching on, off and on again, or "Send it again", never gives a second series: same `UID`, higher `SEQUENCE`.
- A tracker name with commas, semicolons, a backslash, non-ASCII letters and over 75 octets survives escaping and
  folding intact.
- Week endings either side of a summer-time change keep 08:45 local time (`VTIMEZONE` correct for the whole span).
- A cancellation (archived, lost rights, disabled person) goes out once, not in every scheduler cycle; restoring the
  tracker with the switch still on sends a request again.
- A failed delivery changes nothing remembered and is retried at the next cycle.

Plan note: the application has no way to delete a tracker (only archive), so the spec's "deleted" case is covered by
archiving; the table's foreign keys cascade so a database-level delete leaves no orphan rows.

---

### Task 1: The invitation builder and a test-invitation command

**Files:** Create `tracker/calendar_invites/__init__.py`, `tracker/calendar_invites/ics.py`; modify `tracker/app.py`
(one CLI command); test `tests/test_calendar_ics.py` (no database).

**Interfaces (produced):**
- `@dataclass(frozen=True) class Series: tracker_id: int; user_id: int; name: str; weekday: int; first: date;
  last: date; tz: str; url: str` and `Series.uid -> str` (property, the format above).
- `series_for(tracker: Tracker, user: User, url: str) -> Series`.
- `fingerprint(series: Series) -> dict` — `{"name", "weekday", "first", "last", "tz"}` (dates ISO), stored to detect
  changes.
- `build_calendar(series: Series, organizer: str, attendee: str, method: Literal["REQUEST", "CANCEL"], sequence: int,
  now_utc: datetime) -> str` — the full `VCALENDAR` text.
- `build_invite_email(series, organizer, attendee, method, sequence, now_utc) -> EmailMessage` — `To` the attendee,
  the subject above, a short plain-text body and HTML body (the link, "Outlook adds this to your calendar; it is
  updated or removed automatically."), and the calendar as a `text/calendar; method=<METHOD>; charset=UTF-8` part
  (also attached as `invite.ics`), which Outlook 2016 and 2021 process as a meeting item.

- [ ] Tests first (`tests/test_calendar_ics.py`): CRLF only; no line over 75 octets and unfolding restores the
  original (use a name of 120 characters with `é` and `—`); `SUMMARY:Write the weekly update: A\, B\; C\\ D` for name
  `A, B; C\ D`; `DTSTART;TZID=Europe/London:20261016T084500`, `DTEND` 09:00; `RRULE:FREQ=WEEKLY;UNTIL=` the last week
  ending 08:45 London in UTC with `Z`; a `VTIMEZONE` with `TZID:Europe/London` whose components give +01:00 before 25
  Oct 2026 and +00:00 after (a tracker from 2 Oct to 27 Nov 2026); the same for `Australia/Sydney` (southern summer);
  `TRANSP:TRANSPARENT`; `BEGIN:VALARM`, `ACTION:DISPLAY`, `TRIGGER:PT0M`; `ATTENDEE;RSVP=FALSE...:mailto:` the person;
  `ORGANIZER` the sender; `METHOD:REQUEST` and `SEQUENCE:3` when asked; `METHOD:CANCEL` with `STATUS:CANCELLED`; the
  `UID` format; `fingerprint` changes when the name, either date, the weekday or the time zone changes and not
  otherwise; the email has the `text/calendar; method=REQUEST` part and the subject.
- [ ] Implement. `VTIMEZONE`: list the zone's offset changes between 1 January of the first year and 31 December of the
  last year with `zoneinfo` (one `STANDARD` or `DAYLIGHT` component per change with its own `DTSTART`, plus one for
  the offset in force at the start), no `RRULE` inside the zone.
- [ ] Add `flask calendar-test-invite --to EMAIL --tracker ID --method REQUEST|CANCEL --sequence N [--name TEXT]` in
  `tracker/app.py`: builds the series for that tracker (attendee = `--to`, the name replaced by `--name` when given) and sends it with `smtp.send_message`. This
  is for the owner's pre-build check; it changes no data.
- [ ] Run `tests/test_calendar_ics.py tests/test_templates.py`; commit `feat: calendar invitation builder and a test
  invitation command`.
- [ ] **Owner check (stop here):** the controller sends a request, then the same `UID` with `SEQUENCE` 1 after
  with a different `--name`, then a
  `CANCEL`, to the owner, and waits for the owner's result in Outlook 2016 and 2021. Continue only on their go-ahead.

### Task 2: Remembering reminders and keeping them in step

**Files:** Modify `tracker/models.py`; create `migrations/versions/0012_calendar_reminders.py` (revision `"0012"`,
down `"0011"`), `tracker/calendar_invites/service.py`; modify `tracker/sched/runner.py`; test
`tests/test_calendar_reminders.py` (database).

**Interfaces:**
- Consumes: Task 1's `series_for`, `fingerprint`, `build_invite_email`.
- Produces: model `CalendarReminder` (`calendar_reminders`): `user_id` (FK users, CASCADE) and `tracker_id` (FK
  trackers, CASCADE) as the primary key; `enabled: bool`; `sequence: int` default 0; `sent_state: str` in
  `('none', 'sent', 'cancelled')` (check constraint) default `'none'`; `sent_fingerprint: dict | None` (JSONB);
  `sent_at: datetime | None`; `last_error: str | None`.
- `wanted(session, row: CalendarReminder) -> bool` — `row.enabled` and tracker active and
  `user_role(...) in ('editor', 'owner')`.
- `sync_reminder(session, row: CalendarReminder, now_utc: datetime, force: bool = False) -> Literal["request",
  "update", "cancel", None]` — wanted and `sent_state != 'sent'` → request; wanted and sent with a different
  fingerprint (or `force`) → update; not wanted and `sent_state == 'sent'` → cancel; otherwise nothing. On success:
  `sequence += 1` (the first request uses 0), state, fingerprint (None after a cancel), `sent_at`, `last_error=None`,
  commit. On a delivery failure: record `last_error`, commit, re-raise nothing (return None).
- `sync_all(session, now_utc) -> int` — every row with `enabled` or `sent_state == 'sent'`; returns the number sent.
- `run_scheduler_cycle` calls `sync_all` in its own `try`/`except` with a log line, like the update reminders.

- [ ] Tests first: switching on (`enabled=True`, then `sync_reminder`) sends one REQUEST with `SEQUENCE:0`; a second
  `sync_reminder` sends nothing; renaming the tracker then `sync_all` sends an update with `SEQUENCE:1` and the same
  `UID`; changing `last_week_ending` likewise; archiving sends one CANCEL and a second cycle sends nothing; restoring
  to active sends a REQUEST with a higher `SEQUENCE`; dropping the person to viewer cancels; a disabled person
  cancels; `enabled=False` cancels; a never-sent row switched off sends nothing; a delivery that raises leaves
  `sent_state`, `sequence` and `sent_fingerprint` unchanged, records `last_error`, and the next cycle sends it;
  `force=True` on a sent row sends an update with a higher `SEQUENCE`; `run_scheduler_cycle` sends a due update.
- [ ] Implement, with the migration (create table, check constraint, index on `tracker_id`; downgrade drops it).
- [ ] Run `tests/test_calendar_reminders.py tests/sched tests/test_migrations*.py tests/test_templates.py` (find the
  migration test file by `ls tests | grep -i migra`); commit `feat: calendar reminders are remembered and kept in step
  with the tracker`.

### Task 3: The switch on the Weekly update tab

**Files:** Modify `tracker/entries/views.py` (the `inputs` view passes the person's row), `tracker/templates/entries/
inputs.html`, `tracker/static/tracker.css`; add routes (in `tracker/entries/views.py` or a small
`tracker/calendar_invites/views.py` blueprint, registered in `tracker/app.py`); tests `tests/test_calendar_reminders.py`
(routes) and `tests/test_calendar_reminders_browser.py`.

**Interfaces:**
- Consumes: Task 2's `CalendarReminder`, `sync_reminder`.
- Produces: `POST /trackers/<id>/calendar-reminder` (form field `enabled` = `on` or absent, CSRF) and
  `POST /trackers/<id>/calendar-reminder/resend`; both editor or owner only (403 otherwise, 404 for an unknown
  tracker), both redirect to `entries.inputs` for the tracker (keeping `week=` if posted).

- [ ] Tests first: a viewer sees no panel and gets 403 from both routes; an editor sees the panel with the switch off
  and the copy "Remind me at 08:45 on each week-ending day"; switching on sends one REQUEST, flashes "Calendar reminder
  sent to <email>." and the panel then reads "Sent to <email> on <d Mon YYYY>." with "Send it again"; switching off
  sends one CANCEL and flashes "Calendar reminder switched off. A cancellation was sent to <email>."; "Send it again"
  sends an update (same `UID`, higher `SEQUENCE`) and flashes "Calendar reminder sent again to <email>."; a delivery
  failure flashes "The calendar reminder could not be sent now. It will be tried again shortly." and the panel shows
  "Not sent yet"; an archived tracker shows no switch. Browser: the switch works with and without JavaScript, the
  panel is reachable by keyboard, CSP and error recorders stay empty.
- [ ] Implement: a "Calendar reminder" panel under the update form; the switch is a checkbox in a small form with a
  Save button hidden when JavaScript posts on change (in the page's existing script file, ES5).
- [ ] Run the two test files plus `tests/test_inputs_targets_browser.py tests/test_templates.py`; commit `feat: a
  calendar reminder switch on the Weekly update tab`.

### Finish

- [ ] Full suite once (`-n 6`), ruff; screenshots of the panel (off, on, failure) at 1440px light and dark and 390px;
  push and open the PR.
