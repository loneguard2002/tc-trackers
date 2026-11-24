# Report "Status at a glance" view Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the live report a new "Status at a glance" view (answer card, figure tiles, Remaining chart with target
history, status strip, top risks, locations), switchable with the current "Classic view", and record every change of a
tracker's target date.

**Architecture:** Target history is a new table written by the tracker create and settings routes and the importer, read
through `tracker/trackers/targets.py`. The report route picks the view from `?view=` or the session; the new view is a
second template (`report/dashboard.html`) fed by `tracker/report/dashboard.py`, which derives everything from the same
`build_report` result plus target history. Its Remaining chart is an ECharts chart (`report-charts.js`) over a
server-drawn fallback picture, as today.

**Tech Stack:** Flask, Jinja, SQLAlchemy, Alembic, PostgreSQL, matplotlib, ECharts, vanilla ES5, CSS; pytest +
Playwright.

**Spec:** `docs/superpowers/specs/2026-11-24-report-dashboard-design.md` (read "Goals" and "Calls made"; the canvas
artboard "1 · Status at a glance" is the agreed look: https://claude.ai/artifact/UtLzrU4cjJzRCXKCiPtbM2).

## Global Constraints

- Strict Content Security Policy (no inline script or style, no `style=`; SVG geometry attributes are fine), ES5,
  British English, no contractions; copy as in the spec.
- Chart colours, light: actual `#1260d0`, plan `#008f82`, forecast `#c27a00`; dark: `#5b8ff0`, `#22a596`, `#b8801c`.
  Actual solid with a dot per week, plan dashed with a ring per week, forecast dotted; direct labels as in the spec.
  Status colours (Red/Amber/Green) only for status, always with an icon or letter.
- The classic view, the PDF, the PNG, the email and the existing chart pictures do not change.
- Viewers can see both views (the report's existing access rule, `require_tracker_role("viewer")`).
- Tests: browser files start `pytestmark = pytest.mark.browser`, sign in with `browser_sign_in`, add `RECORDER`, end with
  `window.__csp == []` and `window.__errors == []`. Run with `M=/mnt/c/Users/AlexKrovina/Documents/GitHub/tc-trackers;
  $M/.venv/bin/python -m dotenv -f $M/.env run -- $M/.venv/bin/pytest <tests> -n 6 -q` (Bash sandbox disabled). Per task
  run that task's tests plus `tests/test_templates.py` (7 failures for `mail/access/*.html` exist on main).

## Review Focus

- A report for a past week shows the target in force then and only the changes made by then (spec "Calls made").
- A tracker that never had a target, or whose target was removed, shows no target line, no forecast-vs-target text and
  no history list, and no 500.
- A tracker with no weekly update for the week, no risks, no locations, or no completed week yet renders every section
  with its empty wording.
- `?view=` with any other value is ignored; the choice sticks across reports for the same person and never affects the
  PDF, PNG or email routes.
- The chart's x-axis includes every target shown, even before the first week or after the last.

---

### Task 1: Target date history

**Files:** Modify `tracker/models.py`, `tracker/trackers/views.py` (create and settings), `tracker/trackers/forms.py`,
`tracker/templates/trackers/_fields.html`, `tracker/importer/workbook.py`; create `tracker/trackers/targets.py`,
`migrations/versions/0014_target_changes.py` (revision `"0014"`, down `"0013"`); tests `tests/test_target_history.py`,
`tests/test_migration_0014.py`, and the settings/create tests that need the new field (`tests/test_trackers.py`).

**Interfaces (produced):**
- Model `TargetChange` (`target_changes`): `id` identity PK; `tracker_id` FK trackers CASCADE; `changed_at` timestamptz
  default now; `changed_by` FK users SET NULL, nullable; `old_date` date null; `new_date` date null; `reason` text
  default `''`; index `(tracker_id, id)`.
- In `targets.py`: `record_target_change(session, tracker_id: int, old: date | None, new: date | None, user_id: int |
  None, reason: str = "") -> None` (adds nothing when `old == new`; does not commit).
- `@dataclass(frozen=True) class TargetEntry: number: int; date: date | None; kind: Literal["set", "moved",
  "removed"]; changed_on: date; by: str | None; reason: str; days: int | None; current: bool`.
- `target_history(session, tracker: Tracker, upto: date) -> list[TargetEntry]` — the changes whose `changed_at` (in the
  tracker's `send_timezone`) falls on or before `upto`, oldest first, numbered from 1; `days` = new − old for a move;
  `current` on the last one.
- `target_as_of(session, tracker: Tracker, upto: date) -> date | None` — the `new_date` of the last change on or
  before `upto`; with no change by then, the `old_date` of the first later change; with no changes at all,
  `tracker.target_completion`.
- `moves(entries) -> int` — the number of `moved` entries.

- [ ] Tests first: settings saving a new target records one change (old, new, user, reason from the new optional field
  `target_reason`, max 500 characters, error "Keep the reason under 500 characters."); saving with the date unchanged
  records nothing even with a reason; clearing records a `removed` entry; creating a tracker with a target records a
  `set` entry (old None); an import with a target records one `set` entry; `target_history` numbering, kinds, `days`
  (+7 / −3), `upto` filtering by the tracker's zone, `current`; `target_as_of` for a week before the first change, after
  it, and with no changes; migration up/down. The settings form shows "Why is the target moving?" (help: "Optional.
  Recorded with the change, and shown on the report.") under the target date; the create form does not.
- [ ] Implement; reveal the reason field only once the date differs from the saved one (in the settings page's existing
  script; without JavaScript it shows); run `tests/test_target_history.py tests/test_trackers.py tests/test_trackers_forms.py
  tests/importer tests/test_migration_0014.py tests/test_migration_matches_models.py tests/test_templates.py`; commit
  `feat: record every change of a tracker's target date`.

### Task 2: The view switch and the new view's data

**Files:** Modify `tracker/report/views.py`, `tracker/templates/report/page.html`; create `tracker/report/dashboard.py`,
`tracker/templates/report/_view_switch.html`, `tracker/templates/report/dashboard.html` (a first version: toolbar,
switch and the answer card only); tests `tests/test_report_dashboard.py`.

**Interfaces:**
- Consumes: Task 1's `target_history`, `target_as_of`, `moves`.
- Produces in `dashboard.py`: `@dataclass class Dashboard` with `target: date | None`, `targets: list[TargetEntry]`,
  `answer: str`, `tone: str`, `needed: str | None`, `written_by: str | None`, `written_on: date | None`, `tiles: dict`,
  `statuses: list[StatusWeek]`, `status_summary: str`, `locations: list`, `risks: list`;
  `build_dashboard(session, report: Report, today: date) -> Dashboard`; `answer_sentence(headline: Headline, target: date
  | None, behind_plan: int | None) -> str`.
- Session key `report_view` (`"new"` | `"classic"`); `?view=new|classic` sets it; other values ignored; default `new`.

- [ ] Tests first (`tests/test_report_dashboard.py`): `answer_sentence` cases — finished ("All 500 done."), forecast
  before target and behind plan ("On course to finish on 11 Dec, a week before the 18 Dec target, though 30 behind
  plan." — "a week" for 7 days, "N days" otherwise, "on the target date" for 0), after target ("Forecast to finish on 8
  Jan, 21 days after the 18 Dec target."), no target ("Forecast to finish on 11 Dec. No target date is set."), no
  forecast yet ("Not enough completed weeks to forecast yet."); the report page with no `view` shows the new view and
  sets the session; `?view=classic` shows today's page and sticks for the next report of another tracker; a bad value
  is ignored; the switch shows on both views as two links with `aria-current` on the active one; the PDF, PNG and data
  routes are unchanged by the session; a viewer sees both. The answer card shows the status badge with icon and word,
  the sentence, the headline, "Needed from you" with the text (or "None") and "Written by A. Name on 20 Nov 2026", or
  "No weekly update written for this week." with no update.
- [ ] Implement (the target used for the sentence is `target_as_of(…, report.week_ending)`; "behind plan" from the
  report week's `cum_target` − `cum_actual`); run the test file plus `tests/test_report.py tests/test_templates.py`;
  commit `feat: report view switch and the Status at a glance answer card`.

### Task 3: Tiles, status strip, risks and locations

**Files:** `tracker/report/dashboard.py`, `tracker/templates/report/dashboard.html`, `tracker/static/tracker.css`; tests
`tests/test_report_dashboard.py`.

- [ ] Tests first: tiles — Completed ("375 of 500", bar width 75.00, "75% · 125 left"), This week (sparkline points
  for the completed weeks up to the report week, "+2 against target · next week 40" / "On target" / "−3 against target",
  "No target for this week"), Rate ("41.3 a week", bar and the needed mark, "31.3 a week needed" in success or danger,
  "No required rate"), Forecast ("11 Dec", "7 days before the 18 Dec target" / "N days after …", "Target moved twice: 4
  Dec → 11 Dec → 18 Dec" only when `moves >= 1`, "once" for one); status strip — the 12 weeks ending at the report week
  (fewer at the start), letters G/A/R/–, the report week marked, summary per the spec's rule ("Amber for 3 weeks; Red
  once, on 9 Oct.", "Red 3 times", "Green for 5 weeks.", "No statuses yet."); top risks — "3 of 7 open", each with RAG
  chip and icon, "4 days past 20 Nov" in danger when past, else "Due 4 Dec", location and owner, "No open risks.";
  locations — live ones only, lowest % first, chip, "150 of 160 · 94%", bar with the starting part lighter, note "10
  left · 20 done before the first week · planned 4 Dec", the key, and today's "Not shown" and data check notes.
- [ ] Implement with server-drawn SVG for the small visuals (geometry in attributes, colours via CSS classes in both
  themes); run the test file plus `tests/test_report.py tests/test_templates.py`; commit `feat: Status at a glance
  tiles, status strip, risks and locations`.

### Task 4: The Remaining chart with target history

**Files:** `tracker/report/chart_data.py`, `tracker/report/charts.py`, `tracker/report/views.py` (`CHARTS`),
`tracker/static/report-charts.js`, `tracker/templates/report/dashboard.html`, `tracker/static/tracker.css`; tests
`tests/test_chart_data.py` or `tests/test_report.py` (whichever holds the payload tests), `tests/test_render.py`,
`tests/test_report_dashboard.py`, `tests/test_report_page_browser.py`.

**Interfaces:**
- Consumes: Task 1's `target_history`; Task 2's `Dashboard.targets`, `Dashboard.target`.
- Produces: chart payload key `targets: [{"date": iso, "number": n, "current": bool}]` and `report_week: iso`
  (added, nothing removed); picture name `remaining-glance` in `CHARTS` (the classic `remaining` is untouched).

- [ ] Tests first: the payload carries the targets up to the report week and the report week; the `remaining-glance`
  picture (matplotlib) draws remaining actual, plan and forecast, a line per target (earlier ones faint, numbered),
  the report-week marker, and an x-axis covering every target; the new view's chart host has `data-chart=
  "remaining-glance"`, the title "Remaining", the subtitle "Units left to do, by week ending" with the tracker's unit
  label, and the "Target date changes" list (number, date struck through when not current, "Set on 1 Sep." / "Moved on
  12 Oct, 7 days later: <reason>." / "No reason given" / "Target removed on …", the note "moved twice, 14 days later
  than first set") only when there is at least one change; browser: the chart draws with the lines labelled ("Actual:
  125 left", "Plan: 95 left", "Forecast: none left on 11 Dec"), a target markLine per entry (earlier ones dashed and
  faint with their number), hover tooltips, no CSP or script errors, light and dark.
- [ ] Implement (ECharts: remaining series computed from the payload's cumulative series and the scope; `markLine` for
  the report week and each target; x-axis extended to the latest of the last week, the forecast end and every target);
  run the listed tests plus `tests/test_templates.py`; commit `feat: Status at a glance Remaining chart with the target
  history`.

### Finish

- [ ] Full suite once (`-n 6`), ruff; screenshots of both views at 1440px light and dark and 390px; push and open the PR.
