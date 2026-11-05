# Regional Access Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** An administrator gives a person a role on a region; that person reaches every tracker covering the region at
that role, and every access screen shows the route (stage 3 of the regions spec).

**Architecture:**
- A `region_grants` table (one role per person per region, migration 0007) joins the role walk in
  `tracker/auth/roles.py` as a fourth route, beside direct, team and `view_all_trackers`.
- A new Access screen per region, under Lists, lists and edits the grants. It is administrator-only, through one
  named check that can later become a permission.
- The tracker's access list and Effective access show the route.

**Tech Stack:** Flask 3.1, SQLAlchemy 2 (no `relationship()`), Jinja, Postgres, hand-written Alembic migrations,
pytest with Playwright browser tests.

**Spec:** `docs/superpowers/specs/2026-11-02-regions-locations-business-lines-design.md`, section 4 ("Regional
access"), plus its Anti-goals and Constraints.

**Branch:** `feat/region-access` from main 0a63981. **Tests:** from the worktree, `WT=$PWD ../tools/acc-test.sh <args>`
(sandbox disabled), database `tracker_test_design`.

## Global Constraints

- "On the region's page, an administrator gives a person access to that region with a role: **Viewer**, **Editor** or
  **Owner**, the same three roles a tracker already uses. The page lists everyone with access to the region and lets
  an administrator change the role or remove it."
- "A person's role on a tracker becomes the highest of: administrator, a direct role, a team role,
  `view_all_trackers` and, new, **the highest role among their grants on the regions the tracker covers**."
- "Regional access applies to active people only, as every other route does."
- "The tracker's access list and the person's Effective access screen show the regional route … beside the existing
  routes."
- "Grants and their changes go to Activity."
- "A tracker with no region is reached by no regional grant."
- "Regional grants on a retired region keep working until removed."
- **Anti-goal:** a region never grants access through a **team's** region. Only the regions a tracker covers count.
- "Administrator-only management … written so that each can later become a permission in the permission sets without
  restructuring."
- Strict CSP (no inline script or style), CSRF on every POST, works without JavaScript, light and dark themes, no
  page-level horizontal scroll at 390 px, British formal copy in the active voice. Access stays fail-closed.

## Review Focus

1. **A person with a grant who is later disabled:** they reach nothing. When re-enabled, they reach the trackers
   again, because the grant is kept. Pinned in Task 1 (`test_inactive_person_reaches_nothing_by_region`).
2. **A tracker's regions changing:** removing EMEA from a tracker removes the EMEA holders' access at once. A tracker
   with no regions is reached by no grant. Pinned in Task 1 (`test_region_route_follows_the_tracker_regions`).
3. **A team placed in a region:** it gives the region's holders nothing (the anti-goal). Pinned in Task 1
   (`test_team_region_grants_nothing`).
4. **Two administrators granting the same person the same region at once:** the second sees a message, not an error
   page, and only one row and one Activity entry exist. Pinned in Task 2 (`test_grant_given_at_the_same_moment`).
5. **Deleting a region that has grants:** it is refused, as for any region in use. Pinned in Task 2
   (`test_region_with_grants_cannot_be_deleted`).

---

### Task 1: Grants table and the role walk

**Files:**
- Modify: `tracker/models.py` (new `RegionGrant`)
- Create: `migrations/versions/0007_region_grants.py`
- Modify: `tracker/auth/roles.py` (`_grants`, `tracker_access_routes`, `tracker_access_list`, `AccessRow`, new
  `RegionAccess`)
- Modify: `tests/conftest.py` (new `region_grant` fixture)
- Test: `tests/test_region_access_roles.py` (new), `tests/test_migration_0007.py` (new), and the existing
  `tests/test_migration_matches_models.py` (must keep passing)

**Interfaces:**
- Produces:
  - `RegionGrant` model, table `region_grants`:
    - `region_id` is a foreign key to `regions.id`, ON DELETE RESTRICT.
    - `user_id` is a foreign key to `users.id`, ON DELETE CASCADE.
    - `role` is text, with `CheckConstraint("role IN ('viewer', 'editor', 'owner')", name="role")`.
    - `created_at` uses `_now()`.
    - The primary key is `(region_id, user_id)`.
    - It has `Index("ix_region_grants_user_id", "user_id")`.
    - The migration uses the `op.f` names `pk_region_grants`, `fk_region_grants_region_id_regions`,
      `fk_region_grants_user_id_users` and `ck_region_grants_role`.
  - `RegionAccess(NamedTuple)`: `region_id: int`, `code: str`, `role: str`.
  - `AccessRow` gains `regions: list[RegionAccess]`. It goes before `view_all_sets` and is sorted by code ignoring
    case.
  - Route text in `tracker_access_routes` is `f"Region {code}: {role.title()}"`. These routes come after the team
    routes and before "View all trackers", sorted by code ignoring case.
  - `region_grant(region, user, role)` is a conftest fixture that adds the row and commits.

- [ ] **Step 1: Write the failing tests** (`tests/test_region_access_roles.py`)
  - `test_region_grant_reaches_trackers_covering_the_region`:
    - EMEA viewer → `user_role` is `"viewer"` on a tracker covering EMEA.
    - The same user gets `None` on a tracker covering only APAC.
    - `visible_trackers` lists the EMEA tracker only.
  - `test_highest_role_wins_across_routes`:
    - Region editor plus direct viewer → `"editor"`.
    - Region viewer plus team owner → `"owner"`.
    - A tracker covering EMEA and APAC, with EMEA viewer and APAC editor → `"editor"`.
  - `test_region_route_follows_the_tracker_regions`:
    - Delete the tracker's EMEA `TrackerRegion` → `user_role` becomes `None`.
    - A tracker with no regions gives `None`.
  - `test_inactive_person_reaches_nothing_by_region`:
    - Set the user's status to `"disabled"` → `tracker_roles` is `{}`.
    - Set it back to `"active"` → the role returns.
  - `test_retired_region_grant_keeps_working`: `region.retired = True` → the role is unchanged.
  - `test_team_region_grants_nothing`:
    - The tracker's team has a location in EMEA, but the tracker covers APAC.
    - The EMEA holder → `None`.
  - `test_effective_access_lists_the_region_route`:
    - `tracker_access_routes` for the EMEA viewer gives one entry.
    - Its routes include `Route("Region EMEA: Viewer", "viewer")`.
  - `test_access_list_shows_region_route_once_per_region`:
    - `tracker_access_list` row for the holder: `regions == [RegionAccess(emea.id, "EMEA", "viewer")]`.
    - `role == "viewer"`.
    - An inactive holder is absent from the list.

  `tests/test_migration_0007.py`:
  - `test_upgrade_creates_region_grants_and_downgrade_drops_it`: inspect the table's columns at head; it is absent
    after `downgrade 0006`.

- [ ] **Step 2: Run them and watch them fail**

Run: `WT=$PWD ../tools/acc-test.sh tests/test_region_access_roles.py tests/test_migration_0007.py -q`
Expected: FAIL. `RegionGrant` cannot be imported, and revision 0007 does not exist.

- [ ] **Step 3: Implement the model, migration 0007 and the role walk**

- `_grants` gains a fourth `union_all` member: `TrackerRegion.tracker_id` with `_rank(RegionGrant.role)`, joined on
  `region_id`, where `RegionGrant.user_id == user_id`. Update the module docstring's list of routes.
- `tracker_access_routes` reads the user's grants and the `TrackerRegion` rows, then adds each route through the
  existing `add`.
- `tracker_access_list` collects, for each active user, the grants on the tracker's regions and counts their ranks
  with the others.

- [ ] **Step 4: Run the new tests, then the full suite and ruff**

Run: `WT=$PWD ../tools/acc-test.sh -q -p no:cacheprovider -rs`
Expected: all pass, with the 2 known skips from `test_golden.py`. Ruff is clean.

- [ ] **Step 5: Commit** `git commit -m "feat: a region grant reaches every tracker covering the region"`

---

### Task 2: The region's Access screen

**Files:**
- Create: `tracker/lists/access.py` (routes on the existing `lists` blueprint)
- Create: `tracker/templates/lists/region_access.html`
- Modify:
  - `tracker/lists/views.py` (`_region_in_use`, `REGION_IN_USE`, the regions table people count)
  - `tracker/templates/lists/regions.html` (a People column)
  - `tracker/activity/labels.py`
  - the blueprint registration, if `lists` needs the new module imported
- Test: `tests/test_region_access_admin.py` (new), `tests/test_lists_admin.py` (updated messages and column)

**Interfaces:**
- Consumes: `RegionGrant` and `ROLES` from Task 1.
- Produces:
  - **Routes**, both guarded by `manage_region_access_required = admin_required`, which is defined in `access.py`:
    - `GET /admin/regions/<int:region_id>/access` is endpoint `lists.region_access`.
    - `POST /admin/regions/<int:region_id>/access` is endpoint `lists.change_region_access`. Its form fields are
      `user_id`, `role` (one of `ROLES`, or `"remove"`) and `action` (`"give"`, or `"set"` for a change and a
      removal).
  - **Activity** (`entity="region"`, `entity_id=region.id`, `tracker_id=None`, `target_user_id=user.id`):
    - `region_access_given` reads "Region access given", with detail `{"region": code, "role": role}`.
    - `region_access_changed` reads "Region access changed", with detail `{"region": code, **change(old, new)}`.
    - `region_access_removed` reads "Region access removed", with detail `{"region": code, "role": old}`.
  - **Messages:**
    - `CHOOSE_PERSON = "Choose an active person from the list."`
    - `ALREADY_HAS_ACCESS = "That person already has access to this region."`
    - `RETIRED_NO_NEW_ACCESS = "This region is retired. Restore it before giving anyone new access."`
    - `REGION_IN_USE = "This region has locations, trackers or people with access, so it can only be retired."`
    - Success flashes:
      - "Gave {name} {Role} access to {code}."
      - "{name} now has {Role} access to {code}."
      - "Removed {name}'s access to {code}."
    - `NO_CHANGES_MESSAGE` from `tracker/audit.py` for the same role.

**Screen** (`region_access.html`, page title "Access to {code}"):
- The Lists tab bar with Regions current, as on the other list pages.
- The heading reads "Access to {code}", followed by the region name.
- The lede: "People given access to a region reach every tracker that covers it, at the role shown. Their access
  follows the tracker's regions: it ends when a tracker stops covering the region."
- When the region is retired, a muted note reads "This region is retired. Access given here keeps working until it
  is removed."
- **Table** with the columns Person, Role and Actions:
  - Person shows the name, the email and a status badge when the person is not active.
  - Role is a select with `data-autosubmit` and a "Set role" fallback button, copied from the direct-role row in
    `trackers/roles.html`.
  - Actions holds a "Remove access" button.
  - When nobody has access, the table is replaced by "Nobody has access to this region yet."
- **"Give access" form:**
  - It has a person select (active people without a grant, sorted by name ignoring case), a role select (default
    Viewer) and a "Give access" button.
  - It is hidden on a retired region, which shows the retired note instead.
- **Regions table:** a new "People" column after Teams shows the grant count as a `count_pill`, linking to the Access
  screen. Sorting by it works like the other counts.
- `_region_in_use` also counts grants.

- [ ] **Step 1: Write the failing tests** (`tests/test_region_access_admin.py`)
  - `test_access_page_lists_people_and_offers_only_active_people_without_access`
  - `test_give_access_logs_and_reaches_the_tracker`:
    - Afterwards `user_role` on an EMEA tracker is `"viewer"`.
    - Activity has `region_access_given` with the detail and target above.
  - `test_change_role_and_remove_log_before_and_after`
  - `test_same_role_is_no_change`: the flash is `NO_CHANGES_MESSAGE` and no entry is recorded.
  - `test_grant_given_at_the_same_moment`:
    - Insert the same grant directly between the page load and the POST.
    - The response is 400 with `ALREADY_HAS_ACCESS`.
    - There is one row and no new entry.
  - `test_inactive_or_unknown_person_or_bad_role_is_400` covers `user_id` values "abc", a disabled user, `MAX_ID+1`,
    and the role "admin".
  - `test_retired_region_refuses_new_access_but_keeps_and_edits_existing`
  - `test_region_with_grants_cannot_be_deleted`: the response is 400 with `REGION_IN_USE`, and the region remains.
  - `test_regions_table_shows_people_count_linking_to_access`
  - `test_access_screen_is_administrators_only`:
    - A user with every permission except administrator gets 403 on GET and POST.
    - Anonymous visitors are redirected to sign-in.
  - Browser test in `tests/test_lists_browser.py`, `test_region_access_role_autosubmits`:
    - Changing the select saves the role without pressing the button.
    - The page does not scroll sideways at 390 px.

- [ ] **Step 2: Run them and watch them fail.**

- [ ] **Step 3: Implement.**
  - Mirror `add_member` and `update_member` in `tracker/teams/views.py` for validation order, IntegrityError
    handling and flashes.
  - Read the region's code before writing, so that the Activity entry names it as it was.

- [ ] **Step 4: Full suite and ruff**, as in Task 1. Take light and dark screenshots of the Access screen at 1440 px
  and 390 px, saved under the scratchpad and not committed. Look at them.

- [ ] **Step 5: Commit** `git commit -m "feat: administrators give people access to a region"`

---

### Task 3: Show the regional route on the tracker's access list

**Files:**
- Modify: `tracker/templates/trackers/roles.html`, `tracker/templates/trackers/_label_fields.html`
- Test: `tests/test_tracker_access.py`

**Interfaces:**
- Consumes: `AccessRow.regions` (list of `RegionAccess`) from Task 1, and the `lists.region_access` endpoint from
  Task 2.

**Changes:**
- **Access list routes.** In the Routes column, after the team routes, each regional route reads "Region {code}"
  followed by the muted role. The text links to `lists.region_access` for administrators and is plain text for
  everyone else.
- **Row filter.**
  - The row's `data-route` gains `region` when `row.regions` is not empty.
  - The row filter gains "Regions ({n})" between Teams and Permission sets.
- **Settings help.** The help text on the tracker's Regions field becomes: "Choose every region the tracker covers.
  People given a region see its trackers, so changing the regions changes who can see this tracker."

- [ ] **Step 1: Write the failing tests**
  - `test_access_list_shows_region_route_and_filter`:
    - The access page for an EMEA tracker with one EMEA viewer contains "Region EMEA" and "Regions (1)".
    - The row's `data-route` contains "region".
  - `test_region_route_links_only_for_administrators`:
    - An administrator sees a link to `/admin/regions/<id>/access`.
    - A tracker owner who is not an administrator sees the text without a link.
  - `test_regions_help_says_people_given_a_region_see_its_trackers`: this covers the settings page and the New
    tracker page.

- [ ] **Step 2: Run them and watch them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Full suite and ruff.**
- [ ] **Step 5: Commit** `git commit -m "feat: the tracker access list shows regional access"`
