# Teams redesign, PR 2 (Where it sits and the main team) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let an owner change where a team sits in one editor: add and take out higher teams, choose the main team,
see who gains or loses access, then save everything at once. The structure, ladder and dropdowns then follow the
chosen main team.

**Architecture:** Migration 0021 adds `team_parents.is_main`. `set_team_parents` becomes the one writer of higher
teams and keeps exactly one main. `TeamRow` gains `main_id`, so `main_parent_ids` and `overview.chart` use the stored
main. A pure module `tracker/teams/sits.py` turns query or form values into a draft. New routes `teams.sits` (GET,
the editor in the team card) and `teams.save_sits` (POST, one save) replace the old New view Where it sits page.
Classic keeps its own page and routes.

**Tech Stack:** Flask, Jinja2, SQLAlchemy 2, Alembic, PostgreSQL, pytest + Playwright.

**Spec:** `docs/superpowers/specs/2026-11-26-teams-simple-redesign-design.md` (section 4.6, the 4.7 dropdown rule for
"Add a team above", and PR 2 of section 5)

## Global Constraints

- Classic screens do not change. The tests keep `TEAMS_DEFAULT_VIEW = "classic"`, so New view tests ask for
  `?view=new` first.
- CSP is `script-src 'self'; style-src 'self'`: no inline scripts, no `style=` attributes, no inline event handlers.
  The editor needs no JavaScript: every action is a button that reloads the page with the draft in the address.
- Copy, word for word from the spec:
  - "Where <team> sits"
  - "A team can sit under more than one team. That makes it a shared team: members of every team above can see its
    trackers. The main team decides where it shows in the structure."
  - "Main team", "Make main", "Take out of <team>"
  - "Top level: no team above it."
  - "Add a team above", "Add"
  - the reasons "this team", "below this team, would make a loop", "already above"
  - "N gain access: …", "N lose access: …", "No change in who can see its trackers."
  - "The same applies to the teams below it."
  - "Cancel", "Save"
  - the activity label "Main team set"
- The main team rule: every team with higher teams has exactly one main. Taking out the main makes the next one by
  name the main. The first higher team a team is given is its main. Changing only the main changes no access, needs
  no self-promotion check, and writes one `team_main_set` entry.
- Save runs, under the `load_team_rows(db, lock=True)` lock:
  - validation (unknown team → `TEAM_CHOICE_ERROR`, loop → `CYCLE_MESSAGE`);
  - one `snapshot_access` / `raises_own_access` check over the whole change;
  - one `team_parent_added` or `team_parent_removed` entry per link (detail `{"team", "parent"}`), plus
    `team_main_set` (detail `{"team", "before", "after"}`) when the main changed and the team still has higher teams.
- Commit identity, CRLF, test database and runner as in the PR 1 plan. Run the test files each task names. Task 5
  ends with one full `pytest -n 6` run.

## Review Focus

1. **Taking out every higher team:** Save makes the team top level, writes one removal entry per link and no
   `team_main_set`, and the ladder reads "this team · top level". The test is in Task 4.
2. **A stale draft** (a team in the address or form was deleted meanwhile): the editor page leaves it out quietly,
   and Save refuses with `TEAM_CHOICE_ERROR`, status 400, and the editor shown again. Tests are in Tasks 3 and 4.
3. **A loop arriving by a hand-made post** (a team below this one posted as a higher team): Save refuses with
   `CYCLE_MESSAGE` and nothing changes. The test is in Task 4.
4. **Only the main changed:** no guard refusal even for a non-administrator, exactly one `team_main_set` entry, no
   link entries, and the tree places the team under the new main. The test is in Task 4.
5. **Classic removing the main** (the old one-action page): the next by name becomes main, so the New view still
   shows the team once. The test is in Task 2.

---

### Task 1: The main team in the data

**Files:**
- Create: `migrations/versions/0021_team_main.py`, `tests/test_migration_0021.py`
- Modify: `tracker/models.py` (`TeamParent`), `tracker/teams/tree.py` (`TeamRow`, `load_team_rows`,
  `set_team_parents`), `tests/conftest.py` (`team_factory`)
- Test: `tests/test_team_tree.py` (add to it), `tests/test_migration_matches_models.py` (must stay green)

**Interfaces:**
- Produces:
  - Column `team_parents.is_main boolean not null server_default false`, and partial unique index
    `uq_team_parents_main` on `(team_id) WHERE is_main`, declared in both the migration and the model.
  - `TeamRow(id, name, parent_ids, main_id: int | None = None)`. The default keeps every hand-built
    `TeamRow(1, "A", ())` working. `load_team_rows` fills `main_id` from `is_main`.
  - `set_team_parents(session, team_id: int, parent_ids: Iterable[int], main_id: int | None = None) -> None`. The
    main is `main_id` if it is among `parent_ids`, else the current main if it is kept, else the first by name
    (`Team.name` casefold, then id). There is no main when `parent_ids` is empty.
  - `team_factory(..., main: Team | None = None)`: when `main` is not given, the first higher team **by name** is
    main. That matches the migration and keeps existing tests meaningful.

- [ ] **Step 1: Write the failing tests**
  - `tests/test_migration_0021.py::test_existing_links_mark_the_first_by_name_as_main_and_downgrade_drops_it`. Follow
    the 0020 test's pattern:
    1. downgrade to 0020;
    2. insert teams "Zed", "alpha" and "Mid", with Mid under both;
    3. upgrade to 0021: Mid's main is alpha (casefold order);
    4. inserting a second `is_main` row for Mid raises `IntegrityError`;
    5. downgrade, and the column is gone.
  - `tests/test_team_tree.py::test_set_team_parents_keeps_the_current_main`: B is main of T (under A and B), then
    `set_team_parents(db, T, [B, C])`, and B is still main.
  - `...::test_set_team_parents_moves_the_main_to_the_next_by_name`: main B is taken out of {A, B, C}, so A becomes
    main.
  - `...::test_set_team_parents_takes_the_given_main` and `...::test_top_level_has_no_main`.
  - `...::test_load_team_rows_reads_the_main`: `row.main_id == B.id` after `team_factory("T", parents=(a, b),
    main=b)`.

- [ ] **Step 2: Run them to check they fail**

Run: `t.sh tests/test_migration_0021.py tests/test_team_tree.py -q`
Expected: FAIL (no revision 0021; `TeamRow` has no `main_id`)

- [ ] **Step 3: Implement** the migration, model, `TeamRow`, `load_team_rows`, `set_team_parents` and the fixture.
  The migration's backfill is one `UPDATE … FROM (SELECT DISTINCT ON (tp.team_id) tp.team_id, tp.parent_id FROM
  team_parents tp JOIN teams t ON t.id = tp.parent_id ORDER BY tp.team_id, lower(t.name), t.id)`.

- [ ] **Step 4: Run them to check they pass**, plus `tests/test_migration_matches_models.py`. Expected: PASS

- [ ] **Step 5: Commit** with the message `feat: Teams: the main higher team in the data (migration 0021)`

---

### Task 2: Everything follows the stored main

**Files:**
- Modify: `tracker/teams/layout.py` (`main_parent_ids`), `tracker/teams/overview.py` (`chart`),
  `tracker/teams/views.py` (`create`, `change_parents`)
- Test: `tests/test_teams_layout.py`, `tests/test_teams_new_view.py`, `tests/test_team_parents.py`

**Interfaces:**
- Consumes: `TeamRow.main_id` and `set_team_parents(..., main_id=)` (Task 1).
- Produces:
  - `main_parent_ids(rows)` returns `row.main_id` when it is one of the row's existing `parent_ids`, else the first
    by name (the fallback for hand-built rows and damaged data).
  - `chart(rows)` places each team under `main_parent_ids(rows)[id]`. `also_under` and `also_ids` hold the other
    higher teams, by name.
  - `create` writes its links with `set_team_parents(db, team.id, [parent, also], main_id=parent.id)`.
  - Classic `change_parents` writes add, remove and move through `set_team_parents`. Add keeps the current main, or
    makes the new team main when there was none. Remove of the main passes to the next by name. Move makes the
    chosen team main.

- [ ] **Step 1: Write the failing tests**
  - `test_teams_layout.py::test_main_parent_follows_the_stored_main`: `TeamRow(4, "Shared", (2, 3), main_id=2)` gives
    2, although 3 ("Data Products") sorts first.
  - `test_teams_layout.py::test_a_main_that_is_not_a_parent_falls_back_to_first_by_name`: `main_id=99` gives 3.
  - `test_teams_new_view.py::test_structure_card_places_a_team_under_its_main`: Shared under Alpha and Beta with
    `main=beta`. The card shows "Also under Alpha", and Shared's node sits inside Beta's `<li>`.
  - `test_teams_new_view.py::test_also_under_does_not_become_main`: create "Ops" with Sits under Zeta and Also under
    Alpha. Zeta is main, although Alpha sorts first.
  - `test_team_parents.py::test_classic_remove_of_the_main_passes_it_to_the_next_by_name` (Review Focus 5): T under
    A, B and C with main B. The Classic POST `{"action": "remove", "parent_id": B}` makes A main.
  - `test_team_parents.py::test_classic_add_to_a_top_level_team_makes_it_main`.

- [ ] **Step 2: Run them to check they fail**

Run: `t.sh -q tests/test_teams_layout.py tests/test_teams_new_view.py tests/test_team_parents.py -k "main"`
Expected: FAIL

- [ ] **Step 3: Implement the four changes above.** The Classic flash messages and activity entries do not change.

- [ ] **Step 4: Run all three files.** Expected: PASS

- [ ] **Step 5: Commit** with the message `feat: Teams: the structure, ladder and dropdowns follow the main team`

---

### Task 3: The draft

**Files:**
- Create: `tracker/teams/sits.py`
- Test: `tests/test_teams_sits.py` (no database)

**Interfaces:**
- Consumes: `TeamRow`, `descendants`, `sorted_by_name` (`tree.py`); `main_parent_ids` (`layout.py`); `MoveImpact`
  (`impact.py`).
- Produces:
  - `class Draft(NamedTuple): above: tuple[int, ...]; main: int | None`. `above` is sorted by name.
  - `read_draft(rows: list[TeamRow], team_id: int, values: Mapping[str, str] with getlist) -> Draft`.
    - Without `draft=1` it starts from the team's saved higher teams and main.
    - With `draft=1` it reads `above` (repeated) and `main`, dropping ids that are not teams.
    - It then applies, in this order: `add=<id>` (ignored if it is the team itself, below it, or already above),
      `drop=<id>`, and `make_main=<id>` (ignored unless above).
    - Finally, a main that is not above becomes the first by name; empty `above` means no main.
  - `draft_errors(rows, team_id, above: list[str], main: str) -> tuple[Draft | None, list[str]]` for Save. Returns
    `TEAM_CHOICE_ERROR` for an unknown or unparsable id or a `main` not among `above`, and `CYCLE_MESSAGE` for the
    team itself or a team below it. Duplicates collapse.
  - `add_reason(rows, team_id, draft) -> Callable[[int], str | None]`, for `tree_options`. Returns "this team",
    "below this team, would make a loop", "already above", or None.
  - `class Preview(NamedTuple): gain: list[str]; lose: list[str]; other_role: list[str]`. Distinct person names, by
    casefold. `preview(impact: MoveImpact) -> Preview` reads `impact.gains`, `.losses` and `.changes`.

- [ ] **Step 1: Write the failing tests** (rows A top; B under A; T under A and B with main B; K under T; C top)
  - `test_without_draft_starts_from_what_is_saved`: `read_draft(rows, T, {}) == Draft((A, B), B)`.
  - `test_add_drop_and_make_main_apply_in_order`: `{"draft": "1", "above": [A, B], "main": B, "add": C, "drop": A,
    "make_main": C}` gives `Draft((B, C), C)` (above sorted by name: B, C).
  - `test_add_ignores_itself_teams_below_and_teams_already_above`: add K, T or A leaves the draft unchanged.
  - `test_dropping_the_main_passes_it_on_and_dropping_all_leaves_top_level`.
  - `test_unknown_ids_are_dropped_quietly` (Review Focus 2): `above=[A, 999]` gives `Draft((A,), A)`.
  - `test_draft_errors_refuse_unknown_and_loops`: `["999"]` gives `TEAM_CHOICE_ERROR`, `[str(K)]` gives
    `CYCLE_MESSAGE`, `main` not in above gives `TEAM_CHOICE_ERROR`, and `([str(A), str(A)], str(A))` gives
    `Draft((A,), A)` with no errors.
  - `test_add_reasons`: T gives "this team", K gives "below this team, would make a loop", A gives "already above",
    C gives None.
  - `test_preview_names_people_once`: build a `MoveImpact` with two gains for the same user on two trackers, plus one
    loss. `preview(...) == Preview(["Ana"], ["Ben"], [])`.

- [ ] **Step 2: Run them to check they fail.** Run `t.sh -q tests/test_teams_sits.py`. Expected: FAIL (module
  missing)

- [ ] **Step 3: Implement `tracker/teams/sits.py`.** `values` is anything with `.get` and `.getlist`: Flask's
  `request.args` and `request.form`, and a `werkzeug.datastructures.MultiDict` in the tests.

- [ ] **Step 4: Run them to check they pass.** Expected: PASS

- [ ] **Step 5: Commit** with the message `feat: Teams: the Where it sits draft`

---

### Task 4: The editor and Save

**Files:**
- Modify: `tracker/teams/views.py` (new `sits` and `save_sits` routes; `_render_team` gains `sits`; `add_below` and
  `parents` in the New view), `tracker/templates/teams/team_new.html` (the editor in place of the ladder),
  `tracker/activity/labels.py` (`"team_main_set": "Main team set"`), `tracker/activity/scope.py` (add
  `team_main_set` to the Teams group)
- Test: `tests/test_teams_new_view.py`

**Interfaces:**
- Consumes: Task 3 (`read_draft`, `draft_errors`, `add_reason`, `preview`, `Draft`); `move_impact`;
  `set_team_parents(..., main_id=)`; `tree_options`; `ladder`.
- Produces:
  - `GET /admin/teams/<id>/sits`, endpoint `teams.sits`, `manage_teams`. In Classic it redirects to `teams.parents`.
    In the New view it renders the team page with `sits` set: the draft, the `tree_options(rows, add_reason(...))`,
    the preview of `move_impact(db, team, frozenset(draft.above))`, and `back` (from `?back=`, as `_back_team`).
  - `POST /admin/teams/<id>/sits`, endpoint `teams.save_sits`, `manage_teams`. Form fields: `above` (repeated),
    `main`, `back`.
    - On refusal: status 400, the editor again with the posted draft, and the errors inside the editor
      (`role="alert"`).
    - With nothing changed: flash `NO_CHANGES_MESSAGE` ("info") and redirect.
    - On success: flash "Saved where <team> sits." and redirect to `back` or the team.
  - New view only: "Change where it sits" links to `teams.sits`. `add_below` redirects to `teams.sits` for the team
    being placed, with `add=<this team>&back=<this team>`. GET `teams.parents` redirects to `teams.sits`.
    `parents_new.html` is no longer rendered.
  - Editor markup (copy in Global Constraints):
    - `<section class="family sits-editor">` holds a GET `<form>` with hidden `draft=1`, `above`, `main` and `back`.
    - Each higher team is a row with its name, then either a "Main team" marker or a `<button name="make_main"
      value=id>Make main</button>`, then `<button name="drop" value=id aria-label="Take out of <team>">✕</button>`.
    - Then the "Add a team above" select (`name="add"`) with an Add button, the preview, and Cancel (a link) beside
      Save (a POST form with hidden `above`, `main` and `back`).

- [ ] **Step 1: Write the failing tests** (on the `swaps` fixture and small teams)
  - `test_editor_lists_higher_teams_with_the_main_marked`: T under A and B with main B. GET
    `/admin/teams/<T>/sits?view=new` shows "Where T sits", "Main team" next to B, "Make main" for A, and "Take out of
    A".
  - `test_editor_actions_change_the_draft_in_the_address`: GET `?draft=1&above=A&above=B&main=B&add=C` shows three
    rows. `make_main=A` moves the "Main team" marker. `drop=B` removes B's row.
  - `test_editor_preview_names_who_gains_and_loses`: on London Swaps, taking out EMEA Rates reads "lose access" and
    names Priya Nair. A draft that only changes the main reads "No change in who can see its trackers."
  - `test_save_writes_links_main_and_activity`: from {A} to {B, C} with main C gives links {B, C} with C main, and
    entries `team_parent_removed` A, `team_parent_added` B, `team_parent_added` C and `team_main_set` (before A,
    after C). The flash reads "Saved where T sits."
  - `test_only_the_main_changed_writes_one_entry` (Review Focus 4): log in as a non-administrator `manage_teams`
    holder, switch main from A to B, and get exactly one `team_main_set` entry and no refusal.
  - `test_taking_out_every_higher_team_makes_it_top_level` (Review Focus 1): no links and no `team_main_set`, and
    the team page ladder reads "this team · top level".
  - `test_save_refuses_a_loop_and_a_stale_team` (Review Focus 2 and 3): posting a team below gives 400 with
    `CYCLE_MESSAGE` in the editor. Posting id 999 gives 400 with `TEAM_CHOICE_ERROR`. Links are unchanged in both.
  - `test_save_refuses_a_change_that_raises_own_access`: follow the existing guard test (the `mine` team pattern in
    this file). The result is `SELF_PROMOTION_MESSAGE`, and the links are unchanged.
  - `test_unchanged_save_says_so`.
  - `test_put_below_opens_the_editor_of_the_team_being_placed`: GET `/admin/teams/<R>/below?team_id=<X>` in the New
    view redirects to `/admin/teams/<X>/sits?add=<R>&back=<R>`. The editor shows R in the draft. Save returns to R.
  - `test_new_view_parents_page_redirects_to_the_editor` and `test_classic_sits_redirects_to_the_parents_page`.
  - `test_main_team_set_has_a_label`: `ACTION_LABELS["team_main_set"] == "Main team set"`, and it is in the Teams
    group of `scope.py`.
  - Delete the tests of the old New view Where it sits page (the `?view=new&to=…&how=…` previews) that this
    replaces. Keep and adapt any that check the guard or loop refusals to the new routes.

- [ ] **Step 2: Run them to check they fail.** Run `t.sh -q tests/test_teams_new_view.py -k "editor or save or
  main or put_below or redirects or top_level"`. Expected: FAIL

- [ ] **Step 3: Implement the routes, template branch, labels and scope.**
  - `save_sits` takes the lock, then calls `draft_errors`, then compares with the saved links and main. Then it
    takes the snapshot, calls `set_team_parents(db, team.id, draft.above, main_id=draft.main)`, checks
    `raises_own_access` (only when the set of links changed), records the entries, and commits.

- [ ] **Step 4: Run all of `tests/test_teams_new_view.py tests/test_team_parents.py tests/test_activity.py`.**
  Expected: PASS

- [ ] **Step 5: Commit** with the message `feat: Teams New view: the Where it sits editor with one Save`

---

### Task 5: Styles, browser test, clean-up, full run

**Files:**
- Modify: `tracker/static/tracker.css`, `tracker/teams/overview.py`, `tracker/teams/views.py`
- Delete: `tracker/templates/teams/parents_new.html`
- Test: `tests/test_teams_new_view_browser.py`

- [ ] **Step 1: Write the browser test**
  `test_where_it_sits_editor_end_to_end`:
  1. On a team page, click "Change where it sits".
  2. Choose a team in "Add a team above" and click Add; the row appears.
  3. Click "Make main" on it, and check the preview text.
  4. Save, and land on the team page with "Saved where …".
  5. The Structure card shows the team under its new main.
  6. The test ends with `clean(page)`, which checks for no CSP or script errors.

  Extend `test_no_page_scrolls_sideways_at_phone_width` with `/admin/teams/<id>/sits`.

- [ ] **Step 2: Run it.** It passes once the styles are in, and fails only on layout if they are missing.

- [ ] **Step 3: Style the editor** (`.sits-editor` rows, the main marker, the gain and loss preview colours, using
  `var(--success)` and `var(--danger)` mixes as the old `.sits-change` did).
  - Delete `parents_new.html`, `paths_to` and `MAX_CHAINS` (check with `grep -rn` that they have no callers), and the
    New view branch of `_render_parents`.
  - Delete the CSS rules whose classes no longer appear anywhere, with the PR 1 rule: drop a rule only when every
    class in its selector is unused.

- [ ] **Step 4: Run the Teams, activity and template tests, then the full suite**

Run: `t.sh -n 6 -q tests/test_teams_layout.py tests/test_teams_sits.py tests/test_teams_new_view.py tests/test_teams_new_view_browser.py tests/test_team_parents.py tests/test_team_tree.py tests/test_activity.py tests/test_templates.py tests/test_migration_0021.py tests/test_migration_matches_models.py`, then `t.sh -n 6`
Expected: all pass. Some date-dependent tests in entries, inputs and reminders fail on main around midnight going
into Friday. If any of them fail, check them against main and name them in the hand-over.

- [ ] **Step 5: Commit** with the message `refactor: Teams: remove the old Where it sits page`, then hand over
  (push with Windows git.exe, open the PR with gh.exe `--body-file`, and leave the merge to the owner).
