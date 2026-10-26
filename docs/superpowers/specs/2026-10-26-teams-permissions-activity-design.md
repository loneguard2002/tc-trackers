# Teams, permission sets and activity log: design

Date: 2026-10-26
Status: draft for approval
Backlog: item 1 in `docs/backlog.md`
Builds on: `docs/superpowers/specs/2026-10-20-generic-progress-tracker-design.md` (section 5.2, Users and access)

## 1. Intent

Today an administrator gives each person a role on each tracker, one tracker at a time, and only administrators can create trackers, manage users or change settings. As trackers multiply (licensing, patching, vulnerabilities and so on), that does not scale: a manager responsible for several teams must be added to every tracker separately, and every small administrative job waits for an administrator.

The capacity app (`Documents\GitHub\capacity`) solves the same problem with teams, scoped access, editable permission sets and an audit log with a viewing screen. This work brings that model into the tracker, adapted to it:

- **Teams of people**, which can sit inside other teams. A person's role in a team applies to that team's trackers and to the trackers of every team below it, so one person can see several teams' trackers.
- **Permission sets**: named bundles of elevated (administrator-type) functions that administrators give to teams or to individual people.
- **An activity log as in the capacity app**: before and after values, the user affected, an Activity screen and an optional retention period.

### What success looks like

- An administrator sets up a team tree (for example Infrastructure, containing Windows and Network), puts each tracker in a team and adds people with a role. The head of Infrastructure sees every tracker below without being added to each one; a Windows team member does not see Network's trackers.
- A PMO team can be given "view all trackers" and "create trackers" without anyone in it being an administrator.
- Every access change can be traced on the Activity screen: who did it, to whom, when, and the value before and after.
- On upgrade, every existing user keeps exactly the access they have today.

## 2. Goals, non-goals and anti-goals

### Goals

1. Teams with an optional parent team, nested to any depth, never in a cycle.
2. Team membership with a role (viewer, editor or owner) that applies to the trackers of the team and of every team below it.
3. Each tracker belongs to at most one team. A tracker with no team behaves as today.
4. Per-tracker roles remain for exceptions (for example one person from outside the team). A person's role on a tracker is the highest they hold by any route.
5. Permission sets: named, created and edited by administrators from a fixed list of permissions, and held by teams or by individual users. Sets held by a team apply to that team's own members only.
6. User management features from the capacity app: create local users and reset local passwords from the Users screen, keep Entra display names in step at each sign-in, and show each user's effective access.
7. An activity log as in the capacity app: before and after values, the user affected, an Activity screen with filters, and an optional retention period.
8. Progress entries can be corrected in place (section 7.1), instead of being deleted and recorded again.

### Non-goals

- Groups of trackers that are separate from teams (the capacity app's team groups). The owner dropped this.
- Creating or filling teams automatically from Microsoft Entra security groups. This is a possible later backlog item.
- Permissions limited to part of the team tree (for example "create trackers only in my own team"). Permissions apply across the whole application, as in the capacity app.
- The capacity app's "approve" right. The tracker has no approval workflow.
- Roles other than viewer, editor and owner.
- Deleting users. Users are disabled, as today, so the audit trail keeps its references.

### Anti-goals (would make this a failure even if it works)

- Anyone gaining access or elevated rights without an activity log entry.
- Existing users gaining or losing access to existing trackers because of the upgrade.
- Any route by which a non-administrator can make themselves an administrator, edit permission sets, or take over an administrator's account or the account of someone with elevated rights.
- Locking out every administrator.
- Revealing that a tracker exists to someone who cannot see it. The existing rule (no access gives 404) stays. The only exception is deliberate and narrow: holders of `manage_teams` and `view_activity` see tracker names on the administration screens their job needs (section 6.2), but not the trackers' contents.

## 3. Constraints

- The existing stack and conventions: Flask, SQLAlchemy 2.x, Postgres through `DATABASE_URL`, one new Alembic migration (`0003`), Jinja templates (StrictUndefined in tests), the strict Content Security Policy (no inline scripts or styles; behaviour in `tracker/static/*.js`, styles in `tracker.css`), CSRF tokens on every POST, British English in the interface.
- Plain Postgres only. The recursive team lookup uses standard `WITH RECURSIVE` SQL; no Supabase-specific features.
- Sign-in stays as it is: local accounts and Microsoft Entra single sign-on, Entra users matched on their Microsoft account (`sso_subject`), no takeover of a password account by an Entra sign-in, and new Entra users pending until approved. This is stricter than the capacity app, which matches Entra users by email address, and it is kept deliberately.
- Activity log entries never contain passwords, password hashes, tokens or SMTP secrets.
- No personal data beyond users' names and email addresses (unchanged).
- How long audit records must be kept is for Tradition's regional Compliance team to confirm. Nothing in this document is a regulatory view.

## 4. Approaches considered

**A. Work out access from the team tree on each request (chosen by the owner).** Each team records its parent; each tracker records its team. To answer "what can this person see?", one Postgres query takes the person's teams, expands them to every team below, and finds those teams' trackers. With tens of teams this costs well under a millisecond, and the answer is always current because nothing is stored twice.

**B. Store a ready-made table of every team below every team (a closure table).** Lookups are slightly faster, but every team move must rebuild the table, and a bug there gives people the wrong access. The speed only matters with thousands of teams. Rejected.

**C. Copy the capacity app's `user_access` grant table as it is.** Each grant has a scope (everything, a team or a tracker) and view, edit and approve flags. Closest to the capacity app, but it mixes "who is in which team" with "who has which grant", where the owner's design keeps them apart, and it brings an approve right the tracker has no use for. Rejected.

## 5. What the application holds (migration 0003)

All additions; no existing column changes meaning and no existing row changes, apart from the audit backfill described below.

- **`teams`**: `id`; `name` (unique, compared case-insensitively); `description` (optional); `parent_id` (references `teams`, empty for a top-level team, `ON DELETE RESTRICT`); `created_at`. Cycles are prevented in application code (section 6.4).
- **`team_members`**: `team_id`, `user_id` (together the primary key; both cascade on delete), `role` (`viewer`, `editor` or `owner`, enforced by a check constraint as in `tracker_roles`).
- **`trackers.team_id`**: optional, references `teams`, `ON DELETE RESTRICT`.
- **`permission_sets`**: `id`, `name` (unique, case-insensitive), `description` (optional), `created_at`.
- **`permission_set_permissions`**: `set_id` (cascade on delete), `permission` (text), together the primary key. Permission names are validated in application code against the fixed list in section 6.2; unknown names in the database are ignored, so adding a permission later needs no migration.
- **`permission_set_holders`**: `id`, `set_id` (cascade), `team_id` (optional, cascade), `user_id` (optional, cascade). A check constraint requires exactly one of `team_id` and `user_id`; a set is held at most once by the same team or user (two partial unique indexes).
- **`audit_log.target_user_id`**: optional, references `users` (`ON DELETE SET NULL`). This is the "User affected" column. Add indexes on `audit_log (at)`, `(target_user_id)` and `(action)` for the Activity screen. Changes record `detail` as `{"before": …, "after": …}`; other events keep a plain `detail` object.
- **Backfill**: existing audit rows whose `entity` is `user` get `target_user_id` set from `entity_id` when that user exists.
- **`app_settings` key `audit_retention_days`**: absent means keep entries indefinitely.

## 6. Access rules

### 6.1 A person's role on a tracker

A user who is not active (pending or disabled) has no access, as today. For an active user, the role on a tracker is the highest of:

1. **Administrator**: owner on every tracker (unchanged).
2. **Direct role**: their row in `tracker_roles` for that tracker (unchanged).
3. **Team role**: their membership role in the tracker's team or in any team above it. With several memberships on the path, the highest wins.
4. **View all trackers** permission (section 6.2): viewer on every tracker.

No route means no access, and the tracker's pages answer 404 as today. A tracker with no team is reached only through routes 1, 2 and 4, which is exactly today's behaviour.

`user_role` and `visible_trackers` in `tracker/auth/roles.py` are rewritten to apply these rules, and every check goes through them. `visible_trackers` remains a single query. The rule `require_tracker_role` already applies (404 for a missing tracker, a missing role or too low a role) is unchanged.

### 6.2 Elevated permissions

The fixed list. Each permission gives access to the screens and actions named; nothing else changes.

| Permission | Lets the holder |
|---|---|
| `manage_users` | Approve pending Entra users; create local users; reset local users' passwords; disable and re-enable users. |
| `manage_teams` | Create, rename, move and delete teams; add and remove members and change their roles; put trackers in teams and move them between teams; manage direct per-tracker roles (the tracker Access screen). |
| `create_trackers` | Create trackers, in any team or in none. |
| `import_workbooks` | Use the Import workbook screen and the import confirmation, which creates a tracker. |
| `manage_email_settings` | Change the application's email (SMTP) settings. |
| `view_all_trackers` | Viewer on every tracker. |
| `view_activity` | Read the Activity screen. |

**Administrators only**, never delegable: the administrator flag; creating, editing and deleting permission sets and choosing who holds them; the audit retention setting.

**Who holds a permission:** an administrator holds every permission. Anyone else holds a permission when a set containing it is held by them directly, or by a team of which they are a direct member (any role). A set held by a team does not apply to members of the teams below it, nor to members of the teams above it.

**A creator becomes owner:** whoever creates a tracker, by hand or by import, is given a direct owner role on it (an administrator needs none and gets none), so they can configure it. Owners already change settings, groups, recipients, templates and schedules and send reports (unchanged). Archiving stays administrator-only, as today.

**Names on administration screens:** putting trackers in teams and reading the log cannot be done blind. Holders of `manage_teams` therefore see the names of every team and tracker on the Teams screens, the team field and the tracker Access screen, and can open the Access screen of any tracker, as administrators can today. Holders of `view_activity` see every entry, including tracker names. Neither permission opens a tracker's pages, entries or reports; those still follow section 6.1.

### 6.3 Guards against misuse

- **No self-promotion.** A holder of `manage_teams` who is not an administrator cannot make any change that would raise their own role on any tracker. This covers changing their own memberships or direct roles, moving a team they belong to, and moving a tracker into a team they belong to. The check compares the actor's tracker roles before and after the change inside the same transaction and refuses the change, with a message, if any role would rise or any tracker would become visible to them. Granting access to someone else at their request is possible and is logged; it is not prevented.
- **No account takeover.** Holders of `manage_users` who are not administrators cannot reset the password of, disable or re-enable an elevated user. An elevated user is anyone with the administrator flag, or anyone who holds any permission set directly or through any team membership, whatever the account's status (so a disabled former administrator cannot be re-enabled this way). They also cannot act on their own account.
- **Team places at approval.** The optional team and role offered when approving an Entra user appear, and are accepted, only for administrators and `manage_teams` holders, and the self-promotion rule applies.
- **The last administrator stays.** The application refuses to disable, or remove the administrator flag from, the last active administrator. This adds to the existing rule that administrators cannot disable themselves or remove their own flag.
- **Pending and disabled users** keep any memberships and holdings in the database, but those give nothing until the user is active.

### 6.4 Team tree rules

- A team cannot be moved under itself or under any team below it. The move form offers only valid parents, and the server checks again.
- A team can be deleted only when it has no teams below it and no trackers, archived trackers included. Deleting it removes its memberships and the permission sets it holds, and each removal is logged.
- Archived trackers keep their team and give read-only access through it, as direct roles do today. Unlike role edits, a team change is allowed on an archived tracker, so a team can be emptied and deleted.
- Moving a team or a tracker changes who can see trackers, so both take a confirmation step naming the old and the new position.

## 7. Screens

The sidebar's Administration section shows each link only to those who may use it:

| Link | Shown to |
|---|---|
| Users | Administrators and `manage_users` holders |
| Teams | Administrators and `manage_teams` holders |
| Permission sets | Administrators |
| Import workbook | Administrators and `import_workbooks` holders |
| Email settings | Administrators and `manage_email_settings` holders |
| Activity | Administrators and `view_activity` holders |

The Administration heading appears when at least one link does. The home page's "New tracker" button appears for administrators and `create_trackers` holders.

- **Teams**: the tree as an indented list, with each team's member and tracker counts, and a form to create a team (name, description, parent). A team's own page allows renaming, moving (with confirmation) and deleting (only when allowed). It also has a members table (add an active user with a role, change a role, remove) and lists the trackers in the team.
- **Tracker settings and the new tracker form**: a Team field. Only administrators and `manage_teams` holders can change it on an existing tracker, with confirmation. Whoever creates a tracker chooses its team, or none.
- **Tracker Access** (the existing roles screen): open to administrators and `manage_teams` holders. It keeps direct roles and adds a read-only list, "Access through teams", showing each person who reaches the tracker through a team, the team path (for example "Infrastructure › Windows") and their role.
- **Permission sets** (administrators): a grid like the capacity app's role permissions screen, with sets as columns and permissions as rows, saved in one action. It also allows creating, renaming and deleting sets, and adding and removing holders (teams and users) for each set.
- **Users**: the existing screen, including its existing "create local user" form (`POST /admin/users`), opens to `manage_users` holders within the guards of section 6.3. New: "Reset password" for local users (new password typed by the person resetting it, checked against the existing password rules; nothing is emailed; today this exists only as the `reset-password` command) and "Re-enable" for disabled users. Each user's row shows their teams and their permission sets, with a link to Effective access. Approving a pending Entra user can optionally add them to one team with a role in the same step (section 6.3).
- **Import confirmation**: gains the same Team field as the new tracker form.
- **Effective access** (one user, shown to administrators and `manage_users` holders): every tracker the user can see with their role and every route that gives it (administrator, direct role, team path and role, view all trackers), then every permission they hold and where it comes from.
- **Activity**: newest first, 50 entries a page, with columns for time, performed by, user affected, action (as a readable label), tracker and detail (shown as before → after where there is one). It can be filtered by person (as the one who acted or the one affected), by action and by date range. At the foot, administrators see the retention setting.
- **Home page**: each tracker card shows its team's name when it has one.
- **Entra display name**: at each Entra sign-in, if the name from Microsoft differs from the stored name, the stored name is updated and the change is logged.

### 7.1 Correcting a progress entry

Today a wrong entry must be deleted and recorded again (the entries page says so). The owner does not want that. Each row on the entries page gains an **Edit** action:

- **Who:** anyone who can record entries on the tracker, that is editors and owners by any route (section 6.1).
- **What can change:** the date, the location (the tracker's grouping label), the quantity and the note.
- **Checks:** the same as for a new entry (`check_entry_date` and `parse_quantity` in `tracker/entries/forms.py`). The week ending is recalculated from the new date. An entry may keep a location that has been retired since it was recorded; moving it to another location requires one that is not retired.
- **Archived trackers:** edits are refused, as adding and deleting are today.
- **Activity log:** one `entry_updated` entry with the changed fields before and after (for example quantity 12 → 15), committed with the change.
- **Delete stays** for entries recorded by mistake. The note "To correct an entry, delete it and record it again" is replaced by the Edit action.

## 8. Activity log

### 8.1 What is logged

Existing actions stay as they are; `target_user_id` is filled in wherever a user is affected. New and extended actions:

- **Sign-in**: `login` and `sso_login` (existing); `login_failed`, with the email address entered (cut to 254 characters) and the reason (unknown account, wrong password, not active), never the password. Attempts refused by the existing sign-in throttle are not logged one by one, so repeated attempts cannot flood the table; the throttle that blocks them is the record.
- **Users**: `user_created` (with source: local, Entra or command line), `user_approved`, `user_disabled`, `user_enabled`, `password_reset` (no password or hash), `user_admin_changed` (before and after), `user_name_synced` (before and after).
- **Teams**: `team_created`, `team_renamed`, `team_moved` (parent before and after), `team_deleted`; `team_member_added`, `team_member_role_changed` (before and after), `team_member_removed`.
- **Trackers**: `tracker_team_changed` (team before and after); `role_set` and `role_removed` (existing, now with `target_user_id`).
- **Progress entries**: `entry_created` and `entry_deleted` (existing); `entry_updated` (changed fields before and after).
- **Permission sets**: `permission_set_created`, `permission_set_renamed`, `permission_set_deleted`, `permission_set_permissions_changed` (permission lists before and after), `permission_set_holder_added`, `permission_set_holder_removed`.
- **Settings and housekeeping**: `smtp_settings_updated` (existing; names of changed keys only), `audit_retention_changed` (before and after), `audit_pruned` (number of entries removed and the cutoff date).
- **Email**: the existing report send actions (`report_sent`, `report_send_queued`, `report_send_failed`, `report_test_sent`) stay as they are.

Every change and its log entry are committed in the same database transaction, so a change is never saved without its entry.

Existing entries are not rewritten. Older actions store `detail` in their own shapes (for example `role_set` as `{"role": [before, after]}` and `user_admin_changed` as `{"is_admin": …}`); the Activity screen shows those shapes as before → after where it can, and otherwise lists the stored values.

### 8.2 Retention

The default is to keep entries indefinitely. An administrator may set a retention period on the Activity screen, from 90 to 3,650 days. When it is set, the scheduler worker deletes older entries once a day and records an `audit_pruned` entry. Clearing the setting returns to keeping entries indefinitely. Entries cannot be edited from the application.

## 9. Upgrade

- Migration 0003 adds the tables, columns, indexes and the audit backfill. It changes no other existing data, so every user keeps exactly today's access: existing trackers have no team, and no permission sets exist until an administrator creates them.
- `alembic check` must report no differences after the migration.
- The `create-admin` and `reset-password` commands keep working as today.

## 10. Testing

Database tests (run against Postgres, as for the rest of the suite):

- **Roles:**
  - the role through each route on its own;
  - the highest role winning when routes combine;
  - access flowing down through several levels, and not sideways or upwards;
  - a tracker with no team;
  - pending and disabled users;
  - 404 for trackers that cannot be seen.
- **Permissions:**
  - held directly;
  - held through a team the user belongs to;
  - not held through teams below or above;
  - each screen and action refused without the permission.
- **Guards:**
  - every self-change refused for `manage_teams`, including the indirect routes (moving a team they belong to, moving a tracker into their team, the team place at approval);
  - `manage_users` refused on administrators, elevated users and the holder's own account;
  - the last active administrator kept;
  - non-administrators refused on permission sets and retention.
- **Team tree:**
  - cycle prevention on move, on the form and on the server;
  - the delete guards.
- **Activity:**
  - each listed action writes one entry with the actor, the user affected and before and after where relevant;
  - no secrets in any entry;
  - the filters and paging;
  - retention pruning and its own entry.
- **Upgrade:** the migration on a copy of today's schema leaves every existing user's visible trackers unchanged.
- **Entry edits:**
  - editors and owners can edit and viewers cannot;
  - each field change is checked as for a new entry, and the week ending is recalculated;
  - a retired location can be kept but not chosen;
  - edits are refused on archived trackers;
  - one `entry_updated` entry records the before and after values;
  - the report figures follow the corrected entry.

Tests that need no database:

- sidebar links for each combination of permissions;
- the existing template scan for the security policy, extended to the new templates.

## 11. Decided by the owner

- "Groups" means teams of people. Teams can sit inside teams, so one person can see several teams' trackers.
- Each tracker belongs to one team. Access flows down the tree, never up or sideways. Teams can nest to any depth.
- Team membership carries a role (viewer, editor or owner).
- Administrators manage teams and membership, together with anyone given that permission. Per-tracker roles stay for exceptions.
- Elevated functions work like the capacity app: named permission sets that can be given to a team, and to individual people.
- Groups of trackers are dropped.
- Audit logging follows the capacity app. Entries are kept indefinitely by default, and the retention period is to be confirmed with Compliance.
- Approach A (section 4).
- Progress entries are corrected in place, not deleted and recorded again (section 7.1).

## 12. Calls made by Claude (please check)

1. The fixed permission list in section 6.2, including `view_activity` as a separate permission so an auditor or the PMO can read the log without being an administrator.
2. Permission sets can also be held by individual users, not only by teams, as in the capacity app's per-user grants.
3. A team's permission sets apply to its direct members only (not to teams below or above), so elevated rights are always given on purpose.
4. The misuse guards in section 6.3: no self-changes for `manage_teams`, and `manage_users` holders cannot act on administrators or elevated users.
5. Whoever creates a tracker becomes its owner through a direct role.
6. Administrators type the initial and reset passwords for local users; nothing is emailed, which matches the capacity app.
7. Approving an Entra user can optionally add them to a team in the same step, which replaces the capacity app's single default role for new single sign-on users.
8. A retention period, when set, must be between 90 and 3,650 days. The capacity app allows a minimum of 7, but the higher floor guards against an accidental wipe.
9. Failed sign-ins are logged with the email address entered and the reason.
10. Team and permission set names are unique regardless of capitals.
11. Holders of `manage_teams` and `view_activity` see the names of every tracker on the screens their job needs, but not the trackers' contents (sections 2 and 6.2).
12. The self-promotion guard compares the actor's own tracker roles before and after any `manage_teams` change, rather than listing forbidden actions one by one, so indirect routes (moving teams or trackers) are covered too.
13. Archiving stays administrator-only; archived trackers count for access read-only, block team deletion, and can still change team.
14. Attempts refused by the sign-in throttle are not logged individually.
15. Old audit entries keep their stored shapes, and the Activity screen reads both.
16. An edited entry may keep a location that has since been retired, so old figures can still be corrected; Delete stays for entries recorded by mistake.

## 13. Left to the builder

- Page layouts within the existing style (cards, tables and the Everton-style sidebar), and the labels shown for each action.
- The exact shape of the recursive query and of the indexes, within section 5.
- How the before and after values are laid out on the Activity screen.
- Splitting the work into tasks, and the order of delivery.
