# Progress Tracker

A generic Flask and Postgres application for tracking progress against defined targets, with reports, email and scheduled jobs.

## Local setup

1. Install Postgres in WSL: `sudo apt install postgresql`, then create a `tracker_test` database (and a `tracker` database for development).
2. Create the environment: `python -m venv .venv && .venv/bin/pip install -r requirements.txt`, then `playwright install chromium` for PDF and PNG rendering.
3. Set environment variables (for example in an untracked `.env`):
   - `FLASK_SECRET_KEY` (at least 32 characters), `DATABASE_URL`, `APP_URL`
   - `SESSION_COOKIE_SECURE` (`true` by default; set `false` for plain HTTP locally)
   - Optional SSO, enabled only when all three are set: `SSO_TENANT_ID`, `SSO_CLIENT_ID`, `SSO_CLIENT_SECRET`
   - Email: `SMTP_PASSWORD` or `SMTP_CLIENT_SECRET`, as the chosen SMTP authentication requires
   - `TEST_DATABASE_URL=postgresql+psycopg://<user>@localhost/tracker_test` for the tests
4. Apply the migrations: `alembic upgrade head`. Alembic stops with an error when neither `DATABASE_URL` nor `TEST_DATABASE_URL` is set.
5. Create an administrator: `flask --app "tracker.app:create_app()" create-admin EMAIL`. A forgotten local password is reset with `flask --app "tracker.app:create_app()" reset-password EMAIL`.
6. Run the web application with `flask --app "tracker.app:create_app()" run` and, in a second terminal, the scheduler with `flask --app "tracker.app:create_app()" run-scheduler` (`--once` runs a single cycle).

## Tests

- `pytest` runs the suite; database tests are skipped when Postgres is unreachable. For the full run, set `TEST_DATABASE_URL` to a reachable Postgres.
- `pytest -m db` runs the database tests only.
- `alembic check` (against a real database) confirms that the models and migrations agree.
- Golden workbook test: open the v2_27 workbook in Excel, save it, then run `python tools/capture_workbook_golden.py PATH tests/fixtures/tc_win11_golden.json`. The test skips while the fixture is absent.

The CI workflow is kept in `ci/github-ci.yml`; after cloning, move it to `.github/workflows/ci.yml`.

## Front-end libraries

The live report page draws its charts with Apache ECharts 6.1.0 (Apache-2.0), and the report, Risks and Entries tables use Tabulator 6.6.1 (MIT). Both are stored in `tracker/static/vendor/` with their licence files, because the Content Security Policy allows scripts from the application only. To update one, run `npm pack <name>@<version>`, copy the `dist` file and the licence into `tracker/static/vendor/`, and change the version in the file name and in the templates that load it (`report/page.html` and `_table_assets.html`). The PDF, PNG and email keep the matplotlib charts.

## Importing the existing workbook

Sign in as an administrator and open `/import`, or run `flask --app "tracker.app:create_app()" import-workbook PATH --name NAME --weekday N [--owner EMAIL]`. The import reports a reconciliation check; `--accept-mismatch` imports regardless.

## Deployment

`render.yaml` defines the web service and the scheduler worker. Its variables are all entered in the Render dashboard; the `SSO_*` variables and whichever of `SMTP_PASSWORD` or `SMTP_CLIENT_SECRET` is unused are optional and may be left blank when Render prompts for them. The demo runs on Render with a Supabase database: `DATABASE_URL` is the Supabase session pooler connection string (port 5432, `postgresql+psycopg://` prefix; not the transaction pooler on port 6543), and no Render Postgres database is created. The one migration path is from Supabase to a Postgres server hosted by Tradition. See `docs/runbooks/deploy-render.md` for setup and operations, and `docs/runbooks/supabase-to-postgres.md` for the data move.

Operational notes:

- If the scheduler worker is down for more than 24 hours past a tracker's send time, that week's automatic send is skipped; send it manually from the tracker's email page.
- A crash mid-send can leave a `report_sends` row with status `sending` that blocks that week's scheduled send. Check with `SELECT id, tracker_id, week_ending FROM report_sends WHERE status = 'sending' AND created_at < now() - interval '15 minutes';`, mark the row `failed`, then send manually. The age condition avoids matching a send that is legitimately in progress, because the `sending` row is committed before the PDF and SMTP work begins. The runbook has the full steps.
