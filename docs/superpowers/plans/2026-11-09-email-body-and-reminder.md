# Email Body, Person in Charge and Reminder Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The report email's message becomes a short status sheet (figures, this week, needed from you, risks, a
two-axis chart); each tracker has a person in charge who is reminded 24 hours before the automatic send when the
update is missing; the Email page shows the subject as text.

**Architecture:** Four block placeholders rendered from a Jinja macro file (`mail/_blocks.html`) and inserted unescaped
by `render_placeholders`; a new `email_chart` in `report/charts.py`; migration 0009 adds `trackers.lead_user_id`,
`report_reminders` and removes saved bodies equal to the old default; the scheduler cycle sends reminders.

**Tech Stack:** Flask 3.1, SQLAlchemy 2, Jinja, Alembic, matplotlib, pytest, Playwright.

**Spec:** docs/superpowers/specs/2026-11-09-email-body-and-reminder-design.md

## Global Constraints

- Figure order: Next week's target, Needed per week, Target finish, Forecast finish, Status. Missing value "Not set".
- Colours (mail): red #b8283f on #fbe5e9, green #087553 on #e3f4ec, amber #9a5b00 on #fdf1dc, grey outline #9aa5b8,
  "No status" grey #5d6b83 on #f1f3f7.
- No update: "No update was written for this week." Heading "Risks: N". Risk table columns RAG, Ref, Risk, Owner, Due.
- Field label "Person in charge"; reminder 24 hours before the next automatic send; one per tracker and week.
- Targeted tests only: run the files each task names.

## Review Focus

- A tracker with no unit label: figures read "4" and "4.8", never a trailing space or "None".
- Owner text containing `<script>` or `&` in the headline, decisions or a risk description is escaped in the email
  and the preview.
- A risk raised this week that is outside the top three still appears, marked NEW, without duplicating a top risk.
- A reminder is never sent for a week whose update exists, for a disabled schedule, an archived tracker, or twice.
- The Settings form posted without the person-in-charge field (older forms, other tests) keeps the stored value.

---

### Task 1: Schema — person in charge, reminders, old default bodies

**Files:** `migrations/versions/0009_lead_and_reminders.py`, `tracker/models.py`, `tests/test_migration_0009.py`

- Produces: `Tracker.lead_user_id: int | None` (FK users, ON DELETE SET NULL); `ReportReminder(tracker_id, week_ending,
  sent_at, recipients: list[str])`, PK `(tracker_id, week_ending)`, FK tracker ON DELETE CASCADE.
- Upgrade backfills `lead_user_id` from the single direct owner (exactly one `tracker_roles` owner) and deletes
  `email_templates` rows whose `body_html` equals the old default body (whitespace-insensitive).
- Test: downgrade to 0008, insert a tracker with one direct owner, one with two, a template with the old default and
  one custom; upgrade; assert lead set only on the first and only the default template removed. Model-vs-migration
  test stays green.

### Task 2: The message blocks and the two-axis chart

**Files:** `tracker/report/build.py` (`Report.new_risks`), `tracker/report/charts.py` (`email_chart`),
`tracker/mail/compose.py`, `tracker/templates/mail/_blocks.html`, `tracker/templates/mail/email_body.html`,
`tracker/static/email-preview.css`, `tracker/static/email.js`, tests in `tests/test_mail.py`, `tests/test_report.py`.

- `Report.new_risks: list[Risk]` (open, raised in the week); `new_risk_rags` keeps its meaning.
- `BLOCK_PLACEHOLDERS = ("figures", "this_week", "needed_from_you", "risks")`, all in `PLACEHOLDERS`;
  `placeholder_context` gains them as HTML strings; `render_placeholders` inserts them unescaped; `render_subject`
  replaces them with nothing. `DEFAULT_BODY = "{{figures}}\n{{this_week}}\n{{needed_from_you}}\n{{risks}}\n"`.
- `email_chart(rows, unit_label, report_week, fmt="png") -> bytes` replaces `remaining_chart` in the email and preview.
- `html_to_text` separates table cells. email.js inserts block values unescaped (list passed from the page).
- Tests: figure order and colours (red next week below needed, green forecast before target, red after, plain when
  missing, Not set), bullets per line, no-update sentence, needed part omitted when empty, risk table with NEW for a
  fifth new risk, no risks part with none open, escaping of `<b>` in all owner text, no unit, subject ignores blocks,
  chart returns PNG bytes for empty and real rows.

### Task 3: The Email page shows the subject as text

**Files:** `tracker/templates/mail/settings.html`, `tracker/mail/views.py`, `tracker/static/email.js`,
`tests/test_mail.py`, `tests/test_email_settings_browser.py`.

- The subject shows as text (the rendered subject) with the note, the admin link for `manage_email_settings` holders,
  a hidden `#subject` carrying the template for the live preview; new section text.

### Task 4: Person in charge on Settings and at creation

**Files:** `tracker/auth/roles.py` (`give_creator_ownership` sets the lead; `lead_candidates`, `lead_in_charge`),
`tracker/trackers/views.py`, `tracker/templates/trackers/settings.html`, `tracker/templates/mail/settings.html`,
tests in `tests/test_trackers.py` (or the settings test file).

- `lead_candidates(session, tracker) -> list[User]` (active, editor or owner by any route, by name);
  `lead_in_charge(session, tracker) -> User | None` (the lead when still a candidate).
- Settings: a select `lead_user_id`; posted blank → 400 "Choose the person in charge."; not a candidate → 400;
  absent → unchanged; change audited in `settings_updated` as `lead` [old name, new name].
- Warning on Settings and Email pages when `lead_in_charge` is None.

### Task 5: The reminder

**Files:** `tracker/sched/reminders.py`, `tracker/sched/runner.py`, `tracker/templates/mail/reminder.html`,
`tracker/activity/labels.py`, `tests/sched/test_reminders.py`.

- `due_reminders(session, now_utc) -> list[tuple[int, date]]`: active, scheduled trackers whose next send is in
  `(now, now + 24h]`, with no reminder row and no written headline for that week.
- `send_reminder(session, tracker_id, week_ending, now_utc)`: claims the row, emails the person in charge (else direct
  owners), records `report_reminder_sent`; on failure removes the claim and logs.
- Tests: due inside 24 h, not due at 25 h, not when written, not twice, not when off or archived, fallback recipients,
  failure retried.
