# Backlog

Work agreed but not yet scheduled. Each item needs a short spec before it is built.

## 1. Users, groups and permissions as in the capacity app

Requested 26 Oct 2026. Bring the capacity app's access model (`Documents\GitHub\capacity`, `capacity_app/auth.py` and the schema in `capacity_app/db.py`) into the tracker.

What the capacity app has:

- **Roles with editable permissions.** A `roles` table (system roles Admin, Manager and Viewer, plus custom roles) and a `role_permissions` matrix of named permissions, such as `manage_access`, `manage_team_groups` and `export_data`, managed in the application by anyone with `manage_role_permissions`.
- **Scoped access grants.** A `user_access` table that grants a user view, edit or approve rights at a scope: global, a group, or a single item (a region, location or team).
- **Groups.** `team_groups` and `team_group_members` bundle teams, so one grant covers every team in the group.
- **Sign-in.** Local accounts and Microsoft Entra single sign-on. A first Entra sign-in creates the user with a default role (`SSO_DEFAULT_ROLE`), pending approval.

What the tracker has today: an administrator flag, one role per tracker (owner, editor or viewer) in `tracker_roles`, and local plus Entra sign-in with administrator approval of new single sign-on users.

Scope to settle in the spec:

- Tracker groups (the equivalent of team groups) and grants at global, group and single-tracker scope.
- Whether the owner, editor and viewer roles map onto permission sets, and how existing `tracker_roles` rows migrate.
- An Access screen for roles, permissions and grants, with every change written to the audit log.
- The default role for a first Entra sign-in, and whether approval stays mandatory.

## 2. Deferred from the first release (ruling R30)

- A retried email can show newer figures than the PDF stored with the first attempt.
- Stored PDFs cannot be downloaded from the application.
- A double click on manual send sends the report twice.
- A Chromium failure during a manual send shows an error page instead of a message.
- The Render starter plan may run short of memory while Chromium renders a PDF.
- Package versions in `requirements.txt` are not pinned.
- The remaining minor review points are listed in the plan ledger (`.superpowers/sdd/2026-10-20-generic-progress-tracker/progress.md`).
