# Generic Progress Tracker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A Flask and Postgres web application in which users define progress trackers (a quantity in scope, grouped, completed week by week), record progress, and get a calculated forecast and an "answer first" weekly report that is shown live, exported as PDF and PNG, and emailed on a schedule. TC Windows 11 is the first tracker, imported from its workbook.

**Architecture:** One Flask package `tracker/` built with an app factory. Postgres is reached through SQLAlchemy 2.0, and Alembic manages migrations. The week and forecast arithmetic lives in pure modules (`tracker/engine/`) with no database access. Each feature has its own blueprint (auth, trackers, entries, report, mail, admin). Charts are rendered on the server with matplotlib, so the live page, the PDF, the PNG and the email all show identical images. The PDF and PNG are rendered from the same HTML with headless Chromium (Playwright). A separate worker process (`flask run-scheduler`) sends scheduled emails. The app is deployed as a Docker image on Render, with one web service and one background worker.

**Tech Stack:** Python 3.12, Flask 3, SQLAlchemy 2 with psycopg 3, Alembic, passlib[bcrypt], msal, matplotlib, Playwright (Chromium), openpyxl, APScheduler (only for its cron parser), gunicorn, pytest, ruff, sqlfluff.

**Spec:** `docs/superpowers/specs/2026-10-20-generic-progress-tracker-design.md`. Read it before starting any task; the section numbers below (§) refer to it.

**Source projects** (read-only; port code from them, never modify them):
- `EVERTON` = `/mnt/c/Users/AlexKrovina/Documents/GitHub/everton-ticket-dashboard/dashboard`
- `CAPACITY` = `/mnt/c/Users/AlexKrovina/Documents/GitHub/capacity/capacity_app`

## Global Constraints

- Python `>=3.12`. Ruff: `line-length = 120`, `target-version = "py312"`, rules `E, F, I, W` (as in EVERTON's `pyproject.toml`).
- Database access goes only through `DATABASE_URL` (a `postgresql+psycopg://` URL). Do not use Supabase REST (PostgREST), Supabase Auth, Supabase Storage, Edge Functions, `pg_cron` or row-level security policies (§3).
- Schema changes go through Alembic migrations only; `alembic check` must report no differences from the models.
- Content-Security-Policy as in EVERTON's `create_app`: no CDNs, no inline scripts or styles; all JavaScript and CSS come from `tracker/static/`. Charts are server-rendered SVG or PNG images.
- Every change to entries, scope, settings, recipients, roles and sends writes an `audit_log` row through `tracker.audit.record(...)`.
- No Excel export anywhere (§2).
- Report links always require sign-in (§7.2).
- Test files under `tests/` contain no real location names; use names such as "Site A".
- User-facing copy is in British English, matching the workbook's wording ("Remaining on Windows 10" becomes "Remaining", with the unit label taken from the tracker).
- Shell commands in this repository are prefixed with `rtk` when they are run (repository convention), for example `rtk pytest`.

## Review Focus

1. **A week with no entries, or a tracker with no targets yet:** the report must render with "–" in place of dates and rates, never a 500 error. The test lives in Task 4 (`test_headline_no_targets_no_actuals`) and Task 8 (`test_report_page_empty_tracker`).
2. **An entry dated outside the tracker's weeks** (before the first week, or after the last week-ending date): reject it with a message, and do not store it. Test in Task 7 (`test_entry_after_last_week_rejected`, `test_entry_before_first_week_rejected`).
3. **Two scheduler workers, or a restart around 17:00:** exactly one scheduled email per tracker and week. Test in Task 11 (`test_scheduler_cycle_twice_sends_once`).
4. **A user without a role opens a tracker URL directly** (report, PDF, entries, settings): respond with 404, not 403, so that the existence of the tracker is not revealed. Test in Task 5 (`test_require_tracker_role_hides_tracker`) and Task 8 (`test_report_pdf_requires_role`).
5. **A workbook baseline cell holding a formula such as `=202+135`, or a workbook whose totals do not reconcile:** the importer evaluates simple arithmetic and reports the mismatch instead of importing silently. Test in Task 12 (`test_import_evaluates_baseline_formula`, `test_import_reports_mismatch`).

---

## File map

```
tracker/
  __init__.py
  app.py              create_app(), security headers, blueprints, CLI registration
  config.py           load_config(), validate_config(), ConfigurationError
  db.py               engine/session setup, Base, get_session()
  models.py           all ORM models (Task 2)
  audit.py            record()
  engine/
    weeks.py          pure week arithmetic (Task 3)
    calc.py           pure calculations: WeekRow, GroupPosition, Headline (Task 4)
  auth/
    __init__.py       blueprint "auth"
    passwords.py      hash_password(), verify_password()
    session.py        login_user(), logout_user(), current_user(), login_required, admin_required
    csrf.py           csrf_token(), valid_csrf(), LoginThrottle
    sso.py            MSAL routes
    roles.py          ROLE_ORDER, user_role(), require_tracker_role(), visible_trackers()
  trackers/           blueprint "trackers": home, tracker CRUD, settings, groups, roles (Task 6)
  entries/            blueprint "entries": completions, targets, report inputs, risks (Task 7)
  report/
    build.py          build_report() -> Report (Task 8)
    charts.py         matplotlib charts (Task 8)
    render.py         html_to_pdf(), html_to_png() (Task 9)
    views.py          blueprint "report"
  mail/
    smtp.py           send_message() ported from CAPACITY emails.py (Task 10)
    compose.py        PLACEHOLDERS, render_placeholders(), build_report_email() (Task 10)
    sending.py        send_report(), retry_queued() (Task 10)
    views.py          blueprint "mail": recipients, template, preview, test-send, send now
  sched/
    schedules.py      copied verbatim from CAPACITY sched/schedules.py (Task 11)
    runner.py         due_sends(), run_scheduler_cycle(), CLI run-scheduler (Task 11)
  importer/
    workbook.py       import_workbook() (Task 12)
  admin/              blueprint "admin": users, approvals, SMTP settings (Task 5)
  templates/          Jinja templates (base.html and macros.html adapted from EVERTON)
  static/             tracker.css (from EVERTON dashboard.css), tracker.js
migrations/           Alembic environment and versions
tests/                pytest; conftest.py provides app, db, client, login helpers
scripts/capture_workbook_golden.py   (Task 12)
docs/runbooks/supabase-to-postgres.md (Task 13)
Dockerfile, render.yaml, Procfile, pyproject.toml, requirements.txt, .sqlfluff, .github/workflows/ci.yml
```

---

### Task 1: Project skeleton, configuration and CI

**Files:**
- Create: `pyproject.toml`, `requirements.txt`, `.gitignore`, `.sqlfluff`, `.github/workflows/ci.yml`, `tracker/__init__.py`, `tracker/app.py`, `tracker/config.py`, `tracker/templates/base.html`, `tracker/templates/macros.html`, `tracker/templates/error.html`, `tracker/static/tracker.css`, `tests/conftest.py`, `tests/test_app.py`, `README.md`

**Interfaces:**
- Produces: `create_app(overrides: dict | None = None) -> Flask`; `load_config(overrides: dict | None = None) -> dict`; `validate_config(config: dict) -> None` raising `ConfigurationError`; route `GET /healthz` returning `{"status": "ok"}`.
- Config keys: `SECRET_KEY` (env `FLASK_SECRET_KEY`), `DATABASE_URL`, `APP_URL`, `SESSION_COOKIE_SECURE` (default true), `SSO_TENANT_ID`, `SSO_CLIENT_ID`, `SSO_CLIENT_SECRET` (all three optional; SSO is enabled only when all are set), `TESTING`.

- [ ] **Step 1: Write the failing tests** in `tests/test_app.py`:

```python
def test_healthz(client):
    r = client.get("/healthz")
    assert r.status_code == 200 and r.get_json() == {"status": "ok"}

def test_security_headers(client):
    r = client.get("/healthz")
    csp = r.headers["Content-Security-Policy"]
    assert "default-src 'self'" in csp and "unsafe-inline" not in csp
    assert r.headers["X-Frame-Options"] == "DENY"

def test_missing_database_url_fails_fast():
    with pytest.raises(ConfigurationError):
        validate_config({"SECRET_KEY": "x", "DATABASE_URL": ""})

def test_sso_disabled_without_all_three_settings():
    cfg = load_config({"SECRET_KEY": "x", "DATABASE_URL": "postgresql+psycopg://u@h/d", "SSO_TENANT_ID": "t"})
    assert cfg["SSO_ENABLED"] is False
```

`tests/conftest.py` builds `app` from `create_app({"TESTING": True, "SECRET_KEY": "test", "DATABASE_URL": os.environ["TEST_DATABASE_URL"], "SESSION_COOKIE_SECURE": False})` and provides `client`.

- [ ] **Step 2: Run `rtk pytest tests/test_app.py -v`.** Expected: FAIL (`ModuleNotFoundError: tracker`).
- [ ] **Step 3: Implement.** Port `create_app`'s security-headers hook and error handlers from EVERTON `app.py` and `load_config`/`validate_config` from EVERTON `config.py`, with the keys above. Adapt `base.html` (top bar, sidebar, dark mode) and `macros.html` from EVERTON, removing all Everton branding and image hosts; the sidebar shows "Trackers" and, for administrators, "Admin". `requirements.txt` pins: flask, sqlalchemy>=2, psycopg[binary]>=3, alembic, passlib[bcrypt], bcrypt==3.2.2, msal, matplotlib, playwright, openpyxl, apscheduler, gunicorn, python-dotenv, pytest, ruff, sqlfluff. `.gitignore` includes `.superpowers/`, `.env*`, `__pycache__/`, `.venv/`. CI (`.github/workflows/ci.yml`) runs a `postgres:16` service, then `ruff check`, `ruff format --check`, `sqlfluff lint migrations/sql` (if present), `alembic upgrade head`, `alembic check` and `pytest`, with `TEST_DATABASE_URL` pointing at the service.
- [ ] **Step 4: Run `rtk pytest tests/test_app.py -v` and `rtk ruff check .`.** Expected: all PASS and no lint errors.
- [ ] **Step 5: Commit** with `feat: project skeleton, config, security headers, CI`.

Local prerequisite (record it in the README): Postgres in WSL (`sudo apt install postgresql`), with a `tracker_test` database and `TEST_DATABASE_URL=postgresql+psycopg://<user>@localhost/tracker_test`.

---

### Task 2: Database models and initial migration

**Files:**
- Create: `tracker/db.py`, `tracker/models.py`, `tracker/audit.py`, `alembic.ini`, `migrations/env.py`, `migrations/versions/0001_initial.py`, `tests/test_models.py`
- Modify: `tests/conftest.py` (add the `db` fixture), `tracker/app.py` (initialise the database)

**Interfaces:**
- Produces: `Base`; `get_session() -> Session` (request-scoped, removed on teardown); `init_db(app)`; `record(session, *, user_id: int | None, tracker_id: int | None, action: str, entity: str, entity_id: str | int | None, detail: dict | None = None) -> None`.
- Models (table name in brackets; all ids are integer identity columns; timestamps are `timestamptz`, default `now()`):
  - `User [users]`: email (unique, stored lowercase), full_name, password_hash (nullable), auth_source (`local` or `sso`), status (`pending`, `active` or `disabled`), is_admin (bool, default false), created_at.
  - `TrackerRole [tracker_roles]`: user_id, tracker_id, role (`viewer`, `editor` or `owner`); primary key (user_id, tracker_id).
  - `AuditLog [audit_log]`: at, user_id, tracker_id, action, entity, entity_id (text), detail (JSONB).
  - `Tracker [trackers]`: name, unit_label, group_label, description, status (`active` or `archived`), week_ending_weekday (smallint 0–6, Monday = 0), first_week_ending (date), last_week_ending (date), target_completion (date, nullable), completed_before_first (int, default 0), moving_average_weeks (int, default 3), send_time (time, default 17:00), send_timezone (text, default `Europe/London`), schedule_enabled (bool, default false), created_at. Check constraints: `last_week_ending >= first_week_ending`, `last_week_ending - first_week_ending <= 357`, `moving_average_weeks between 1 and 12`.
  - `Group [groups]`: tracker_id, name, baseline (int ≥ 0), starting_completed (int ≥ 0, default 0), ready_not_complete (int ≥ 0, default 0), planned_completion (date, nullable), rag (`Green`, `Amber`, `Red` or null), comment, retired (bool), sort_order (int); unique (tracker_id, name).
  - `CompletionEntry [completion_entries]`: tracker_id, group_id, entry_date, week_ending, quantity (int > 0), note, created_by, created_at; index (tracker_id, week_ending).
  - `Week [weeks]`: tracker_id, week_ending (primary key together), target (int, nullable), imported_actual (int, nullable).
  - `ReportInput [report_inputs]`: tracker_id, week_ending (primary key together), status (`Green`, `Amber`, `Red` or null), headline, decisions, prepared_by (user id), updated_at.
  - `Risk [risks]`: tracker_id, ref (text, for example `R1`), description, impact, group_id (nullable), owner_role, raised_on, target_date, status (`Open`, `In progress` or `Closed`), rag, latest_update; unique (tracker_id, ref).
  - `Recipient [recipients]`: tracker_id, email, name; unique (tracker_id, email).
  - `EmailTemplate [email_templates]`: tracker_id (primary key), subject, body_html.
  - `ReportSend [report_sends]`: tracker_id, week_ending, trigger (`scheduled` or `manual`), status (`sending`, `sent`, `queued` or `failed`), recipients (JSONB list of emails), pdf (bytea, nullable), error, attempts (int), next_attempt_at, created_by, created_at, sent_at. A **partial unique index** on (tracker_id, week_ending) `WHERE trigger = 'scheduled'`.
  - `AppSetting [app_settings]`: key (primary key), value.

- [ ] **Step 1: Write the failing tests** in `tests/test_models.py`:

```python
def test_scheduled_send_unique_per_week(db, tracker_factory):
    t = tracker_factory()
    db.add(ReportSend(tracker_id=t.id, week_ending=t.first_week_ending, trigger="scheduled", status="sent", recipients=[]))
    db.commit()
    db.add(ReportSend(tracker_id=t.id, week_ending=t.first_week_ending, trigger="scheduled", status="sent", recipients=[]))
    with pytest.raises(IntegrityError):
        db.commit()

def test_manual_sends_not_limited(db, tracker_factory): ...  # two manual sends for the same week both commit

def test_tracker_span_limited_to_52_weeks(db, tracker_factory):
    with pytest.raises(IntegrityError):
        tracker_factory(first_week_ending=date(2026, 1, 2), last_week_ending=date(2027, 1, 8))  # 53 weeks

def test_audit_record_writes_row(db, tracker_factory):
    t = tracker_factory()
    record(db, user_id=None, tracker_id=t.id, action="update", entity="group", entity_id=5, detail={"baseline": [10, 12]})
    db.commit()
    assert db.scalar(select(func.count()).select_from(AuditLog)) == 1
```

`conftest.py`: the `db` fixture runs `alembic upgrade head` once per session against `TEST_DATABASE_URL`, and truncates all tables (`TRUNCATE ... RESTART IDENTITY CASCADE`) after each test. A `tracker_factory(**overrides)` fixture creates a Friday tracker (`week_ending_weekday=4`, `first_week_ending=date(2026, 9, 4)`, `last_week_ending=date(2026, 12, 25)`).

- [ ] **Step 2: Run `rtk pytest tests/test_models.py -v`.** Expected: FAIL (import errors).
- [ ] **Step 3: Implement** the models, `db.py` and `audit.py`, then generate `0001_initial.py` with `alembic revision --autogenerate`. Write the partial index explicitly with `postgresql_where`, and review the generated file by hand.
- [ ] **Step 4: Run `rtk pytest tests/test_models.py -v` and `rtk alembic check`.** Expected: PASS, and "No new upgrade operations detected".
- [ ] **Step 5: Commit** with `feat: schema, initial migration, audit log`.

---

### Task 3: Week arithmetic (pure)

**Files:**
- Create: `tracker/engine/__init__.py`, `tracker/engine/weeks.py`, `tests/engine/test_weeks.py`

**Interfaces:**
- Produces (in `tracker.engine.weeks`; weekday is an int, Monday = 0):
  - `week_ending_for(d: date, weekday: int) -> date`: the first date ≥ `d` that falls on `weekday`.
  - `first_week_ending(start: date, weekday: int) -> date`: the same as `week_ending_for`.
  - `max_last_week_ending(first: date) -> date`: `first + 51 weeks`.
  - `week_endings(first: date, last: date) -> list[date]`: every 7 days from `first` to `last`. Raises `ValueError` if `last < first`, if `(last - first).days % 7 != 0`, or if `last > max_last_week_ending(first)`.
  - `report_date_to_week_ending(report_date: date, weekday: int) -> date`: the latest date strictly before `report_date` that falls on `weekday`.
  - `in_progress_week(as_of: date, weekday: int) -> date | None`: `week_ending_for(as_of)` when that date is after `as_of`, otherwise `None`.

- [ ] **Step 1: Write the failing tests:**

```python
FRI = 4
def test_week_ending_for_midweek():      assert week_ending_for(date(2026, 10, 14), FRI) == date(2026, 10, 16)
def test_week_ending_for_on_the_day():   assert week_ending_for(date(2026, 10, 16), FRI) == date(2026, 10, 16)
def test_monday_report_maps_to_previous_friday():
    assert report_date_to_week_ending(date(2026, 10, 13), FRI) == date(2026, 10, 10)
def test_report_date_on_week_ending_day_maps_to_previous_week():
    assert report_date_to_week_ending(date(2026, 10, 16), FRI) == date(2026, 10, 9)
def test_week_endings_52_max():
    first = date(2026, 1, 2)
    assert len(week_endings(first, max_last_week_ending(first))) == 52
    with pytest.raises(ValueError): week_endings(first, first + timedelta(weeks=52))
def test_week_endings_misaligned():
    with pytest.raises(ValueError): week_endings(date(2026, 1, 2), date(2026, 1, 10))
def test_in_progress_week():
    assert in_progress_week(date(2026, 10, 14), FRI) == date(2026, 10, 16)
    assert in_progress_week(date(2026, 10, 16), FRI) is None
```

- [ ] **Step 2: Run `rtk pytest tests/engine/test_weeks.py -v`.** Expected: FAIL.
- [ ] **Step 3: Implement** `tracker/engine/weeks.py` (standard library only).
- [ ] **Step 4: Run the tests.** Expected: PASS.
- [ ] **Step 5: Commit** with `feat: week-ending arithmetic`.

---

### Task 4: Calculation engine (pure)

**Files:**
- Create: `tracker/engine/calc.py`, `tests/engine/test_calc.py`

**Interfaces:**
- Consumes: `tracker.engine.weeks`.
- Produces (frozen dataclasses in `tracker.engine.calc`):
  - `WeekRow(week_ending: date, target: int | None, actual: int | None, variance: int | None, cum_target: int | None, cum_actual: int | None, planned_remaining: int | None, actual_remaining: int | None, pct_complete: float | None, moving_average: float | None, forecast_remaining: float | None, state: str)`, where `state` is `"complete"`, `"in_progress"` or `"future"`.
  - `GroupInput(group_id: int, name: str, baseline: int, starting_completed: int, ready_not_complete: int, planned_completion: date | None, rag: str | None, comment: str | None, retired: bool)`.
  - `GroupPosition(group_id, name, baseline, deployed, ready_not_complete, remaining, pct_complete: float | None, planned_completion, rag, comment, retired)`.
  - `Headline(total_scope: int, completed: int, pct_complete: float | None, remaining: int, report_week: date, forecast_based_on: date | None, forecast_rate: float | None, planned_completion: date | None, forecast_completion: date | None, target_completion: date | None, weeks_left: int | None, required_rate: float | None, forecast_vs_target_days: int | None, this_week_actual: int | None, this_week_target: int | None, next_week_target: int | None, totals_check_ok: bool, verdict: str)`.
  - `build_week_rows(weeks: list[date], targets: dict[date, int | None], actuals: dict[date, int], total_scope: int, completed_before_first: int, ma_weeks: int, as_of: date, weekday: int) -> list[WeekRow]`
  - `group_positions(groups: list[GroupInput], entry_totals: dict[int, int]) -> list[GroupPosition]`
  - `build_headline(rows: list[WeekRow], positions: list[GroupPosition], completed_before_first: int, target_completion: date | None, report_week: date) -> Headline`

Rules (§6.2 to §6.4; these determine the bodies):
- A row is `complete` when `week_ending <= as_of`, and its actual is `actuals.get(week, 0)`. The row `in_progress_week(as_of)` is `in_progress`: it shows its actual but is excluded from the moving average and the forecast basis. All later rows are `future`, with actual `None`.
- `cum_target`/`cum_actual` = `completed_before_first` + the running sum; `None` from the first row whose target or actual is `None`. `planned_remaining` = `total_scope - cum_target`; `actual_remaining` = `total_scope - cum_actual`; `pct_complete` = `cum_actual / total_scope` (`None` when the scope is 0).
- `moving_average` on a complete row is the mean of the actuals of the last `min(ma_weeks, number of complete rows so far)` complete rows.
- `forecast_remaining`: on complete rows it equals `actual_remaining`. After the last complete row, it is `max(0, previous - rate)` with `rate` = the moving average of the last complete row, or `None` if there is no complete row.
- Headline: `total_scope` = the sum of all group baselines (including retired groups). `completed` = the sum of group `deployed` figures. `forecast_based_on` = the last complete row at or before `report_week`. `planned_completion` = the first row with `planned_remaining <= 0`. `forecast_completion` is `forecast_based_on` when remaining ≤ 0; `None` when the rate is `None` or ≤ 0; otherwise `forecast_based_on + ceil(remaining / rate) * 7 days`, where `remaining` is that row's `actual_remaining`. `weeks_left` = `max(0, ceil((target_completion - report_week).days / 7))`. `required_rate` = `remaining / weeks_left` when `weeks_left > 0`. `forecast_vs_target_days` = `(forecast_completion - target_completion).days`. `totals_check_ok` = (`completed` == the `cum_actual` of the last complete row, or `completed_before_first` when there is none).
- `verdict`: `"Forecast N weeks behind target"` when the forecast is later than the target (N = `ceil(days / 7)`; "1 week" in the singular); `"Forecast N weeks ahead of target"` when it is earlier by 7 days or more; `"On track for target"` otherwise; `"Complete"` when remaining is 0; `"No forecast yet"` when the forecast is `None`.
- `group_positions`: `deployed` = `starting_completed + entry_totals.get(id, 0)`; `remaining` = `baseline - deployed`.

- [ ] **Step 1: Write the failing tests.** Use the fixture `FRI = 4`, `weeks = week_endings(date(2026, 9, 4), date(2026, 12, 25))`, targets of 50 for each of the first 8 weeks, actuals `{9/4: 40, 9/11: 38, 9/18: 20, 9/25: 40}`, `total_scope = 369`, `completed_before_first = 0`, `ma_weeks = 3`, `as_of = date(2026, 9, 25)`.

```python
def test_cumulative_and_remaining(rows):
    r = rows[3]
    assert (r.cum_actual, r.actual_remaining, r.cum_target, r.planned_remaining) == (138, 231, 200, 169)
def test_moving_average_short_start(rows):
    assert rows[0].moving_average == 40 and rows[1].moving_average == 39
    assert rows[3].moving_average == pytest.approx(32.667, abs=1e-3)
def test_forecast_completion(headline):
    assert headline.forecast_based_on == date(2026, 9, 25)
    assert headline.forecast_completion == date(2026, 9, 25) + timedelta(weeks=8)  # ceil(231/32.667)=8
def test_planned_completion(headline):  # 8 x 50 = 400 >= 369
    assert headline.planned_completion == date(2026, 10, 23)
def test_empty_week_counts_as_zero(): ...  # a complete week absent from actuals -> actual 0, included in the moving average
def test_in_progress_week_excluded_from_average():
    rows = build_week_rows(..., as_of=date(2026, 9, 30), weekday=FRI)  # 2 Oct in progress
    assert rows[4].state == "in_progress" and rows[4].moving_average is None
    assert rows[3].moving_average == pytest.approx(32.667, abs=1e-3)
def test_verdict_behind():  # forecast 20 Nov, target 30 Oct -> 21 days -> "Forecast 3 weeks behind target"
def test_weeks_left_and_required_rate():  # report_week 25 Sep, target 30 Oct -> weeks_left 5, required_rate 231/5
def test_headline_no_targets_no_actuals():
    rows = build_week_rows(weeks, {}, {}, 0, 0, 3, as_of=date(2026, 9, 1), weekday=FRI)
    h = build_headline(rows, [], 0, None, date(2026, 9, 4))
    assert h.forecast_completion is None and h.planned_completion is None and h.verdict == "No forecast yet"
def test_group_positions_deployed_includes_starting(): ...  # starting 135 + entries 5 = 140; remaining = baseline - 140
def test_totals_check_flags_mismatch(): ...
```

- [ ] **Step 2: Run `rtk pytest tests/engine/test_calc.py -v`.** Expected: FAIL.
- [ ] **Step 3: Implement** `tracker/engine/calc.py` following the rules above.
- [ ] **Step 4: Run the tests.** Expected: PASS.
- [ ] **Step 5: Commit** with `feat: forecast and position calculations`.

---

### Task 5: Authentication, approval, roles and administration

**Files:**
- Create: `tracker/auth/{__init__,passwords,session,csrf,sso,roles}.py`, `tracker/admin/__init__.py`, templates `login.html`, `sso_pending.html`, `admin/users.html`, `admin/smtp.html`, `tests/test_auth.py`, `tests/test_roles.py`
- Modify: `tracker/app.py` (register the `auth` and `admin` blueprints and a `flask create-admin EMAIL` CLI command)

**Interfaces:**
- Produces:
  - `hash_password(pw: str) -> str` and `verify_password(pw: str, hashed: str) -> bool` (passlib bcrypt, as in CAPACITY `auth.py`).
  - `login_user(user: User)`, `logout_user()`, `current_user() -> User | None`, and the decorators `login_required` and `admin_required`. Sessions last 8 hours, with `SESSION_COOKIE_SAMESITE="Lax"`.
  - `csrf_token() -> str`, `valid_csrf(token) -> bool`, and `LoginThrottle` (ported from EVERTON `auth.py`). Every POST form checks the CSRF token through a `before_request` hook.
  - `ROLE_ORDER = {"viewer": 1, "editor": 2, "owner": 3}`; `user_role(session, user, tracker_id) -> str | None` (administrators count as `owner`); `require_tracker_role(min_role: str)`, a decorator for views taking `tracker_id`, which aborts with **404** when the user's role is missing or too low and sets `g.tracker` and `g.role`; `visible_trackers(session, user) -> list[Tracker]`.
  - Routes: `GET/POST /login`, `POST /logout`, `GET /auth/sso`, `GET /auth/callback`, `GET /auth/pending`, `GET /admin/users`, `POST /admin/users/<id>/approve`, `POST /admin/users/<id>/disable`, `POST /admin/users/<id>/admin`, `GET/POST /admin/smtp`.
- SSO: port `_msal_app`, `sso_start` and `sso_callback` from CAPACITY `app.py` (lines 430–534). A first SSO login creates a `pending` user. A local user is created by an administrator (or by `flask create-admin`), and is `active` immediately.

- [ ] **Step 1: Write the failing tests:**

```python
def test_local_login_success(client, user_factory):  # active user, correct password -> 302 to "/"
def test_pending_user_cannot_log_in(client, user_factory):  # status pending -> stays on login page, "awaiting approval"
def test_login_throttled_after_5_failures(client, user_factory): ...
def test_post_without_csrf_rejected(client, logged_in_admin):  # POST /admin/users/1/approve without token -> 400
def test_admin_approves_pending_user(client, logged_in_admin, user_factory): ...  # status active; audit row written
def test_non_admin_cannot_open_admin(client, logged_in_user):  # GET /admin/users -> 403
def test_require_tracker_role_hides_tracker(client, logged_in_user, tracker_factory):
    t = tracker_factory()
    assert client.get(f"/trackers/{t.id}").status_code == 404
def test_viewer_cannot_reach_editor_route(client, logged_in_user, tracker_factory, grant):
    t = tracker_factory(); grant(logged_in_user, t, "viewer")
    assert client.get(f"/trackers/{t.id}/entries/new").status_code == 404
def test_visible_trackers_only_with_role(db, user_factory, tracker_factory, grant): ...
def test_sso_routes_absent_when_disabled(client):  # GET /auth/sso -> 404 when SSO_ENABLED is False
```

Add `user_factory`, `logged_in_user`, `logged_in_admin`, `grant(user, tracker, role)` and a CSRF-aware `post(client, url, data)` helper to `conftest.py`. The tests on tracker routes rely on stubs from Task 6 and Task 7; until then, register placeholder views under `require_tracker_role` that return 200.

- [ ] **Step 2: Run `rtk pytest tests/test_auth.py tests/test_roles.py -v`.** Expected: FAIL.
- [ ] **Step 3: Implement** as above. `/admin/smtp` reads and writes the `app_settings` keys `smtp_host`, `smtp_port`, `smtp_auth` (`none`, `plain` or `xoauth2`), `smtp_user`, `smtp_from`, `smtp_tenant_id` and `smtp_client_id`. Secrets (`SMTP_PASSWORD`, `SMTP_CLIENT_SECRET`) are environment variables only and are never stored in the database.
- [ ] **Step 4: Run the tests.** Expected: PASS.
- [ ] **Step 5: Commit** with `feat: local and SSO sign-in, approval, per-tracker roles, admin`.

---

### Task 6: Trackers, settings, groups and the home page

**Files:**
- Create: `tracker/trackers/__init__.py`, `tracker/trackers/views.py`, `tracker/trackers/forms.py`, templates `home.html`, `trackers/new.html`, `trackers/settings.html`, `trackers/groups.html`, `trackers/roles.html`, `tests/test_trackers.py`

**Interfaces:**
- Consumes: `require_tracker_role`, `visible_trackers`, `record`, `week_endings`, `first_week_ending`, `max_last_week_ending`, `build_week_rows`, `group_positions` and `build_headline`.
- Produces:
  - `tracker_summary(session, tracker: Tracker, today: date) -> Headline`. This builds the inputs from the database and calls the engine. It is reused by Task 8 (`build_report`) and by the home page. Its data loader is `load_engine_inputs(session, tracker, as_of: date) -> tuple[list[date], dict, dict, list[GroupInput], dict[int, int]]`, which returns weeks, targets, actuals (the sum of entries per `week_ending` with `entry_date <= as_of`, plus `Week.imported_actual`), groups and entry totals per group (`entry_date <= as_of`).
  - Routes:
    - `GET /`: home, listing `visible_trackers` with status, % complete, forecast against target and the date of the last entry.
    - `GET/POST /trackers/new`: administrators only. The creator becomes owner.
    - `GET /trackers/<id>`: viewer and above. Redirects to the report.
    - `GET/POST /trackers/<id>/settings`: owner.
    - `GET/POST /trackers/<id>/groups`: owner. Supports create, rename, edit baseline, edit snapshot fields, retire and reorder.
    - `GET/POST /trackers/<id>/roles`: administrators only.
    - `POST /trackers/<id>/archive`: administrators only.

Rules:
- Settings are validated with `week_endings(first, last)`. The "first week-ending" field accepts any start date and is stored as `first_week_ending(start, weekday)`. Changing the weekday after entries exist is refused with the message "The week-ending day cannot change once entries exist."
- Retiring a group with `remaining > 0` is refused with the message "Correct the baseline to the deployed figure before retiring this group." (§12).
- Baseline changes write an audit row with `detail={"baseline": [old, new]}`.
- Editors may edit a group's snapshot fields (ready-not-complete, planned completion, RAG and comment); only owners may change the baseline, the name or the retired flag.

- [ ] **Step 1: Write the failing tests:**

```python
def test_admin_creates_tracker_and_becomes_owner(...): ...
def test_first_week_snaps_to_week_ending_day(...):  # start Wed 2 Sep 2026, Friday -> first_week_ending 4 Sep
def test_last_week_beyond_52_rejected(...): ...
def test_weekday_change_refused_with_entries(...): ...
def test_retire_group_with_remaining_refused(...): ...
def test_baseline_change_audited(...): ...
def test_editor_can_edit_snapshot_not_baseline(...): ...
def test_home_lists_only_visible_trackers(...): ...
def test_archived_tracker_hidden_from_home_but_reachable(...): ...
```

- [ ] **Step 2: Run `rtk pytest tests/test_trackers.py -v`.** Expected: FAIL.
- [ ] **Step 3: Implement** the views, forms and templates. Use EVERTON's card and list styles; the wording uses `tracker.group_label` and `tracker.unit_label` (for example "Location", "thin clients").
- [ ] **Step 4: Run the tests.** Expected: PASS.
- [ ] **Step 5: Commit** with `feat: trackers, settings, groups, home page`.

---

### Task 7: Data entry: completions, targets, weekly inputs and risks

**Files:**
- Create: `tracker/entries/__init__.py`, `tracker/entries/views.py`, templates `entries/list.html`, `entries/new.html`, `entries/targets.html`, `entries/inputs.html`, `entries/risks.html`, `tests/test_entries.py`

**Interfaces:**
- Consumes: `require_tracker_role`, `week_ending_for`, `record`.
- Produces routes (editor and above):
  - `GET /trackers/<id>/entries`: a list filtered by week and group.
  - `GET/POST /trackers/<id>/entries/new`: fields are group, date (default today), quantity and note. `week_ending` is computed with `week_ending_for`.
  - `POST /trackers/<id>/entries/<eid>/delete`: audited. Corrections are made by deleting and re-entering.
  - `GET/POST /trackers/<id>/targets`: one target per week, all weeks on one form.
  - `GET/POST /trackers/<id>/inputs?week=YYYY-MM-DD`: status, headline and decisions for one week; `prepared_by` is the current user.
  - `GET/POST /trackers/<id>/risks` and `/risks/<rid>`: register CRUD. `ref` is assigned automatically as `R{n}` when left blank.

Rules:
- An entry date whose `week_ending` falls before `first_week_ending` or after `last_week_ending` is rejected with the message "That date is outside this tracker's weeks (DD Mon YYYY to DD Mon YYYY)." (§12).
- Entries cannot be recorded against a retired group.
- The quantity must be a whole number of at least 1.

- [ ] **Step 1: Write the failing tests:**

```python
def test_entry_assigned_to_week_ending(...):  # Wed 14 Oct 2026 -> week_ending 16 Oct
def test_entries_same_group_week_add_up(...):  # 5 + 7 -> group deployed +12; week actual 12
def test_entry_after_last_week_rejected(...): ...
def test_entry_before_first_week_rejected(...): ...
def test_entry_on_retired_group_rejected(...): ...
def test_zero_or_negative_quantity_rejected(...): ...
def test_delete_entry_audited(...): ...
def test_targets_saved_per_week(...): ...
def test_inputs_record_prepared_by(...): ...
def test_risk_ref_autonumbered(...):  # R1, R2
def test_viewer_cannot_post_entry(...):  # 404
```

- [ ] **Step 2: Run `rtk pytest tests/test_entries.py -v`.** Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the tests.** Expected: PASS.
- [ ] **Step 5: Commit** with `feat: completions, weekly targets, report inputs, risks`.

---

### Task 8: Report model, charts and the live report page

**Files:**
- Create: `tracker/report/__init__.py`, `tracker/report/build.py`, `tracker/report/charts.py`, `tracker/report/views.py`, templates `report/_body.html` (the shared report markup), `report/page.html`, `tests/test_report.py`

**Interfaces:**
- Consumes: `load_engine_inputs`, `build_week_rows`, `group_positions`, `build_headline`, `require_tracker_role`.
- Produces:
  - `Report` dataclass: `tracker: Tracker`, `week_ending: date`, `as_of: date`, `in_progress: bool`, `rows: list[WeekRow]`, `headline: Headline`, `groups: list[GroupPosition]`, `top_risks: list[Risk]` (3 items), `open_risks: int`, `red_risks: int`, `inputs: ReportInput | None`, `charts: dict[str, bytes]` (keys `remaining`, `weekly`, `cumulative`; SVG bytes).
  - `build_report(session, tracker: Tracker, week_ending: date | None, today: date, chart_format: str = "svg") -> Report`. When `week_ending` is `None`, it uses the latest week-ending ≤ `today`, or the first week if none has passed. `as_of = min(week_ending, today)`.
  - `default_report_week(tracker, today) -> date`.
  - `remaining_chart(rows, unit_label, fmt) -> bytes`, `weekly_chart(rows, fmt) -> bytes`, `cumulative_chart(rows, fmt) -> bytes` (matplotlib with the `Agg` backend; plan line dashed grey, actual solid blue, forecast dotted amber, as in the chosen mockup).
  - Route `GET /trackers/<id>/report?week=YYYY-MM-DD` (viewer and above).
- Top risks: status ≠ `Closed`, ordered by RAG (Red, Amber, Green, null), then `target_date` ascending with nulls last, then `ref`.
- Layout (§7.1, option B), top to bottom: title; status band (the overall status from `inputs.status`, falling back to "Not set"; `headline.verdict`; forecast against target dates; headline text; "Needed from you": the decisions text or "None"); remaining chart; three key figures (completed out of scope with %, this week's actual against target, the forecast weekly rate labelled "Rate (N wk)"); top three risks with open and Red counts; details (group table, weekly chart, cumulative chart). `_body.html` is used unchanged by the PDF, PNG and email renderers. An "In progress" badge is shown when `in_progress` is true. Missing values display "–". The mockups are in `.superpowers/brainstorm/*/content/cto-report-layout*.html`.

- [ ] **Step 1: Write the failing tests:**

```python
def test_build_report_defaults_to_last_completed_week(...): ...
def test_build_report_marks_in_progress(...):  # week_ending in the future -> in_progress True, as_of = today
def test_top_risks_order(...):  # Red later date before Amber earlier date; Closed excluded; max 3
def test_report_page_renders_sections(client, ...):  # contains verdict, "Needed from you", group table, 3 <svg
def test_report_page_empty_tracker(client, ...):  # new tracker with no groups/targets -> 200, shows "No forecast yet"
def test_report_figures_match_engine(...):  # page shows headline.completed / total_scope and forecast date
def test_charts_return_svg_and_png(...):  # b"<svg" in svg output; png starts with b"\x89PNG"
```

- [ ] **Step 2: Run `rtk pytest tests/test_report.py -v`.** Expected: FAIL.
- [ ] **Step 3: Implement.** Charts are embedded in the page as `<img src="data:image/svg+xml;base64,...">`; extend the CSP with `img-src 'self' data:`.
- [ ] **Step 4: Run the tests.** Expected: PASS.
- [ ] **Step 5: Commit** with `feat: report model, charts, live report`.

---

### Task 9: PDF and PNG export, and the Docker image

**Files:**
- Create: `tracker/report/render.py`, templates `report/print.html` (standalone: inlined CSS, A4 portrait), `Dockerfile`, `tests/test_render.py`
- Modify: `tracker/report/views.py`

**Interfaces:**
- Produces:
  - `render_print_html(report: Report) -> str`: renders `report/print.html` (which includes `_body.html`) with the CSS read from `tracker/static/tracker.css` inlined and the charts as data URIs. This makes it self-contained, so Chromium needs no network access.
  - `html_to_pdf(html: str) -> bytes` (Playwright `page.pdf(format="A4", print_background=True)`).
  - `html_to_png(html: str, width: int = 1100) -> bytes` (Playwright `page.screenshot(full_page=True)`).
  - Routes `GET /trackers/<id>/report.pdf?week=` and `/report.png?week=` (viewer and above). Filenames are `<tracker-slug>-week-ending-YYYY-MM-DD.pdf` and `.png`.
- Dockerfile: based on `python:3.12-slim`; `pip install -r requirements.txt`; `playwright install --with-deps chromium`; `CMD gunicorn "tracker.app:create_app()" --workers 2 --threads 2 --bind 0.0.0.0:$PORT`.

- [ ] **Step 1: Write the failing tests** (mark the browser tests `@pytest.mark.browser`; `conftest.py` skips them when Chromium is not installed):

```python
def test_print_html_self_contained(...):  # no "http://" or "https://" src/href; contains "data:image/svg+xml"
@pytest.mark.browser
def test_pdf_bytes(...):  assert html_to_pdf(html)[:4] == b"%PDF"
@pytest.mark.browser
def test_png_bytes(...):  assert html_to_png(html)[:8] == b"\x89PNG\r\n\x1a\n"
def test_report_pdf_requires_role(client, ...):  # no role -> 404
@pytest.mark.browser
def test_report_pdf_download_headers(client, ...):  # content-type application/pdf; filename contains week ending
```

- [ ] **Step 2: Run `rtk pytest tests/test_render.py -v`.** Expected: FAIL.
- [ ] **Step 3: Implement.** Install Chromium locally with `rtk python -m playwright install --with-deps chromium`.
- [ ] **Step 4: Run the tests.** Expected: PASS, including the browser tests. Then run `docker build .` if Docker is available; otherwise, note in the PR description that the Render build is the first Docker build.
- [ ] **Step 5: Commit** with `feat: PDF and PNG export, Dockerfile`.

---

### Task 10: Email: recipients, template, composition, sending and retry

**Files:**
- Create: `tracker/mail/{__init__,smtp,compose,sending,views}.py`, templates `mail/settings.html` (recipients, template editor, preview), `mail/email_body.html`, `tests/test_mail.py`

**Interfaces:**
- Consumes: `build_report`, `render_print_html`, `html_to_pdf`, `remaining_chart`, `record`.
- Produces:
  - `send_message(msg: EmailMessage) -> None`. This ports `_get_smtp_config`, `_get_oauth2_token`, `_xoauth2_string` and the SMTP part of `_send_now` from CAPACITY `emails.py` (lines 202–380), reading the `app_settings` keys from Task 5 plus the environment secrets. It raises `MailError` on failure.
  - `PLACEHOLDERS: dict[str, str]` (name to description): `tracker_name`, `week_ending`, `status`, `verdict`, `percent_complete`, `completed`, `total_scope`, `remaining`, `forecast_date`, `target_date`, `headline`, `decisions`, `report_link`.
  - `placeholder_context(report: Report, link: str) -> dict[str, str]` (dates as `16 Oct 2026`, percentages as `37%`, missing values as `–`).
  - `render_placeholders(text: str, context: dict[str, str]) -> str`: replaces `{{name}}` with the HTML-escaped value. Unknown placeholders are left in place, and the preview flags them.
  - `DEFAULT_SUBJECT = "{{tracker_name}} – week ending {{week_ending}} – {{status}}"` and a `DEFAULT_BODY` covering the status, verdict, headline, "Needed from you" and a link (copy at the implementer's discretion, using only `PLACEHOLDERS`).
  - `build_report_email(report: Report, template: EmailTemplate | None, recipients: list[str], link: str, pdf: bytes) -> EmailMessage`. The HTML body is `email_body.html`: the rendered template, then the remaining chart as an inline PNG (`Content-ID: <remaining-chart>`), then a "View the full report" link. There is a plain-text alternative. The PDF is attached. `To` is the sender's own address; recipients go in `Bcc`.
  - `send_report(session, tracker: Tracker, week_ending: date, trigger: str, user_id: int | None, now: datetime) -> ReportSend`. It builds the report, PDF and email; stores the `ReportSend` with the PDF; on `MailError` it sets `status="queued"`, `attempts += 1` and `next_attempt_at = now + [5, 15, 60, 240] minutes[attempts-1]`; after 4 failed attempts the status becomes `failed`. Every outcome is audited. A tracker with no recipients raises `ValueError("Add at least one recipient before sending.")`.
  - `retry_queued(session, now: datetime) -> int`: resends due queued sends, re-using the stored PDF.
  - Routes (owner): `GET/POST /trackers/<id>/mail` (recipients add and remove; subject and body editor listing `PLACEHOLDERS`), `GET /trackers/<id>/mail/preview?week=`, `POST /trackers/<id>/mail/test` (sends to the current user only, trigger `manual`, not stored as a report send), `POST /trackers/<id>/mail/send?week=` (trigger `manual`).
- The link is `APP_URL + /trackers/<id>/report?week=YYYY-MM-DD`, and opening it requires sign-in.

- [ ] **Step 1: Write the failing tests** (monkeypatch `tracker.mail.smtp.send_message` with a recorder; the PDF tests monkeypatch `html_to_pdf` to return `b"%PDF-fake"`):

```python
def test_render_placeholders_escapes_html(): assert render_placeholders("{{headline}}", {"headline": "<b>"}) == "&lt;b&gt;"
def test_unknown_placeholder_left_in_place(): assert render_placeholders("{{nope}}", {}) == "{{nope}}"
def test_email_has_inline_chart_and_pdf(...):
    msg = build_report_email(...)
    parts = list(msg.walk())
    assert any(p.get("Content-ID") == "<remaining-chart>" for p in parts)
    assert any(p.get_filename() and p.get_filename().endswith(".pdf") for p in parts)
    assert msg["Bcc"] and "a@example.com" in msg["Bcc"]
def test_send_report_success_records_send(...):  # status sent, recipients stored, pdf stored, audit row
def test_send_report_failure_queues_with_backoff(...):  # MailError -> queued, attempts 1, next_attempt +5 min
def test_retry_queued_resends_and_fails_after_4(...): ...
def test_send_without_recipients_rejected(...): ...
def test_test_send_goes_only_to_current_user(...): ...
def test_mail_settings_owner_only(client, ...):  # editor -> 404
```

- [ ] **Step 2: Run `rtk pytest tests/test_mail.py -v`.** Expected: FAIL.
- [ ] **Step 3: Implement.** The template editor is a plain `<textarea>` for HTML with a server-rendered preview; the capacity app's Tiptap editor is out of scope.
- [ ] **Step 4: Run the tests.** Expected: PASS.
- [ ] **Step 5: Commit** with `feat: report email with inline chart and PDF, recipients, retry queue`.

---

### Task 11: Scheduled sending

**Files:**
- Create: `tracker/sched/__init__.py`, `tracker/sched/schedules.py` (copied verbatim from CAPACITY `sched/schedules.py`, with its module docstring kept), `tracker/sched/runner.py`, `tests/sched/test_schedules.py` (copy the relevant schedule tests from CAPACITY `tests/` if present, otherwise the test below), `tests/sched/test_runner.py`
- Modify: `tracker/trackers/views.py` and `settings.html` (fields `schedule_enabled`, `send_time` and `send_timezone`), `tracker/app.py` (register the CLI)

**Interfaces:**
- Consumes: `next_occurrences(kind, spec, timezone, after, until)`, `send_report`, `retry_queued`.
- Produces:
  - `cron_for(tracker: Tracker) -> str`: `f"{m} {h} * * {(tracker.week_ending_weekday + 1) % 7}"` (cron numbers Sunday as 0).
  - `due_sends(session, now_utc: datetime) -> list[tuple[int, date]]`: for each active tracker with `schedule_enabled`, take the latest fire from `next_occurrences("cron", {"expr": cron_for(t)}, t.send_timezone, now_utc - 24h, now_utc)`. Its local date is the `week_ending`. The pair is due if that week lies within the tracker's weeks and no `ReportSend` with `trigger="scheduled"` exists for it. Fires older than 24 hours are skipped.
  - `run_scheduler_cycle(session, now_utc: datetime) -> int`: for each due pair, **claim** it with `INSERT INTO report_sends (..., trigger='scheduled', status='sending') ... ON CONFLICT DO NOTHING RETURNING id`. Only the claimant calls `send_report(..., trigger="scheduled")`, which updates the claimed row (adjust `send_report` to accept an optional `claimed: ReportSend`). The cycle then calls `retry_queued`. It returns the number of sends attempted.
  - CLI `flask run-scheduler [--interval 60] [--once]`: loops over `run_scheduler_cycle` and logs each cycle.

- [ ] **Step 1: Write the failing tests:**

```python
def test_cron_for_friday_1700(): ...  # "0 17 * * 5"
def test_due_after_fire_time_london(...):  # Fri 16 Oct 2026 17:00 Europe/London = 16:00 UTC; now 16:05 UTC -> due (t, 16 Oct)
def test_not_due_before_fire_time(...):  # now 15:55 UTC -> []
def test_dst_end_week(...):  # Fri 30 Oct 2026 17:00 London = 17:00 UTC (GMT) -> due at 17:05 UTC, not 16:05
def test_scheduler_cycle_twice_sends_once(...):  # run_scheduler_cycle twice (and from two sessions) -> 1 send_report call
def test_fire_older_than_24h_skipped(...): ...
def test_schedule_disabled_not_due(...): ...
def test_week_outside_tracker_not_due(...): ...
```

- [ ] **Step 2: Run `rtk pytest tests/sched -v`.** Expected: FAIL.
- [ ] **Step 3: Implement.** Copy `schedules.py` byte for byte; do not port CAPACITY's planner, worker or repo (YAGNI). Weekly sends are claimed through the partial unique index from Task 2.
- [ ] **Step 4: Run the tests.** Expected: PASS.
- [ ] **Step 5: Commit** with `feat: scheduled weekly report sending`.

---

### Task 12: Workbook import

**Files:**
- Create: `tracker/importer/__init__.py`, `tracker/importer/workbook.py`, templates `importer/upload.html`, `importer/confirm.html`, `scripts/capture_workbook_golden.py`, `tests/importer/build_fixture.py`, `tests/importer/test_workbook.py`, `tests/engine/test_golden.py`
- Modify: `tracker/app.py` (CLI `flask import-workbook PATH --name NAME --weekday 4`; routes `GET/POST /import`, administrators only)

**Interfaces:**
- Consumes: `report_date_to_week_ending`, `week_endings`, the models, `record`.
- Produces:
  - `ImportPreview` dataclass: `settings: dict`, `groups: list[dict]`, `weeks: list[dict]` (`week_ending`, `target`, `actual`), `risks: list[dict]`, `inputs: dict`, `group_total: int`, `weekly_total: int`, `mismatch: int` (`group_total - (completed_before_first + weekly_total)`).
  - `read_workbook(path_or_file, weekday: int) -> ImportPreview` (openpyxl, `data_only=False`): it reads input cells only and never depends on Excel's cached values.
  - `create_tracker_from_preview(session, preview: ImportPreview, name: str, unit_label: str, group_label: str, user_id: int, accept_mismatch: bool) -> Tracker`. It raises `ImportMismatch` when `mismatch != 0` and `accept_mismatch` is false.
  - `eval_simple_formula(value) -> int | None`: accepts ints, floats and strings matching `^=\s*[\d\s+\-*/().]+$`, evaluated with `ast` (only numbers and `+ - * /`). Anything else raises `ImportError_` with the cell reference.
- Cell map (from the v2_27 workbook, §9; the sheet names are exact):
  - `Settings`: B6 is the first report date, B7 the last report date, B8 the target completion date, B9 the quantity completed before the first report, B10 the moving-average weeks. `first_week_ending = report_date_to_week_ending(B6 snapped to Monday as the workbook does, weekday)`; `last_week_ending` likewise from B7, capped at `max_last_week_ending`.
  - `By Location`: rows 5–10 (stop at the "Total" row): A is the name, B the baseline (formula allowed), C deployed (which becomes `starting_completed`), D ready-not-complete, G the planned completion date, H the RAG, I the comment. Skip rows with an empty name.
  - `Weekly Tracker`: rows 5–56. Row `i` represents report date `first_report + 7*(i-5)` and maps to its week-ending with `report_date_to_week_ending`. B is the target, C the actual (which becomes `Week.imported_actual` when not blank).
  - `Risks & Issues`: rows 5–19, columns A–J in the order of §5.1. Skip rows where B is empty.
  - `Report Inputs`: B7 is the status, B8 the headline, B9 the decisions, stored against the week-ending of B5.
- Dates may be Excel serial numbers or datetimes; normalise both to `date`.

- [ ] **Step 1: Write the failing tests.** `tests/importer/build_fixture.py` builds an anonymised workbook with openpyxl, using the exact sheet names and cells above, three groups ("Site A" with baseline `=202+135` and deployed 135, "Site B" 2/0, "Remote" 30/3), weekly actuals 40/38/20/40 (sum 138, equal to deployed 135 + 0 + 3, so the reconciliation passes), first report date Monday 7 Sep 2026, and one risk. The tests:

```python
def test_import_evaluates_baseline_formula(fixture_xlsx):
    p = read_workbook(fixture_xlsx, weekday=4); assert p.groups[0]["baseline"] == 337
def test_import_maps_monday_rows_to_previous_friday(fixture_xlsx):  # first report Mon 7 Sep 2026 -> first week 4 Sep
def test_import_creates_tracker(db, fixture_xlsx, admin):  # groups, starting figures, weeks, risks, inputs; creator owner; audit row
def test_import_reports_mismatch(db, fixture_xlsx_mismatch, admin):  # deployed 136 -> ImportMismatch(mismatch=1)
def test_import_rejects_unsafe_formula(...):  # "=SUM(A1:A3)" or "=__import__('os')" -> ImportError_ naming the cell
def test_imported_figures_match_engine(db, fixture_xlsx, admin):
    # after import: headline.completed 138, total_scope 369, forecast based on week ending 25 Sep 2026
def test_import_page_admin_only(client, ...): ...
```

`scripts/capture_workbook_golden.py PATH OUT.json` reads a workbook **that has been opened and saved in Excel** (so that its cached values exist) with `data_only=True`. It writes the inputs plus the workbook's computed outputs (Weekly Tracker columns E–K for rows with dates; Settings B18–B22), with location names replaced by "Site A", "Site B" and so on. `tests/engine/test_golden.py` loads `tests/fixtures/tc_win11_golden.json` when it exists (it is skipped otherwise) and asserts that the engine reproduces every figure exactly and every date shifted by `-3 days` (Monday report date to Friday week-ending, §9).

- [ ] **Step 2: Run `rtk pytest tests/importer tests/engine/test_golden.py -v`.** Expected: FAIL (the golden test is skipped).
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the tests.** Expected: PASS. The golden test stays skipped until the owner provides the Excel-saved workbook. Ask the owner to open `TC_Win11_Migration_CTO_Report_Template_v2_27.xlsx` in Excel, save it, and run the capture script; the uploaded file has no cached values.
- [ ] **Step 5: Commit** with `feat: one-time workbook import with reconciliation check`.

---

### Task 13: Render deployment and the migration runbook

**Files:**
- Create: `render.yaml`, `docs/runbooks/supabase-to-postgres.md`, `docs/runbooks/deploy-render.md`, `tests/test_cli.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: the Dockerfile from Task 9 and the CLI commands from Tasks 5, 11 and 12.
- `render.yaml` defines:
  - a `web` service (docker) with `preDeployCommand: alembic upgrade head` and health check `/healthz`;
  - a `worker` service (docker) running `flask --app "tracker.app:create_app()" run-scheduler --interval 60`.

  Both services read the env vars `DATABASE_URL`, `FLASK_SECRET_KEY`, `APP_URL`, `SMTP_PASSWORD`, `SMTP_CLIENT_SECRET`, `SSO_TENANT_ID`, `SSO_CLIENT_ID` and `SSO_CLIENT_SECRET` (all `sync: false`).
- The runbook (§10) covers:
  1. Freezing writes, by scaling the web and worker services to zero.
  2. `pg_dump --format=custom --no-owner --no-privileges --schema=public "$SUPABASE_DB_URL" -f tracker.dump`.
  3. Creating the target database.
  4. `pg_restore --no-owner --dbname "$TARGET_URL" tracker.dump`.
  5. `alembic current` on the target, which must equal head.
  6. Changing `DATABASE_URL` and scaling back up.
  7. Smoke-checking `/healthz`, the home page and one report PDF.
  8. Rollback: point `DATABASE_URL` back to Supabase.

  It notes that Supabase's direct (non-pooler) connection string, port 5432, must be used for `pg_dump`.

- [ ] **Step 1: Write the failing test** `tests/test_cli.py`: `flask run-scheduler --once` exits 0 against the test database with no trackers; `flask create-admin a@example.com` creates an active admin (password read from the `--password` option in tests).
- [ ] **Step 2: Run `rtk pytest tests/test_cli.py -v`.** Expected: FAIL if any wiring is missing; otherwise PASS. Fix the wiring.
- [ ] **Step 3: Write `render.yaml` and both runbooks.** Update the README with local setup (WSL Postgres, `.env` keys, `alembic upgrade head`, `flask create-admin`, `flask run`, `flask run-scheduler`), deployment and the import procedure.
- [ ] **Step 4: Run the full suite:** `rtk ruff check . && rtk ruff format --check . && rtk alembic check && rtk pytest -v`. Expected: all PASS (the browser tests pass when Chromium is installed; the golden test is skipped until it is provided).
- [ ] **Step 5: Commit** with `chore: Render blueprint, deployment and Supabase-to-Postgres runbooks`.

---

## Spec coverage

| Spec | Task |
|---|---|
| §1, §2 goals 1–2: multiple user-defined trackers, entries per group per week, no double entry | 2, 6, 7 |
| §2 goal 3, §6: calculations and the week-ending change | 3, 4, golden test in 12 |
| §2 goal 4, §7: report layout B, PDF, PNG, email body, sign-in links | 8, 9, 10 |
| §2 goal 5, §5.2: SSO and local accounts, approval, per-tracker roles, audit | 2, 5, 6 |
| §2 goal 6, §9: one-time import, week mapping, reconciliation | 12 |
| §3, §10: direct Postgres, Alembic, Render, Supabase-to-Postgres runbook | 1, 2, 13 |
| §4: reuse of EVERTON and CAPACITY | 1, 5, 10, 11 |
| §5.1 groups, retire rule, baseline audit, risks, inputs | 6, 7 |
| §5.3 home page | 6 |
| §8 one email per tracker, recipients, templates, schedule, retry, no duplicates | 10, 11 |
| §12 calls (zero for empty weeks, live report and stored PDF, retire rule, extend last week, fixtures anonymised) | 4, 6, 7, 10, 12 |
