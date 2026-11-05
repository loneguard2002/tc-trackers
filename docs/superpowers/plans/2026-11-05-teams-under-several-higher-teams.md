# Teams Under Several Higher Teams Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A team can sit under zero or more higher teams (stage 2 of the regions spec), with team roles, counts, the
tree, the team page and a new Higher teams screen following every path.

**Architecture:** A `team_parents` link table replaces `teams.parent_id` (migration 0006). The pure tree helpers in
`tracker/teams/tree.py` take rows carrying a tuple of higher-team ids; every reader (role walk, team people, reach
counts, effective access, permission sources) walks all paths. Team labels become the team's own name, since a path
is no longer unique. The Move screen becomes a Higher teams screen that adds or removes one link at a time, each
with the existing impact preview and self-promotion guard.

**Tech Stack:** Flask 3.1, SQLAlchemy 2 (no `relationship()`), Jinja, Postgres, hand-written Alembic migrations,
pytest with Playwright browser tests.

**Spec:** `docs/superpowers/specs/2026-11-02-regions-locations-business-lines-design.md`, section 5 ("Teams under
several higher teams"), plus its Constraints.

**Branch:** `feat/team-parents`, cut from `feat/locations-table` (6149cdf), because migration 0005 lives there. Merge
that branch first.

**Tests:** from the worktree, `WT=$PWD ../tools/acc-test.sh <args>` (sandbox disabled), database
`tracker_test_design`.

## Global Constraints

- "A team has **zero or more higher teams**. A team with none is top level. This replaces the single higher team."
- "A member of a team holds their membership role on the trackers of that team and of every team below it, by any
  path. If several paths reach a tracker, the highest role wins."
- "A team cannot be placed below itself or below any team beneath it, by any path."
- "All of a team's higher teams are **equal**: none is the main one, and nothing records an order."
- "Counts of people who reach a team count each person once, however many paths reach them."
- "A team that has teams below it still cannot be deleted. Deleting a team removes its links to its higher teams."
- "Existing data migrates as is: each team's current higher team becomes its only higher team."
- Labels that name a team (selects, Activity entries, routes) use the team's own name (the spec allows this).
- Strict CSP (no inline script or style), CSRF on every POST, works without JavaScript, light and dark themes, no
  page-level horizontal scroll at 390 px, British formal copy in the active voice, every change to Activity.
- Access stays fail-closed; the self-promotion guard (`snapshot_access` / `raises_own_access`) covers every link
  change.

## Review Focus

1. A diamond: a person reaches one tracker through two paths with different roles. They get the higher role, are
   counted once and are listed once on the team page. Pinned in Task 1 (`test_diamond_*`).
2. A cycle through a second path: when C sits under both A and B, adding A under C is refused; adding B under a team
   below C is refused too. Pinned in Task 2 (`test_add_under_a_team_below_by_another_path_is_refused`).
3. Removing one higher team while another path still grants the same role: the preview shows no loss for that
   person. Pinned in Task 2 (`test_preview_remove_keeps_access_through_the_other_path`).
4. A concurrent request that has already added or removed the link: no duplicate row, no error page, and no
   Activity entry. Pinned in Task 2 (`test_adding_an_existing_link_is_a_notice` and
   `test_removing_a_missing_link_is_a_notice`).
5. A team under two higher teams appears under both in the tree, and each appearance names the other ("Also under
   …"). Pinned in Task 3.

---

### Task 1: Links table, tree helpers and every access reader

**Files:**
- Modify: `tracker/models.py` (Team, new TeamParent)
- Create: `migrations/versions/0006_team_parents.py`
- Modify: `tracker/teams/tree.py`, `tracker/teams/people.py`, `tracker/auth/roles.py`, `tracker/auth/permissions.py`
- Modify: `tracker/teams/impact.py`, `tracker/teams/views.py` (interim: create, delete, team page, move)
- Modify: `tests/conftest.py` (`team_factory`)
- Test: `tests/test_migration_0006.py` (new), `tests/test_team_tree.py`, `tests/test_team_people.py`,
  `tests/test_roles.py`, `tests/test_guards.py`, and every test asserting a `" › "` path label (test_teams,
  test_tracker_teams, test_tracker_access, test_permission_sets, test_users_admin, test_teams_browser,
  test_team_move_preview)

**Interfaces:**
- Produces:
  - `TeamParent` model: table `team_parents`.
    - Columns: `team_id` (FK teams.id, ON DELETE CASCADE) and `parent_id` (FK teams.id, ON DELETE RESTRICT); the
      two together form the primary key.
    - `CheckConstraint("team_id <> parent_id", name="not_self")` and `Index("ix_team_parents_parent_id", "parent_id")`.
    - `Team.parent_id` and `ix_teams_parent_id` are removed.
  - `TeamRow(id: int, name: str, parent_ids: tuple[int, ...])` (`parent_ids` sorted ascending; empty means top
    level).
  - `children_map(rows) -> dict[int | None, list[TeamRow]]`: a team is listed under each of its higher teams.
  - `descendants(rows, team_id) -> set[int]`: unchanged meaning, by any path.
  - `ancestors(rows, team_id) -> list[int]`: new. Every team above, by any path, without the team itself and
    without repeats, nearest first (breadth-first, with ties by name ignoring case, then id). It ends on a cycle.
  - `team_labels(rows) -> dict[int, str]`: id to the team's name.
  - `team_choices(session) -> list[tuple[int, str]]`: `(id, name)` sorted by name ignoring case, then id.
  - `load_team_rows(session, lock=False) -> list[TeamRow]`: with `lock`, it reads every `teams` row `FOR UPDATE`, then
    the links.
  - `move_impact(session, team, parent_ids: frozenset[int]) -> MoveImpact`: compares access with the team's links
    replaced by `parent_ids`, inside a rolled-back savepoint.
  - `set_team_parents(session, team_id: int, parent_ids: Iterable[int]) -> None` in `tree.py`: it replaces the
    team's links. It is used by the interim move and by `move_impact`.
- Removed: `paths`, `order_tree`, `PATH_SEPARATOR`.
- Renamed fields: `TeamAccess.path` and `InheritedRole.path` become `team_name`; the templates that use them
  (`trackers/roles.html`, `teams/team.html`) change to match.
- `team_factory(name=None, parent=None, parents=(), **kw)`: it links `parent` and each team in `parents`.

- [ ] **Step 1: Write the failing tests**

`tests/test_team_tree.py` (rewrite the module's rows):
```python
ROWS = [
    TeamRow(1, "Infrastructure", ()),
    TeamRow(2, "Windows", (1,)),
    TeamRow(3, "network", (1,)),
    TeamRow(4, "Desktops", (2, 5)),
    TeamRow(5, "Applications", ()),
]

def test_children_map_lists_a_team_under_each_higher_team():
    children = children_map(ROWS)
    assert [r.id for r in children[None]] == [5, 1]
    assert [r.id for r in children[1]] == [3, 2]
    assert [r.id for r in children[2]] == [4] and [r.id for r in children[5]] == [4]

def test_descendants_follow_every_path():
    assert descendants(ROWS, 5) == {5, 4} and descendants(ROWS, 1) == {1, 2, 3, 4}

def test_ancestors_every_path_nearest_first_without_repeats():
    assert ancestors(ROWS, 4) == [5, 2, 1]   # 5 and 2 at distance 1, Applications before Windows by name
    assert ancestors(ROWS, 1) == []

def test_tree_functions_terminate_on_a_cycle():
    rows = [TeamRow(1, "A", (2,)), TeamRow(2, "B", (1,)), TeamRow(3, "C", ())]
    assert descendants(rows, 1) == {1, 2} and ancestors(rows, 1) == [2]
    assert [r.id for r in children_map(rows)[None]] == [3]

def test_team_labels_are_names():
    assert team_labels(ROWS)[4] == "Desktops"

def test_load_team_rows_reads_links(db, team_factory):   # team_choices too: sorted by name, bare names
    ...
```

`tests/test_migration_0006.py` uses the `at_revision_0005` fixture pattern from `test_migration_0005.py`:
- `test_upgrade_turns_each_parent_into_the_only_higher_team`: insert three teams at 0005, B under A and C at top
  level. After `upgrade head`, `team_parents` holds exactly `{(B, A)}`.
- `test_downgrade_keeps_the_lowest_id_higher_team`: at head, put a team under two teams and downgrade to 0005.
  `teams.parent_id` is the lower id.

`tests/test_team_people.py` and `tests/test_roles.py` add the diamond tests:
- `test_diamond_highest_role_wins_and_person_counted_once`:
  - Desktops sits under Windows and under Applications.
  - The person is a viewer in Windows and an editor in Applications, and the tracker belongs to Desktops.
  - `user_role` is `"editor"`.
  - `reach_counts(db)[desktops.id] == 1`.
  - `team_people(db, desktops.id)` holds the person once, with two `InheritedRole` entries named "Applications"
    and "Windows".
- `test_diamond_effective_access_lists_both_team_routes`: `tracker_access_routes` gives one `TrackerAccess` for the
  tracker. Its role is `"editor"`, and its route texts include `"Team Windows: Viewer"` and
  `"Team Applications: Editor"`.

- [ ] **Step 2: Run them and watch them fail**

Run: `WT=$PWD ../tools/acc-test.sh tests/test_team_tree.py tests/test_migration_0006.py tests/test_team_people.py tests/test_roles.py -q`
Expected: FAIL. `TeamRow` takes the wrong fields, `ancestors` does not exist, and revision 0006 is missing.

- [ ] **Step 3: Implement the model and migration 0006**

- `upgrade`:
  - Create `team_parents` with op.f names `pk_team_parents`, `fk_team_parents_team_id_teams`,
    `fk_team_parents_parent_id_teams` and `ck_team_parents_not_self`, plus `ix_team_parents_parent_id`.
  - `INSERT INTO team_parents (team_id, parent_id) SELECT id, parent_id FROM teams WHERE parent_id IS NOT NULL`.
  - Drop `ix_teams_parent_id` and the `parent_id` column.
- `downgrade`:
  - Add `parent_id` back with its FK and index.
  - Set it to `(SELECT min(parent_id) FROM team_parents WHERE team_id = teams.id)`.
  - Drop the table. The docstring says that a downgrade keeps only the lowest-id higher team.

- [ ] **Step 4: Implement the tree helpers, then switch every reader**

- `roles._grants`: the recursive step joins `TeamParent` (`TeamParent.parent_id == reach.c.team_id`, selecting
  `TeamParent.team_id`). Keep `UNION`.
- `roles.team_access`: the teams that reach the tracker are its team plus `ancestors(rows, tracker.team_id)`.
- `roles.tracker_access_routes`: route text `f"Team {name}: {Role}"`, with memberships sorted by team name.
- `people.team_people`:
  - Use `ancestors` in place of `_chain`, keeping nearest first for the tie-break of the "Owner from X" note.
  - Delete `_chain` and `_parents`.
- `people.reach_counts`: the union over the team and its `ancestors`.
- `permissions.set_permission_sources`: switch to `team_labels` (it used `paths`).
- `impact.move_impact`: inside the savepoint, call `set_team_parents(session, team.id, parent_ids)` and flush. Because
  `team` no longer changes, `session.expire(team)` goes.
- `views` (interim, replaced in Task 2):
  - `create` inserts a `TeamParent` for the chosen parent.
  - `_delete_blocker` checks `any(team_id in row.parent_ids for row in rows)`.
  - The team page's `parent_label` lists the names of the higher teams, joined with " and ", or reads "Top level".
  - Move POST and preview treat the chosen parent as the whole new set: `frozenset({id})`, or empty for the top level.
  - `team_deleted` detail key `"parent"` becomes `"parents"`, holding a list of names (empty list for none).
- Update the test assertions that expected `"A › B"` labels so they expect `"B"`.

- [ ] **Step 5: Run the touched modules, then the full suite**

Run: `WT=$PWD ../tools/acc-test.sh -q -x`
Expected: every test passes (about 1157 plus the new ones). Ruff is clean: `$MAIN/.venv/bin/ruff check . && $MAIN/.venv/bin/ruff format --check .`

- [ ] **Step 6: Commit**

`git commit -m "feat: teams link to zero or more higher teams"`

---

### Task 2: Higher teams screen in place of Move

**Files:**
- Modify: `tracker/teams/views.py` (remove `move_preview`/`move`, add `parents`/`change_parents`)
- Create: `tracker/templates/teams/parents.html`; delete `tracker/templates/teams/move.html`
- Modify: `tracker/activity/labels.py`
- Modify: `tracker/templates/teams/team.html` (button "Higher teams…")
- Test: rename `tests/test_team_move_preview.py` to `tests/test_team_parents.py` and rewrite it; remove the move tests
  from `tests/test_teams.py` (`test_move_*`, `test_holder_cannot_move_a_team_under_their_own_team` and
  `test_team_moved_names_the_team_by_its_path`), moving the behaviour they cover into `test_team_parents.py`.

**Interfaces:**
- Consumes: from Task 1, `move_impact`, `set_team_parents`, `descendants`, `load_team_rows(lock=True)` and
  `team_labels`.
- Produces:
  - `GET /admin/teams/<id>/parents` is endpoint `teams.parents`.
    - Query `?add=<team id>` or `?remove=<team id>` shows the preview for that one change.
  - `POST /admin/teams/<id>/parents` is endpoint `teams.change_parents`.
    - Its form fields are `action` (`add` or `remove`) and `parent_id`.
  - Activity actions `team_parent_added` ("Higher team added") and `team_parent_removed` ("Higher team removed").
    - Their detail is `{"team": <name>, "parent": <name>}`.
  - `team_moved` stays in `ACTION_LABELS` for old entries.
  - Messages:
    - `CYCLE_MESSAGE = "A team cannot be placed under itself or under a team below it."`
    - `ALREADY_UNDER = "{team} is already under {parent}."`
    - `NOT_UNDER = "{team} is not under {parent}."`
    - Flashes on success:
      - "Added {team} under {parent}."
      - "Removed {team} from under {parent}."
      - When the last link goes: "Removed {team} from under {parent}. It is now at the top level."

**Screen** (`parents.html`, titled "Higher teams for {team}"):
- Breadcrumb: Teams › {team} › Higher teams.
- **Section "Now under".**
  - When the team has links: a list of its higher teams, each with a name link and a "Remove…" link to
    `?remove=<id>`.
  - When it has none: the note "{team} is at the top level."
  - The lede: "People in a higher team reach this team's trackers. A team can sit under several higher teams; all
    count equally."
- **Section "Add under another team".**
  - A GET form: a select named `add`, offering every team that is not the team itself, not below it and not already
    a higher team, sorted by name.
  - Its button reads "Show what changes".
  - When no team qualifies, the section shows "No other team can take {team}." in place of the form.
- **Preview** (`?add` or `?remove` valid and a real change):
  - The heading reads "Adding {team} under {parent}" or "Removing {team} from under {parent}".
  - The Lose access / Gain access / Role changes / Trackers lists come from the existing move template.
  - A POST confirm form has hidden `action` and `parent_id` fields, a primary button "Add under {parent}" or
    "Remove from {parent}", and a Cancel link back to the screen.

**Rules, on GET (preview) and again on POST:**
- **Parent id:** a malformed id, or one that is not a team, gives `TEAM_CHOICE_ERROR` with status 400.
- **Add:**
  - A parent among `descendants(rows, team.id)` gives `CYCLE_MESSAGE` with status 400. This covers the team itself
    and any path.
  - A parent that is already a higher team gives `ALREADY_UNDER` as a notice (200 on GET). On POST it shows a flash
    "info" and records no entry.
- **Remove:** a parent that is not a current higher team gives `NOT_UNDER` as a notice, by the same pattern.
- **POST:**
  - Reads `load_team_rows(db, lock=True)` first.
  - The guard runs `snapshot_access` before the change, inserts or deletes the one `TeamParent` row, and then runs
    `raises_own_access`. A refused change goes through `_refuse(team, SELF_PROMOTION_MESSAGE)`.
  - Then it records Activity and commits.
- **Preview:** `move_impact(db, team, frozenset(current) | {parent})` for an add, and `frozenset(current) - {parent}`
  for a remove.

- [ ] **Step 1: Write the failing tests** in `tests/test_team_parents.py`:
- `test_screen_lists_higher_teams_and_offers_only_valid_ones`:
  - Desktops sits under Windows. The page names Windows with a Remove… link.
  - The add select offers Applications and Infrastructure. It does not offer Desktops or anything below Desktops.
  - It does not offer Windows, which is already a higher team.
- `test_preview_add_lists_gains`: adding Desktops under Applications shows "Apps Lead gains Editor on Laptop refresh."
- `test_preview_remove_keeps_access_through_the_other_path`:
  - Desktops sits under Windows and Applications, and one person is an editor in both.
  - The preview for removing Windows shows "No one loses access." and "No roles change." The person is unaffected.
- `test_add_logs_and_links`: the POST adds the row, flashes "Added Desktops under Applications." and records
  `team_parent_added` with detail `{"team": "Desktops", "parent": "Applications"}`.
- `test_remove_last_link_makes_top_level`: the flash ends "It is now at the top level.", the team has no rows and the
  Activity entry is `team_parent_removed`.
- `test_add_under_a_team_below_by_another_path_is_refused`:
  - C sits under A and B. Adding A under C gives status 400 with `CYCLE_MESSAGE`.
  - D sits under C. Adding B under D gives status 400 with `CYCLE_MESSAGE`.
  - No row or entry is written.
- `test_adding_an_existing_link_is_a_notice` and `test_removing_a_missing_link_is_a_notice`:
  - The POST redirects with the info message and leaves the rows unchanged.
  - The number of entries is unchanged.
- `test_malformed_or_unknown_parent_is_400` (GET and POST, including `parent_id=abc`, a deleted id and an id over
  `MAX_ID`).
- `test_holder_cannot_add_a_team_under_their_own_team`: this carries over the old guard test.
  - A non-administrator with `manage_teams` adds a team that holds a tracker under a team they belong to.
  - The request is refused with `SELF_PROMOTION_MESSAGE`, and no row is written.
- `test_old_move_address_is_gone`: `GET /admin/teams/<id>/move` returns 404.
- `test_team_page_links_to_higher_teams`: the button "Higher teams…" points to `/admin/teams/<id>/parents`.
- `test_parents_requires_manage_teams`: both routes return 403 for a person without the permission.

- [ ] **Step 2: Run and watch them fail** (`tests/test_team_parents.py -q`; expect 404s on the new address).

- [ ] **Step 3: Implement** the two routes, the template (copy `change_list` from `move.html`, then delete
  `move.html`) and the two Activity labels.

- [ ] **Step 4: Full suite and ruff**, as in Task 1. Expected: all pass.

- [ ] **Step 5: Commit** `git commit -m "feat: Higher teams screen adds or removes one higher team at a time"`

---

### Task 3: Tree and team page show every place

**Files:**
- Modify: `tracker/templates/teams/_tree.html`, `tracker/teams/views.py` (`_tree_context`, `_render_team`),
  `tracker/templates/teams/team.html`, `tracker/templates/teams/index.html`, `tracker/static/tracker.css`
- Test: `tests/test_teams.py`, `tests/test_teams_browser.py`

**Interfaces:**
- Consumes: `children_map` (a team under each higher team) and `team_labels`, both from Task 1.
- Produces: the `_tree_context` key `higher` maps a team id to a list of `(id, name)` for its higher teams, sorted by
  name. Only teams with more than one higher team appear in it.

**Look:**
- **Tree.**
  - Under each higher team, a team appears with its whole subtree.
  - Each appearance of a team with more than one higher team carries a muted line after its place. The line reads
    "Also under {names of the other higher teams, joined with ', ' and a final ' and '}" and is classed
    `team-also`. It is computed against the higher team that this appearance sits under.
  - Every appearance links to the one team page.
  - `aria-current="page"` goes on every appearance of the current team.
  - The tree card's note gains one sentence: "A team under several higher teams appears under each."
  - The `level` macro passes the higher team's id down, so the "Also under" text can leave it out.
- **Team page header.**
  - It shows "Under {name links joined as above}", or "Top level", on its own line under the place.
  - The breadcrumb reads "Teams › {name}".
  - The counts line keeps "N teams below", counting the teams directly below.
- **New team form (index).**
  - The field reads "Higher team", with the help text "Optional. You can add more higher teams from the team's
    page."
  - It offers `team_choices` (names, sorted).

- [ ] **Step 1: Write the failing tests**
- `test_tree_shows_a_team_under_each_higher_team_with_also_under`:
  - Desktops sits under Windows and Applications, and Laptops sits under Desktops.
  - The tree HTML has two Desktops links, each followed by a Laptops link.
  - The Windows appearance reads "Also under Applications" and the Applications appearance reads "Also under
    Windows".
- `test_also_under_names_two_others_with_and`: a team under three higher teams reads "Also under B and C" under A.
- `test_team_page_header_names_every_higher_team`: the header reads "Under Applications and Windows", with links.
- `test_top_level_team_page_says_top_level`.
- `test_tree_people_count_counts_each_person_once` (diamond): the count beside Desktops reads "1 person".
- Browser test `test_tree_filter_shows_every_appearance` (`@pytest.mark.browser`): typing "Desktops" in the filter
  leaves both appearances visible, and the page has no horizontal scroll at 390 px.

- [ ] **Step 2: Run and watch them fail.**

- [ ] **Step 3: Implement.** The CSS adds `.team-also` (muted, small, wraps) and no other rule.

- [ ] **Step 4: Full suite and ruff.** Take light and dark screenshots at 1440 px and 390 px of the Teams page and of
  a team page with two higher teams, saved under the scratchpad and not committed. Confirm by sight that there is no
  horizontal scroll.

- [ ] **Step 5: Commit** `git commit -m "feat: the tree and team page show every higher team"`
