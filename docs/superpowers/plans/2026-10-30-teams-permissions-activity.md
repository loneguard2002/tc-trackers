# Teams, Permission Sets and Activity Log Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the tracker nested teams whose roles flow down the tree, named permission sets that delegate administrator-type functions, a full activity log with a viewing screen and optional retention, and in-place correction of progress entries.

**Architecture:** Migration `0003` adds teams, memberships, permission sets and their holders, `trackers.team_id` and `audit_log.target_user_id`. Access is worked out on each request: one recursive Postgres query (`WITH RECURSIVE`) in `tracker/auth/roles.py` gives a user's role on every tracker, and `tracker/auth/permissions.py` gives the permissions they hold. New blueprints (`teams`, `permsets`, `activity`) follow the existing settings-card layout; every change writes its activity entry in the same transaction.

**Tech Stack:** Python 3.12, Flask 3.1, SQLAlchemy 2.1, Alembic 1.20, Postgres, Jinja (StrictUndefined in tests), pytest with Playwright Chromium for browser tests, ruff.

**Spec:** `docs/superpowers/specs/2026-10-26-teams-permissions-activity-design.md` (binding; sections 11 and 12 are approved).

## Global Constraints

- Work only in the worktree `/tmp/claude-1000/-home-alexkrovina/cf13b4e4-1890-473a-b9dc-06d0fca97d35/scratchpad/wt-access` (branch `feat/access-teams-permissions`). Never touch `/mnt/c/Users/AlexKrovina/Documents/GitHub/tc-trackers`, which another session uses; only its `.venv` and `.env` are read, by absolute path. One branch, one PR at the end; do not push.
- Tests (Postgres-backed; run with the Bash sandbox disabled because of the Postgres socket): `/tmp/claude-1000/-home-alexkrovina/cf13b4e4-1890-473a-b9dc-06d0fca97d35/scratchpad/tools/acc-test.sh <pytest args>`. A run that reports many "skipped" database tests is broken, not green.
- Lint: `cd /tmp/claude-1000/-home-alexkrovina/cf13b4e4-1890-473a-b9dc-06d0fca97d35/scratchpad/wt-access && /mnt/c/Users/AlexKrovina/Documents/GitHub/tc-trackers/.venv/bin/ruff check . && /mnt/c/Users/AlexKrovina/Documents/GitHub/tc-trackers/.venv/bin/ruff format --check .` (120-character lines). Run `ruff format .` with the same binary before committing when the check fails.
- Schema drift (CI runs `alembic upgrade head` then `alembic check`). Locally the `tracker_check` database is shared with the main folder's session, so the worktree checks its private `tracker_test_design` database instead (sandbox disabled): `cd /tmp/claude-1000/-home-alexkrovina/cf13b4e4-1890-473a-b9dc-06d0fca97d35/scratchpad/wt-access && export DATABASE_URL=$(grep ^TEST_DATABASE_URL= /mnt/c/Users/AlexKrovina/Documents/GitHub/tc-trackers/.env | cut -d= -f2- | sed -E 's#/tracker_test[a-z_]*$#/tracker_test_design#') && /mnt/c/Users/AlexKrovina/Documents/GitHub/tc-trackers/.venv/bin/alembic upgrade head && /mnt/c/Users/AlexKrovina/Documents/GitHub/tc-trackers/.venv/bin/alembic check`. Expected last line: `No new upgrade operations detected.`
- Commits: `git -c user.name="Alex Krovina" -c user.email="alex.krovina@tradition.ch" commit -m "<message>"`, the message ending with the line `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Do not commit CRLF-only changes.
- One new migration only: `migrations/versions/0003_teams_permissions_activity.py`, `revision = "0003"`, `down_revision = "0002"`. Plain Postgres; recursive team lookups use standard `WITH RECURSIVE`.
- Strict Content Security Policy: no inline scripts, `<style>` blocks, `style=` attributes or `on*=` handlers in served templates (`tests/test_templates.py` scans every template under `tracker/templates`, so new templates are covered automatically). Behaviour goes in `tracker/static/*.js`, styles in `tracker/static/tracker.css`.
- Every POST form carries `{{ csrf_field(csrf_token()) }}`; tests post through `post()` from `tests/conftest.py`.
- British English, formal interface copy, no contractions in the interface.
- Roles are exactly `viewer`, `editor`, `owner` (`ROLE_ORDER = {"viewer": 1, "editor": 2, "owner": 3}`).
- The permission names, exactly: `manage_users`, `manage_teams`, `create_trackers`, `import_workbooks`, `manage_email_settings`, `view_all_trackers`, `view_activity`. Administrators hold every permission. Administrator only, never delegable: the administrator flag; creating, editing and deleting permission sets and choosing who holds them; the audit retention setting.
- Tracker pages keep the 404 rule (missing tracker, no role and too low a role all answer 404). Administration screens refuse with 403, as `admin_required` does today.
- Every change and its activity entry are committed in one transaction (`record(...)` then a single `db.commit()`). New change entries store `detail` as `{"before": …, "after": …}` (other keys may sit beside them). Entries never contain passwords, password hashes, tokens or SMTP secrets.
- Limits from the spec: retention from 90 to 3,650 days (absent means keep entries indefinitely); the Activity screen shows 50 entries a page; `login_failed` stores the email address entered cut to 254 characters.
- Page idiom (see `tracker/templates/mail/settings.html` and `tracker/templates/trackers/settings.html`): `.settings-section` cards with `.settings-section-head` (and `.has-action`) and `.settings-section-foot`, the `field` macro, `.subnav`, `.section-table`, `.chips`/`.chip`, `.status-pill` and `.badge`, `.member-list`/`.member-cell`. Confirmations use `form[data-inline-confirm]` with `[data-ask]`, `[data-confirm-box]`, `[data-confirm-yes]`, `[data-confirm-no]` and the `data-confirm` attribute as the fallback (`tracker/static/tracker.js`).
- Name limits decided for this build: team and permission set names are trimmed, required, at most 100 characters and unique ignoring case; descriptions are at most 500 characters.

## Review Focus

- Activity rows whose actor, affected user or tracker has since been deleted (references set to NULL), whose `detail` is NULL, in an older shape, or for an action with no label: the screen still renders and shows the stored values (test in Task 11).
- Malformed query strings and form ids (`page=abc`, `page=0`, `from=2026-13-45`, `person=xyz`, `parent_id=abc`): a normal page with the filter ignored, or a 400, never a 500 (tests in Tasks 5 and 11).
- Team and permission set names that differ only in capitals or surrounding spaces, or that are over 100 characters: refused with a message and nothing stored, never an `IntegrityError` 500 (tests in Tasks 5 and 8).
- Stale forms: approving with a team that has since been deleted, adding a user who has since been disabled, editing an entry that has since been deleted: a message or 404 and no partial change (tests in Tasks 5, 9 and 13).
- The retention period typed the way the screen writes it, `3,650` or ` 365 `, is accepted; `89`, `0`, `90.5` and `3651` are refused with the message (test in Task 12).

---

### Task 1: Schema, migration 0003 and the audit helper

**Files:**
- Modify: `tracker/models.py`
- Create: `migrations/versions/0003_teams_permissions_activity.py`
- Modify: `tracker/audit.py`
- Modify: `tests/conftest.py` (alembic config helper and team/permission fixtures)
- Test: `tests/test_migration_matches_models.py`, `tests/test_models.py`, `tests/test_migration_0003.py` (new)

**Interfaces:**
- Produces (models, all in `tracker/models.py`):
  - `Team`: `teams` (`id` identity; `name` Text not null; `description` Text not null default `""`; `parent_id` FK `teams.id` `ondelete="RESTRICT"`, nullable; `created_at`). Module-level `Index("uq_teams_name_lower", func.lower(Team.name), unique=True)` and `Index("ix_teams_parent_id", Team.parent_id)`.
  - `TeamMember`: `team_members` (`team_id` FK cascade, `user_id` FK cascade, together the primary key; `role` Text with `CheckConstraint("role IN ('viewer', 'editor', 'owner')", name="role")`), plus `Index("ix_team_members_user_id", "user_id")`.
  - `Tracker.team_id: Mapped[int | None]` FK `teams.id` `ondelete="RESTRICT"`, with `Index("ix_trackers_team_id", "team_id")`.
  - `PermissionSet`: `permission_sets` (`id`, `name`, `description` default `""`, `created_at`), with `Index("uq_permission_sets_name_lower", func.lower(PermissionSet.name), unique=True)`.
  - `PermissionSetPermission`: `permission_set_permissions` (`set_id` FK `permission_sets.id` cascade, `permission` Text; together the primary key).
  - `PermissionSetHolder`: `permission_set_holders` (`id`; `set_id` FK cascade not null; `team_id` FK `teams.id` cascade nullable; `user_id` FK `users.id` cascade nullable; `CheckConstraint("num_nonnulls(team_id, user_id) = 1", name="one_holder")`; partial unique indexes `uq_permission_set_holders_set_team` on `(set_id, team_id) WHERE team_id IS NOT NULL` and `uq_permission_set_holders_set_user` on `(set_id, user_id) WHERE user_id IS NOT NULL`).
  - `AuditLog.target_user_id: Mapped[int | None]` FK `users.id` `ondelete="SET NULL"`; indexes `ix_audit_log_at`, `ix_audit_log_target_user_id`, `ix_audit_log_action`.
- Produces (audit): `record(session, *, user_id, tracker_id, action, entity, entity_id, detail=None, target_user_id: int | None = None) -> None` and `change(before, after) -> dict` returning `{"before": before, "after": after}` in `tracker/audit.py`.
- Produces (test fixtures in `tests/conftest.py`): `alembic_config() -> Config` (used by `_db_engine` too); `team_factory(name: str | None = None, parent: Team | None = None, **kw) -> Team`; `add_member(team: Team, user: User, role: str) -> None`; `give_set(permissions: list[str], *, team: Team | None = None, user: User | None = None, name: str | None = None) -> PermissionSet` (creates the set, its permissions and one holder, commits).

- [ ] **Step 1: Write the failing model tests in `tests/test_models.py`**

```python
def test_team_name_unique_ignoring_case(db, team_factory):
    team_factory(name="Windows")
    with pytest.raises(IntegrityError):
        team_factory(name="windows")

def test_holder_needs_exactly_one_of_team_and_user(db, team_factory, user_factory):
    s = PermissionSet(name="PMO"); db.add(s); db.commit()
    for team_id, user_id in ((None, None), (team_factory().id, user_factory().id)):
        db.add(PermissionSetHolder(set_id=s.id, team_id=team_id, user_id=user_id))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()

def test_set_held_once_per_team_and_per_user(db, team_factory, user_factory): ...
    # a second identical holder row for the same team (and for the same user) raises IntegrityError

def test_team_with_tracker_or_child_cannot_be_deleted_in_the_database(db, team_factory, tracker_factory): ...
    # db.delete(team) with a tracker in it, and with a child team, each raise IntegrityError (RESTRICT)

def test_deleting_a_user_clears_target_user_id(db, user_factory):
    # record(..., target_user_id=u.id); delete u; the row survives with target_user_id None
```

- [ ] **Step 2: Write the failing migration tests**

In `tests/test_migration_matches_models.py` add `test_migration_creates_access_indexes_and_backfill`, asserting on `_offline_sql()`:

```python
assert "CREATE UNIQUE INDEX uq_teams_name_lower ON teams (lower(name))" in sql
assert "CREATE UNIQUE INDEX uq_permission_sets_name_lower ON permission_sets (lower(name))" in sql
assert re.search(r"CREATE UNIQUE INDEX uq_permission_set_holders_set_team ON permission_set_holders "
                 r"\(set_id, team_id\) WHERE team_id IS NOT NULL", sql)
assert re.search(r"CREATE UNIQUE INDEX uq_permission_set_holders_set_user ON permission_set_holders "
                 r"\(set_id, user_id\) WHERE user_id IS NOT NULL", sql)
for name in ("ix_audit_log_at", "ix_audit_log_target_user_id", "ix_audit_log_action"):
    assert f"CREATE INDEX {name} ON audit_log" in sql
assert re.search(r"UPDATE audit_log SET target_user_id = users\.id FROM users\s+WHERE audit_log\.entity = 'user' "
                 r"AND audit_log\.entity_id = users\.id::text", sql)
```

Create `tests/test_migration_0003.py` with one test, `test_upgrade_keeps_visible_trackers_and_backfills_affected_users(db)`. It uses a fixture `at_revision_0002(db)` that runs `command.downgrade(alembic_config(), "0002")` and, in `finally`, `command.upgrade(alembic_config(), "head")` (the fixture depends on `db`, so it tears down before the truncation). In the 0002 schema, insert with raw SQL: an active administrator, an active user with a `viewer` row on tracker A, an active user with no rows, a pending user with an `owner` row on tracker B, two trackers, and three audit rows (`entity='user'` with an existing user's id, `entity='user'` with id `'9999'`, `entity='tracker'`). Record each active user's visible tracker ids with the old rule (administrator: every tracker; anyone else: their `tracker_roles` rows). Upgrade, then:

```python
for user_id, before in old_visible.items():
    assert [t.id for t in visible_trackers(db, db.get(User, user_id))] == before
assert targets == {existing_user_row: existing_user_id, missing_user_row: None, tracker_row: None}
assert db.scalar(select(func.count()).select_from(Team)) == 0
assert db.scalar(select(func.count()).select_from(PermissionSet)) == 0
```

- [ ] **Step 3: Run the tests to verify they fail**

Run (sandbox disabled): `/tmp/claude-1000/-home-alexkrovina/cf13b4e4-1890-473a-b9dc-06d0fca97d35/scratchpad/tools/acc-test.sh tests/test_models.py tests/test_migration_matches_models.py tests/test_migration_0003.py -q`
Expected: FAIL (`ImportError` for `Team`, missing indexes in the offline SQL).

- [ ] **Step 4: Add the models, the audit helper change and the fixtures**

As in the Interfaces block. Name every constraint so the naming convention yields `pk_team_members`, `ck_team_members_role`, `ck_permission_set_holders_one_holder`, `fk_teams_parent_id_teams`, `fk_trackers_team_id_teams`, `fk_audit_log_target_user_id_users` (the existing named-constraint test checks they appear in the migration).

- [ ] **Step 5: Write migration 0003**

`upgrade()`: create `teams`, `team_members`, `permission_sets`, `permission_set_permissions`, `permission_set_holders` with the constraints and indexes above; `op.add_column("trackers", team_id)` with its foreign key and index; `op.add_column("audit_log", target_user_id)` with its foreign key and the three indexes; then the backfill, comparing as text so non-numeric ids cannot fail a cast:

```sql
UPDATE audit_log SET target_user_id = users.id FROM users
WHERE audit_log.entity = 'user' AND audit_log.entity_id = users.id::text
```

`downgrade()` reverses every step (drop indexes and columns, then tables in dependency order).

- [ ] **Step 6: Run the tests and the schema check**

Run (sandbox disabled): `/tmp/claude-1000/-home-alexkrovina/cf13b4e4-1890-473a-b9dc-06d0fca97d35/scratchpad/tools/acc-test.sh tests/test_models.py tests/test_migration_matches_models.py tests/test_migration_0003.py tests/test_roles.py -q`
Expected: PASS.
Run (sandbox disabled): `cd /tmp/claude-1000/-home-alexkrovina/cf13b4e4-1890-473a-b9dc-06d0fca97d35/scratchpad/wt-access && export DATABASE_URL=$(grep ^TEST_DATABASE_URL= /mnt/c/Users/AlexKrovina/Documents/GitHub/tc-trackers/.env | cut -d= -f2- | sed -E 's#/tracker_test[a-z_]*$#/tracker_test_design#') && /mnt/c/Users/AlexKrovina/Documents/GitHub/tc-trackers/.venv/bin/alembic upgrade head && /mnt/c/Users/AlexKrovina/Documents/GitHub/tc-trackers/.venv/bin/alembic check`
Expected: `No new upgrade operations detected.`

- [ ] **Step 7: Lint and commit**

Run the lint command from Global Constraints; expected `All checks passed!` and no files to reformat.

```bash
git add tracker/models.py tracker/audit.py migrations/versions/0003_teams_permissions_activity.py tests/conftest.py tests/test_models.py tests/test_migration_matches_models.py tests/test_migration_0003.py
git -c user.name="Alex Krovina" -c user.email="alex.krovina@tradition.ch" commit -m "feat: migration 0003 for teams, permission sets and the affected user on activity entries

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Role resolution through teams

**Files:**
- Modify: `tracker/auth/roles.py`
- Modify: `tracker/trackers/views.py` (`home` reads every card's role from one call)
- Test: `tests/test_roles.py`

**Interfaces:**
- Consumes: the Task 1 models; fixtures `team_factory`, `add_member`, `give_set`, `grant`.
- Produces (in `tracker/auth/roles.py`):
  - `ROLE_BY_RANK = {1: "viewer", 2: "editor", 3: "owner"}`.
  - `tracker_roles(session, user: User) -> dict[int, str]`: tracker id to the highest role, for every tracker the user reaches (archived included). Administrators: every tracker as `"owner"`. Users whose `status != "active"`: `{}`.
  - `user_role(session, user: User, tracker_id: int) -> str | None` (same rules, one tracker).
  - `visible_trackers(session, user: User) -> list[Tracker]`, ordered by name then id, one SQL statement.
  - `require_tracker_role(min_role)` unchanged in behaviour.

The grants query (built with SQLAlchemy Core, `select(...).cte(recursive=True)` and a `case()` for the rank). `UNION` (not `UNION ALL`) in the recursive part guarantees the walk ends even if a cycle ever reached the table:

```sql
WITH RECURSIVE reach(team_id, rank) AS (
    SELECT m.team_id, rank(m.role) FROM team_members m WHERE m.user_id = :uid
  UNION
    SELECT t.id, r.rank FROM teams t JOIN reach r ON t.parent_id = r.team_id
)
SELECT tracker_id, max(rank) FROM (
    SELECT tracker_id, rank(role) FROM tracker_roles WHERE user_id = :uid
  UNION ALL
    SELECT k.id, r.rank FROM trackers k JOIN reach r ON k.team_id = r.team_id
  UNION ALL
    SELECT k.id, 1 FROM trackers k WHERE EXISTS (
        SELECT 1 FROM permission_set_holders h
        JOIN permission_set_permissions p ON p.set_id = h.set_id AND p.permission = 'view_all_trackers'
        WHERE h.user_id = :uid OR h.team_id IN (SELECT team_id FROM team_members WHERE user_id = :uid))
) grants GROUP BY tracker_id
```

`visible_trackers` selects `Tracker` joined to this grouped subquery (or every tracker for an administrator).

- [ ] **Step 1: Write the failing tests in `tests/test_roles.py`**

```python
def test_team_role_alone(db, user_factory, tracker_factory, team_factory, add_member):
    team, user = team_factory(name="Windows"), user_factory()
    t = tracker_factory(team_id=team.id)
    add_member(team, user, "editor")
    assert user_role(db, user, t.id) == "editor"

def test_team_role_flows_down_several_levels(...):   # A > B > C; editor in A; tracker in C -> "editor"
def test_team_role_not_sideways_or_upwards(...):     # member of B: tracker in A -> None; tracker in sibling B2 -> None
def test_highest_route_wins(...):
    # direct viewer + team owner -> owner; direct owner + team viewer -> owner;
    # viewer in A and editor in B (B under A), tracker in B -> editor; view_all + direct editor -> editor
def test_view_all_trackers_gives_viewer_everywhere(...):   # set held directly, and set held by a team the user is in
def test_view_all_held_by_team_above_or_below_does_not_apply(...):  # held by B; member of A (parent) or C (child) -> None
def test_tracker_without_team_is_reached_only_directly_by_admin_or_view_all(...)
def test_pending_and_disabled_users_have_no_access(...):
    # each holds a direct role, a team role and view_all_trackers:
    assert user_role(db, u, t.id) is None and visible_trackers(db, u) == [] and tracker_roles(db, u) == {}
def test_team_member_opens_tracker_and_others_get_404(client, ...):   # 200 via team; 404 for a sibling team's tracker
def test_visible_trackers_is_one_statement(db, ...):
    # count "before_cursor_execute" events on the engine around visible_trackers(...) -> exactly 1
def test_archived_tracker_reached_through_team_is_read_only(client, ...):
    # team editor posts a new entry to an archived tracker in the team -> page says "This tracker is archived."
def test_home_lists_team_trackers_with_their_role(client, ...)
```

Keep the existing tests in the file unchanged.

- [ ] **Step 2: Run them to verify they fail**

Run (sandbox disabled): `/tmp/claude-1000/-home-alexkrovina/cf13b4e4-1890-473a-b9dc-06d0fca97d35/scratchpad/tools/acc-test.sh tests/test_roles.py -q`
Expected: FAIL (team routes give `None`; `tracker_roles` not defined).

- [ ] **Step 3: Rewrite `tracker_roles`, `user_role` and `visible_trackers`**

As in the Interfaces block. In `home()`, replace the per-card `user_role(db, user, t.id)` with one `roles = tracker_roles(db, user)` and `roles.get(t.id)`.

- [ ] **Step 4: Run the role tests and the whole suite**

Run (sandbox disabled): `/tmp/claude-1000/-home-alexkrovina/cf13b4e4-1890-473a-b9dc-06d0fca97d35/scratchpad/tools/acc-test.sh tests/test_roles.py tests/test_migration_0003.py -q`, then `/tmp/claude-1000/-home-alexkrovina/cf13b4e4-1890-473a-b9dc-06d0fca97d35/scratchpad/tools/acc-test.sh -q -x`
Expected: PASS.

- [ ] **Step 5: Lint and commit**

Run the lint command from Global Constraints.

```bash
git add tracker/auth/roles.py tracker/trackers/views.py tests/test_roles.py
git -c user.name="Alex Krovina" -c user.email="alex.krovina@tradition.ch" commit -m "feat: tracker roles flow down the team tree in one recursive query

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Permissions, the `can()` helper and gated links

**Files:**
- Create: `tracker/auth/permissions.py`
- Modify: `tracker/auth/__init__.py` (export), `tracker/app.py` (context processor), `tracker/templates/base.html`, `tracker/templates/home.html`
- Modify: `tracker/trackers/views.py` (`new`), `tracker/importer/views.py` (all three routes), `tracker/admin/__init__.py` (`smtp`)
- Test: `tests/test_permissions.py` (new), `tests/test_templates.py`

**Interfaces:**
- Consumes: Task 1 models, `team_factory`, `add_member`, `give_set`.
- Produces (in `tracker/auth/permissions.py`, re-exported from `tracker.auth`):
  - `PERMISSIONS: dict[str, tuple[str, str]]`, in this order, name to (label, description):
    `manage_users` ("Manage users", "Approve pending Entra users; create local users; reset local users' passwords; disable and re-enable users."), `manage_teams` ("Manage teams", "Create, rename, move and delete teams; add and remove members and change their roles; put trackers in teams and move them between teams; manage direct per-tracker roles (the tracker Access screen)."), `create_trackers` ("Create trackers", "Create trackers, in any team or in none."), `import_workbooks` ("Import workbooks", "Use the Import workbook screen and the import confirmation, which creates a tracker."), `manage_email_settings` ("Manage email settings", "Change the application's email (SMTP) settings."), `view_all_trackers` ("View all trackers", "Viewer on every tracker."), `view_activity` ("View activity", "Read the Activity screen.").
  - `user_permissions(session, user: User) -> frozenset[str]`: every name for an administrator; nothing for a user who is not active; otherwise the known names in sets held by the user directly or by a team the user is a direct member of (any role). Unknown names in the database are ignored.
  - `has_permission(user: User | None, permission: str) -> bool`: for the current request, cached on `g` by user id; `False` for `None`; `ValueError` for a name not in `PERMISSIONS`.
  - `permission_required(permission: str)`: decorator; anonymous users go to the sign-in page (as `admin_required`), users without the permission get `abort(403, description="You do not have permission to open this page.")`.
  - Template global `can(permission: str) -> bool`, from a context processor in `create_app`, bound to `current_user()`.
- Route changes: `trackers.new` uses `permission_required("create_trackers")`; `importer.upload`, `importer.preview`, `importer.confirm` use `permission_required("import_workbooks")`; `admin.smtp` uses `permission_required("manage_email_settings")`. The Users routes stay administrator-only until Task 9.

- [ ] **Step 1: Write the failing database tests in `tests/test_permissions.py`**

```python
def test_admin_holds_every_permission(db, user_factory):
    assert user_permissions(db, user_factory(is_admin=True)) == frozenset(PERMISSIONS)

def test_permission_held_directly(db, user_factory, give_set): ...          # {"view_activity"}
def test_permission_held_through_a_direct_team_membership(...)            # member with role "viewer" still holds it
def test_permission_not_held_through_teams_below_or_above(...)            # set held by B; members of A and C hold nothing
def test_unknown_permission_names_in_the_database_are_ignored(...)        # give_set(["approve", "view_activity"])
def test_inactive_user_holds_nothing(...)                                 # pending and disabled holders -> frozenset()
def test_has_permission_rejects_an_unknown_name(app, ...):  pytest.raises(ValueError)

@pytest.mark.parametrize("method,url", [("get", "/trackers/new"), ("post", "/trackers/new"), ("get", "/import"),
                                        ("post", "/import/confirm"), ("get", "/admin/smtp"), ("post", "/admin/smtp")])
def test_screens_refused_without_the_permission(client, logged_in_user, method, url):
    assert (client.get(url) if method == "get" else post(client, url)).status_code == 403

def test_create_trackers_holder_creates_a_tracker(client, logged_in_user, give_set, db): ...   # 302, tracker exists
def test_import_workbooks_holder_opens_import(client, logged_in_user, give_set): ...          # GET /import -> 200
def test_email_settings_holder_saves_settings(client, logged_in_user, give_set, db): ...     # smtp_settings_updated logged
def test_new_tracker_button_follows_create_trackers(client, logged_in_user, give_set): ...   # href="/trackers/new" absent, then present
```

- [ ] **Step 2: Write the failing sidebar tests (no database) in `tests/test_templates.py`**

Add a helper `render_sidebar(app, is_admin: bool, held: set[str]) -> str` that renders `base.html` inside `app.test_request_context("/")` with `current_user=SimpleNamespace(id=1, full_name="Pat", is_admin=is_admin)` and `can=lambda p: is_admin or p in held` (explicit render arguments override the context processor).

```python
LINKS = {"manage_users": None, "import_workbooks": 'href="/import"', "manage_email_settings": 'href="/admin/smtp"'}

@pytest.mark.parametrize("held", [set(), {"import_workbooks"}, {"manage_email_settings"},
                                  {"import_workbooks", "manage_email_settings"}, {"view_all_trackers"}])
def test_sidebar_shows_only_the_links_held(app, held):
    html = render_sidebar(app, is_admin=False, held=held)
    for permission, link in LINKS.items():
        if link:
            assert (link in html) == (permission in held)
    assert 'href="/admin/users"' not in html            # Users stays administrator-only until Task 9
    assert ("Administration" in html) == bool(held & {"import_workbooks", "manage_email_settings"})

def test_sidebar_shows_every_link_to_administrators(app): ...
```

- [ ] **Step 3: Run the tests to verify they fail**

Run (sandbox disabled): `/tmp/claude-1000/-home-alexkrovina/cf13b4e4-1890-473a-b9dc-06d0fca97d35/scratchpad/tools/acc-test.sh tests/test_permissions.py tests/test_templates.py -q`
Expected: FAIL (`tracker.auth.permissions` missing).

- [ ] **Step 4: Implement `tracker/auth/permissions.py`, the context processor and the gating**

In `base.html`, set one boolean per link (`can('import_workbooks')`, `can('manage_email_settings')`, `current_user.is_admin` for Users) and show the `Administration` heading when any is true. In `home.html`, show "New tracker" when `can('create_trackers')`; "Show archived" keeps its current condition.

- [ ] **Step 5: Run the tests and the whole suite**

Run (sandbox disabled): `/tmp/claude-1000/-home-alexkrovina/cf13b4e4-1890-473a-b9dc-06d0fca97d35/scratchpad/tools/acc-test.sh tests/test_permissions.py tests/test_templates.py tests/test_trackers.py tests/test_auth.py -q`, then `/tmp/claude-1000/-home-alexkrovina/cf13b4e4-1890-473a-b9dc-06d0fca97d35/scratchpad/tools/acc-test.sh -q -x`
Expected: PASS.

- [ ] **Step 6: Lint and commit**

Run the lint command from Global Constraints.

```bash
git add tracker/auth/permissions.py tracker/auth/__init__.py tracker/app.py tracker/templates/base.html tracker/templates/home.html tracker/trackers/views.py tracker/importer/views.py tracker/admin/__init__.py tests/test_permissions.py tests/test_templates.py
git -c user.name="Alex Krovina" -c user.email="alex.krovina@tradition.ch" commit -m "feat: permission sets grant create, import and email settings; sidebar shows only usable links

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Team tree helpers and the self-promotion guard

**Files:**
- Create: `tracker/teams/__init__.py` (docstring only in this task), `tracker/teams/tree.py`
- Create: `tracker/auth/guards.py`
- Test: `tests/test_team_tree.py` (new; pure functions need no database), `tests/test_guards.py` (new)

**Interfaces:**
- Consumes: `tracker_roles`, `ROLE_ORDER` (Task 2).
- Produces (in `tracker/teams/tree.py`):
  - `TeamRow(NamedTuple)`: `id: int`, `parent_id: int | None`, `name: str`.
  - `children_map(rows: list[TeamRow]) -> dict[int | None, list[TeamRow]]`: siblings sorted by `name.casefold()`.
  - `order_tree(rows: list[TeamRow]) -> list[tuple[TeamRow, int]]`: pre-order with depth (top level is 0).
  - `descendants(rows: list[TeamRow], team_id: int) -> set[int]`: the team and every team below it.
  - `paths(rows: list[TeamRow]) -> dict[int, str]`: team id to the path label from the top, joined with `" › "` (for example `"Infrastructure › Windows"`).
  - `load_team_rows(session, lock: bool = False) -> list[TeamRow]`: every team; with `lock=True` the rows are read `FOR UPDATE`.
  - `team_choices(session) -> list[tuple[int, str]]`: (id, path label) in tree order, for selects.
  - `parse_team_id(session, value: str | None) -> tuple[Team | None, str | None]`: empty means no team `(None, None)`; anything not the id of an existing team gives `(None, "Choose a team from the list.")`.
- Produces (in `tracker/auth/guards.py`):
  - `SELF_PROMOTION_MESSAGE = "You cannot make a change that gives you more access to a tracker. Ask an administrator."`
  - `snapshot_access(session, actor: User) -> dict[int, str] | None`: `tracker_roles(session, actor)`, or `None` for an administrator (exempt).
  - `raises_own_access(session, actor: User, before: dict[int, str] | None) -> bool`: flushes the session, recomputes `tracker_roles` inside the same transaction and returns `True` when any tracker appears or any role rises; always `False` when `before is None`.
  - Calling pattern for every `manage_teams` change (Tasks 5, 6, 7 and 9): `before = snapshot_access(db, actor)`; apply the change; `if raises_own_access(db, actor, before): db.rollback(); flash(SELF_PROMOTION_MESSAGE, "danger"); return redirect(...)`; otherwise `record(...)` and `db.commit()`.

- [ ] **Step 1: Write the failing tests**

`tests/test_team_tree.py` (no database):

```python
ROWS = [TeamRow(1, None, "Infrastructure"), TeamRow(2, 1, "Windows"), TeamRow(3, 1, "network"),
        TeamRow(4, 2, "Desktops"), TeamRow(5, None, "Applications")]

def test_order_tree_is_preorder_with_depth_and_sorted_ignoring_case():
    assert [(r.id, d) for r, d in order_tree(ROWS)] == [(5, 0), (1, 0), (3, 1), (2, 1), (4, 2)]

def test_descendants_include_the_team_itself():
    assert descendants(ROWS, 1) == {1, 2, 3, 4} and descendants(ROWS, 4) == {4}

def test_paths_join_names_from_the_top():
    assert paths(ROWS)[4] == "Infrastructure › Windows › Desktops" and paths(ROWS)[5] == "Applications"
```

`tests/test_guards.py` (database):

```python
def test_joining_a_team_with_trackers_raises_own_access(db, ...)        # True
def test_raising_own_direct_role_raises_own_access(db, ...)             # viewer -> owner: True
def test_lowering_own_role_does_not(db, ...)                            # owner -> viewer: False
def test_moving_a_tracker_into_own_team_raises_own_access(db, ...)      # True
def test_moving_another_team_under_own_team_raises_own_access(db, ...)  # X (with a tracker) moved under W: True
def test_moving_own_team_without_new_trackers_does_not(db, ...)         # W moved to top level: False
def test_change_for_someone_else_does_not(db, ...)                      # False
def test_administrator_is_exempt(db, ...)                               # snapshot_access(...) is None; False
```

- [ ] **Step 2: Run them to verify they fail**

Run (sandbox disabled): `/tmp/claude-1000/-home-alexkrovina/cf13b4e4-1890-473a-b9dc-06d0fca97d35/scratchpad/tools/acc-test.sh tests/test_team_tree.py tests/test_guards.py -q`
Expected: FAIL (modules missing).

- [ ] **Step 3: Implement `tracker/teams/tree.py` and `tracker/auth/guards.py`**

As in the Interfaces block.

- [ ] **Step 4: Run them to verify they pass**

Run (sandbox disabled): `/tmp/claude-1000/-home-alexkrovina/cf13b4e4-1890-473a-b9dc-06d0fca97d35/scratchpad/tools/acc-test.sh tests/test_team_tree.py tests/test_guards.py -q`
Expected: PASS.

- [ ] **Step 5: Lint and commit**

Run the lint command from Global Constraints.

```bash
git add tracker/teams/__init__.py tracker/teams/tree.py tracker/auth/guards.py tests/test_team_tree.py tests/test_guards.py
git -c user.name="Alex Krovina" -c user.email="alex.krovina@tradition.ch" commit -m "feat: team tree helpers and a guard against raising one's own tracker access

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Teams screens

**Files:**
- Modify: `tracker/teams/__init__.py` (blueprint `teams`), Create: `tracker/teams/views.py`
- Create: `tracker/templates/teams/index.html`, `tracker/templates/teams/team.html`
- Modify: `tracker/app.py` (register), `tracker/templates/base.html` (Teams link), `tracker/templates/macros.html` (icon `teams`), `tracker/static/tracker.css` (tree list), `tracker/static/tracker.js` (confirmation names the choice)
- Test: `tests/test_teams.py` (new), `tests/test_teams_browser.py` (new), `tests/test_templates.py`

**Interfaces:**
- Consumes: `permission_required`, `can` (Task 3); `TeamRow`, `children_map`, `descendants`, `paths`, `load_team_rows`, `team_choices` (Task 4); `snapshot_access`, `raises_own_access`, `SELF_PROMOTION_MESSAGE` (Task 4); `record`, `change` (Task 1).
- Produces (all `permission_required("manage_teams")`, prefix `/admin/teams`):
  - `teams.index` `GET /admin/teams`: the tree as nested `<ul class="team-tree">` (a recursive macro over `children_map`, so any depth indents without inline styles), each team with member and tracker counts and a link; the create form (name, description, parent).
  - `teams.create` `POST /admin/teams`: logs `team_created` with `{"name": …, "parent": <parent path or None>}`.
  - `teams.view` `GET /admin/teams/<int:team_id>`: rename form, move form (parent select offering only teams outside `descendants(...)`, plus "Top level"), delete (shown only when allowed), members table (role select, remove), add-member form (active users who are not members), and the team's trackers by name (archived marked).
  - `teams.rename` `POST /admin/teams/<int:team_id>/rename` (name, description): logs `team_renamed` with `change({changed fields before}, {changed fields after})`; no entry when nothing changed.
  - `teams.move` `POST /admin/teams/<int:team_id>/move` (`parent_id`, empty for top level): locks the tree (`load_team_rows(db, lock=True)`), refuses a parent in `descendants(rows, team.id)` with `CYCLE_MESSAGE = "A team cannot be moved under itself or under a team below it."`, applies the self-promotion guard, logs `team_moved` with `change(<old parent path or None>, <new parent path or None>)`. A non-numeric `parent_id` gives 400.
  - `teams.delete` `POST /admin/teams/<int:team_id>/delete`: refused with `"This team has teams below it. Move or delete them first."` or `"This team has trackers, including archived ones. Move them to another team first."`; otherwise logs `team_member_removed` for each membership (with `target_user_id`), `permission_set_holder_removed` for each holding (`{"set": name, "team": team name}`), then `team_deleted` (`{"name": …, "parent": …}`), then deletes.
  - `teams.add_member` `POST /admin/teams/<int:team_id>/members` (`user_id`, `role`): active users only (400 otherwise); an existing member gives `"That person is already a member of this team."`; logs `team_member_added` with `{"team": name, "role": role}` and `target_user_id`. A non-administrator adding anyone to a team that holds a permission set is refused with `TEAM_WITH_SETS_MESSAGE` (adding a member chooses who holds the set, which section 6.2 keeps for administrators). Add to `tracker/auth/guards.py`: `TEAM_WITH_SETS_MESSAGE = "This team holds permission sets, so only an administrator can add people to it."` and `team_holds_sets(session, team_id: int) -> bool`.
  - `teams.update_member` `POST /admin/teams/<int:team_id>/members/<int:user_id>` (`role`, or `action=remove`): logs `team_member_role_changed` with `{"team": name, "before": old, "after": new}` or `team_member_removed` with `{"team": name, "role": old}`, each with `target_user_id`. A user who is not a member gives 404.
  - Self-promotion guard on move, add and role change; `team_name_error(session, name: str, exclude_id: int | None = None) -> str | None` in `tracker/teams/views.py` gives `"Enter a team name."`, `"A team name can be at most 100 characters."` or `"A team with that name already exists."` (compares `func.lower(Team.name) == name.lower()` after trimming; an `IntegrityError` on commit is turned into the same message).
  - `tracker.js`: inside a `form[data-inline-confirm]`, when `[data-ask]` opens the box, every `[data-confirm-choice]` element gets the text of the selected option of the form's `select[data-confirm-source]`. The team move confirmation reads "Move {team} from {old parent or Top level} to {choice}? People in the teams above it will gain or lose access to its trackers." and the `data-confirm` fallback reads "Move {team} to the chosen place? Access to its trackers will change."
  - Sidebar: Teams link (`href="/admin/teams"`) when `can('manage_teams')`.

- [ ] **Step 1: Write the failing tests in `tests/test_teams.py`**

```python
def test_teams_screens_refused_without_manage_teams(client, logged_in_user, team_factory):
    team = team_factory()
    assert client.get("/admin/teams").status_code == 403
    assert client.get(f"/admin/teams/{team.id}").status_code == 403
    assert post(client, "/admin/teams", {"name": "X"}).status_code == 403

def test_tree_is_nested_with_member_and_tracker_counts(client, logged_in_admin, ...):  # nested <ul>, "2 members", "1 tracker"
def test_create_team_logs_team_created(client, logged_in_admin, db): ...   # detail {"name": "Windows", "parent": "Infrastructure"}
def test_team_name_unique_ignoring_case_and_spaces(client, logged_in_admin, team_factory, db):
    team_factory(name="Windows")
    page = post(client, "/admin/teams", {"name": " windows "})
    assert page.status_code == 400 and "A team with that name already exists." in page.get_data(as_text=True)
    assert db.scalar(select(func.count()).select_from(Team)) == 1
def test_team_name_required_and_at_most_100_characters(...)   # "" and "x" * 101 -> 400, nothing stored
def test_rename_logs_before_and_after(...)
def test_move_form_offers_only_valid_parents(...)            # options exclude the team and every team below it
def test_move_under_itself_or_below_refused_on_the_server(...)   # CYCLE_MESSAGE shown; parent unchanged; no team_moved
def test_move_logs_parent_before_and_after(...)              # change("Infrastructure", None)
def test_move_with_a_malformed_parent_is_400(...)            # parent_id="abc"
def test_delete_refused_with_a_child_team_a_tracker_or_an_archived_tracker(...)
def test_delete_removes_and_logs_memberships_and_holdings(...):
    # actions in order: team_member_removed x2 (each with target_user_id), permission_set_holder_removed, team_deleted
def test_add_member_logs_with_the_affected_user(...)
def test_add_member_refuses_users_who_are_not_active(...)    # disabled user id -> 400, no membership
def test_change_role_and_remove_member_log_before_and_after(...)
def test_missing_team_or_member_is_404(...)                  # /admin/teams/9999; update_member for a non-member
def test_holder_cannot_add_self_to_a_team_with_trackers(...) # SELF_PROMOTION_MESSAGE; no membership; no entry
def test_holder_cannot_raise_own_team_role_but_can_lower_it(...)
def test_holder_cannot_move_a_team_under_their_own_team(...)
def test_non_admin_cannot_add_members_to_a_team_holding_a_set(...)   # TEAM_WITH_SETS_MESSAGE; admin can
def test_team_page_names_trackers_the_holder_cannot_open(...)        # name shown; GET /trackers/<id> still 404
```

Extend the sidebar test in `tests/test_templates.py` so `manage_teams` maps to `'href="/admin/teams"'`.

- [ ] **Step 2: Write the failing browser test in `tests/test_teams_browser.py`**

`pytestmark = pytest.mark.browser`. `test_move_confirmation_names_the_old_and_new_parent`: an administrator opens a team under "Infrastructure", chooses "Applications" in the move select, clicks the move button; the confirm box is visible and contains "from Infrastructure to Applications"; clicking the confirm button moves the team (the page then shows the new place).

- [ ] **Step 3: Run the tests to verify they fail**

Run (sandbox disabled): `/tmp/claude-1000/-home-alexkrovina/cf13b4e4-1890-473a-b9dc-06d0fca97d35/scratchpad/tools/acc-test.sh tests/test_teams.py tests/test_teams_browser.py tests/test_templates.py -q`
Expected: FAIL (404 for `/admin/teams`).

- [ ] **Step 4: Implement the blueprint, templates, styles and script**

As in the Interfaces block. Use `.settings-section` cards (Teams page: "Teams" and "New team"; team page: "Details", "Place in the tree", "Members", "Trackers", and a `.settings-section-danger` "Delete" card), the `field` macro and `.section-table` for members.

- [ ] **Step 5: Run the tests and the whole suite**

Run (sandbox disabled): `/tmp/claude-1000/-home-alexkrovina/cf13b4e4-1890-473a-b9dc-06d0fca97d35/scratchpad/tools/acc-test.sh tests/test_teams.py tests/test_teams_browser.py tests/test_templates.py -q`, then `/tmp/claude-1000/-home-alexkrovina/cf13b4e4-1890-473a-b9dc-06d0fca97d35/scratchpad/tools/acc-test.sh -q -x`
Expected: PASS.

- [ ] **Step 6: Lint and commit**

Run the lint command from Global Constraints.

```bash
git add tracker/teams tracker/templates/teams tracker/app.py tracker/templates/base.html tracker/templates/macros.html tracker/static/tracker.css tracker/static/tracker.js tests/test_teams.py tests/test_teams_browser.py tests/test_templates.py
git -c user.name="Alex Krovina" -c user.email="alex.krovina@tradition.ch" commit -m "feat: Teams screens with nested teams, members, confirmed moves and delete guards

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: A tracker's team, and the creator becomes owner

**Files:**
- Modify: `tracker/trackers/views.py` (`new`, new route `set_team`, `home` card team name, `give_creator_ownership`)
- Create: `tracker/templates/trackers/_team_form.html`
- Modify: `tracker/templates/trackers/_fields.html` (Team select on the new tracker form only), `tracker/templates/trackers/settings.html` (Team section and subnav link), `tracker/templates/home.html`
- Modify: `tracker/importer/views.py`, `tracker/importer/workbook.py`, `tracker/templates/importer/confirm.html`
- Test: `tests/test_tracker_teams.py` (new), `tests/test_trackers.py` (one existing test changes)

**Interfaces:**
- Consumes: `team_choices`, `parse_team_id`, `paths`, `load_team_rows` (Task 4); guard functions (Task 4); `has_permission`, `can` (Task 3); `record`, `change` (Task 1).
- Produces:
  - `give_creator_ownership(session, tracker: Tracker, actor: User) -> None` in `tracker/trackers/views.py`: for a non-administrator, adds `TrackerRole(owner)` and logs `role_set` with `change(None, "owner")` and `target_user_id=actor.id`; for an administrator, does nothing (an administrator needs no role and gets none).
  - `create_tracker_from_preview(session, preview, name, unit_label, group_label, user_id, accept_mismatch, team_id: int | None = None, owner_role: bool = True) -> Tracker`: sets `team_id`; adds the owner role (and its `role_set` entry) only when `owner_role`. The web import passes `owner_role=not current_user().is_admin`; the `import-workbook` command keeps the default.
  - `trackers.set_team` `POST /trackers/<int:tracker_id>/team` (`team_id`, empty for no team; `next` = `settings` or `access`): `permission_required("manage_teams")`; 404 for a missing tracker; allowed on archived trackers; no entry when the team is unchanged; self-promotion guard; logs `tracker_team_changed` with `change(<old team path or None>, <new team path or None>)`.
  - `trackers/_team_form.html`: expects `tracker`, `team_choices`, `team_path` (current path or `None`) and `next`; select `name="team_id"` with `data-confirm-source`; in-page confirmation "Move {tracker} from {old team or No team} to {choice}? People's access to this tracker will change."; fallback `data-confirm="Move {tracker} to the chosen team? People's access to this tracker will change."`.
  - Home cards carry `card["team"]` (the team's name or `None`), shown on the card.
  - `tracker_created` detail gains `"team"` (path or `None`).

- [ ] **Step 1: Write the failing tests in `tests/test_tracker_teams.py` and change the existing one**

In `tests/test_trackers.py`, rename `test_admin_creates_tracker_and_becomes_owner` to `test_admin_creates_tracker_without_a_role` and assert `db.get(TrackerRole, (logged_in_admin.id, tracker.id)) is None`.

```python
def test_creator_without_admin_becomes_owner_and_it_is_logged(client, logged_in_user, give_set, db):
    give_set(["create_trackers"], user=logged_in_user)
    post(client, "/trackers/new", SETTINGS)
    tracker = db.scalars(select(Tracker)).one()
    assert db.get(TrackerRole, (logged_in_user.id, tracker.id)).role == "owner"
    entry = db.scalars(select(AuditLog).where(AuditLog.action == "role_set")).one()
    assert entry.detail == {"before": None, "after": "owner"} and entry.target_user_id == logged_in_user.id

def test_new_tracker_in_a_team_or_none(...)                 # team_id set; empty -> None
def test_new_tracker_with_an_unknown_team_is_refused(...)   # team_id="9999" and "abc" -> 400 "Choose a team from the list."
def test_import_confirmation_sets_team_and_owner(...)       # import_workbooks holder: team set, owner role; admin: no role
def test_set_team_requires_manage_teams(...)                # owner without the permission -> 403
def test_set_team_logs_before_and_after_and_works_when_archived(...)  # change("Infrastructure › Windows", "Network")
def test_set_team_to_the_same_team_writes_nothing(...)
def test_holder_cannot_move_a_tracker_into_their_own_team(...)   # SELF_PROMOTION_MESSAGE; team unchanged
def test_settings_team_form_only_for_team_managers(...)     # owner sees the team name read-only; holder or admin sees the form
def test_home_card_shows_the_team_name(...)
```

- [ ] **Step 2: Run them to verify they fail**

Run (sandbox disabled): `/tmp/claude-1000/-home-alexkrovina/cf13b4e4-1890-473a-b9dc-06d0fca97d35/scratchpad/tools/acc-test.sh tests/test_tracker_teams.py tests/test_trackers.py -q`
Expected: FAIL.

- [ ] **Step 3: Implement**

As in the Interfaces block. The Settings "Team" section sits outside the main settings form (like the Archive section), so saving settings never changes the team.

- [ ] **Step 4: Run the tests and the whole suite**

Run (sandbox disabled): `/tmp/claude-1000/-home-alexkrovina/cf13b4e4-1890-473a-b9dc-06d0fca97d35/scratchpad/tools/acc-test.sh tests/test_tracker_teams.py tests/test_trackers.py tests/importer -q`, then `/tmp/claude-1000/-home-alexkrovina/cf13b4e4-1890-473a-b9dc-06d0fca97d35/scratchpad/tools/acc-test.sh -q -x`
Expected: PASS.

- [ ] **Step 5: Lint and commit**

Run the lint command from Global Constraints.

```bash
git add tracker/trackers/views.py tracker/templates/trackers tracker/templates/home.html tracker/importer tracker/templates/importer/confirm.html tests/test_tracker_teams.py tests/test_trackers.py
git -c user.name="Alex Krovina" -c user.email="alex.krovina@tradition.ch" commit -m "feat: trackers belong to a team, chosen at creation and moved with confirmation

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: Tracker Access screen with access through teams

**Files:**
- Modify: `tracker/trackers/views.py` (`roles`), `tracker/auth/roles.py` (`team_access`)
- Modify: `tracker/templates/trackers/roles.html`, `tracker/templates/trackers/_nav.html`
- Test: `tests/test_tracker_access.py` (new), `tests/test_templates.py` (nav)

**Interfaces:**
- Consumes: `permission_required`, `can` (Task 3); `paths`, `load_team_rows`, `team_choices` (Task 4); guard functions (Task 4); `_team_form.html` (Task 6).
- Produces:
  - `TeamAccess(NamedTuple)`: `user: User`, `path: str`, `role: str`; `team_access(session, tracker: Tracker) -> list[TeamAccess]` in `tracker/auth/roles.py`: one row per membership of an active user in the tracker's team or any team above it, the path being the membership team's path; sorted by user name then path; `[]` for a tracker with no team.
  - `trackers.roles` (`GET/POST /trackers/<int:tracker_id>/roles`): `permission_required("manage_teams")` first (403), then 404 for a missing tracker; sets `g.tracker` and `g.role = user_role(...)` (may be `None`). POST keeps today's rules (archived refused with "This tracker is archived.", administrators cannot be given roles, 400 for a bad choice), adds the self-promotion guard, and logs `role_set`/`role_removed` with `change(previous, new)` and `target_user_id`.
  - The page adds a read-only "Access through teams" section (person, team path, role) and the Team section (`_team_form.html` with `next="access"`).
  - `_nav.html`: tracker tabs need `g.role` (a `manage_teams` holder without a role sees only the Access tab); the Access tab shows when `can('manage_teams')`.

- [ ] **Step 1: Write the failing tests**

```python
def test_access_screen_opens_for_a_holder_without_a_role(client, logged_in_user, give_set, tracker_factory):
    give_set(["manage_teams"], user=logged_in_user)
    t = tracker_factory(name="Patching")
    page = client.get(f"/trackers/{t.id}/roles")
    assert page.status_code == 200 and "Patching" in page.get_data(as_text=True)
    assert f'href="/trackers/{t.id}/report"' not in page.get_data(as_text=True)
    assert client.get(f"/trackers/{t.id}").status_code == 404

def test_access_screen_for_a_missing_tracker_is_404_for_a_holder(...)
def test_role_set_logs_before_after_and_the_affected_user(...)   # detail {"before": None, "after": "viewer"}; then {"before": "viewer", "after": None} for role_removed
def test_holder_cannot_give_themselves_a_direct_role(...)        # SELF_PROMOTION_MESSAGE; no TrackerRole
def test_access_through_teams_lists_path_and_role(...)           # "Infrastructure › Windows" editor and "Infrastructure" owner rows
def test_access_through_teams_leaves_out_inactive_users(...)
def test_archived_tracker_refuses_roles_but_offers_the_team_form(...)
```

Keep `test_roles_page_admin_only` (an owner without `manage_teams` still gets 403). In `tests/test_templates.py`, render `_nav.html` with `g.role = None` and `can` returning `True` for `manage_teams`: only the Access tab is present.

- [ ] **Step 2: Run them to verify they fail**

Run (sandbox disabled): `/tmp/claude-1000/-home-alexkrovina/cf13b4e4-1890-473a-b9dc-06d0fca97d35/scratchpad/tools/acc-test.sh tests/test_tracker_access.py tests/test_trackers.py tests/test_templates.py -q`
Expected: FAIL.

- [ ] **Step 3: Implement**

As in the Interfaces block.

- [ ] **Step 4: Run the tests and the whole suite**

Run (sandbox disabled): `/tmp/claude-1000/-home-alexkrovina/cf13b4e4-1890-473a-b9dc-06d0fca97d35/scratchpad/tools/acc-test.sh tests/test_tracker_access.py tests/test_trackers.py tests/test_templates.py -q`, then `/tmp/claude-1000/-home-alexkrovina/cf13b4e4-1890-473a-b9dc-06d0fca97d35/scratchpad/tools/acc-test.sh -q -x`
Expected: PASS.

- [ ] **Step 5: Lint and commit**

Run the lint command from Global Constraints.

```bash
git add tracker/trackers/views.py tracker/auth/roles.py tracker/templates/trackers/roles.html tracker/templates/trackers/_nav.html tests/test_tracker_access.py tests/test_templates.py
git -c user.name="Alex Krovina" -c user.email="alex.krovina@tradition.ch" commit -m "feat: tracker Access screen for team managers, with access through teams

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: Permission sets screen

**Files:**
- Create: `tracker/permsets/__init__.py` (blueprint `permsets`), `tracker/permsets/views.py`
- Create: `tracker/templates/permsets/index.html`, `tracker/templates/permsets/set.html`
- Modify: `tracker/app.py` (register), `tracker/templates/base.html` (link for administrators), `tracker/templates/macros.html` (icon `key`), `tracker/static/tracker.css` (grid)
- Test: `tests/test_permission_sets.py` (new), `tests/test_templates.py`

**Interfaces:**
- Consumes: `PERMISSIONS`, `user_permissions` (Task 3); `admin_required`; `paths`, `load_team_rows` (Task 4); `record`, `change` (Task 1).
- Produces (all `admin_required`, prefix `/admin/permission-sets`):
  - `permsets.index` `GET /admin/permission-sets`: the grid (`.section-table`, permissions as rows with their labels and descriptions, sets as columns, one checkbox per cell named `set-<set id>` with the permission name as value, plus a hidden `sets` field per column) and the create form.
  - `permsets.save_grid` `POST /admin/permission-sets/grid`: for each set id listed in `sets` that still exists, replaces its permissions with the checked known names; logs `permission_set_permissions_changed` with `change(sorted before, sorted after)` per changed set only. Unknown names and unknown set ids are ignored.
  - `permsets.create` `POST /admin/permission-sets` (name, description): logs `permission_set_created` (`{"name": …}`).
  - `permsets.view` `GET /admin/permission-sets/<int:set_id>`: rename, delete, holders (teams with their paths, users with name and email), add-holder form.
  - `permsets.rename` `POST /admin/permission-sets/<int:set_id>/rename`: logs `permission_set_renamed` with `change(...)` of the changed fields.
  - `permsets.delete` `POST /admin/permission-sets/<int:set_id>/delete`: logs `permission_set_holder_removed` for each holder, then `permission_set_deleted` (`{"name": …, "permissions": [...]}`), then deletes.
  - `permsets.add_holder` `POST /admin/permission-sets/<int:set_id>/holders` (`holder` = `team:<id>` or `user:<id>`; active users only): `"That team or person already holds this set."` for a duplicate; logs `permission_set_holder_added` with `{"set": name, "team": path}` or `{"set": name}` and `target_user_id`.
  - `permsets.remove_holder` `POST /admin/permission-sets/<int:set_id>/holders/<int:holder_id>/delete`: logs `permission_set_holder_removed` likewise; 404 when the holder belongs to another set.
  - `set_name_error(session, name: str, exclude_id: int | None = None) -> str | None`: `"Enter a set name."`, `"A set name can be at most 100 characters."`, `"A permission set with that name already exists."`.
  - Sidebar: "Permission sets" (`href="/admin/permission-sets"`) for administrators only.

- [ ] **Step 1: Write the failing tests in `tests/test_permission_sets.py`**

```python
ENDPOINTS = [("get", "/admin/permission-sets"), ("post", "/admin/permission-sets"), ("post", "/admin/permission-sets/grid"),
             ("get", "/admin/permission-sets/{id}"), ("post", "/admin/permission-sets/{id}/rename"),
             ("post", "/admin/permission-sets/{id}/delete"), ("post", "/admin/permission-sets/{id}/holders")]

@pytest.mark.parametrize("method,url", ENDPOINTS)
def test_non_administrators_are_refused_even_with_every_permission(client, logged_in_user, give_set, method, url):
    s = give_set(list(PERMISSIONS), user=logged_in_user)
    target = url.format(id=s.id)
    assert (client.get(target) if method == "get" else post(client, target)).status_code == 403

def test_create_set_logs_and_names_are_unique_ignoring_case_and_spaces(...)   # " pmo " after "PMO" -> 400, message
def test_set_name_at_most_100_characters(...)
def test_grid_saves_every_set_in_one_action_and_logs_each_changed_set(...):
    # two sets; change one -> one entry with {"before": ["view_activity"], "after": ["create_trackers", "view_activity"]}
def test_grid_ignores_unknown_permissions_and_sets(...)        # "approve" and set id 9999 -> nothing stored, 302
def test_rename_logs_before_and_after(...)
def test_delete_logs_each_holder_then_the_set(...)
def test_add_and_remove_team_and_user_holders_are_logged(...)   # user holder entries carry target_user_id
def test_duplicate_holder_refused(...)
def test_removing_a_holder_takes_the_permission_away(...)       # user_permissions(...) before and after
```

Extend the sidebar test in `tests/test_templates.py`: `href="/admin/permission-sets"` only for administrators.

- [ ] **Step 2: Run them to verify they fail**

Run (sandbox disabled): `/tmp/claude-1000/-home-alexkrovina/cf13b4e4-1890-473a-b9dc-06d0fca97d35/scratchpad/tools/acc-test.sh tests/test_permission_sets.py tests/test_templates.py -q`
Expected: FAIL.

- [ ] **Step 3: Implement**

As in the Interfaces block.

- [ ] **Step 4: Run the tests and the whole suite**

Run (sandbox disabled): `/tmp/claude-1000/-home-alexkrovina/cf13b4e4-1890-473a-b9dc-06d0fca97d35/scratchpad/tools/acc-test.sh tests/test_permission_sets.py tests/test_templates.py -q`, then `/tmp/claude-1000/-home-alexkrovina/cf13b4e4-1890-473a-b9dc-06d0fca97d35/scratchpad/tools/acc-test.sh -q -x`
Expected: PASS.

- [ ] **Step 5: Lint and commit**

Run the lint command from Global Constraints.

```bash
git add tracker/permsets tracker/templates/permsets tracker/app.py tracker/templates/base.html tracker/templates/macros.html tracker/static/tracker.css tests/test_permission_sets.py tests/test_templates.py
git -c user.name="Alex Krovina" -c user.email="alex.krovina@tradition.ch" commit -m "feat: Permission sets screen with a permissions grid and holders

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9: Users screen for `manage_users`, with guards and effective access

**Files:**
- Modify: `tracker/admin/__init__.py` (keeps `bp` and imports the two modules below); Create: `tracker/admin/users.py` (the user views, moved unchanged first), `tracker/admin/smtp.py` (the SMTP view, moved unchanged)
- Create: `tracker/auth/accounts.py`
- Modify: `tracker/auth/roles.py` (`tracker_access_routes`), `tracker/auth/permissions.py` (`permission_sources`)
- Modify: `tracker/templates/admin/users.html`, `tracker/templates/base.html`; Create: `tracker/templates/admin/user_password.html`, `tracker/templates/admin/user_access.html`
- Modify: `tracker/app.py` (`create-admin` and `reset-password` set `target_user_id`)
- Test: `tests/test_users_admin.py` (new), `tests/test_auth.py`, `tests/test_cli.py`, `tests/test_templates.py`

**Interfaces:**
- Consumes: `permission_required`, `has_permission`, `can`, `PERMISSIONS` (Task 3); `tracker_roles` (Task 2); `team_choices`, `parse_team_id`, `paths`, `load_team_rows` (Task 4); guard functions, `TEAM_WITH_SETS_MESSAGE` and `team_holds_sets` from `tracker/auth/guards.py` (Tasks 4 and 5); `validate_new_password`, `hash_password`.
- Produces (in `tracker/auth/accounts.py`):
  - `is_elevated(session, user: User) -> bool`: the administrator flag, or any permission set held directly or through any team membership, whatever the account's status.
  - `OWN_ACCOUNT_MESSAGE = "You cannot change your own account here."`, `ELEVATED_MESSAGE = "Only an administrator can change an administrator or a user with elevated permissions."`, `LAST_ADMIN_MESSAGE = "The application must keep at least one active administrator."`
  - `account_refusal(session, actor: User, target: User) -> str | None`: for a non-administrator, `OWN_ACCOUNT_MESSAGE` when `target.id == actor.id`, else `ELEVATED_MESSAGE` when `is_elevated(target)`; for an administrator, `None` (the existing self rules stay in the views).
  - `last_admin_refusal(session, target: User) -> str | None`: when `target` is an active administrator, reads the active administrators `FOR UPDATE` and returns `LAST_ADMIN_MESSAGE` when `target` is the only one.
- Produces (in `tracker/auth/roles.py`): `TrackerAccess(NamedTuple)`: `tracker: Tracker`, `role: str`, `routes: list[str]`; `tracker_access_routes(session, user: User) -> list[TrackerAccess]` with route texts exactly `"Administrator"`, `"Direct role: Viewer"` (role title-cased), `"Team Infrastructure › Windows: Editor"`, `"View all trackers: Viewer"`; `[]` for a user who is not active.
- Produces (in `tracker/auth/permissions.py`): `permission_sources(session, user: User) -> dict[str, list[str]]`, with texts `"Administrator"`, `"Set PMO, held directly"`, `"Set PMO, held by team PMO Office"`.
- Routes (`permission_required("manage_users")` unless stated; each refusal flashes the message, changes nothing and redirects to `admin.users`):
  - `admin.users`, `admin.new_user`, `admin.create_user`: as today; rows show teams (name and role) and permission sets (direct and through teams), a link to Effective access, and only the actions the viewer may take; "Re-enable" now posts to `admin.enable`.
  - `admin.approve` `POST /admin/users/<id>/approve`: pending users only (400 otherwise); `account_refusal`; optional `team_id` and `team_role`: accepted only when `has_permission(actor, "manage_teams")` (403 otherwise, user stays pending), refused with `TEAM_WITH_SETS_MESSAGE` for a non-administrator when the team holds a set, `parse_team_id` errors give 400 and the user stays pending; logs `user_approved` with `change("pending", "active")` and, when placed, `team_member_added` (`{"team": path, "role": role}`), both with `target_user_id`.
  - `admin.enable` `POST /admin/users/<id>/enable`: disabled users only (400 otherwise); `account_refusal`; logs `user_enabled` with `target_user_id`.
  - `admin.disable`: adds `account_refusal` and `last_admin_refusal`; logs `user_disabled` with `target_user_id`.
  - `admin.password` `GET/POST /admin/users/<id>/password` (`password`): local accounts only (`"This person signs in with Microsoft and has no password here."`); `account_refusal`; `validate_new_password`; logs `password_reset` with `{"source": "web"}` and `target_user_id`, never the password or hash.
  - `admin.set_admin`: stays `admin_required`; adds `last_admin_refusal` when removing; logs `user_admin_changed` with `change(old, new)` and `target_user_id`.
  - `admin.access` `GET /admin/users/<id>/access`: the user's trackers with role and routes, then permissions with sources. Tracker names are shown when the viewer is an administrator, holds `manage_teams`, or can open that tracker; any other trackers are summed in one line, "and 1 tracker you cannot open" or "and {n} trackers you cannot open".
  - `user_created` (web) gains `target_user_id`; `create-admin` and `reset-password` set `target_user_id` too.
  - Sidebar: Users link when `can('manage_users')`.

- [ ] **Step 1: Move the user and SMTP views into `tracker/admin/users.py` and `tracker/admin/smtp.py` without changing behaviour**

Run (sandbox disabled): `/tmp/claude-1000/-home-alexkrovina/cf13b4e4-1890-473a-b9dc-06d0fca97d35/scratchpad/tools/acc-test.sh tests/test_auth.py tests/test_auth_helpers.py -q`
Expected: PASS (endpoint names stay `admin.*`).

- [ ] **Step 2: Write the failing tests in `tests/test_users_admin.py`**

```python
@pytest.fixture
def user_manager(client, user_factory, give_set):
    actor = user_factory(full_name="Manager"); give_set(["manage_users"], user=actor); sign_in(client, actor); return actor

def test_holder_opens_users_and_creates_a_local_user(client, user_manager, db): ...
def test_administrator_flag_stays_administrator_only(client, user_manager, user_factory): ...  # 403

@pytest.mark.parametrize("action", ["password", "disable", "enable", "approve"])
@pytest.mark.parametrize("kind", ["admin", "direct_set", "team_set", "self", "disabled_former_admin"])
def test_holder_refused_on_elevated_users_and_own_account(client, user_manager, ..., action, kind):
    # target built per kind (statuses chosen so the action would otherwise apply); after the post:
    # the flashed message is ELEVATED_MESSAGE or OWN_ACCOUNT_MESSAGE, and status, hash and flags are unchanged

def test_holder_resets_a_local_password_and_it_is_logged_without_secrets(...):
    # hash verifies the new password; entry password_reset with target_user_id; "new-password-456" and "$2b$" not in str(detail)
def test_reset_password_rules_and_microsoft_accounts(...)   # 11 characters -> error; sso user -> refused message
def test_reenable_logs_user_enabled(...)
def test_user_entries_name_the_affected_user(...)   # user_created (web) and user_disabled carry target_user_id
def test_approve_only_pending_users(...)                    # active user -> 400
def test_last_admin_refusal(db, user_factory):
    only = user_factory(is_admin=True)
    assert last_admin_refusal(db, only) == LAST_ADMIN_MESSAGE
    user_factory(is_admin=True)
    assert last_admin_refusal(db, only) is None
def test_user_admin_changed_logs_before_after_and_affected_user(...)
def test_approval_with_a_team_place(...)                    # admin: active, member with role, two entries with target
def test_team_place_refused_for_a_holder_without_manage_teams(...)    # 403; still pending; no membership
def test_team_place_in_a_team_holding_a_set_refused_for_non_admins(...)
def test_approval_with_a_deleted_team_is_400_and_the_user_stays_pending(...)
def test_rows_show_teams_sets_and_the_effective_access_link(...)
def test_effective_access_lists_routes_and_permission_sources(client, logged_in_admin, ...):
    # "Team Infrastructure › Windows: Editor", "Direct role: Viewer", "View all trackers: Viewer",
    # "Set PMO, held by team PMO Office"
def test_effective_access_hides_names_the_holder_cannot_open(...)     # "and 1 tracker you cannot open"
def test_effective_access_refused_without_manage_users(...)
```

In `tests/test_cli.py`, extend the `create-admin` and `reset-password` tests to assert `row.target_user_id == user.id`. Extend the sidebar test in `tests/test_templates.py`: `manage_users` maps to `'href="/admin/users"'`.

- [ ] **Step 3: Run them to verify they fail**

Run (sandbox disabled): `/tmp/claude-1000/-home-alexkrovina/cf13b4e4-1890-473a-b9dc-06d0fca97d35/scratchpad/tools/acc-test.sh tests/test_users_admin.py tests/test_cli.py tests/test_templates.py -q`
Expected: FAIL.

- [ ] **Step 4: Implement `tracker/auth/accounts.py`, the routes, the templates and the CLI change**

As in the Interfaces block. `user_password.html` and `user_access.html` use one `.settings-section` card each; the password page reuses the "At least 12 characters" help text from `user_form.html`.

- [ ] **Step 5: Run the tests and the whole suite**

Run (sandbox disabled): `/tmp/claude-1000/-home-alexkrovina/cf13b4e4-1890-473a-b9dc-06d0fca97d35/scratchpad/tools/acc-test.sh tests/test_users_admin.py tests/test_auth.py tests/test_cli.py tests/test_templates.py -q`, then `/tmp/claude-1000/-home-alexkrovina/cf13b4e4-1890-473a-b9dc-06d0fca97d35/scratchpad/tools/acc-test.sh -q -x`
Expected: PASS.

- [ ] **Step 6: Lint and commit**

Run the lint command from Global Constraints.

```bash
git add tracker/admin tracker/auth/accounts.py tracker/auth/roles.py tracker/auth/permissions.py tracker/templates/admin tracker/templates/base.html tracker/app.py tests/test_users_admin.py tests/test_auth.py tests/test_cli.py tests/test_templates.py
git -c user.name="Alex Krovina" -c user.email="alex.krovina@tradition.ch" commit -m "feat: user management for manage_users holders, with password reset, re-enable and effective access

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 10: Sign-in entries and Entra name sync

**Files:**
- Modify: `tracker/auth/__init__.py` (`login`), `tracker/auth/sso.py`
- Test: `tests/test_auth.py`, `tests/test_sso.py`

**Interfaces:**
- Consumes: `record`, `change` (Task 1).
- Produces:
  - `login_failed` entries: `user_id=None`, `entity="user"`, `entity_id` and `target_user_id` set to the account when one exists, `detail={"email": <entered email, trimmed and lower-cased, cut to 254 characters>, "reason": "unknown_account" | "wrong_password" | "not_active"}`. Reasons: no account with that email gives `unknown_account`; an account with a wrong password or no password gives `wrong_password`; a pending or disabled account with the right password gives `not_active`. Attempts refused by the throttle return before any entry is written.
  - `login` and `sso_login` entries gain `target_user_id`; `user_created` (Entra) and `sso_linked` gain `target_user_id`.
  - `user_name_synced`: at an Entra sign-in of an active Entra user whose stored name differs from the name returned, `user_id=user.id`, `target_user_id=user.id`, `detail=change(old, new)`; committed with the name change. No entry when the name is unchanged.

- [ ] **Step 1: Write the failing tests**

In `tests/test_auth.py`:

```python
def failures(db): return db.scalars(select(AuditLog).where(AuditLog.action == "login_failed")).all()

def test_failed_sign_in_with_an_unknown_account_is_logged(client, db):
    post(client, "/login", {"email": "Nobody@Example.com", "password": "x" * 12})
    (entry,) = failures(db)
    assert entry.detail == {"email": "nobody@example.com", "reason": "unknown_account"}
    assert entry.user_id is None and entry.target_user_id is None

def test_wrong_password_logged_with_the_affected_user(...)
def test_pending_and_disabled_accounts_logged_as_not_active(...)   # right password; reason "not_active"
def test_logged_email_is_cut_to_254_characters(...)                # "a" * 300 + "@example.com" -> len == 254
def test_failed_sign_in_never_stores_the_password(...)             # the typed password not in str(detail)
def test_throttled_attempts_are_not_logged(...)                    # 6 bad attempts -> 5 entries
def test_sign_in_entry_names_the_user(...)                         # login entry target_user_id == user.id
```

In `tests/test_sso.py`:

```python
def test_changed_entra_name_is_synced_and_logged(...)   # stored "Old Name", claims name "New Name" -> entry {"before": "Old Name", "after": "New Name"}
def test_unchanged_entra_name_writes_no_entry(...)
def test_first_sign_in_entry_names_the_new_user(...)    # user_created target_user_id == new user id
```

- [ ] **Step 2: Run them to verify they fail**

Run (sandbox disabled): `/tmp/claude-1000/-home-alexkrovina/cf13b4e4-1890-473a-b9dc-06d0fca97d35/scratchpad/tools/acc-test.sh tests/test_auth.py tests/test_sso.py -q`
Expected: FAIL.

- [ ] **Step 3: Implement**

As in the Interfaces block. Keep the email used for the account lookup exactly as today (blanked when over the limit); log the entered email cut to 254 characters separately.

- [ ] **Step 4: Run them to verify they pass**

Run (sandbox disabled): `/tmp/claude-1000/-home-alexkrovina/cf13b4e4-1890-473a-b9dc-06d0fca97d35/scratchpad/tools/acc-test.sh tests/test_auth.py tests/test_sso.py tests/test_auth_helpers.py -q`
Expected: PASS.

- [ ] **Step 5: Lint and commit**

Run the lint command from Global Constraints.

```bash
git add tracker/auth/__init__.py tracker/auth/sso.py tests/test_auth.py tests/test_sso.py
git -c user.name="Alex Krovina" -c user.email="alex.krovina@tradition.ch" commit -m "feat: log failed sign-ins and Entra name changes, naming the affected user

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 11: Activity screen

**Files:**
- Create: `tracker/activity/__init__.py` (blueprint `activity`), `tracker/activity/labels.py`, `tracker/activity/views.py`
- Create: `tracker/templates/activity/index.html`
- Modify: `tracker/app.py` (register), `tracker/templates/base.html` (link), `tracker/templates/macros.html` (icon `activity`), `tracker/static/tracker.css`
- Test: `tests/test_activity_labels.py` (new, no database), `tests/test_activity.py` (new), `tests/test_templates.py`

**Interfaces:**
- Consumes: `permission_required`, `can` (Task 3); every action written in Tasks 1 to 10.
- Produces (in `tracker/activity/labels.py`):
  - `ACTION_LABELS: dict[str, str]`, a readable label for exactly these actions: `login`, `sso_login`, `sso_linked`, `login_failed`, `user_created`, `user_approved`, `user_disabled`, `user_enabled`, `password_reset`, `user_admin_changed`, `user_name_synced`, `team_created`, `team_renamed`, `team_moved`, `team_deleted`, `team_member_added`, `team_member_role_changed`, `team_member_removed`, `tracker_created`, `tracker_imported`, `tracker_archived`, `settings_updated`, `tracker_team_changed`, `role_set`, `role_removed`, `group_created`, `group_updated`, `group_deleted`, `group_retired`, `group_unretired`, `group_reordered`, `baseline_changed`, `entry_created`, `entry_updated`, `entry_deleted`, `targets_updated`, `inputs_saved`, `risk_created`, `risk_updated`, `risk_deleted`, `recipient_added`, `recipient_removed`, `email_template_saved`, `email_template_reset`, `report_sent`, `report_send_queued`, `report_send_failed`, `report_test_sent`, `permission_set_created`, `permission_set_renamed`, `permission_set_deleted`, `permission_set_permissions_changed`, `permission_set_holder_added`, `permission_set_holder_removed`, `smtp_settings_updated`, `audit_retention_changed`, `audit_pruned`. (Labels are sentence case, for example "Failed sign-in", "Team member role changed".)
  - `action_label(action: str) -> str`: the label, or the stored action name when unknown.
  - `DetailLine(NamedTuple)`: `field: str`, `before: str | None`, `after: str | None`, `value: str | None`.
  - `describe(detail: dict | None) -> list[DetailLine]`: `None` gives `[]`; `"before"`/`"after"` keys give change lines first (one per key when both are dicts, otherwise one line with an empty field), then every other key a plain line; a value that is a two-item list in an older entry (for example `{"role": [None, "viewer"]}`, `settings_updated`, `targets_updated`) gives a change line; anything else a plain line. Values are shown as text: `None` as "none", lists joined with ", ", booleans as "Yes"/"No", nested dicts as `key: value` pairs.
- Produces (in `tracker/activity/views.py`):
  - `PAGE_SIZE = 50`.
  - `ActivityFilters(NamedTuple)`: `person: int | None`, `action: str | None`, `start: date | None`, `end: date | None`, `page: int`; `parse_filters(args) -> ActivityFilters`: any unparsable value is ignored (and `page` below 1 becomes 1).
  - `activity.index` `GET /admin/activity` (`permission_required("view_activity")`): newest first (`at` then `id`, descending), 50 a page (one extra row read to know whether an older page exists, with "Newer" and "Older" links keeping the filters), columns Time (`%d %b %Y %H:%M` UTC), Performed by, User affected, Action (label), Tracker (name, for every entry), Detail (`describe`, before → after). Filters: person (matches `user_id` or `target_user_id`), action (from `ACTION_LABELS`), from and to dates (inclusive, UTC). Missing people or trackers show "–".
  - Sidebar: Activity link (`href="/admin/activity"`) when `can('view_activity')`.

- [ ] **Step 1: Write the failing tests (no database) in `tests/test_activity_labels.py`**

```python
def test_every_action_written_in_the_code_has_a_label():
    package = Path(__file__).resolve().parent.parent / "tracker"
    source = "\n".join(p.read_text(encoding="utf-8") for p in package.rglob("*.py"))
    written = set(re.findall(r'action="([a-z_]+)"', source))
    assert written <= set(ACTION_LABELS)
    assert {"login_failed", "entry_updated", "audit_pruned", "tracker_team_changed"} <= set(ACTION_LABELS)

def test_describe_reads_the_new_shape():
    assert describe({"team": "Windows", "before": "viewer", "after": "editor"}) == [
        DetailLine("", "viewer", "editor", None), DetailLine("team", None, None, "Windows")]

def test_describe_reads_older_shapes():
    assert describe({"role": [None, "viewer"]}) == [DetailLine("role", "none", "viewer", None)]
    assert describe({"is_admin": True}) == [DetailLine("is_admin", None, None, "Yes")]
    assert describe(None) == []

def test_describe_lists_changed_fields_one_per_line():
    lines = describe({"before": {"quantity": 12}, "after": {"quantity": 15}})
    assert lines == [DetailLine("quantity", "12", "15", None)]
```

- [ ] **Step 2: Write the failing database tests in `tests/test_activity.py`**

```python
def test_activity_refused_without_view_activity(client, logged_in_user): ...           # 403
def test_holder_and_admin_open_activity(...)
def test_newest_first_50_a_page(client, logged_in_admin, db):
    # 120 rows -> page 1 has 50 rows, newest first; page 3 has 20; page 1 links "Older", page 3 links "Newer" only
def test_person_filter_matches_who_acted_or_who_was_affected(...)
def test_action_and_date_range_filters(...)                                            # "to" date is inclusive
def test_malformed_filters_fall_back_to_the_full_list(client, logged_in_admin):
    for query in ("page=abc", "page=0", "page=-3", "from=2026-13-45", "person=xyz", "action=<b>"):
        assert client.get(f"/admin/activity?{query}").status_code == 200
def test_rows_with_deleted_people_or_trackers_and_any_detail_shape_render(...):
    # entries with user_id/target_user_id/tracker_id None, detail None, {"role": [None, "viewer"]}, action "mystery"
def test_tracker_names_shown_to_a_view_activity_holder_without_access(...)
def test_no_secrets_in_any_entry(client, logged_in_admin, user_factory, db):
    # create a local user (password P1), reset a password (P2), fail a sign-in (P3) and save SMTP settings,
    # then for json.dumps of every entry's detail: no P1, P2, P3, "$2b$", "password_hash" or "smtp_password"
```

Extend the sidebar test in `tests/test_templates.py`: `view_activity` maps to `'href="/admin/activity"'`.

- [ ] **Step 3: Run them to verify they fail**

Run (sandbox disabled): `/tmp/claude-1000/-home-alexkrovina/cf13b4e4-1890-473a-b9dc-06d0fca97d35/scratchpad/tools/acc-test.sh tests/test_activity_labels.py tests/test_activity.py tests/test_templates.py -q`
Expected: FAIL.

- [ ] **Step 4: Implement**

As in the Interfaces block. The page uses one `.settings-section` with `.has-action` head, a filter form (GET, `field` macro) and a `.section-table`; before → after is shown with the old value struck through or muted, styled in `tracker.css`.

- [ ] **Step 5: Run the tests and the whole suite**

Run (sandbox disabled): `/tmp/claude-1000/-home-alexkrovina/cf13b4e4-1890-473a-b9dc-06d0fca97d35/scratchpad/tools/acc-test.sh tests/test_activity_labels.py tests/test_activity.py tests/test_templates.py -q`, then `/tmp/claude-1000/-home-alexkrovina/cf13b4e4-1890-473a-b9dc-06d0fca97d35/scratchpad/tools/acc-test.sh -q -x`
Expected: PASS.

- [ ] **Step 6: Lint and commit**

Run the lint command from Global Constraints.

```bash
git add tracker/activity tracker/templates/activity tracker/app.py tracker/templates/base.html tracker/templates/macros.html tracker/static/tracker.css tests/test_activity_labels.py tests/test_activity.py tests/test_templates.py
git -c user.name="Alex Krovina" -c user.email="alex.krovina@tradition.ch" commit -m "feat: Activity screen with readable actions, before and after values, filters and paging

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 12: Retention setting and the daily prune

**Files:**
- Create: `tracker/activity/retention.py`
- Modify: `tracker/activity/views.py` (retention route), `tracker/templates/activity/index.html` (footer form for administrators)
- Modify: `tracker/sched/runner.py`
- Test: `tests/test_retention.py` (new)

**Interfaces:**
- Consumes: `AppSetting`, `AuditLog`, `record`, `change`.
- Produces (in `tracker/activity/retention.py`):
  - `RETENTION_KEY = "audit_retention_days"`, `LAST_PRUNED_KEY = "audit_last_pruned"`, `MIN_RETENTION_DAYS = 90`, `MAX_RETENTION_DAYS = 3650`.
  - `RETENTION_ERROR = "Enter a whole number of days from 90 to 3,650, or leave the box empty to keep entries indefinitely."`
  - `retention_days(session) -> int | None` (absent key means indefinitely).
  - `parse_retention(value: str | None) -> tuple[int | None, str | None]`: blank gives `(None, None)`; spaces and thousands commas are removed; anything else must be a whole number from 90 to 3,650.
  - `prune_audit_log(session, now_utc: datetime) -> int | None`: `None` when no retention is set or today's prune (UTC date) has already been claimed; the claim is an `INSERT … ON CONFLICT (key) DO UPDATE SET value = :today WHERE app_settings.value <> :today RETURNING key` on `LAST_PRUNED_KEY`, so two workers never prune twice the same day. It deletes entries with `at < now_utc - retention`, records `audit_pruned` (`entity="audit_log"`, `detail={"removed": n, "cutoff": <cutoff ISO timestamp>}`) only when `n > 0`, commits, and returns `n`.
  - `activity.retention` `POST /admin/activity/retention` (`admin_required`, field `retention_days`): on error flashes `RETENTION_ERROR`; otherwise stores the value (or deletes the key when blank) and logs `audit_retention_changed` with `change(old, new)` (`entity="app_settings"`, `entity_id="audit_retention_days"`); no entry when unchanged.
  - The Activity page footer (`.settings-section-foot`) shows the form to administrators only, with the current value and "Entries older than this are deleted once a day. Leave empty to keep entries indefinitely."
  - `run_scheduler_cycle` calls `prune_audit_log(session, now_utc)` first, inside `try`/`except Exception` (rollback and `logger.exception`), so a prune failure never stops sends.

- [ ] **Step 1: Write the failing tests in `tests/test_retention.py`**

```python
@pytest.mark.parametrize("value,expected", [("", (None, None)), ("90", (90, None)), ("3650", (3650, None)),
                                            ("3,650", (3650, None)), (" 365 ", (365, None))])
def test_parse_retention_accepts(value, expected):
    assert parse_retention(value) == expected

@pytest.mark.parametrize("value", ["89", "0", "90.5", "3651", "abc", "-90"])
def test_parse_retention_refuses(value):
    assert parse_retention(value) == (None, RETENTION_ERROR)

def test_retention_form_and_route_are_administrator_only(client, logged_in_user, give_set): ...   # no form; POST 403
def test_retention_set_and_cleared_are_logged(client, logged_in_admin, db):
    # "365" -> {"before": None, "after": 365}; "" -> {"before": 365, "after": None} and the key is gone
def test_prune_deletes_older_entries_and_records_its_own_entry(db, ...):
    # retention 90; rows at now-100 days and now-10 days -> returns 1; one audit_pruned with {"removed": 1, "cutoff": ...}
def test_prune_runs_once_a_day(db, ...)                 # second call the same UTC day -> None, nothing deleted
def test_prune_without_retention_does_nothing(db, ...)  # None; rows kept; no LAST_PRUNED_KEY written
def test_scheduler_cycle_prunes_and_survives_a_prune_failure(app, db, monkeypatch): ...
```

- [ ] **Step 2: Run them to verify they fail**

Run (sandbox disabled): `/tmp/claude-1000/-home-alexkrovina/cf13b4e4-1890-473a-b9dc-06d0fca97d35/scratchpad/tools/acc-test.sh tests/test_retention.py -q`
Expected: FAIL.

- [ ] **Step 3: Implement**

As in the Interfaces block.

- [ ] **Step 4: Run the tests and the scheduler tests**

Run (sandbox disabled): `/tmp/claude-1000/-home-alexkrovina/cf13b4e4-1890-473a-b9dc-06d0fca97d35/scratchpad/tools/acc-test.sh tests/test_retention.py tests/sched tests/test_cli.py tests/test_activity.py -q`
Expected: PASS.

- [ ] **Step 5: Lint and commit**

Run the lint command from Global Constraints.

```bash
git add tracker/activity tracker/templates/activity/index.html tracker/sched/runner.py tests/test_retention.py
git -c user.name="Alex Krovina" -c user.email="alex.krovina@tradition.ch" commit -m "feat: optional activity retention from 90 to 3,650 days, pruned once a day by the worker

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 13: Correcting a progress entry in place, and the final checks

**Files:**
- Modify: `tracker/entries/views.py` (new route `edit_entry`)
- Create: `tracker/templates/entries/edit.html`
- Modify: `tracker/templates/entries/list.html`
- Test: `tests/test_entries.py`

**Interfaces:**
- Consumes: `require_tracker_role("editor")` (now covering team routes); `check_entry_date`, `parse_quantity`, `format_date`; `_refuse_if_archived`, `ARCHIVED_MESSAGE`; `record`, `change`.
- Produces:
  - `entries.edit_entry` `GET/POST /trackers/<int:tracker_id>/entries/<int:entry_id>/edit`: 404 when the entry is missing or belongs to another tracker; archived trackers refused with `"This tracker is archived."` and nothing changed. Fields `group_id`, `entry_date`, `quantity`, `note`. The location select lists the tracker's active groups plus the entry's current group when it is retired (marked "(retired)"); keeping the current group is allowed even when retired; choosing another retired group gives `"Entries cannot be moved to a retired group."`; a group of another tracker gives `"Choose a group."`. Date checked with `check_entry_date(..., today=date.today())`, quantity with `parse_quantity`; `week_ending` recalculated from the new date. On success logs one `entry_updated` (`entity="entry"`) with `change({changed fields before}, {changed fields after})` over `entry_date` (ISO), `group_id`, `group` (name, only when the group changed), `quantity`, `note`; no entry and "No changes to save." when nothing changed. Redirects to the entries list.
  - `entries/list.html`: an Edit `tool_link` (icon `edit`, label "Edit {quantity} for {location} on {date}") before the delete form on active trackers; the section text "To correct an entry, delete it and record it again." becomes "Every completion recorded, newest week first. Use Edit to correct an entry; delete only entries recorded by mistake."

- [ ] **Step 1: Write the failing tests in `tests/test_entries.py`**

```python
def edit_url(tracker, entry): return f"/trackers/{tracker.id}/entries/{entry.id}/edit"

def test_editors_and_owners_can_edit_and_viewers_cannot(client, db, tracker_factory, user_factory, grant): ...
    # editor 200, owner 200, team editor 200, viewer 404
def test_edit_changes_fields_and_recalculates_the_week(...)
    # 2026-10-14 (week ending 16 Oct) moved to 2026-10-20 -> week_ending 2026-10-23
def test_edit_checks_like_a_new_entry(...)
    # future date -> "The date cannot be after today"; date outside -> OUTSIDE; quantity "0" and "abc" -> 400, entry unchanged
def test_a_retired_location_can_be_kept_but_not_chosen(...)
def test_edit_refused_on_an_archived_tracker(...)
def test_edit_logs_one_entry_updated_with_changed_fields_only(client, ...):
    post(client, edit_url(tracker, entry), entry_form(group, quantity="15", note=""))   # was 12
    (logged,) = db.scalars(select(AuditLog).where(AuditLog.action == "entry_updated")).all()
    assert logged.detail == {"before": {"quantity": 12}, "after": {"quantity": 15}} and logged.user_id == user.id
def test_saving_without_changes_writes_no_entry(...)
def test_report_figures_follow_the_corrected_entry(...)   # compute_position(...).headline total rises by 3
def test_editing_a_deleted_or_foreign_entry_is_404(...)
def test_entries_page_offers_edit_and_drops_the_delete_and_record_note(...)
```

- [ ] **Step 2: Run them to verify they fail**

Run (sandbox disabled): `/tmp/claude-1000/-home-alexkrovina/cf13b4e4-1890-473a-b9dc-06d0fca97d35/scratchpad/tools/acc-test.sh tests/test_entries.py -q`
Expected: FAIL (404 for the edit route).

- [ ] **Step 3: Implement**

As in the Interfaces block. `edit.html` follows `entries/new.html` (one `.settings-section` card with the `setting` macro, Cancel and Save buttons).

- [ ] **Step 4: Run the entry tests**

Run (sandbox disabled): `/tmp/claude-1000/-home-alexkrovina/cf13b4e4-1890-473a-b9dc-06d0fca97d35/scratchpad/tools/acc-test.sh tests/test_entries.py tests/test_registers_browser.py -q`
Expected: PASS.

- [ ] **Step 5: Run every final check**

Run (sandbox disabled): `/tmp/claude-1000/-home-alexkrovina/cf13b4e4-1890-473a-b9dc-06d0fca97d35/scratchpad/tools/acc-test.sh -q`
Expected: every test passes; only the golden-workbook test may be skipped (no database or browser test skipped).
Run the lint command from Global Constraints. Expected: `All checks passed!` and no files to reformat.
Run (sandbox disabled): `cd /tmp/claude-1000/-home-alexkrovina/cf13b4e4-1890-473a-b9dc-06d0fca97d35/scratchpad/wt-access && export DATABASE_URL=$(grep ^TEST_DATABASE_URL= /mnt/c/Users/AlexKrovina/Documents/GitHub/tc-trackers/.env | cut -d= -f2- | sed -E 's#/tracker_test[a-z_]*$#/tracker_test_design#') && /mnt/c/Users/AlexKrovina/Documents/GitHub/tc-trackers/.venv/bin/alembic upgrade head && /mnt/c/Users/AlexKrovina/Documents/GitHub/tc-trackers/.venv/bin/alembic check`
Expected: `No new upgrade operations detected.`

- [ ] **Step 6: Commit**

```bash
git add tracker/entries/views.py tracker/templates/entries/edit.html tracker/templates/entries/list.html tests/test_entries.py
git -c user.name="Alex Krovina" -c user.email="alex.krovina@tradition.ch" commit -m "feat: correct a progress entry in place, logged with before and after values

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```
