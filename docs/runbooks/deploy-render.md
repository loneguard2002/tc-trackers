# Deploying to Render

The blueprint `render.yaml` defines two Docker services built from the same `Dockerfile`: `tracker-web` (gunicorn, health check `/healthz`, `alembic upgrade head` as the pre-deploy command) and `tracker-worker` (`flask --app "tracker.app:create_app()" run-scheduler --interval 60`). Both use the `starter` plan; the owner may change it in `render.yaml` or the dashboard.

## First deployment

1. Create a Render Postgres database in the same region and copy its internal connection string, converted to the `postgresql+psycopg://` form.
2. In Render, create a Blueprint from this repository. Render prompts for every variable marked `sync: false`.
3. Enter the variables on both services (the worker needs the same values as the web service):

   | Variable | Purpose |
   |---|---|
   | `DATABASE_URL` | SQLAlchemy URL of the Render Postgres database |
   | `FLASK_SECRET_KEY` | At least 32 random characters; keep identical on both services |
   | `APP_URL` | Public base URL, used in sign-in links in emails |
   | `SMTP_PASSWORD` | SMTP password (when SMTP basic authentication is used) |
   | `SMTP_CLIENT_SECRET` | Client secret (when OAuth is used for SMTP) |
   | `SSO_TENANT_ID`, `SSO_CLIENT_ID`, `SSO_CLIENT_SECRET` | Single sign-on; enabled only when all three are set |

   Optional variables: the three `SSO_*` variables when single sign-on is not used, and whichever of `SMTP_PASSWORD` or `SMTP_CLIENT_SECRET` the chosen SMTP authentication does not use. Leave them blank when Render prompts for them.

   `SESSION_COOKIE_SECURE` stays at its secure default (`true`); do not set it on Render. Never commit a secret value to the repository.
4. Deploy. The pre-deploy command applies the migrations before the new web instance takes traffic.
5. Create the first administrator from the web service shell: `flask --app "tracker.app:create_app()" create-admin EMAIL`.
6. Check `/healthz`, the home page and a report PDF.

## Routine operations

- **Forgotten password:** `flask --app "tracker.app:create_app()" reset-password EMAIL` (prompts, hidden, with confirmation; or `--password`). The action is audited without the password. Single sign-on accounts have no local password.
- **Workbook import:** sign in as an administrator and use `/import`, or run `flask --app "tracker.app:create_app()" import-workbook PATH --name NAME --weekday N [--owner EMAIL]` from a shell with the file available.
- **CI:** after cloning, move `ci/github-ci.yml` to `.github/workflows/ci.yml`.

## Scheduler notes

- **Worker outage.** If the scheduler worker is down for more than 24 hours past a tracker's send time, that week's automatic send is skipped. Send it manually from the tracker's email page.
- **Crash during a send.** A crash part-way through a send can leave a `report_sends` row with status `sending`, which blocks that week's scheduled send. Check:

  ```sql
  SELECT id, tracker_id, week_ending, trigger, status
  FROM report_sends
  WHERE status = 'sending'
    AND created_at < now() - interval '15 minutes';
  ```

  Confirm no send is genuinely in progress (the worker is idle), mark the row as failed, then send manually. The age condition keeps the query from matching a send that is legitimately in progress, because the `sending` row is committed before the PDF and SMTP work begins from the tracker's email page:

  ```sql
  UPDATE report_sends SET status = 'failed' WHERE id = <id from the check> AND status = 'sending'
    AND created_at < now() - interval '15 minutes';
  ```

## Verification

- Full suite with a database: set `TEST_DATABASE_URL` to a reachable Postgres and run `pytest`.
- Schema drift: `alembic check` against a real database, with `DATABASE_URL` set. Alembic refuses to run without `DATABASE_URL` or `TEST_DATABASE_URL`.
- Golden workbook test: open the v2_27 workbook in Excel, save it, then run `python tools/capture_workbook_golden.py PATH tests/fixtures/tc_win11_golden.json`. The test skips while the fixture is absent.
