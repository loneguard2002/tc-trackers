# Progress Tracker

A generic Flask and Postgres application for tracking progress against defined targets, with reports, email and scheduled jobs (added in later tasks).

## Local setup

1. Install Postgres in WSL: `sudo apt install postgresql`, then create a `tracker_test` database (and a `tracker` database for development).
2. Create the environment: `python -m venv .venv && .venv/bin/pip install -r requirements.txt`.
3. Set environment variables (for example in an untracked `.env`):
   - `FLASK_SECRET_KEY` (at least 32 characters), `DATABASE_URL`, `APP_URL`
   - `SESSION_COOKIE_SECURE` (`true` by default; set `false` for plain HTTP locally)
   - Optional SSO, enabled only when all three are set: `SSO_TENANT_ID`, `SSO_CLIENT_ID`, `SSO_CLIENT_SECRET`
   - `TEST_DATABASE_URL=postgresql+psycopg://<user>@localhost/tracker_test` for the tests

## Tests

- `pytest` runs the suite; database tests are skipped when Postgres is unreachable.
- `pytest -m db` runs the database tests only.

The CI workflow is kept in `ci/github-ci.yml` and belongs at `.github/workflows/ci.yml`.
