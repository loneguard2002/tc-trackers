# Runbook: Supabase to Render Postgres

Moves the production data from Supabase to a Render Postgres database. Expect a short write freeze. Use the Supabase direct (non-pooler) connection string, port 5432, for `pg_dump`; the pooler cannot be used for it.

Variables used below: `SUPABASE_DB_URL` (direct connection, port 5432) and `TARGET_URL` (the new database, plain `postgresql://` form for the client tools).

1. **Freeze writes.** In Render, scale `tracker-web` and `tracker-worker` to zero instances. Confirm no instance is running.
2. **Dump.**

   ```bash
   pg_dump --format=custom --no-owner --no-privileges --schema=public "$SUPABASE_DB_URL" -f tracker.dump
   ```

3. **Create the target database.** Create an empty Render Postgres database of the same major version or newer, and note its external connection string for the restore.
4. **Restore.**

   ```bash
   pg_restore --no-owner --dbname "$TARGET_URL" tracker.dump
   ```

5. **Verify the schema version.** With `DATABASE_URL` set to the target in the `postgresql+psycopg://` form, run `alembic current`. The revision must equal `alembic heads`. If it is behind, run `alembic upgrade head`.
6. **Cut over.** Change `DATABASE_URL` on both services to the target, then scale both back up (the web pre-deploy command applies any outstanding migration).
7. **Smoke-check.** Open `/healthz`, the home page, and one report PDF; confirm the scheduler worker logs a cycle.
8. **Rollback.** Scale both services to zero, point `DATABASE_URL` back to Supabase, and scale up. Writes made on the new database after cutover are not carried back; export them first if any were made.

Delete `tracker.dump` once the cutover is confirmed; it contains production data. Keep the Supabase project, unchanged, until the new database has run through at least one scheduled send.

See also `deploy-render.md` for the scheduler outage and stuck-send notes.
