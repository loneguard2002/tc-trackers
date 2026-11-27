# Teams redesign, PR 3 (Whole structure) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the old org chart page with the full-screen Whole structure from the approved mock-up. It reads left to
right with one column per level and fits the screen. It can switch direction, zoom, fold branches, search and
light up lines. Shared teams show dotted lines from their other higher teams.

**Architecture:**
- The server puts every team's data on each New view Teams page as one JSON block: id, name, main team, other higher
  teams, place, people count and address.
- A new script, `tracker/static/teams-structure.js`, lays the teams out as a tidy tree on main teams. It draws HTML
  boxes on an absolutely positioned stage, with SVG lines behind them, inside a hidden full-screen layer.
- The "Whole structure" button opens the layer. The old `structure.html` / `_chart.html` page and its script and
  styles are removed. `/admin/teams/structure` becomes a redirect.

**Tech Stack:** Flask, Jinja2, vanilla ES5 JavaScript (no library), CSS, pytest + Playwright.

**Spec:** `docs/superpowers/specs/2026-11-26-teams-simple-redesign-design.md` (section 4.9; PR 3 of section 5)

## Global Constraints

- CSP is `script-src 'self'; style-src 'self'`:
  - no inline executable script and no `style=` attributes in markup;
  - positions and the scale are set through the CSSOM (`el.style.left`, `el.style.transform`), which the CSP allows;
  - the data block is `<script type="application/json">`, written with Jinja's `|tojson`; it is never run.
- ES5 only, as in `teams-new.js` (no `let`/`const`, arrow functions or template literals). The script starts with
  `"use strict"` inside an IIFE and uses no inline handlers.
- Copy, word for word from the spec:
  - "Whole structure"
  - the stats line "N teams · M levels shown · K shared" (singular "1 team", "1 level shown")
  - "Find a team"
  - Direction: "Left to right" (default), "Top to bottom"
  - Zoom: "−", "Fit", a percentage that returns to 100% when pressed, "+"
  - "Fold all" / "Unfold all", "Close"
  - column labels "Top", "Level 2", "Level 3", …
  - box meta "Region · City · N people" (place parts left out when unset; "1 person")
  - the legend: "Where a team sits", "Also sits under (shared team)", "Point at a team to light up its lines. Click a
    name to open the team. Use − / + on a box to fold or unfold a branch."
- Layout numbers, fixed so the tests can rely on them:
  - box 200 × 56 px; padding 24 px; label band 30 px;
  - left to right: 80 px between columns, 14 px between rows;
  - top to bottom: 18 px between columns, 64 px between levels;
  - Fit scale = `min((viewportWidth − 8) / width, (viewportHeight − 8) / height, 1.25)`, never below 0.2;
  - zoom steps are × 1.2 or ÷ 1.2, kept between 0.2 and 2.
- Teams are placed under their main team (`layout.main_parent_ids`). A team in a damaged loop that cannot be reached
  from the top is left out, as the Structure card leaves it out. Every walk keeps a visited set.
- Classic is untouched. Tests keep `TEAMS_DEFAULT_VIEW = "classic"`.
- Commit identity, CRLF, test runner and hand-over are as in the PR 1 and PR 2 plans. Task 4 ends with a full
  `pytest -n 6` run. Some date-dependent tests in entries, inputs and reminders already fail on main on Fridays;
  compare any failures against main using a scratch database, as was done for PR 2.

## Review Focus

1. **A damaged loop** (two teams under each other, reachable from nowhere): the layer opens with no script error and
   leaves those teams out. The test is in Task 2.
2. **A shared team whose other higher team is folded away:** no dotted line points at a hidden box and nothing
   errors. Unfolding draws the line. The test is in Task 3.
3. **A 100-character team name:** the box keeps its size and the name is cut with an ellipsis. The full name is in
   the box link's `title`. The test is in Task 2.
4. **A big structure** (40 teams over 5 levels): Fit keeps every box inside the viewport. The test is in Task 3.
5. **Keyboard use:** opening puts focus in "Find a team", Escape closes, and focus returns to the "Whole structure"
   button. Tab reaches the box links. The test is in Task 2.

---

### Task 1: The data and the layer markup

**Files:**
- Modify: `tracker/teams/overview.py` (new `structure_items`), `tracker/teams/views.py` (`_structure_context`, the
  `structure` route), `tracker/templates/teams/_simple_head.html` (the button and the layer include)
- Create: `tracker/templates/teams/_structure_layer.html`
- Test: `tests/test_teams_layout.py` (`structure_items`, no database), `tests/test_teams_new_view.py`

**Interfaces:**
- Consumes: `main_parent_ids` (`layout.py`); `Place` (`lists/catalogue.py`: `region_code`, `city`); `reach_counts`.
- Produces:
  - `structure_items(rows: list[TeamRow], places: dict[int, Place], reach: dict[int, int]) -> list[dict]`, in
    `overview.py`. One dict per team, by name:
    - `{"id": int, "name": str, "main": int | None, "others": list[int], "place": str, "people": int}`
    - `others` holds the other higher teams' ids, by name.
    - `place` is `"EMEA · London"`, `"EMEA"`, or `""` when unset.
  - `_structure_context(db, rows, current_id, new_open=False, tree: dict | None = None)`:
    - adds `structure_items`, the list above with `"url": url_for("teams.view", team_id=id)` added to each item;
    - reuses `tree["reach"]` and `tree["places"]` when `tree` is passed. The two callers already hold the
      `_tree_context` result; pass it.
  - The layer markup, in `_structure_layer.html`, included at the end of `_simple_head.html`:
    - `<div class="structure-layer" id="whole-structure" role="dialog" aria-modal="true"
      aria-labelledby="whole-structure-title" data-structure-layer data-current-team="{{ current_id or '' }}" hidden>`
    - Inside it: a header with `h2#whole-structure-title` "Whole structure" and `[data-structure-stats]`; the search
      `input#structure-find[data-structure-find]` with a visually hidden label "Find a team"; the Direction buttons
      `[data-direction="lr"|"tb"]` with `aria-pressed`; the Zoom buttons `[data-zoom="out"|"fit"|"reset"|"in"]`
      ("out" and "in" carry `aria-label` "Zoom out" and "Zoom in"); `[data-fold-all]` "Fold all"; and
      `[data-structure-close]` "Close".
    - Then the viewport, `div.structure-viewport[data-structure-viewport]` >
      `div.structure-sizer[data-structure-sizer]` > `div.structure-stage[data-structure-stage]` >
      `svg.structure-lines[data-structure-lines][aria-hidden=true]`.
    - Then the legend (copy in Global Constraints), and `<script type="application/json"
      id="structure-data">{{ structure_items|tojson }}</script>`.
  - The header button in `_simple_head.html`: `<a class="button" href="#whole-structure" data-open-structure>Whole
    structure</a>`, loading `teams-structure.js` with `defer`.
  - `GET /admin/teams/structure` (still `manage_teams`) redirects to `url_for("teams.index",
    _anchor="whole-structure")`.

- [ ] **Step 1: Write the failing tests**
  - `test_teams_layout.py::test_structure_items_carry_main_others_place_and_people`:
    - rows: Group (top); EMEA under Group; Data under Group; Shared under EMEA and Data with `main_id=EMEA`;
    - places: `{EMEA: Place(1, "EMEA", 2, "London, United Kingdom", "London")}`;
    - reach: `{Shared: 3}`;
    - Shared's item is `{"id": 4, "name": "Shared", "main": 2, "others": [3], "place": "", "people": 3}`;
    - EMEA's place is `"EMEA · London"`;
    - Group's item has `"main": None` and `"others": []`;
    - the items are sorted by name.
  - `test_teams_new_view.py::test_team_page_carries_the_whole_structure_data`:
    - on `swaps`, parse the JSON in `<script type="application/json" id="structure-data">`;
    - there are 3 items; London Swaps' `main` is EMEA Rates' id; its `url` is `/admin/teams/<id>`; its `people` is 6.
  - `...::test_whole_structure_button_and_hidden_layer`:
    - the head has `href="#whole-structure"` with `data-open-structure`;
    - the layer is `hidden`, with `role="dialog"` and `aria-modal="true"`;
    - it holds "Fold all", "Left to right" and "Top to bottom", and the legend line "Also sits under (shared team)".
  - `...::test_structure_data_escapes_names`: a team named `</script><b>x` appears in the JSON block escaped
    (`</script>`), and the page holds no `<b>x`.
  - `...::test_old_structure_address_redirects`: GET `/admin/teams/structure` gives 302 to a Location ending
    `/admin/teams#whole-structure`. Keep the 403 test for a user without `manage_teams`.
  - Replace the old `/admin/teams/structure` tests (the chart page shows each team, marks Also under, carries the
    dotted-lines data, the empty chart and the "Back to teams" route test) with the ones above.

- [ ] **Step 2: Run them to check they fail**

Run: `t.sh -q tests/test_teams_layout.py tests/test_teams_new_view.py -k "structure"`
Expected: FAIL

- [ ] **Step 3: Implement** `structure_items`, the context change, the partial, the button and the redirect. An empty
  `teams-structure.js` file with only the IIFE shell is enough for this task.

- [ ] **Step 4: Run them to check they pass.** Run all of `tests/test_teams_new_view.py` and
  `tests/test_teams_layout.py`. Expected: PASS

- [ ] **Step 5: Commit** with the message `feat: Teams New view: the Whole structure data and layer`

---

### Task 2: Open, lay out, draw, close

**Files:**
- Modify: `tracker/static/teams-structure.js`, `tracker/static/tracker.css`
- Test: `tests/test_teams_structure_browser.py` (new; reuse `admin_page`, `clean` and the `swaps` fixture as
  `tests/test_teams_new_view_browser.py` does)

**Interfaces:**
- Consumes: the markup and JSON of Task 1.
- Produces, in the DOM, so that Task 3 and the tests can rely on these names:
  - Each box is `div.structure-box[data-team-id]` with classes `is-shared` (when `others` is non-empty) and
    `is-current` (when the id is the layer's `data-current-team`). It is positioned in stage pixels.
  - Inside each box: `a.structure-box-open[href=url][title=full name]`, which holds `span.structure-box-name` and
    `span.structure-box-meta`; then, for a team with teams below it on the main tree,
    `button.structure-box-fold` (added in Task 3).
  - Lines: `path.structure-line.is-solid` (from the main team) and `path.structure-line.is-dotted` (from each other
    visible higher team), each with `data-from` and `data-to`. Each dotted line ends in a
    `circle.structure-line-end`.
  - Column labels: `div.structure-level`, reading "Top", "Level 2", and so on. In left to right they sit above each
    column; in top to bottom, at the left of each level.
  - The stats text in `[data-structure-stats]`.
  - Line shape: from the parent's right middle to the child's left middle in left to right, or from the parent's
    bottom centre to the child's top centre in top to bottom, as a cubic curve. A dotted line whose parent is not
    before the child goes round underneath, from the bottom of one box to the bottom of the other, as in the
    mock-up. Dotted ends are offset 8 px (left to right) or 30 px (top to bottom), so they do not cover the solid
    line.
  - Open:
    - the button click or a page load with `#whole-structure` opens the layer;
    - it sets `body.structure-open` (no page scroll), lays out with Fit on, and focuses `#structure-find`.
  - Close:
    - Close, Escape, or a click on the layer backdrop (`event.target === layer`) hides it;
    - it removes the body class, clears `#whole-structure` from the address with `history.replaceState`, and
      returns focus to the button.
  - Light up: pointing at or focusing a box adds `is-lit` to the lines whose `data-from` or `data-to` is that team,
    and `is-linked` to the boxes at their other end.
  - Clicking a box name follows its link: the team page loads and the layer is gone.

  Layout algorithm (tidy tree on main teams):
  - Walk from the top-level teams by name. A team with no visible children takes the next row; a parent's row is the
    middle of its first and last child's rows.
  - The depth is the column (left to right) or the level (top to bottom).
  - Skip any team already on the path, and leave out teams that cannot be reached from the top.

- [ ] **Step 1: Write the browser tests** (each ends with `clean(page)`)
  - `test_the_button_opens_the_layer_with_every_team`: on `swaps` plus a top-level "APAC Desk":
    - after clicking "Whole structure", the layer is visible, with 4 `.structure-box`;
    - the stats line reads "4 teams · 3 levels shown · 0 shared";
    - the labels are "Top", "Level 2" and "Level 3";
    - the current team's box has `is-current`.
  - `test_left_to_right_places_levels_in_columns_and_top_to_bottom_in_rows`:
    - in left to right, a team's box x is greater than its main team's box x, and their y values may be equal;
    - after "Top to bottom", the child's y is greater than the parent's, and `[data-direction="tb"]` has
      `aria-pressed="true"`.
  - `test_shared_team_gets_a_dotted_line_and_an_amber_edge`:
    - setup: Alpha, Beta, and Shared under both with `main=alpha`;
    - one `path.is-dotted` with `data-from` Beta and `data-to` Shared;
    - one `path.is-solid` (Alpha→Shared: the solid line runs from the main team only);
    - Shared's box has `is-shared`.
  - `test_pointing_at_a_box_lights_its_lines`: hover Shared, and its lines get `is-lit` while Beta's box gets
    `is-linked`.
  - `test_escape_closes_and_focus_returns_to_the_button` (Review Focus 5):
    - opening puts focus on `#structure-find`;
    - Escape hides the layer;
    - the focused element is the "Whole structure" link.
  - `test_close_and_backdrop_close_the_layer`, and `test_the_address_opens_the_layer` (goto
    `/admin/teams/<id>#whole-structure`, and the layer is visible).
  - `test_clicking_a_name_opens_the_team`: click London Swaps' box link, and the URL ends `/admin/teams/<id>`.
  - `test_a_damaged_loop_is_left_out_without_errors` (Review Focus 1): insert teams X and Y with `TeamParent` rows X
    under Y and Y under X (`is_main` true for both), then open the layer. There are no errors, and no box for X or
    Y.
  - `test_a_long_name_keeps_the_box_size` (Review Focus 3): with a 100-character name, the box's bounding width is
    200 × scale (within 1 px), and the link's `title` is the full name.

- [ ] **Step 2: Run them to check they fail.** Run `t.sh -q tests/test_teams_structure_browser.py`. Expected: FAIL
  (no boxes yet)

- [ ] **Step 3: Implement** the open/close, the layout, boxes, lines, labels, stats and lighting in
  `teams-structure.js`, and the styles in `tracker.css`.
  - The layer fills the window at `z-index` above the top bar.
  - The panel is a grid: header, viewport (`overflow: auto`), legend.
  - Boxes have ellipsis on name and meta.
  - `.is-shared` gets a 4 px amber left edge (`var(--warning)`).
  - Solid lines use `var(--field-border)`; dotted lines use `var(--warning)` with `stroke-dasharray: 6 5`.
  - `.is-lit` makes lines 3.5 px wide (solid lines turn `var(--primary)`); `.is-linked` gets a 3 px primary ring.
  - The scale for this task is Fit only; Task 3 adds the zoom buttons.

- [ ] **Step 4: Run them to check they pass.** Expected: PASS

- [ ] **Step 5: Commit** with the message `feat: Teams Whole structure: open, lay out, draw and close`

---

### Task 3: Fit and zoom, fold, search

**Files:**
- Modify: `tracker/static/teams-structure.js`, `tracker/static/tracker.css`
- Test: `tests/test_teams_structure_browser.py`

**Interfaces:**
- Consumes: Task 2's DOM names.
- Produces:
  - Zoom:
    - "Fit" (`aria-pressed="true"` while it is on) recomputes the scale on open, on direction change, on fold
      changes and on window resize;
    - "−" and "+" turn Fit off and step the scale;
    - the percentage button shows `Math.round(scale × 100) + "%"` and returns to 100% when pressed;
    - the sizer takes the scaled width and height, so the viewport scrolls.
  - Fold:
    - `button.structure-box-fold` reads "−" with `aria-label` "Fold <name>" while open, and "+N" with `aria-label`
      "Unfold <name>" while folded (N is every team below on the main tree);
    - folding hides the team's descendants and re-lays out;
    - "Fold all" folds every team below the top level that has teams below it, so the top two levels stay
      visible, and the button becomes "Unfold all"; pressed again, everything opens.
  - Search:
    - typing in "Find a team" (case-insensitive, by name) unfolds the main-tree path to each match;
    - matches get `is-match`, and the stage gets `is-searching`, which fades boxes that are not matches to 0.35;
    - an empty box clears it.
  - The stats line's "levels shown" follows folding.

- [ ] **Step 1: Write the browser tests**
  - `test_fit_keeps_a_big_structure_on_screen` (Review Focus 4):
    - 40 teams over 5 levels (8 under each of 4 chains);
    - after opening, every `.structure-box` bounding box lies inside the viewport's bounding box;
    - "Fit" has `aria-pressed="true"`.
  - `test_zoom_buttons_step_and_reset`:
    - "+" makes the percentage rise and turns Fit off;
    - the percentage button reads "100%" after it is pressed;
    - "Fit" turns Fit back on.
  - `test_folding_a_branch_hides_it_and_says_how_many`:
    - on `swaps`, fold EMEA Rates;
    - London Swaps' box is gone; the button reads "+1" with aria-label "Unfold EMEA Rates"; the stats read "2
      levels shown";
    - unfolding brings the box back.
  - `test_fold_all_keeps_the_top_two_levels`:
    - with 4 levels, after "Fold all" only Top and Level 2 boxes show and the button reads "Unfold all";
    - after pressing it again, all show.
  - `test_search_unfolds_and_marks_matches`:
    - fold all, then type "swaps";
    - London Swaps' box is visible and has `is-match`; the stage has `is-searching`; Global Markets has no
      `is-match`;
    - clearing the box removes `is-searching`.
  - `test_a_folded_other_parent_draws_no_dotted_line` (Review Focus 2):
    - Shared under Alpha (main) and Beta, where Beta sits under Group;
    - fold Group, and there are no `path.is-dotted` and no errors;
    - unfold, and the dotted line is back.

- [ ] **Step 2: Run them to check they fail.** Expected: FAIL

- [ ] **Step 3: Implement** zoom, fold, fold all and search.

- [ ] **Step 4: Run all of `tests/test_teams_structure_browser.py`.** Expected: PASS

- [ ] **Step 5: Commit** with the message `feat: Teams Whole structure: fit and zoom, fold, search`

---

### Task 4: Remove the old chart, phone width, full run

**Files:**
- Delete: `tracker/templates/teams/structure.html`, `tracker/templates/teams/_chart.html`
- Modify:
  - `tracker/static/teams-new.js`: delete the chart search and dotted-line blocks, and keep the New team form code;
  - `tracker/static/tracker.css`: delete the `.org-*` rules and the 640 px org-chart block;
  - `tracker/teams/overview.py`: delete `FOLD_FROM_DEPTH`, `FOLD_OVER` and `ChartNode.folded` / `also_ids`, if no
    caller remains;
  - `tracker/teams/views.py`: the `structure` route keeps only the redirect.
- Test: `tests/test_teams_new_view.py` (delete `test_deep_wide_branches_fold` and the `FOLD_OVER` import),
  `tests/test_teams_new_view_browser.py` (delete the chart search and dotted-line tests that Task 2 and Task 3
  replace), `tests/test_teams_structure_browser.py`

- [ ] **Step 1: Write the phone test**
  `test_the_layer_works_at_phone_width`:
  - at 390 × 844, open the layer;
  - the header controls wrap inside the window (`document.documentElement.scrollWidth <= window.innerWidth`);
  - Fit shows every box inside the viewport, and Close works.

  Also add `/admin/teams/<id>` with the layer open to `test_no_page_scrolls_sideways_at_phone_width`.

- [ ] **Step 2: Run it.** Fix the layout until it passes.

- [ ] **Step 3: Delete the old code.** Check each name with `grep -rn` before deleting it. Drop CSS rules only when
  no template, script or Python file uses every class in the selector. Keep any class built at render time, as PR 2
  learned with `fam-depth-N`.

- [ ] **Step 4: Run the Teams, template and browser tests, then the full suite**

Run: `t.sh -n 6 -q tests/test_teams_layout.py tests/test_teams_new_view.py tests/test_teams_new_view_browser.py tests/test_teams_structure_browser.py tests/test_templates.py`, then `t.sh -n 6`
Expected: Teams and template tests all pass. Compare any full-suite failures against main using a scratch database,
and name them in the hand-over.

- [ ] **Step 5: Commit** with the message `refactor: Teams: remove the old org chart page`, then hand over (push with
  Windows git.exe, open the PR with gh.exe `--body-file`, and leave the merge to the owner).
