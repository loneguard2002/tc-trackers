# Teams redesign, PR 1 (Layout) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Teams New view with the simple layout: each team once in a Structure card on the left, and the
chosen team on the right with an indented "Where it sits" ladder, People ("How they get access") and Trackers tabs,
a New team form with "Also under", and indented team dropdowns.

**Architecture:** New pure functions in `tracker/teams/layout.py` compute the main higher team, the ladder and the
indented options from `TeamRow`s. `_render_team` and `_render_index` feed them to a rewritten `team_new.html` and a
new `_structure.html` partial. The current chart landing page moves to a `teams.structure` route until PR 3. Classic
is untouched.

**Tech Stack:** Flask, Jinja2, SQLAlchemy 2, PostgreSQL, vanilla ES5 JavaScript, pytest + Playwright.

**Spec:** `docs/superpowers/specs/2026-11-26-teams-simple-redesign-design.md` (sections 4.1–4.5 and 4.7; PR 1 in section 5)

## Global Constraints

- Classic templates and behaviour do not change. The test app keeps `TEAMS_DEFAULT_VIEW = "classic"`, so New view
  tests ask for `?view=new` first.
- CSP is `script-src 'self'; style-src 'self'`: no inline scripts, no `style=` attributes, no inline event handlers.
  The JavaScript is ES5, as in `teams-new.js`.
- No migration in this PR. The main higher team is the **first by name** (`name.casefold()`, then id), which is what
  `overview.chart` already does.
- Copy is fixed by the spec. Use it word for word: "Structure", "+ New team", "Find a team or person", "Sits under",
  "Also under", "makes it a shared team", "Where it sits", "this team", "this team · top level", "No teams below",
  "+N below", "shared, mainly under <team>", "Also sits under", "Change where it sits", "Put an existing team
  below", "N members", "N people through teams", "N trackers", "Everyone", "Members of this team", "Through a team
  above", "How they get access", "Member of this team", "Through <team> (<Role>)", "Sees as <Role> through a team
  above", "Change in <team>", "Members also see N trackers of the M teams below.", the People note of spec 4.5, and
  the foot note "The number is how many people reach a team through teams. A team under two teams shows once, under
  its main team."
- Every count leaves out inactive people. Inactive direct members are still listed, with their badge.
- Every tree walk must end on a team already seen (corrupted data can hold a cycle).
- Commit as `-c user.name="Alex Krovina" -c user.email="alex.krovina@tradition.ch"`, ending with the
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` line. Do not commit files that differ only in CRLF.
- Tests need `TEST_DATABASE_URL` from the main folder's `.env` and run with the sandbox off. Run the test files
  each task names. Task 7 ends with one full `pytest -n 6` run.

## Review Focus

1. **A cycle in corrupted data** (A under B, B under A, out of reach of the top): the page must still render; the
   ladder, the tree and the dropdowns stop on a team already seen. Tests are in Task 1.
2. **No teams at all:** `/admin/teams` in the New view shows "No teams yet." and offers the New team form. It must
   not redirect to a missing team. The test is in Task 2.
3. **A refused create** (duplicate name, missing region): the form opens again with the name, Sits under, Also
   under, region and location as entered. The test is in Task 5.
4. **Also under the same as Sits under:** this creates one link, not an error and not two rows. The test is in
   Task 5.
5. **Inactive members:** a disabled direct member is listed with "Disabled", and the header figures, filter counts
   and tree count all leave them out. The test is in Task 4.

---

### Task 1: Layout functions

**Files:**
- Create: `tracker/teams/layout.py`
- Test: `tests/test_teams_layout.py` (no database: build `TeamRow`s by hand, as `tests/test_teams_new_view.py`
  does)

**Interfaces:**
- Consumes: `TeamRow`, `sorted_by_name`, `children_map`, `descendants` from `tracker/teams/tree.py`.
- Produces:
  - `main_parent_ids(rows: list[TeamRow]) -> dict[int, int]`: team id to its main higher team (first by name among
    `parent_ids` that exist). Top-level teams are absent.
  - `class BelowTeam(NamedTuple): row: TeamRow; deeper: int; mainly_under: str | None`. `deeper` counts the teams
    below that team by any path, without itself. `mainly_under` is the name of its main team when that is not the
    team being viewed, otherwise None.
  - `class Ladder(NamedTuple): path: list[TeamRow]; below: list[BelowTeam]; also: list[list[TeamRow]]`. `path` runs
    from the top down to the main higher team (empty for a top-level team). `below` holds the teams directly below
    (every team listing this one among its `parent_ids`), by name. `also` holds one path per other higher team, by
    that team's name: its main path, then the team itself.
  - `ladder(rows: list[TeamRow], team_id: int) -> Ladder`
  - `class TreeOption(NamedTuple): id: int; label: str; disabled: bool`
  - `tree_options(rows: list[TeamRow], reason: Callable[[int], str | None] = lambda _id: None) -> list[TreeOption]`:
    teams in main-tree order (depth first, children by name). Each team appears once. The label is
    `" " * (3 * depth - 2) + "└ " + name` for depth ≥ 1 and the plain name at depth 0. When `reason(id)`
    returns text, the label gains `" (<reason>)"` and `disabled` is True.

- [ ] **Step 1: Write the failing tests**

```python
ROWS = [TeamRow(1, "Group", ()), TeamRow(2, "EMEA", (1,)), TeamRow(3, "Data Products", (1,)),
        TeamRow(4, "Shared Analytics", (2, 3)), TeamRow(5, "London Desk", (2,)), TeamRow(6, "London Rates", (5,))]

def test_main_parent_is_first_by_name():
    assert main_parent_ids(ROWS)[4] == 3  # Data Products before EMEA
    assert 1 not in main_parent_ids(ROWS)

def test_ladder_of_a_shared_team():
    lad = ladder(ROWS, 4)
    assert [r.name for r in lad.path] == ["Group", "Data Products"]
    assert lad.below == []
    assert [[r.name for r in p] for p in lad.also] == [["Group", "EMEA"]]

def test_ladder_below_counts_deeper_and_marks_shared():
    lad = ladder(ROWS, 2)  # EMEA
    assert [(b.row.name, b.deeper, b.mainly_under) for b in lad.below] == [
        ("London Desk", 1, None), ("Shared Analytics", 0, "Data Products")]

def test_top_level_ladder_has_empty_path():
    assert ladder(ROWS, 1).path == []

def test_tree_options_indent_by_tier_and_disable_with_reason():
    opts = tree_options(ROWS, lambda i: "this team" if i == 5 else None)
    assert [o.label for o in opts][:2] == ["Group", " └ Data Products"]
    rates = next(o for o in opts if o.id == 6)
    assert rates.label == " " * 4 + "└ London Rates" and not rates.disabled
    assert next(o for o in opts if o.id == 5) == TreeOption(5, " " * 4 + "└ London Desk (this team)", True)
    assert [o.id for o in opts].count(4) == 1  # the shared team appears once, under Data Products

def test_cycles_end():  # Review Focus 1
    rows = [TeamRow(1, "A", ()), TeamRow(2, "B", (3,)), TeamRow(3, "C", (2,))]
    assert ladder(rows, 2).path == [rows[2]]  # stops at C, which points back at B
    assert [o.id for o in tree_options(rows)] == [1]  # B and C cannot be reached from the top
```

The depth-2 label above has 4 no-break spaces (3 × 2 − 2).

- [ ] **Step 2: Run the tests to check they fail**

Run: `.venv/bin/python -m pytest tests/test_teams_layout.py -v`
Expected: FAIL with `ModuleNotFoundError: tracker.teams.layout`

- [ ] **Step 3: Implement the interfaces above in `tracker/teams/layout.py`**

Walks keep a set of visited ids and stop on a repeat. `ladder.path` follows `main_parent_ids` upward.

- [ ] **Step 4: Run the tests to check they pass**

Run: `.venv/bin/python -m pytest tests/test_teams_layout.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit** with the message `feat: Teams layout: main team, ladder and indented options`

---

### Task 2: The Structure card, index, and Whole structure route

**Files:**
- Create: `tracker/templates/teams/_structure.html`, `tracker/templates/teams/structure.html`
- Modify: `tracker/teams/views.py` (`_render_index`, `index`, new `structure` route),
  `tracker/templates/teams/index_new.html`
- Test: `tests/test_teams_new_view.py` (replace the "switch and chart" section)

**Interfaces:**
- Consumes: `overview.chart(rows)` (its `ChartNode.also_under` and `children` already give each team once, under
  its main team); `reach_counts(db)`; `team_places(db)`; the existing `data-tree-filter` script in `admin.js`.
- Produces:
  - `_structure_context(db, rows, current_id: int | None) -> dict` with the keys `nodes` (chart nodes), `reach`
    (`reach_counts`), `places`, `search` (as in `_tree_context`), `current_id`, `option_rows` (`rows`, for
    `tree_options`) and `new_open: bool`.
  - Route `GET /admin/teams/structure`, endpoint `teams.structure`, guarded by `manage_teams`. It renders the
    current chart (moved from `index_new.html` with its search and dotted lines) inside `structure.html`, with a
    "Back to teams" link.
  - `_structure.html` macro `structure_card()`, used by `team_new.html` and `index_new.html`.

- [ ] **Step 1: Write the failing tests**
  - `test_new_view_index_opens_on_the_first_top_level_team`: teams "Zeta" and "Alpha" at top level → GET
    `/admin/teams?view=new` returns 302 to `/admin/teams/<alpha.id>`.
  - `test_new_view_index_without_teams_offers_the_form`: no teams → 200, contains "No teams yet." and
    `id="new-team-form"` (not hidden).
  - `test_structure_card_shows_each_team_once`: Shared under Alpha and Beta. The card's HTML contains `>Shared<`
    exactly once, contains "Also under Beta", and contains "The number is how many people reach a team through
    teams."
  - `test_structure_card_marks_the_current_team_and_counts_people`: one active member and one disabled member in a
    team. The node has `aria-current="page"` and reads "1 person". The count pluralises: "1 person", "2 people".
  - `test_whole_structure_route_shows_the_chart`: GET `/admin/teams/structure` contains `data-chart` and
    "Back to teams". A non-`manage_teams` user gets 403.
  - Keep the existing switch tests: `test_the_switch_keeps_the_choice_and_classic_is_unchanged` and
    `test_the_switch_keeps_the_page_and_its_tab`.

- [ ] **Step 2: Run them to check they fail**

Run: `.venv/bin/python -m pytest tests/test_teams_new_view.py -k "index or structure" -v`
Expected: the new tests FAIL

- [ ] **Step 3: Implement**
  - The New view `index` redirects to the first top-level team by name. With no teams it renders `index_new.html`
    (header, Structure card, empty state, form open).
  - `_structure.html` matches the mock-up's Structure card (spec 4.2): a header with "Structure" and "+ New team",
    then the search input `data-tree-filter` (hidden until the script shows it), then the nested `<ul data-tree>` of
    nodes. Each node is a link to `teams.view`, with the name, the place line as in `_chart.html`, the people count,
    and "Also under …". Then the foot note.
  - Header button "Whole structure" links to `teams.structure`.

- [ ] **Step 4: Run them to check they pass**

Run: `.venv/bin/python -m pytest tests/test_teams_new_view.py -k "index or structure or switch" -v`
Expected: all PASS

- [ ] **Step 5: Commit** with the message `feat: Teams New view: Structure card, index, Whole structure route`

---

### Task 3: Team panel: header, figures, ladder, tabs

**Files:**
- Modify: `tracker/templates/teams/team_new.html` (rewrite), `tracker/teams/views.py` (`_render_team` New view
  context)
- Test: `tests/test_teams_new_view.py` (replace the "team page" section)

**Interfaces:**
- Consumes: `ladder`, `tree_options`, `BelowTeam` (Task 1); `_structure_context` (Task 2); the existing
  `_edit_details.html`, the delete form and blocker, `teams.add_below`, and `teams.parents`.
- Produces: New view context keys `ladder`, `below_options` (`tree_options` whose reason disables the team itself,
  its teams below by any path, and teams already directly below, reading "this team", "already below"), `member_total`
  (active direct), `people_total` (active, from this team and above), and `tracker_total` (not archived). The tab is
  `people` or `trackers`. Any other value, including `below`, falls back to `people` in the New view.

- [ ] **Step 1: Write the failing tests** (use the `swaps` fixture: Global Markets > EMEA Rates > London Swaps)
  - `test_team_header_figures`: London Swaps shows "4 members" (Ana, Lee, Mia and Tom), "6 people through teams"
    (those four, plus Priya and Sam from above; Tom is counted once) and "1 tracker".
  - `test_ladder_shows_path_this_team_and_below`: EMEA Rates' ladder lists "Global Markets", then "EMEA Rates" with
    "this team", then "London Swaps". Each team is a link to its page.
  - `test_ladder_of_a_shared_team_has_also_sits_under`: a team under Alpha and Beta shows "Also sits under" followed
    by "Beta".
  - `test_ladder_without_teams_below`: London Swaps shows "No teams below".
  - `test_only_two_tabs_and_below_tab_falls_back`: the page has the tabs People and Trackers and no "Teams below".
    GET `?tab=below` shows the People tab as current.
  - `test_put_an_existing_team_below_uses_indented_options`: the select `name="team_id"` exists, posts by GET to
    `teams.add_below`, and lists London Swaps disabled as "(already below)" on the EMEA Rates page.

- [ ] **Step 2: Run them to check they fail**

Run: `.venv/bin/python -m pytest tests/test_teams_new_view.py -k "header or ladder or tabs or below" -v`
Expected: FAIL

- [ ] **Step 3: Implement the New view branch of `_render_team` and rewrite `team_new.html`** following spec 4.4 and
  the mock-up: the header card with the name, region pill, Edit and Delete; the description; the figures; the
  ladder (indent with a class per depth, `fam-depth-0` … `fam-depth-8`, deeper levels capped at 8); and the foot
  links "Change where it sits" (to `teams.parents`) and the "Put an existing team below" form. Then the tabs.

- [ ] **Step 4: Run them to check they pass** (same command). Expected: PASS

- [ ] **Step 5: Commit** with the message `feat: Teams New view: team header, figures and Where it sits ladder`

---

### Task 4: People tab and Trackers tab

**Files:**
- Modify: `tracker/templates/teams/team_new.html`, `tracker/teams/views.py` (one more context key)
- Test: `tests/test_teams_new_view.py`

**Interfaces:**
- Consumes: `PersonRow` / `TeamPerson` (unchanged); `teams.add_member`; `teams.update_member` (role and remove);
  `status_filters`, `search_box`, `sort_header` and `table_pager` from `lists/_table.html`; `_tab_trackers.html`.
- Produces: context key `below_trackers: tuple[int, int]` = (number of active trackers in teams strictly below, by
  any path; number of teams strictly below).

- [ ] **Step 1: Write the failing tests**
  - `test_people_how_they_get_access`: on London Swaps, Ana's row reads "Member of this team". Priya's row reads
    "Through EMEA Rates (Owner)", with EMEA Rates linking to its page. Tom's row has both lines.
  - `test_role_column`: Tom (direct Viewer, Editor from above) has a role select and "Sees as Editor through a team
    above". Priya has no select and reads "Owner" with "Change in EMEA Rates".
  - `test_filters_hide_empty_groups`: a top-level team with direct members only shows "Everyone" and "Members of
    this team", and not "Through a team above".
  - `test_people_note_names_what_is_not_listed`: the page contains the spec 4.5 note "Administrators, people with
    View all trackers, regional access and roles given on a single tracker are not listed here."
  - `test_inactive_members_listed_not_counted` (Review Focus 5): add a disabled direct member. The row shows
    "Disabled". The header still reads the active count, the Everyone filter reads the same number, and the tree
    node reads the same number.
  - `test_trackers_tab_says_what_members_also_see`: on Global Markets, the Trackers tab reads "Members also see 2
    trackers of the 2 teams below."
  - Keep the existing add, role change and remove tests for the New view. They must pass unchanged, including the
    refusals and messages.

- [ ] **Step 2: Run them to check they fail.** Run `-k "people or role_column or filters or inactive or trackers_tab"`.
  Expected: FAIL

- [ ] **Step 3: Implement** the People tab (spec 4.5): the add row, the filters (only those with a count above 0),
  the table (Person | How they get access | Role | remove), the legend and the note. The Trackers tab includes
  `_tab_trackers.html`, then the line.

- [ ] **Step 4: Run them to check they pass.** Run all of `tests/test_teams_new_view.py`. Expected: PASS

- [ ] **Step 5: Commit** with the message `feat: Teams New view: People with how they get access, Trackers line`

---

### Task 5: New team form with Also under

**Files:**
- Modify: `tracker/templates/teams/_structure.html` (the form), `tracker/teams/views.py` (`create`,
  `_render_index`)
- Test: `tests/test_teams_new_view.py`

**Interfaces:**
- Consumes: `tree_options` (Task 1); `parse_team_id`; `parse_place`; `snapshot_access` / `raises_own_access`;
  `_place_fields.html`.
- Produces: the form `id="new-team-form"` with the fields `name`, `parent_id` (Sits under: "Top level" plus
  `tree_options`), `also_parent_id` ("No second team" plus `tree_options`), `region_id`, `location_id` and
  `description`. It is hidden unless `new_open`, which is true for `?new=1` or after a refused create. Each option
  carries `data-place-region` and `data-place-location` for Task 6. Sits under preselects the team being viewed.
  A refused create in the New view re-renders the Sits under team's page (or the index when there is none), with
  the form open and the errors.

- [ ] **Step 1: Write the failing tests**
  - `test_create_with_also_under_makes_a_shared_team`: post name "Rates Ops", parent Alpha, also Beta, a region.
    Rows `team_parents` hold (Rates Ops, Alpha) and (Rates Ops, Beta). Activity holds `team_created` with parent
    "Alpha" and `team_parent_added` with parent "Beta".
  - `test_also_under_same_as_sits_under_makes_one_link` (Review Focus 4): one `team_parents` row, and no
    `team_parent_added` entry.
  - `test_refused_create_keeps_what_was_entered` (Review Focus 3): a duplicate name returns 400. The form is open,
    and the name, parent, also, region and location options are selected as posted.
  - `test_sits_under_preselects_the_viewed_team`: on EMEA Rates' page, `?new=1` shows the EMEA Rates option
    `selected` in `parent_id`.
  - Classic's create tests stay green. Classic posts no `also_parent_id`.

- [ ] **Step 2: Run them to check they fail.** Run `-k "create or also_under or refused or preselects"`.
  Expected: FAIL

- [ ] **Step 3: Implement** the form and the `create` change.
  - `also_parent_id` is parsed with `parse_team_id`. If it is the same as `parent_id`, it is ignored.
  - The second link is added in the same transaction, under the self-promotion guard. Take the snapshot before
    `db.add(team)`. On refusal, roll back and re-render with `SELF_PROMOTION_MESSAGE`.
  - The `team_parent_added` detail is `{"team": name, "parent": <also name>}`.

- [ ] **Step 4: Run them to check they pass.** Run all of `tests/test_teams_new_view.py tests/test_teams.py`.
  Expected: PASS

- [ ] **Step 5: Commit** with the message `feat: Teams New view: New team form with Also under`

---

### Task 6: Script, styles and browser tests

**Files:**
- Modify: `tracker/static/teams-new.js`, `tracker/static/tracker.css`
- Test: `tests/test_teams_new_view_browser.py` (rewrite against the new pages)

**Interfaces:**
- Consumes: the markup of Tasks 2–5 (`[data-new-team]` button, `#new-team-form`, `select[name=parent_id]` options
  with `data-place-*`, `[data-place-hint]`, `[data-chart]` on the structure page).
- Produces: in `teams-new.js`:
  - "+ New team" opens `#new-team-form` in place and focuses the name; Cancel hides it.
  - Choosing Sits under fills the region and location from the option's data, unless the person changed them, and
    shows "Filled from <team>." This keeps the existing fill logic, reading the option instead of a radio.
  - The structure page's search and dotted lines (from PR #134) keep working.
  - The role-switch and Add a member preview code are deleted.

- [ ] **Step 1: Write the browser tests** (each ends with the existing `clean(page)`, which checks for no CSP or
  script errors)
  - `test_new_team_form_opens_in_place_and_fills_the_place`: open the form, choose EMEA Rates, then check the
    region and location values and the hint, then create, and land on the new team.
  - `test_structure_search_filters_teams`: typing "swaps" leaves London Swaps and its parents visible and hides
    others.
  - `test_whole_structure_page_draws_dotted_lines`: move the existing dotted-line test to `/admin/teams/structure`.
  - `test_no_page_scrolls_sideways_at_phone_width`: keep it, at 390 px, for the team page and the index.
  - Delete the browser tests for the removed features (role switch, Add a member preview, access map).

- [ ] **Step 2: Run them to check they fail where the feature is new**

Run: `.venv/bin/python -m pytest tests/test_teams_new_view_browser.py -v`

- [ ] **Step 3: Implement** the script changes and the styles.
  - Styles follow the mock-up and reuse the app's tokens: Structure card, ladder (`.family`, `.fam-row`,
    `.fam-depth-N`), figures, people "how" dots and legend.
  - The New view's two-column grid stacks at 860 px.
  - Remove the CSS rules whose selectors no longer appear in any template (grep each `.org-`, `.access-map`,
    `.role-card`, `.sits-` and `.new-team-` rule before deleting it).

- [ ] **Step 4: Run them to check they pass.** Expected: PASS

- [ ] **Step 5: Commit** with the message `feat: Teams New view: script, styles and browser tests`

---

### Task 7: Remove the old New view code, then a full run

**Files:**
- Modify: `tracker/teams/views.py`, `tracker/teams/overview.py`, `tests/test_teams_new_view.py`
- Delete: any template no longer rendered (check `_chart.html`; it stays if `structure.html` uses it)

- [ ] **Step 1: Delete the dead code.** Remove `_new_team_context` and every name in `overview.py` with no
  remaining caller. Check each with `grep -rn "<name>" tracker tests` before deleting. The likely candidates are
  `ROLE_SUMMARY`, `ancestor_levels` and `reach_people`. `paths_to` and `move_impact` stay, because `parents_new.html`
  uses them until PR 2. Delete the tests for removed functions.

- [ ] **Step 2: Run the Teams tests and the template check**

Run: `.venv/bin/python -m pytest -n 6 tests/test_teams_layout.py tests/test_teams_new_view.py tests/test_teams_new_view_browser.py tests/test_teams.py tests/test_team_page.py tests/test_team_parents.py tests/test_team_people.py tests/test_templates.py -v`
Expected: all PASS

- [ ] **Step 3: Full suite** (this PR changes several files and the shared Teams code)

Run: `.venv/bin/python -m pytest -n 6`
Expected: all pass. The only failures allowed are the ones already failing on main; list them in the hand-over.

- [ ] **Step 4: Commit** with the message `refactor: remove the old Teams New view code`, then hand over (push with
  Windows git.exe, open the PR with gh.exe `--body-file`, and leave the merge to the owner).
