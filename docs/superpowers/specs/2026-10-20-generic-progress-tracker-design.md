# Generic progress tracker: design

Date: 2026-10-20
Status: draft for approval
Working name: TC Trackers (the first tracker is "TC Windows 11 migration")

## 1. Intent

The TC Windows 11 migration (upgrading Windows 10 thin clients to Windows 11) is currently run from an Excel workbook (`TC_Win11_Migration_CTO_Report_Template_v2_27.xlsx`). Each week a person enters progress figures, the workbook calculates the position and a forecast completion date, and the person emails the workbook with a pasted picture of its Dashboard sheet to the project owner, the CTO and the PMO.

The goal is a web application that does the same job without the spreadsheet: people record progress as it happens, the application calculates the position and the forecast from history, and it produces and emails the weekly report automatically.

The same pattern applies to many other pieces of IT work: licensing, Windows 11 updates, patching, security vulnerabilities, asset management, websites, and anything else with a quantity to complete and track. The application is therefore generic from the start: a user defines a tracker (what is being counted and how it is grouped), and TC Windows 11 is set up as the first tracker. It is not a special case in the code.

### What success looks like

- The TC Windows 11 tracker reproduces everything the workbook does (inputs, calculations, forecast, report) with its history imported, and the weekly email goes out without anyone opening Excel.
- A second tracker of a different kind (for example, licences by team) can be created through the application, with no code change.
- The demo runs on Render with a Supabase database, and moving to a Tradition-hosted Postgres server later is a change of connection string plus a standard dump and restore.

## 2. Goals, non-goals and anti-goals

### Goals

1. Multiple trackers, each defined by users: name, the unit being counted, the grouping label, groups, scope, settings, recipients, email template and schedule.
2. Progress recorded per group per week; group and tracker totals derived from those entries, never typed twice.
3. The workbook's calculations reproduced exactly (section 6), with the week-ending date correction (section 6.1).
4. A weekly report in the "answer first" layout (section 7), viewable in the application, downloadable as PDF and PNG, and emailed on a schedule.
5. Per-tracker access control, with Microsoft Entra ID single sign-on and local accounts.
6. Import of the existing TC Windows 11 workbook.

### Non-goals

- Tracking individual devices, licences or items. Trackers record quantities per group per week.
- An Excel export of the report.
- A combined email covering several trackers. Each tracker sends its own email.
- A separate report for the people whose devices are being upgraded. The recipients are the project owner, the CTO and the PMO.
- Report links that open without signing in.
- Weekly targets per group. Targets are one figure per week for the whole tracker.
- Scope that grows during a tracker. New work (a new patching cycle, a new batch of vulnerabilities) becomes a new tracker.

### Anti-goals (would make this a failure even if it works)

- Data entered twice (for example, a weekly figure and a separately typed location total that can disagree).
- A forecast that differs from the workbook's for the same data, without the difference being deliberate and documented.
- Code tied to Supabase-specific features, so that the move to plain Postgres becomes a rewrite.
- Several competing migration paths. There is one path: Supabase to Postgres.
- Over-engineering for the proof of concept: no features beyond this document.

## 3. Constraints

- **Language and framework:** Python and Flask.
- **Database:** Postgres. The demo uses Supabase as a hosted Postgres database; production moves to a Tradition-hosted Postgres server. The application connects directly to Postgres through one `DATABASE_URL` connection string. It does not use Supabase's REST API (PostgREST), Supabase Auth, Supabase Storage, Edge Functions, `pg_cron` or row-level security policies.
- **Hosting:** development and the proof of concept run locally in WSL. The demo is deployed to Render from GitHub, in the same way as the Everton dashboard.
- **Data:** the tracker data contains no customer information. The owner has confirmed that holding it on Render and Supabase is acceptable.
- **Email:** sent through Microsoft 365 (SMTP with XOAUTH2, falling back to plain SMTP), as in the capacity app.
- **Single sign-on:** Microsoft Entra ID requires an app registration with the Render URL as a redirect URI, which Tradition IT may need to approve. Local accounts must work on their own so that the demo is not blocked by that approval.
- **No customer, counterparty or personal data** beyond the users' own names and email addresses.

## 4. Building on existing projects

The application combines two existing projects of the owner's. Both are in `C:\Users\AlexKrovina\Documents\GitHub\`.

### From `everton-ticket-dashboard`

- The application factory and its security-headers hook, including the strict Content-Security-Policy (all scripts and styles served from `static/`, no CDNs).
- `config.py`: load and validate configuration at start-up, failing fast on missing values.
- The `base.html` layout, icon macros, CSS theme variables and dark mode.
- Tooling: `pyproject.toml` (ruff, Python 3.11, line length 120), `.sqlfluff` (Postgres dialect), the GitHub Actions workflow, and the `Procfile` (gunicorn).
- Not reused: its Supabase REST client, its single-user login and everything Everton-specific.

### From `capacity` (the copy in `Documents\GitHub\capacity`, which matches GitHub)

- Authentication: local bcrypt accounts, Microsoft Entra ID single sign-on through MSAL, the pending-approval flow for new users, CSRF protection and the `audit_log` pattern.
- The roles and permissions model, adapted to per-tracker roles (section 5.2).
- Scheduling: the `sched/` package (`schedules.py`, `calendars.py`, the planner and worker). This is more complete than the live APScheduler job runner, which the capacity app uses today, but nothing in the capacity app starts it yet. Its SQL lives in one file (`sched/repo.py`) and must be ported from SQLite to Postgres.
- Email: `emails.py` (SMTP and XOAUTH2 sending, the `email_queue` retry with backoff), database-stored templates with `{{placeholder}}` tokens, layouts, preview and test-send.
- The capacity app's conventions: request helpers in `web.py` to avoid circular imports, `SESSION_COOKIE_SAMESITE=Lax` for the single sign-on redirect, and a smoke script for each new screen.
- Not reused: SQLite and the hand-written migrations in `init_db()`. This application uses Alembic migrations against Postgres.

### New work neither project provides

Recipient lists with several recipients, PDF and PNG rendering of the report, charts embedded in email as images, PDF attachments, the tracker engine and calculations, and the workbook importer.

## 5. What the application holds

### 5.1 Trackers, groups and entries

- **Tracker.** Name; the unit being counted (for example "thin clients"); the grouping label (for example "Location"); a description; an overall status. A tracker is archived, not deleted.
- **Tracker settings** (the workbook's Settings sheet, adjusted per section 6.1):
  - week-ending day (for example Friday);
  - first week-ending date;
  - last week-ending date (at most 52 weeks after the first, as in the workbook);
  - target completion date;
  - quantity completed before the first week (the workbook's "devices deployed before first report");
  - moving-average period in weeks (default 3).
- **Groups** (locations for TC Windows 11). Users create, rename and retire groups. A retired group with entries keeps its history. Each group has:
  - baseline: the quantity in scope for that group;
  - "ready, not yet complete" quantity, entered as a snapshot (for TC Windows 11: "built on Windows 11, in stock");
  - planned completion date;
  - Red, Amber or Green status;
  - comment or exception.

  A correction to a baseline is allowed and recorded in the audit log; it is not reported as a scope change.
- **Completion entries.** Each entry records a group, a date, a quantity and an optional note, and is assigned to the week whose week-ending date is on or after the entry date. Several entries for the same group and week add together. Group "deployed" totals, tracker totals and weekly actuals are all derived from these entries.
- **Weekly targets.** One target quantity per week for the whole tracker.
- **Weekly report inputs** (the workbook's Report Inputs sheet), one set per week:
  - overall status (Green, Amber, Red);
  - headline (two or three sentences);
  - decisions or support required from senior managers;
  - prepared by (recorded automatically as the signed-in user).
- **Risks, issues and dependencies.** One register per tracker, with the workbook's fields: ID, description, impact on plan, group, owner role, date raised, target resolution date, status, Red, Amber or Green, and latest update. The report shows the three highest-priority open items; how priority is ordered is left to the builder (for example, Red before Amber, then earliest target date).

### 5.2 Users and access

- **Sign-in:** Microsoft Entra ID single sign-on, with local accounts as a fallback. New users wait for an administrator's approval.
- **Administrators** create trackers, manage users, assign roles and configure the email connection.
- **Per-tracker roles**, assigned by an administrator:
  - Viewer: sees the tracker and its reports.
  - Editor: also enters completions, targets, weekly report inputs and risks.
  - Owner: also changes settings, groups, recipients, email templates and schedules, and can send the report manually.
- A user sees only the trackers on which they hold a role. Administrators see all trackers.
- Every change to entries, scope, settings, recipients and sends is written to the audit log with the user and the time.

### 5.3 Home page

A list of the trackers the user can see, each showing status, % complete, forecast completion date against target, and the date of the last update.

## 6. Calculations

These reproduce the workbook. A builder should verify them against the workbook's formulas on the Settings, Weekly Tracker, By Location and Report Inputs sheets, and should write tests that compare the application's results with the workbook's for the imported TC Windows 11 data.

### 6.1 Weeks (a deliberate change from the workbook)

The workbook labels each week with a Monday report date and moves the first report date back to the previous report day. That is wrong. In the application:

- Each week is identified by its **week-ending date**, on the tracker's week-ending day.
- The first week is the first week-ending date on or after the date the tracker starts.
- An entry belongs to the week that ends on or after the entry date.
- The report for a week is produced on its week-ending date and covers all entries up to and including that day.
- A week still in progress is shown as in progress and is excluded from the moving average.

### 6.2 Per week, for the tracker

- Target: the entered weekly target.
- Actual: the sum of completion entries in that week (or the imported weekly actual, section 9).
- Variance: actual minus target.
- Cumulative target: the quantity completed before the first week plus the sum of targets to date.
- Cumulative actual: the quantity completed before the first week plus the sum of actuals to date.
- Planned remaining: the total in scope minus the cumulative target.
- Actual remaining: the total in scope minus the cumulative actual.
- % complete: the cumulative actual divided by the total in scope.
- Moving average: the mean of the actuals for the last N completed weeks, where N is the moving-average period. At the start, when fewer than N weeks exist, it averages the weeks available.
- Forecast remaining: equal to the actual remaining up to the latest week with an actual. After that, it falls by the forecast weekly rate each week, never below zero.

### 6.3 Per group

Baseline, deployed (the sum of the group's entries plus any imported starting figure), ready-not-complete, remaining (baseline minus deployed), % complete, planned completion date, Red, Amber or Green status, and comment. The tracker's total in scope is the sum of the group baselines.

### 6.4 Headline figures

- Forecast based on: the latest week that has an actual, or the report week if that is earlier.
- Forecast weekly rate: the moving average at that week.
- Planned completion date: the first week in which planned remaining reaches zero.
- Forecast completion date: if nothing remains, the "forecast based on" week; otherwise that week plus (remaining divided by the forecast rate, rounded up) weeks. Blank if the rate is zero.
- Supporting figures, from the Report Inputs sheet: this week's actual against target; next week's target; weeks left to the target date; the weekly rate required to meet the target date; forecast against target in days; and a data check that the tracker totals agree with the group totals.

## 7. The report

### 7.1 Layout: "answer first" (option B, chosen by the owner)

From top to bottom:

1. Title: tracker name and week-ending date.
2. Status band: the overall Red, Amber or Green status and a one-line verdict, for example "Forecast 3 weeks behind target". Below it: the forecast and target completion dates, the headline, and "Needed from you" (decisions or support required, or "None").
3. Chart: remaining over time, showing plan (dashed), actual (solid) and forecast (dotted) to zero.
4. Key figures: completed out of the total in scope with % complete; this week's actual against target; the forecast weekly rate (moving average).
5. Top three risks and blockers, with owner role, target date and Red, Amber or Green status, plus counts of open and Red items.
6. Details: the table of positions by group, the chart of weekly target against actual, and the chart of cumulative target against actual.

The mockups from the design discussion are in `.superpowers/brainstorm/` (file `cto-report-layout*.html`).

### 7.2 Formats

- **In the application:** the live report for any week, for users with at least Viewer access.
- **PDF:** the full report. It is downloadable and attached to the email.
- **PNG:** an image of the report, downloadable, for pasting into Teams or slides.
- **Email body:** sections 1 to 3 of the layout, with the chart as an inline image, and a link to the live report.
- **Links** to the live report always require sign-in.
- No Excel export.

The PDF, the PNG and the email body must render the same figures as the live report for the same week.

## 8. Email and scheduling

- **One email per tracker.** Each tracker has its own recipient list (managed in the application by the tracker's owners; recipients do not need a role on the tracker to receive it, but do need one to open the link), its own email template and its own schedule.
- **Templates** are edited in the application, as in the capacity app, with `{{placeholder}}` tokens for report values (for example `{{forecast_date}}`, `{{percent_complete}}`, `{{status}}`, `{{headline}}`, `{{report_link}}`), a preview and a test-send.
- **Schedule:** by default, the week-ending day at a set local time (for example 17:00 Europe/London), using the capacity app's schedule engine with time zones. Owners can also send the report manually, for example after correcting a figure.
- **Each send** is logged with its recipients, time and result; failed sends retry with backoff, as in the capacity app.
- The scheduled send must not send twice for the same tracker and week, even if more than one worker process is running.

## 9. Importing the TC Windows 11 workbook

The import is a **one-time cutover** (decided by the owner): the workbook is imported once and then retired. The importer creates a new tracker from the workbook (`TC_Win11_Migration_CTO_Report_Template_v2_27.xlsx`, or a later version of the same template); it does not update an existing tracker, so there are no merge rules. If an import needs to be redone, the imported tracker is archived and the import run again before any entries are recorded in the application. The importer imports:

- **Mapping weeks (decided by the owner):** each workbook row is labelled with a Monday report date and holds the work completed in the week just finished. It maps to the latest week-ending date **before** that report date. For example, with Friday as the week-ending day, the row dated Monday 13 October becomes the week ending Friday 10 October. The same rule converts the workbook's first and last report dates. Weekly figures, cumulative figures, the moving average and remaining counts therefore match the workbook exactly. Dates derived from them (planned and forecast completion) are earlier than the workbook's by the fixed offset between the week-ending day and the following report day (3 days for Friday and Monday). The comparison tests assert identical figures and dates shifted by that offset.
- **Settings:** target completion date, quantity completed before the first report, moving-average period, and the first and last report dates converted to week-ending dates on the chosen week-ending day.
- **Groups** from the By Location sheet: one group per location row with a name. Its baseline, "built on Windows 11, in stock" figure, planned completion date, Red, Amber or Green status and comment are imported. The "Deployed" figure becomes the group's **starting figure**.
- **Weekly history** from the Weekly Tracker sheet: targets and actuals for each week are imported as tracker-level history, not split by group, so that the charts and the forecast continue without a gap. All entries after the import are recorded against a group.
- **Risks and issues** from the Risks and Issues sheet.
- **Latest report inputs** from the Report Inputs sheet: status, headline and decisions required.
- **Check:** the importer compares the sum of group starting figures with the quantity completed before the first report plus the sum of weekly actuals, as the workbook's own data check does. It reports any difference and asks for confirmation; it never imports silently.

The workbook's baseline cells may contain formulas (for example `=202+135`); the importer uses the calculated value.

## 10. Database and migration path

- Alembic migrations define the schema in plain Postgres: tables, constraints, indexes and views only. No Supabase-specific features (section 3).
- Locally, the builder may run Postgres in WSL, or point at the Supabase project.
- **The one migration path:** from Supabase to a Tradition-hosted Postgres server, by dump and restore (`pg_dump` and `pg_restore`) and a change to `DATABASE_URL`. A short written runbook for this move is part of the work.

## 11. Decided by the owner

- One generic application, with TC Windows 11 as the first tracker.
- Combine the Everton dashboard and the capacity app as described in section 4.
- Flask and Postgres; Supabase for the demo; one migration path to Postgres.
- Run locally in WSL; demo on Render deployed from GitHub.
- Completions recorded per group per week; groups created and managed in the application; no double entry.
- Weeks identified by their week-ending date, with the report produced on that day.
- One weekly target for the whole tracker.
- Fixed scope per tracker; new work becomes a new tracker.
- Report layout B ("answer first").
- Recipients are the project owner, the CTO and the PMO; one email per tracker; recipient lists, templates and schedules managed in the application, as in the capacity app.
- Email body, PDF attachment, sign-in link, and PDF and PNG downloads; no Excel export.
- Sign-in and per-tracker access as in the capacity app; report links require sign-in.
- Import the existing workbook once, as a cutover, then retire it.
- A workbook row dated Monday holds the work of the week that ended the previous week-ending day.

## 12. Calls made by Claude (please check)

- Entries for the same group and week add together, rather than one value replacing another.
- The "built on Windows 11, in stock" figure becomes a general "ready, not yet complete" snapshot per group.
- Imported weekly history stays at tracker level; group "Deployed" figures become starting figures.
- The three viewer, editor and owner roles, and that users without a role cannot see a tracker.
- A week in progress is excluded from the moving average.
- The home page lists all visible trackers with status and forecast.
- Retired groups and archived trackers keep their history.
- Connect directly to Postgres, not through Supabase's REST API.
- Alembic for migrations.
- A finished week with no completion entries counts as an actual of zero; only the week in progress and future weeks have no actual.
- The live report is always recalculated from current data, including the current group snapshot fields and risk statuses. Each sent report is stored as its PDF together with its send log, which is the record of what was reported at the time.
- A group with work outstanding cannot be retired until its baseline is corrected (audited) to match what was deployed, so that retiring never leaves a tracker unable to reach 100%.
- Owners can extend the last week-ending date (still at most 52 weeks after the first); entries after the last week-ending date are rejected until it is extended.
- The v2_27 workbook is the reference for formulas. The supporting figures in section 6.4 follow its Report Inputs formulas exactly: weeks left = (target date minus report date) divided by 7, rounded up, not below zero; required weekly rate = remaining divided by weeks left; forecast against target = forecast date minus target date in days. Test fixtures committed to the repository use the workbook's figures with location names anonymised.

## 13. Left to the builder

- Database schema details, module structure and route names.
- The chart library (it must be served from `static/` under the strict Content-Security-Policy) and the PDF and PNG rendering approach. Both must work on Render.
- How the schedule worker runs on Render (for example, a separate worker service, or a scheduler inside the web process with a database lock).
- How the top-three risks are ordered.
- Wording and visual details of the screens, following the Everton dashboard's look.
- The test approach, provided the calculations are tested against the workbook's results.
