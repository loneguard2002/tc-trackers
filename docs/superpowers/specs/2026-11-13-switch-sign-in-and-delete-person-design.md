# Switching a person to Microsoft sign-in, and deleting a person

Date: 2026-11-13. Status: Approved by the owner on 2026-11-13; built on branch feat/user-delete-sso-switch.

## Why

A person added with a password (a "local" account) cannot later sign in with Microsoft using the same email address.
`_resolve_user` in `tracker/auth/sso.py` refuses with "This account signs in with a password. Ask an administrator
for help." The refusal is deliberate: the teams and permissions design
(`docs/superpowers/specs/2026-10-26-teams-permissions-activity-design.md`, line 59) rules out any takeover of a password
account by a Microsoft sign-in. Administrators have no way to move such a person to Microsoft sign-in.

Administrators also have no way to remove an account. Disable is the only option, so accounts created by mistake, and
pending accounts created by a mistaken Microsoft sign-in, stay in the list for ever.

Separately, the Activity page names people by full name only. Two people with the same name cannot be told apart, and
a deleted person makes this more likely to matter.

## Goals

1. **Switch to Microsoft sign-in:** a deliberate action that turns a password account into a Microsoft account. The
   person keeps their teams, region access, tracker roles, permission sets and history.
2. **Delete:** remove a person for good. Their access, sign-in and report emails go; the history keeps their name
   and email.
3. **Activity page:** show each person's email beside their name, so people with the same name can be told apart.

## Non-goals

- Copying one person's access to another account.
- Two accounts with the same email address.
- Switching from Microsoft sign-in back to a password.
- Viewing the app as another person.
- Linking a password account automatically when someone signs in with Microsoft. That stays refused.
- Undoing a delete in the app.
- Purging deleted people's records after a retention period (see "Open point").

## Anti-goals (failure even if it works)

- A Microsoft sign-in takes over a password account without an explicit action by a person allowed to switch it.
- History loses who did something, or who was affected.
- Adding the same email again gives the new account the deleted person's history or access.
- A person is deleted by one slip of the mouse.

## Approaches considered

| Problem | Option | Outcome |
|---|---|---|
| Password account cannot use Microsoft sign-in | Allow two accounts per email (different ids) | Rejected: the email is unique in the database and both sign-in paths look people up by email; the person would appear twice with access split between the accounts. |
| | Link automatically by email at Microsoft sign-in | Rejected: reverses the deliberate "no takeover" rule. |
| | Copy access to the new Microsoft account, then delete the old one | Rejected: largest build, every copy must pass the granting checks, and history splits across two people. |
| | **An explicit "Switch to Microsoft sign-in" action** | **Chosen:** small, keeps one account, and the existing code already links a Microsoft account with no link yet to a Microsoft account by email. |
| Deleting a person | Delete the row | Rejected: foreign keys set the person's id to NULL on activity entries, report inputs, completion entries, report sends and tracker leads, so history loses the name. |
| | Delete the row and keep a separate table of deleted people | Rejected: the links are already blanked at delete, so every history record and page would need new linking. |
| | **Keep the row and mark it Deleted** | **Chosen (the owner's preference):** every existing history link keeps working unchanged. |
| Confirming a delete | Inline confirm box, as Delete team | Not chosen. |
| | Separate confirmation page | Not chosen (kept only as the no-JavaScript fallback). |
| | **Dialog listing what goes and what stays, with the email typed to confirm** | **Chosen by the owner** (mockup version 4). |

## Decided behaviour

### Switch to Microsoft sign-in

- **Who:** administrators, and holders of Manage users. A Manage users holder is refused on their own account and on an
  elevated account, through the existing `account_refusal` in `tracker/auth/accounts.py`, exactly as for Reset password.
- **When offered:** the account signs in with a password (`auth_source == "local"`) and single sign-on is configured
  (`SSO_ENABLED`). Status active or disabled. *(Builder's note: local accounts are never pending.)*
- **Emergency administrator (the owner's decision):** the app always keeps at least one active administrator who signs
  in with a password, so a failure of Microsoft sign-in (a mismatched email, an expired client secret) never locks
  every administrator out. The switch is refused when the person is the last active administrator with a password,
  with the message "Keep at least one administrator who signs in with a password, in case Microsoft sign-in stops
  working." A new guard beside `last_admin_refusal` in `tracker/auth/accounts.py`, locking the same rows the same way.
  It applies to administrators as well as to Manage users holders. *Our call:* Disable and Remove administrator apply
  the same guard while single sign-on is configured, so the emergency account cannot be removed by another route.
- **Where:** the person's Access page, in its action list. *Our call:* not on the Users list row, which keeps its four
  fixed icon slots.
- **Confirmation:** *our call:* an inline confirm box, as Delete team uses (`data-inline-confirm`), naming the person
  and their email: "Switch Jordan Lee (jordan.lee@example.com) to Microsoft sign-in? Their password stops working now.
  They keep all their access, and sign in with Microsoft using this email address from now on."
- **Effect:** `auth_source = "sso"`, `password_hash = NULL`; `sso_subject` stays NULL. On the person's next Microsoft
  sign-in, `_resolve_user` finds the account by email and links it (existing path, records `sso_linked`). From then on
  the Entra name replaces the app name, as for every Microsoft account.
- **Sessions:** a session already signed in is not ended. This matches Reset password today (the session holds only the
  user id).
- **Activity log:** a new action `sign_in_switched`, label "Sign-in switched to Microsoft", entity `user`,
  `target_user_id` the person, detail `change("local", "sso")`.
- **Known limit:** if the person's Microsoft email differs from the app email, their Microsoft sign-in creates a new
  pending account instead of linking. The confirm text tells the administrator which email must match.

### Delete

- **Who:** administrators only.
- **Which accounts:** status `disabled` or `pending` only, so a delete is always a second, deliberate step. Never the
  administrator's own account. *Our call:* also run `last_admin_refusal` as a safeguard, although a disabled or pending
  account can never be the last active administrator.
- **Where:** the person's Access page, as a danger button "Delete" in the action list.
- **Confirmation dialog** (agreed mockup, version 4):
  - Title "Delete [full name]" with the email on the line beneath (two people may share a name).
  - **Removed**, with counts: teams, region access, tracker roles, permission sets held directly, trackers led (the
    lead is cleared), report emails (the number of trackers whose recipient list holds the person's email), sign-in.
  - **Kept**, with counts: activity entries naming the person (as performer or as the person affected), report inputs,
    and "Their name in all history".
  - The note: "The email address becomes free, so the person can be added again as a new account. This cannot be
    undone."
  - A field "Type [email] to confirm". The **Delete** button (text "Delete", not the name) stays disabled until the
    typed text matches, ignoring case and surrounding spaces. Cancel closes the dialog.
  - The server checks the typed email again and refuses a mismatch; the browser check is a convenience only.
  - *Our call:* without JavaScript, the Delete button is a link to a confirmation page at
    `/admin/users/<id>/delete` with the same content; the form posts to the same URL. This mirrors Reset password.
  - The counts are shown as they stand when the dialog opens; the delete works on the state at the moment it runs.
- **Effect, in one transaction**, with the person's row locked (`FOR NO KEY UPDATE`) and the status checked again.
  That lock still serialises every change of the person's status, and it lets through the `KEY SHARE` lock that a
  report retry takes on the person who queued the send, through the foreign key of the activity entry it writes; with
  `FOR UPDATE`, that retry and the delete could deadlock. Re-enable and Approve take the same lock; Disable locks the
  administrators first and then reads the person again under it, so none of them can write over a delete:
  - remove their `team_members`, `region_grants`, `tracker_roles` and `permission_set_holders` (user) rows;
  - set `trackers.lead_user_id` to NULL wherever they lead;
  - **(the owner's decision)** remove the person's email from every tracker's report recipient list (`recipients` rows
    whose email matches, ignoring case). Recipients are typed-in addresses with no link to accounts, so the match is by
    email only;
  - *our call:* also remove the email from report sends still `queued` for a retry, so no report reaches the person
    after the delete; a queued send left with no recipients is marked `failed` with the error "No recipients left";
  - set `is_admin = false`, `password_hash = NULL`, `sso_subject = NULL`, `status = "deleted"`;
  - keep `full_name` and `email` on the row, for history and for the Deleted filter.
- **Activity log:** *our call, following Delete team (`delete_team` in `tracker/teams/views.py`; "each removal is
  logged" in the 2026-10-26 design):*
  - one entry per removal, using the existing actions where they exist (`team_member_removed`,
    `permission_set_holder_removed`, `region_access_removed`, `role_removed` and `recipient_removed` with `tracker_id`
    set), and a lead change
    per tracker led, also with `tracker_id` set (the builder picks the action, reusing the tracker settings change
    entry if one records the lead);
  - then a summary entry, new action `user_deleted`, label "User deleted", `target_user_id` the person, detail holding
    the name, the email and the counts removed, with no tracker names.
  - Because tracker-specific entries carry `tracker_id`, the existing `hidden()` rule on the Activity page hides their
    detail from viewers who cannot open that tracker. The summary names no tracker, so nothing leaks through it.
- **After a delete:**
  - The email is free: adding a person with it creates a new account with a new id and no history.
  - A deleted account cannot sign in. The password is gone, the Microsoft link is gone, password sign-in skips
    deleted rows, and `current_user()` already treats any status but active as signed out.
  - Signing in again with the same Microsoft account creates a new pending account (the old link was cleared). To stop
    a person from asking again, an administrator disables them instead of deleting them.

### Where deleted people appear

- **Users list:** hidden unless the status filter is "Deleted" (a new value in `STATUS_FILTERS`). The count in the
  title leaves them out. Under the filter, each row shows name and email, a "Deleted" badge, and only the Access
  action.
- **Access page:** *our call:* it still opens for a deleted person, shows the Deleted badge and no actions, and says
  "Deleted on [date] by [name]." taken from the `user_deleted` entry.
- **Pickers** (team members, permission set holders, tracker roles, region access, tracker lead): these already offer
  active people only. The builder confirms that every `select(User)` used for choosing people does so.
- **History** (activity log, report inputs, completion entries): unchanged, because the row remains.

### Activity page: emails beside names

- *Our call:* the **Performed by** and **User affected** cells show the name with the email on a second, muted line, as
  the Users list does. No extra column, which keeps the table at six columns.
- A deleted person also shows a small "Deleted" badge in those cells.
- The person filter lists "Name (email)", with " – deleted" added for deleted people. Deleted people stay in the filter
  so their history can still be looked up.
- Entries with no person (system actions, or a performer removed by the old delete path) keep showing "–".

## Data model

- A new migration after the latest in `migrations/versions/`:
  - the `users.status` check constraint gains `'deleted'`;
  - the unique constraint on `users.email` is replaced by a partial unique index, unique where
    `status <> 'deleted'`, so deleted rows keep their email and the email can be used again.
- `sso_subject` stays unique; a delete clears it.
- Every lookup of a person by email must skip deleted rows:
  - password sign-in (`tracker/auth/__init__.py`);
  - `_resolve_user` (`tracker/auth/sso.py`);
  - the `create-admin`, `reset-password` and `import-workbook --owner` commands (`tracker/app.py`).
  `create_user` relies on the database refusing a duplicate, which the partial index still does for live accounts.

## Permissions documentation

- Update the teams and permissions design document so that Manage users also covers the switch, record that
  delete is administrator-only, and record the emergency administrator rule.

## Testing

Targeted tests while building, then the full suite (`pytest -n 6`) before hand-over. At least the following:

- **Switch:**
  - before the switch, a Microsoft sign-in with the same email is refused (the existing test);
  - after the switch, it links and signs in, with all access intact;
  - the password no longer works;
  - refused for a Manage users holder on their own or an elevated account;
  - refused, for anyone, on the last active administrator with a password; allowed when another remains;
  - Disable and Remove administrator refuse the last active administrator with a password while single sign-on is
    configured;
  - not offered and refused when single sign-on is not configured, or when the account already uses Microsoft;
  - the activity entry is recorded.
- **Delete:**
  - administrators only;
  - disabled or pending accounts only;
  - a mismatched typed email is refused by the server;
  - every access row is removed and leads are cleared;
  - the email leaves every recipient list (any letter case) and every queued send, each logged against its tracker;
  - a non-administrator Activity viewer cannot see removal details for trackers they cannot open;
  - history still names the person;
  - the email can be used again and gets a new id;
  - a deleted account cannot sign in by password, and a Microsoft sign-in creates a new pending account;
  - the Users list hides deleted people and the Deleted filter shows them;
  - the activity entry detail is complete;
  - the no-JavaScript page works.
- **Activity page:** emails show under names in both columns, the Deleted badge shows, and the filter lists
  "Name (email)".
- **Browser:** the dialog's Delete stays disabled until the email matches, then is enabled. Both themes.
- **Migration:** upgrades and downgrades, following the existing migration tests.

## Left to the builder

- Wording of flash messages, within the app's existing tone.
- How the counts are queried.
- Styling, using existing classes (`list-dialog`, `confirm-box`, `badge`, `member-email`).
- The migration file name and number.

## Open point (not blocking this build)

- Keeping a deleted person's name and email is personal data. The Data Protection Officer may want a retention period
  for deleted records. That would be a later piece of work.
