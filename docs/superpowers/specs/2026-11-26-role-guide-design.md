# What each role can do: a table in the app

Agreed with the owner on 26 Nov 2026. A small change.

## Why

People do not know what Viewer, Editor and Owner allow. The Access tab has three vague lines, and viewers and editors
never see even those. The owner wants a clear table in the app so everyone understands the roles.

## Goals

1. **One table, defined once** (rows below), shown the same everywhere:

   | | Viewer | Editor | Owner |
   |---|:-:|:-:|:-:|
   | Open the report and download it as PDF or PNG | ✓ | ✓ | ✓ |
   | Record, edit and delete entries; download entries | | ✓ | ✓ |
   | Write the weekly update; set a calendar reminder | | ✓ | ✓ |
   | Add and edit risks; set weekly targets | | ✓ | ✓ |
   | Set a location's status, planned date, ready figure and comment | | ✓ | ✓ |
   | Add locations; change a location's name, baseline and starting figure | | | ✓ |
   | Change the tracker's settings; archive it | | | ✓ |
   | Preview, test and send the report email | | | ✓ |

   ("location" follows the tracker's own label for its groups where the table is shown on a tracker to someone
   with a role on it; elsewhere it reads "group", the app's generic word, as the tracker's tabs do.) Under it:
   "Administrators can do everything on every tracker." "If you have a role from more than one place, the highest
   one counts." "People with Manage teams choose who has which role."
2. **Every tracker page** shows, beside its tabs, "Your role: Editor · What each role can do" (an administrator sees
   "Your role: Owner (administrator)"). The link opens the table in a pop-up; without JavaScript it opens a page with
   the table.
3. **Where roles are given**, a fold-out "What each role can do" shows the table: the tracker's Access tab (replacing
   today's three lines), a team's People tab and a region's Access page.
4. **The table cannot drift:** each row names the routes it describes, and a test checks each route's required role
   is the row's role.

## Non-goals

No change to what any role can do; no new roles.

## Approaches

- **Chosen:** rows in one Python module, one Jinja macro renders them, a test ties rows to the routes' required
  roles.
- Rejected: the table written out in each template (drifts); a help page only (people would not find it).

## Left to the builder

Markup and class names, the pop-up mechanism (following the app's existing dialogs), the help page's address.
