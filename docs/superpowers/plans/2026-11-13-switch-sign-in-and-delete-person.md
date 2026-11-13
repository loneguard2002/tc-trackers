# Switch to Microsoft sign-in, and delete a person: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Administrators (and Manage users holders, for the switch) can move a password account to Microsoft sign-in and delete a person while history keeps their name; the Activity page shows emails beside names.

**Architecture:**
- A deleted person stays in `users` with `status = 'deleted'`, and a partial unique index frees their email.
- `tracker/admin/deletion.py` computes what a delete removes and carries it out. Both new actions are routes in
  `tracker/admin/users.py`, offered only on the person's Access page.
- A new guard in `tracker/auth/accounts.py` keeps one active administrator who signs in with a password.

**Tech Stack:** Flask 3.1, SQLAlchemy 2, Alembic, Jinja, PostgreSQL, pytest with pytest-xdist, Playwright.

**Spec:** `docs/superpowers/specs/2026-11-13-switch-sign-in-and-delete-person-design.md`

## Global Constraints

- Work only in the worktree `/tmp/claude-1000/-home-alexkrovina/3aedc358-6c9a-47eb-9f48-ae779a8c6a2b/scratchpad/wt-userdelete` (branch `feat/user-delete-sso-switch`). Never modify `/mnt/c/Users/AlexKrovina/Documents/GitHub/tc-trackers`.
- Run tests with `WT=<worktree> bash /tmp/claude-1000/-home-alexkrovina/3aedc358-6c9a-47eb-9f48-ae779a8c6a2b/scratchpad/tools/run-tests.sh <args>` and the sandbox disabled. Inside the sandbox, every database test skips with "database unavailable".
- No new dependencies. Lint with `ruff check` and `ruff format --check` (line length 120).
- Copy is British English, formal, active voice, with no contractions.
- Every change is committed together with its activity entries in one transaction. Entries name the affected person in `target_user_id`.
- Commit with `git -c user.name="Alex Krovina" -c user.email="alex.krovina@tradition.ch" commit`, and end each message with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Exact copy from the spec:
  - `"Keep at least one administrator who signs in with a password, in case Microsoft sign-in stops working."`
  - The switch confirmation: `"Switch {name} ({email}) to Microsoft sign-in? Their password stops working now. They keep all their access, and sign in with Microsoft using this email address from now on."`
  - Activity labels `"Sign-in switched to Microsoft"` and `"User deleted"`.
  - The dialog title `"Delete {name}"`, with the email on the line beneath.
  - The dialog note `"The email address becomes free, so the person can be added again as a new account. This cannot be undone."`
  - The field label `"Type {email} to confirm"`, and a button that reads `"Delete"`.
  - The Kept line `"Their name in all history"`.
  - `"No recipients left"`.
  - `"Deleted on {date} by {name}."`
  - The status filter `"Deleted"`.

## Review Focus

1. **Letter case and spaces:**
   - A typed confirmation such as `"  Jordan.Lee@Example.com "` matches.
   - A recipient stored as `Jordan.Lee@Example.com` is removed.
   - Tests: Task 4 (server) and Task 5 (browser).
2. **Re-adding a deleted email:** the new account gets a new id, and filtering Activity by the new person shows none of the old entries. Tests: Task 4 and Task 7.
3. **A tracker whose lead was deleted:** its settings page still opens, and the Lead field is empty. Test: Task 4.
4. **Old entries with no person** (performer NULL from before this change): they still show "–". Test: Task 7.
5. **A delete posted for an account that is no longer disabled or pending** (re-enabled in another tab): refused with 400, nothing changed. Test: Task 4.

---

### Task 1: Deleted status, a reusable email, and email lookups that skip deleted people

**Files:**
- Create: `migrations/versions/0010_deleted_users.py`
- Modify: `tracker/models.py` (the `User` constraints and `email`)
- Modify: `tracker/auth/accounts.py` (`find_by_email`)
- Modify: `tracker/auth/__init__.py:100`, `tracker/auth/sso.py:55`, `tracker/app.py:150,183,253`
- Test: `tests/test_migration_0010.py`, `tests/test_deleted_accounts.py`

**Interfaces:**
- Produces `find_by_email(session: Session, email: str) -> User | None` in `tracker/auth/accounts.py`: the account with that email whose status is not `deleted`.
- Produces `User.status == "deleted"` as a valid value.

- [ ] **Step 1: Write the failing tests**

`tests/test_migration_0010.py`, following `tests/test_migration_0009.py` (downgrade, raw SQL, upgrade back in `finally`):
- `test_deleted_rows_free_their_email`, at head:
  - insert two `users` rows with the same email, one `status='deleted'`: succeeds;
  - a second live row with that email: `IntegrityError`.
- `test_downgrade_restores_unique_emails`:
  - with a deleted row and a live row sharing an email, `command.downgrade(alembic_config(), "0009")` succeeds;
  - the deleted row is now `disabled`, with email `<email>#deleted-<id>`;
  - then upgrade to head.

`tests/test_deleted_accounts.py`:
- `test_password_sign_in_skips_a_deleted_account`:
  - `user_factory(email="a@example.com", status="deleted")`;
  - POST `/login` with `TEST_PASSWORD` shows "Invalid email or password."
- `test_password_sign_in_finds_the_live_account_beside_a_deleted_one`:
  - a deleted row and an active row with the same email;
  - sign-in succeeds, and the session's `user_id` is the active row's id.
- `test_microsoft_sign_in_ignores_a_deleted_account_with_the_same_email`:
  - use `sso_client`, with `FakeMsal`, `claims` and `start` imported from `tests.test_sso`;
  - a deleted SSO row for `person@example.com` with `sso_subject=None`;
  - after the callback, a new `pending` user exists with that email and a different id.
- `test_reset_password_command_skips_a_deleted_account`:
  - `app.test_cli_runner().invoke(args=["reset-password", email, "--password", ...])` exits with "No user with the email".

- [ ] **Step 2: Run them and see them fail**

Run: `run-tests.sh tests/test_migration_0010.py tests/test_deleted_accounts.py -v`. Expected: FAIL (the `ck_users_status` violation, and the unique email).

- [ ] **Step 3: Write the migration `0010` (revision `"0010"`, down_revision `"0009"`)**

Upgrade:
- drop and re-create `ck_users_status` with `('pending', 'active', 'disabled', 'deleted')`;
- drop the constraint `uq_users_email`;
- create the unique index `uq_users_email` on `users (email)` with `postgresql_where=sa.text("status <> 'deleted'")`.

Downgrade:
- `UPDATE users SET status = 'disabled', email = email || '#deleted-' || id WHERE status = 'deleted'`;
- then restore the constraint and the check.

- [ ] **Step 4: Match the model to the migration**

- In `User`, drop `unique=True` from `email`, and add `'deleted'` to the status `CheckConstraint`.
- After the class, add `Index("uq_users_email", User.email, unique=True, postgresql_where=text("status <> 'deleted'"))`.
- `tests/test_migration_matches_models.py` must stay green.

- [ ] **Step 5: Add `find_by_email`, and use it everywhere a person is looked up by email**

The places are: password sign-in, `_resolve_user`, and the `create-admin`, `reset-password` and `import-workbook --owner` commands.

- [ ] **Step 6: Run the tests**

Run: `run-tests.sh tests/test_migration_0010.py tests/test_deleted_accounts.py tests/test_migration_matches_models.py tests/test_sso.py tests/test_auth.py tests/test_cli.py -v`. Expected: PASS.

- [ ] **Step 7: Commit**

`feat: a deleted status, with the email free for a new account`

---

### Task 2: Keep one administrator who signs in with a password

**Files:**
- Modify: `tracker/auth/accounts.py`
- Modify: `tracker/admin/users.py` (`disable`, `set_admin`)
- Modify: `tests/conftest.py` (move `sso_app` and `sso_client` here unchanged from `tests/test_sso.py`)
- Test: `tests/test_user_sign_in_switch.py`

**Interfaces:**
- Produces:
  - `LAST_PASSWORD_ADMIN_MESSAGE` (the exact copy above);
  - `last_password_admin_refusal(session: Session, target: User) -> str | None`.
- How the guard works:
  - it returns `None` unless `target` is an active administrator with `auth_source == "local"`;
  - otherwise it locks the active administrators exactly as `last_admin_refusal` does (`FOR UPDATE`, ordered by id);
  - it returns the message when no other active administrator signs in with a password.

- [ ] **Step 1: Write the failing tests**

Each test signs in an administrator whose `auth_source="sso"`, through `sign_in(sso_client, actor)`.
- `test_disable_refuses_the_last_password_administrator_while_sso_is_on`:
  - the target is the only active `local` administrator;
  - POST `/admin/users/<id>/disable` flashes the message;
  - the target is still `active`.
- `test_removing_administrator_refuses_the_last_password_administrator_while_sso_is_on`: POST `/admin/users/<id>/admin` with `is_admin=0` is refused in the same way.
- `test_both_are_allowed_when_another_password_administrator_remains`.
- `test_disable_is_allowed_while_sso_is_off`: the same set-up on the plain `client`, where disabling succeeds.

- [ ] **Step 2: Run them and see them fail**

Run: `run-tests.sh tests/test_user_sign_in_switch.py -v`. Expected: the first two tests FAIL.

- [ ] **Step 3: Implement the guard**

- Add `last_password_admin_refusal`.
- In `disable` and in `set_admin` (when removing), call it after `last_admin_refusal`, only when `current_app.config["SSO_ENABLED"]`.
- Refuse through `_refuse`.

- [ ] **Step 4: Run the tests**

Run: `run-tests.sh tests/test_user_sign_in_switch.py tests/test_users_admin.py tests/test_sso.py -v`. Expected: PASS.

- [ ] **Step 5: Commit**

`feat: keep one administrator who signs in with a password while Microsoft sign-in is on`

---

### Task 3: Switch to Microsoft sign-in

**Files:**
- Modify: `tracker/admin/users.py` (`_actions` and the new route)
- Modify: `tracker/templates/admin/user_access.html`
- Modify: `tracker/activity/labels.py`
- Modify: `docs/superpowers/specs/2026-10-26-teams-permissions-activity-design.md`
- Test: `tests/test_user_sign_in_switch.py`

**Interfaces:**
- Consumes `last_password_admin_refusal` (Task 2).
- Produces:
  - the route `POST /admin/users/<int:user_id>/sign-in`, endpoint `admin.switch_sign_in`, `@permission_required("manage_users")`;
  - `_actions(...)["switch"]`: `may_act and user.auth_source == "local" and user.status in ("active", "disabled") and current_app.config["SSO_ENABLED"]`;
  - `ACTION_LABELS["sign_in_switched"] = "Sign-in switched to Microsoft"`.

- [ ] **Step 1: Write the failing tests** (in `tests/test_user_sign_in_switch.py`)

- `test_switch_then_microsoft_sign_in_links_and_keeps_access`:
  - an administrator switches a local person who has a team place and a tracker role;
  - the person has `auth_source == "sso"` and `password_hash is None`;
  - there is one `sign_in_switched` entry with `detail == {"before": "local", "after": "sso"}` and `target_user_id` set to the person;
  - on a fresh `sso_app.test_client()`, `start(..., FakeMsal(claims(email=person.email)))` and the callback sign the person in as the same id;
  - `sso_subject` is set;
  - the team place and the role remain.
- `test_the_old_password_stops_working`: after the switch, POST `/login` with `TEST_PASSWORD` shows "Invalid email or password."
- `test_switch_refused_for_a_manage_users_holder_on_own_or_elevated_account`: refused with the `account_refusal` message.
- `test_switch_refused_on_the_last_password_administrator`: the message from Task 2; the person stays `local`.
- `test_switch_needs_sso_and_a_password_account`:
  - on the plain `client`, POST gives 400 and the Access page has no "Switch to Microsoft sign-in";
  - on `sso_client`, an `sso` person gives 400.
- `test_access_page_offers_the_switch_with_its_confirmation`:
  - the Access page HTML contains "Switch to Microsoft sign-in";
  - it contains the confirmation copy with the person's name and email (HTML-escaped).

- [ ] **Step 2: Run them and see them fail**

Expected: FAIL (404 on the route).

- [ ] **Step 3: Implement the route `switch_sign_in(user_id: int)`**

1. Run `account_refusal`, then `_refuse` on a refusal.
2. Give `abort(400)` with `"Microsoft sign-in is not set up."` when SSO is off.
3. Give `abort(400)` with `"This person already signs in with Microsoft."` when the person is not `local`.
4. Give `abort(400)` when the person is not active or disabled.
5. Run `last_password_admin_refusal`.
6. Set `auth_source="sso"` and `password_hash=None`.
7. Record `sign_in_switched` with `change("local", "sso")`, then commit.
8. Flash `f"{name} now signs in with Microsoft."` and redirect to `admin.access` for the person.

- [ ] **Step 4: Add the button to the Access page action list**

- Show a "Switch to Microsoft sign-in" form when `actions.switch`.
- It uses `data-inline-confirm` with the `confirm-box` markup, as Delete team does (`tracker/templates/teams/team.html:62-73`).
- `data-confirm` carries the exact confirmation copy.

- [ ] **Step 5: Update the permissions design**

In the 2026-10-26 design, Manage users now also covers the switch, Delete is administrator-only, and the emergency administrator rule is recorded.

- [ ] **Step 6: Run the tests**

Run: `run-tests.sh tests/test_user_sign_in_switch.py tests/test_users_admin.py tests/test_sso.py tests/test_activity_labels.py tests/test_templates.py -v`. Expected: PASS.

- [ ] **Step 7: Commit**

`feat: switch a password account to Microsoft sign-in from the Access page`

---

### Task 4: Delete a person (server side)

**Files:**
- Create: `tracker/admin/deletion.py`
- Modify: `tracker/admin/users.py` (`_actions`, refusals in the existing actions, and the new route)
- Modify: `tracker/trackers/views.py` (around 967: refuse a deleted person)
- Modify: `tracker/activity/labels.py`
- Test: `tests/test_user_delete.py`

**Interfaces:**
- Consumes `find_by_email` (Task 1).
- Produces, in `tracker/admin/deletion.py`:

  ```python
  @dataclass(frozen=True)
  class DeletionSummary:
      teams: list[tuple[int, str]]               # (team id, team path)
      regions: list[tuple[int, str, str]]        # (region id, code, role)
      roles: list[tuple[int, str, str]]          # (tracker id, tracker name, role), direct tracker roles
      sets: list[tuple[int, str]]                # (set id, name), held directly
      led: list[tuple[int, str]]                 # (tracker id, tracker name)
      recipient_trackers: list[tuple[int, str]]  # trackers whose recipient list holds the email, any case
      activity_entries: int                      # entries with user_id or target_user_id = the person
      report_inputs: int                         # report_inputs.prepared_by = the person

  def deletion_summary(session: Session, user: User) -> DeletionSummary: ...
  def delete_person(session: Session, actor: User, user: User) -> None:
      """Remove access, leads, report emails and sign-in, and record each removal; the caller has locked and
      checked the person, and commits."""
  ```
- Also produces:
  - the route `GET|POST /admin/users/<int:user_id>/delete`, endpoint `admin.delete`, `@admin_required`;
  - `_actions(...)["delete"]`: `actor.is_admin and user.id != actor.id and user.status in ("disabled", "pending")`;
  - for a `deleted` person, `_actions` returns every key `False`;
  - `ACTION_LABELS["user_deleted"] = "User deleted"`.

What `delete_person` records, in this order:
1. One `team_member_removed` per team: entity `team`, detail `{"team": path, "role": role}`.
2. One `region_access_removed` per grant: entity `region`, detail `{"region": code, "role": role}`.
3. One `role_removed` per direct tracker role: `tracker_id` set, entity `user`, detail `change(role, None)`.
4. One `permission_set_holder_removed` per directly held set: detail `{"set": name}`.
5. One `settings_updated` per tracker led: `tracker_id` set, entity `tracker`, detail `{"lead": [name, None]}`.
6. One `recipient_removed` per recipient row: `tracker_id` set, entity `email_settings`, detail `{"email": stored email}`.
7. Finally `user_deleted`: entity `user`, detail `{"name", "email", "teams", "regions", "tracker_roles", "permission_sets", "trackers_led", "report_emails"}`, where each count is an int.

Every entry has `target_user_id` set to the person. After recording, `delete_person`:
- deletes the access rows;
- sets the leads to NULL;
- deletes the recipient rows;
- for each `ReportSend` with `status='queued'` (locked `FOR UPDATE`), drops the email (any case) from its `recipients`; a send left empty becomes `status='failed'` with `error="No recipients left"` and `next_attempt_at=None`;
- sets `is_admin=False`, `password_hash=None`, `sso_subject=None` and `status="deleted"`.

- [ ] **Step 1: Write the failing tests** (`tests/test_user_delete.py`, administrator signed in)

The set-up is a disabled person who has:
- a team place;
- a region grant;
- a direct tracker role;
- a directly held set;
- the lead of one tracker;
- their email on two recipient lists, one stored as `Jordan.Lee@Example.com`;
- one queued send whose only recipient is that email.

The tests:
- `test_delete_removes_access_leads_report_emails_and_sign_in`:
  - POST with `confirm_email="  Jordan.Lee@Example.com "` succeeds;
  - the access rows are gone, `lead_user_id` is None, and both recipient rows are gone;
  - the queued send is `failed` with "No recipients left";
  - the person row remains with `status == "deleted"`, `password_hash`/`sso_subject` None and `is_admin` False;
  - `full_name` and `email` are kept.
- `test_delete_records_each_removal_and_a_summary`:
  - each action in the list above appears with the right `tracker_id`;
  - `user_deleted.detail["report_emails"] == 2`.
- `test_history_keeps_the_name_and_the_email_can_be_used_again`:
  - the person's earlier `login` entry still joins to the same row;
  - adding a person with the same email through POST `/admin/users` gives a new id.
- `test_delete_is_for_administrators_only`: a Manage users holder gets 403.
- `test_delete_needs_a_disabled_or_pending_account`: an active person gets 400, with nothing changed.
- `test_delete_refuses_own_account`.
- `test_a_mismatched_email_is_refused`: 400, the page shows `"The email does not match."`, and nothing changes.
- `test_a_deleted_person_cannot_be_changed_again`: disable, re-enable, administrator, password, switch and a tracker role on a deleted person each give 400 or refuse; nothing changes.
- `test_a_tracker_whose_lead_was_deleted_still_opens_its_settings`: GET the tracker settings page returns 200.
- `test_summary_counts`: `deletion_summary` gives the expected lists and counts before the delete.
- `test_activity_hides_tracker_removals_from_viewers_who_cannot_open_the_tracker`: a View activity holder
  without access to the tracker sees the `role_removed` entry's detail replaced by the hidden-detail message,
  and the `user_deleted` summary names no tracker.

- [ ] **Step 2: Run them and see them fail**

Expected: FAIL (404 on the route).

- [ ] **Step 3: Write `deletion.py`**

Write `deletion_summary` and `delete_person` as specified.

- [ ] **Step 4: Write the route `delete(user_id: int)`**

1. On POST, load the person with `db.get(User, user_id, with_for_update=True)`.
2. Refuse one's own account with `_refuse("You cannot delete your own account.")`.
3. Give `abort(400)` with `"Only a disabled or pending person can be deleted."` for any other status.
4. Run `last_admin_refusal`.
5. GET renders `admin/user_delete.html` (Task 5).
6. On POST, compare `confirm_email.strip().lower()` with the person's email. A mismatch re-renders that page with the error, status 400.
7. Call `delete_person`, commit, flash `f"Deleted {name} ({email})."`, and redirect to `admin.users`.

Until Task 5, the template may be a minimal page holding the form.

- [ ] **Step 5: Refuse deleted people in the existing actions**

- In `approve`, `enable`, `disable`, `set_admin` and `password`, give `abort(400)` with `"This person has been deleted."` when `user.status == "deleted"`.
- Do the same in the tracker role handler.
- Make `_actions` return all `False` for a deleted person.

- [ ] **Step 6: Run the tests**

Run: `run-tests.sh tests/test_user_delete.py tests/test_users_admin.py tests/test_tracker_access.py tests/test_activity_labels.py tests/test_cli.py -v`. Expected: PASS.

- [ ] **Step 7: Commit**

`feat: delete a disabled or pending person, keeping their name in history`

---

### Task 5: The delete dialog and its no-JavaScript page

**Files:**
- Create: `tracker/templates/admin/_delete_summary.html`, `tracker/templates/admin/_delete_dialog.html`, `tracker/templates/admin/user_delete.html`
- Modify: `tracker/templates/admin/user_access.html`, `tracker/admin/users.py` (`access` and `delete` pass `deletion`)
- Modify: `tracker/static/users.js` (a second IIFE at the end; the first returns early when there is no reset dialog)
- Modify: `tracker/static/tracker.css` (only if the existing `list-dialog` classes do not cover the two columns)
- Test: `tests/test_user_delete.py`, `tests/test_users_browser.py`

**Interfaces:**
- Consumes `deletion_summary` and `DeletionSummary` (Task 4).
- Produces this markup contract for the script:
  - a link `a[data-delete-person]` (`href` is the delete page) opens `dialog#delete-dialog`;
  - the input `[data-delete-confirm]` carries `data-email`;
  - the button `[data-delete-submit]` starts `disabled` and becomes enabled when the trimmed, lower-cased input equals `data-email`;
  - `[data-delete-close]` closes the dialog.

The summary partial shows:
- **Removed:** counts of teams, region access, tracker roles, permission sets, "Lead of N tracker(s)", "Report emails: N tracker(s)" and "Sign-in".
- **Kept:** "N activity entries", "N report inputs" and "Their name in all history".
- Then the note copy.
- Use the app's plural filter for "tracker(s)".

The dialog and the page share the partial, the title and the email line, the confirm field and the buttons (Cancel, Delete). The page uses `title_crumb([(users, 'Users'), (access, 'Access')], 'Delete')`.

- [ ] **Step 1: Write the failing tests**

- `test_access_page_has_the_delete_dialog_for_a_disabled_person`:
  - it contains `id="delete-dialog"` and `"Delete Jordan Lee"`;
  - the email appears on the line beneath the title;
  - it contains `"Type jordan.lee@example.com to confirm"`, the note copy and `"Their name in all history"`;
  - the counts are present;
  - there is no dialog for an active person.
- `test_delete_page_works_without_javascript`: GET shows the same content and a form posting to the same URL.
- Browser, `test_delete_dialog_unlocks_only_for_the_matching_email`:
  1. open the Access page and click Delete: the dialog is open and `[data-delete-submit]` is disabled;
  2. type `jordan.lee@exam`: still disabled;
  3. type the whole email in mixed case with spaces: enabled;
  4. submit: the Users page shows the flash, and the person is not in the list.

- [ ] **Step 2: Run them and see them fail**

- [ ] **Step 3: Build the templates and the script**

- Build the partials and the page.
- Include the dialog on the Access page when `actions.delete`, with a danger "Delete" button in the action list.
- Add the second IIFE to `users.js`.
- The strict CSP forbids inline scripts and handlers.

- [ ] **Step 4: Run the tests**

Run: `run-tests.sh tests/test_user_delete.py tests/test_users_browser.py -v`. Expected: PASS, in light and dark themes, with no horizontal overflow at 390 px.

- [ ] **Step 5: Commit**

`feat: the delete dialog lists what goes and what stays and asks for the email`

---

### Task 6: Deleted people on the Users list and their Access page

**Files:**
- Modify: `tracker/admin/users.py` (`STATUS_FILTERS`, `_filtered_users`, `users`, `access`)
- Modify: `tracker/templates/admin/user_access.html`, and `tracker/templates/admin/users.html` if the badge needs a class
- Test: `tests/test_user_delete.py`

**Interfaces:**
- Consumes `status == "deleted"` (Task 1) and the `user_deleted` entries (Task 4).
- Produces:
  - `STATUS_FILTERS["deleted"] = "Deleted"`;
  - `_filtered_users` adds `User.status != "deleted"` unless the status filter is `deleted`;
  - `users()` leaves deleted people out of `everyone` (the total, pending and actions);
  - `access()` passes `deleted_note: tuple[datetime, str | None] | None`, the time and the performer's name from the latest `user_deleted` entry for the person.

- [ ] **Step 1: Write the failing tests**

- `test_users_list_hides_deleted_people_and_the_filter_shows_them`:
  - the default list and the count pill leave the person out;
  - `?status=deleted` lists them with their email and a "Deleted" badge, and offers no action except Access.
- `test_access_page_of_a_deleted_person`:
  - it shows the "Deleted" badge and `"Deleted on 13 Nov 2026 by Ann Admin."` (the date in `%d %b %Y`, as on Activity);
  - it has no action buttons;
  - it does not show the "not active" note meant for disabled accounts.

- [ ] **Step 2: Run them and see them fail**

- [ ] **Step 3: Implement the filter, the count and the Access page note**

- [ ] **Step 4: Run the tests**

Run: `run-tests.sh tests/test_user_delete.py tests/test_users_admin.py tests/test_users_browser.py -v`. Expected: PASS.

- [ ] **Step 5: Commit**

`feat: deleted people sit under a Deleted filter on Users, and their Access page says when and by whom`

---

### Task 7: Activity page: emails beside names

**Files:**
- Modify: `tracker/activity/views.py` (the query, the entries, `people`)
- Modify: `tracker/templates/activity/index.html`
- Test: `tests/test_activity.py`

**Interfaces:**
- Each entry dict gains `actor_email`, `actor_deleted: bool`, `affected_email` and `affected_deleted: bool`.
- `people` becomes `list[tuple[int, str]]` of `(id, label)`, where the label is `f"{full_name} ({email})"` with `" – deleted"` added for deleted people. It is ordered by name, then email.

- [ ] **Step 1: Write the failing tests**

- `test_entries_show_the_email_under_each_name`:
  - two active people named "Jordan Lee" with different emails each have one entry;
  - both emails appear in the Performed by and User affected cells, inside `member-email` elements.
- `test_a_deleted_person_shows_a_deleted_badge_and_stays_in_the_filter`: the filter option reads `"Jordan Lee (jordan.lee@example.com) – deleted"`.
- `test_filtering_by_a_new_account_with_a_reused_email_shows_only_its_entries`.
- `test_entries_without_a_person_show_a_dash`: an entry with `user_id=None` renders "–".

- [ ] **Step 2: Run them and see them fail**

- [ ] **Step 3: Implement the changes**

- Select `actor.email`, `actor.status`, `affected.email` and `affected.status`.
- Render the name, then the email in `<span class="member-email">` on its own line, then a muted "Deleted" badge when deleted.
- Build the people labels.

- [ ] **Step 4: Run the tests**

Run: `run-tests.sh tests/test_activity.py tests/test_activity_labels.py -v`. Expected: PASS.

- [ ] **Step 5: Commit**

`feat: Activity shows each person's email beside their name`

---

## Finish

- [ ] Run `ruff check .` and `ruff format --check .` in the worktree.
- [ ] Run the full suite: `run-tests.sh -n 6`, with live progress through a background Bash and a Monitor. Expected: every test passes, apart from the known skips.
- [ ] Take screenshots in dark mode at 1440 px, using a temporary `tests/test_zz_shot.py` (then delete it):
  - the Access page of a disabled person, with the dialog open;
  - the Users list under the Deleted filter;
  - the Activity page.
- [ ] Push with `git.exe push` from the main folder, and open the PR with `gh.exe pr create --body-file -`. The body ends with "🤖 Generated with [Claude Code](https://claude.com/claude-code)".
