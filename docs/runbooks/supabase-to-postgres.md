# Runbook: Supabase to a Tradition-hosted Postgres server

Moves the data from Supabase (where the demo runs) to a Postgres server hosted by Tradition. Tradition IT supplies the target server and its connection URL. Expect a short write freeze. Run `pg_dump` against Supabase's direct connection, or its session pooler, on port 5432 (verify in the Supabase dashboard which applies to the project); never the transaction pooler (port 6543).

Variables used below: `SUPABASE_DB_URL` (direct connection or session pooler, port 5432) and `TARGET_URL` (the Tradition-hosted database supplied by Tradition IT, plain `postgresql://` form for the client tools).

1. **Freeze writes.** Scale `tracker-web` and `tracker-worker` to zero instances. Confirm no instance is running.
2. **Dump.**

   ```bash
   pg_dump --format=custom --no-owner --no-privileges --schema=public "$SUPABASE_DB_URL" -f tracker.dump
   ```

3. **Prepare the target database.** Ask Tradition IT for an empty database of the same major version or newer, and for its connection URL. Confirm the Render services (or their new host) can reach it.
4. **Restore.**

   ```bash
   pg_restore --no-owner --dbname "$TARGET_URL" tracker.dump
   ```

5. **Verify the schema version.** With `DATABASE_URL` set to the target in the `postgresql+psycopg://` form, run `alembic current`. The revision must equal `alembic heads`. If it is behind, run `alembic upgrade head`.
6. **Cut over.** Change `DATABASE_URL` on both services to the target (`postgresql+psycopg://` form), then scale both back up (the web pre-deploy command applies any outstanding migration).
7. **Smoke-check.** Open `/healthz`, the home page, and one report PDF; confirm the scheduler worker logs a cycle.
8. **Rollback.** Scale both services to zero, point `DATABASE_URL` back to Supabase, and scale up. Writes made on the new database after cutover are not carried back; export them first if any were made.

Delete `tracker.dump` once the cutover is confirmed; it contains production data. Keep the Supabase project, unchanged, until the new database has run through at least one scheduled send.

See also `deploy-render.md` for the scheduler outage and stuck-send notes.
