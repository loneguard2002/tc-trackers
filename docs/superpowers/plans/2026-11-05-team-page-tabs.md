# Team Page Tabs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild a team's page with a compact header (edit in place, Delete beside the actions), tabs for People,
Teams below and Trackers, searchable sortable paged tables, and ways to place existing teams and move trackers into the
team from its page.

**Architecture:** Server-rendered, as today. The tab and the edit mode are query parameters on the team's address
(`?tab=people|below|trackers`, `?edit=1`). Tables reuse the Lists table macros and `lists.js`, which gains token
filters and paging. Placing an existing team below reuses the Higher teams preview of the lower team, with a `back`
parameter; moving trackers is a new preview-then-confirm route beside the team.

**Tech Stack:** Flask 3.1, SQLAlchemy 2 (no `relationship()`), Jinja, Postgres, plain ES5 static scripts, pytest with
Playwright browser tests.

**Spec:** `docs/superpowers/specs/2026-11-05-team-page-tabs-design.md` (mockup linked in it).

**Tests:** only the files a task names (owner's rule: no full suite). From the worktree, sandbox disabled:
`WT=$PWD ../tools/acc-test.sh <files> -q`. Ruff check and format on changed files.

## Global Constraints

- Strict CSP (no inline script or style), CSRF on every POST, works without JavaScript, light and dark themes, no
  page-level horizontal scroll at 390 px, British formal copy in the active voice, every change to Activity.
- Main actions carry an icon and a label; Delete team (bin) and every row Remove (×) are icon-only with the full name
  as `title` and screen-reader text, for example "Remove Sam from Infrastructure".
- Tree help, beside the tree card's "Teams" title: "A team in several groups shows under each, marked “Also under”.
  Numbers count the people who reach a team."
- Pager: "Showing 1–25 of 40 people", Rows per page 25 / 50 / 100 (25 to start), Previous, page numbers, Next; hidden
  without JavaScript, when all rows show.
- A moved tracker keeps every region and gains the team's region when it lacks it; nothing is removed.
- The page and every new route need `manage_teams`, as today.

## Review Focus

1. **Moving trackers would raise the actor's own access** (they belong to the team): refused with
   `SELF_PROMOTION_MESSAGE`, nothing moved. Task 4, `test_move_refused_when_it_raises_own_access`.
2. **A stale or forged tracker id on confirm** (unknown, deleted, already in the team, "abc"): 400 with a message,
   nothing moved, no Activity. Task 4, `test_move_with_a_bad_tracker_id_moves_nothing`.
3. **An unknown `?tab=` value:** the People tab, status 200. Task 1, `test_unknown_tab_shows_people`.
4. **A failed Edit details save:** the header stays in edit mode with the typed values and the error beside the
   form. Task 1, `test_failed_save_keeps_edit_mode_and_values`.
5. **A forged `back` value** ("abc", an unknown team): ignored; the Higher teams screen redirects as today. Task 3,
   `test_back_to_an_unknown_team_is_ignored`.

---

### Task 1: Header, edit in place, Delete beside the actions, tabs

**Files:**
- Modify: `tracker/teams/views.py` (`_render_team`, `view`, `rename`, `delete_team`), `tracker/templates/teams/team.html`,
  `tracker/templates/teams/_tree.html` (or wherever the tree card's title and help live), `tracker/static/tracker.css`
- Test: `tests/test_team_page.py` (new); update `tests/test_teams.py`, `tests/test_team_places.py`,
  `tests/test_teams_browser.py`, `tests/test_templates.py` where they rely on the Details section or `#details`

**Interfaces:**
- Produces:
  - `TEAM_TABS = ("people", "below", "trackers")` in `tracker/teams/views.py`; `_render_team(team, errors, status,
    form=None, editing=False, tab="people")` replaces `open_details`.
  - `GET /admin/teams/<id>?tab=<tab>&edit=1`; `teams.view` reads both. Links: `url_for("teams.view", team_id=…,
    tab="below")`.
  - The template exposes one tab panel per tab with `id="tab-people"`, `id="tab-below"`, `id="tab-trackers"`; only the
    current one is rendered.

- [ ] **Step 1: Failing tests** in `tests/test_team_page.py`:
  - `test_header_shows_place_under_and_description_and_actions`: the name in `<h1>`, the place pill ("EMEA" and
    "London, United Kingdom", or the region code alone), "Under" with a link to each higher team, the description,
    an "Edit details" link to `?edit=1`, a "Higher teams" link, and a Delete button with `title="Delete team"` in the
    header; no "Details" section and no `id="details"`.
  - `test_tabs_link_with_counts_and_mark_the_current_one`: three links `?tab=people`, `?tab=below`, `?tab=trackers`
    reading "People" + count, "Teams below" + count, "Trackers" + count; the current one has `aria-current="page"`.
  - `test_unknown_tab_shows_people` (Review Focus 3).
  - `test_edit_mode_shows_the_form_in_the_header`: `?edit=1` renders Name, Region, Location ("No specific location"
    first), Description, "Save details" and a Cancel link back to the page; the read-only header is not rendered.
  - `test_failed_save_keeps_edit_mode_and_values` (Review Focus 4): an empty name gives 400, the form in the header,
    the typed description kept.
  - `test_delete_is_disabled_with_the_reason_when_teams_are_below`: a disabled control with `HAS_CHILDREN_MESSAGE` as
    its title and screen-reader text; without teams below, a POST form to `teams.delete` with the existing
    confirmation text.
  - `test_tree_help_sits_beside_the_title` with the exact Global Constraints copy.
- [ ] **Step 2: Run them; watch them fail.**
- [ ] **Step 3: Implement.** The tab bar is the bottom edge of the header card, styled like the Lists tabs
  (`tabs` class). The delete confirmation reuses the existing `data-inline-confirm` behaviour. A delete refused by the
  blocker re-renders the page with the error in the header.
- [ ] **Step 4: Run** `tests/test_team_page.py tests/test_teams.py tests/test_team_places.py tests/test_templates.py
  tests/test_teams_browser.py`; all pass. Screenshots, light and dark, 1440 and 390 px, under the scratchpad; look
  at them.
- [ ] **Step 5: Commit** `feat: team header with edit in place and tabs`

### Task 2: Tables with search, sorting, filters and pages

**Files:**
- Modify: `tracker/static/lists.js`, `tracker/templates/lists/_table.html` (a pager macro), `tracker/templates/teams/team.html`,
  `tracker/teams/views.py` (row data), `tracker/static/tracker.css`
- Test: `tests/test_team_page.py`, `tests/test_lists_browser.py` (paging), `tests/test_lists_admin.py` (unchanged
  behaviour), `tests/test_teams_browser.py`

**Interfaces:**
- Consumes: Task 1's tab panels.
- Produces:
  - `lists.js`: a row's `data-status` may hold several space-separated tokens; a status button matches a row holding
    its token ("all" matches every row). Paging: a `[data-pager-for="<table id>"]` block below a table; 25 rows to
    start; changing search, filter or sort returns to page 1.
  - `pager(table_id, noun_plural, total)` macro in `lists/_table.html`, hidden until `lists.js` reveals it.

- [ ] **Step 1: Failing tests:**
  - `test_people_table_columns_filters_and_add_form_on_top`: the Add member form comes before the search box; columns
    Person, Route, Role; status buttons All, Direct, From teams above; direct rows have the role select and an
    icon-only Remove with `title="Remove <name> from <team>"`; inherited rows are read-only.
  - `test_teams_below_and_trackers_tables_columns`: Teams below has Team, Place, People, Trackers; Trackers has Tracker,
    Business line, Regions, Status (Active / Archived) and an Access link.
  - Browser, in `tests/test_lists_browser.py`: `test_pager_pages_rows_and_resets_on_search` (30 rows: page 1 shows 25
    and "Showing 1–25 of 30"; Next shows 5; typing a search returns to page 1; Rows per page 50 shows all; no
    horizontal scroll at 390 px); and `test_status_tokens_match_a_row_in_two_groups` (a row "direct inherited" shows
    under both Direct and From teams above).
- [ ] **Step 2: Run them; watch them fail.**
- [ ] **Step 3: Implement.** The Lists pages keep working unchanged (a single token behaves as today).
- [ ] **Step 4: Run** `tests/test_team_page.py tests/test_lists_admin.py tests/test_lists_browser.py
  tests/test_teams_browser.py`; all pass. Screenshots as in Task 1.
- [ ] **Step 5: Commit** `feat: searchable, sortable, paged tables on the team page`

### Task 3: Teams below: place an existing team, remove from under

**Files:**
- Modify: `tracker/teams/views.py` (new `add_below`; `parents`, `change_parents`, `_render_parents` honour `back`),
  `tracker/templates/teams/team.html`, `tracker/templates/teams/parents.html`
- Test: `tests/test_team_page.py`, `tests/test_team_parents.py`

**Interfaces:**
- Consumes: Task 1's `teams.view(..., tab="below")`.
- Produces:
  - `GET /admin/teams/<id>/below?team_id=<child>` → endpoint `teams.add_below`: redirects to
    `teams.parents(team_id=child, add=<id>, back=<id>)`; a missing or unknown child re-renders the team page, tab
    below, status 400, with `TEAM_CHOICE_ERROR`.
  - `back` (a team id) on the Higher teams GET and as a hidden field in its confirm form; after a confirmed change,
    `change_parents` redirects to `teams.view(team_id=back, tab="below")` when `back` names an existing team, else as
    today. The preview's Cancel link goes there too.

- [ ] **Step 1: Failing tests:**
  - `test_top_panel_offers_existing_teams_without_loops`: the panel (Existing team, "Add selected team", "or",
    "New team") comes first in the tab; the select lists every team except this team, its direct lower teams and its
    higher teams at any depth.
  - `test_add_selected_team_previews_then_returns_to_the_tab`: GET add_below redirects to the child's preview; the
    confirm POST with `back` adds the link, logs `team_parent_added` and redirects to `?tab=below`.
  - `test_row_remove_previews_then_returns`: the row's icon-only Remove links to the child's preview with
    `remove=<id>&back=<id>`; confirming removes the link and returns to the tab.
  - `test_back_to_an_unknown_team_is_ignored` (Review Focus 5).
- [ ] **Step 2: Run them; watch them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `tests/test_team_page.py tests/test_team_parents.py tests/test_teams_browser.py`; all pass.
- [ ] **Step 5: Commit** `feat: place existing teams below a team from its page`

### Task 4: Trackers: move trackers into the team, remove

**Files:**
- Create: `tracker/teams/tracker_moves.py` (the preview and the move), `tracker/templates/teams/move_trackers.html`
- Modify: `tracker/teams/views.py` (routes), `tracker/templates/teams/team.html`, `tracker/trackers/views.py`
  (`set_team` destination `"team"`)
- Test: `tests/test_team_trackers.py` (new), `tests/test_tracker_access.py`

**Interfaces:**
- Consumes: Task 1's tabs; `snapshot_access`, `raises_own_access`, `SELF_PROMOTION_MESSAGE`, `record`, `change`, the
  region-adding helper used by tracker settings (`set_tracker_regions` in `tracker/lists/catalogue.py`), and
  `tracker_roles`.
- Produces:
  - `?tab=trackers&add=1` renders the picker panel in the tab: a search box and a table of trackers not in this team
    (tick box `name="tracker_id"`, Tracker, Current team, Regions after the move with "+ EMEA" when added), a GET
    form to `teams.move_trackers`, button "Move here".
  - `GET /admin/teams/<id>/trackers?tracker_id=…` → `teams.move_trackers`: the preview page (each tracker with its
    current team and regions after; then who gains, loses or changes a role, as the Higher teams preview lists them);
    `POST` the same address → `teams.confirm_move_trackers` moves them all in one transaction.
  - `tracker_move_impact(session, team, trackers) -> MoveImpact` in `tracker_moves.py`, reusing `MoveImpact` and
    `AccessChange` from `tracker/teams/impact.py`; savepoint, always rolled back.
  - `move_trackers(session, actor, team, trackers) -> None`: sets `team_id`, adds `team.region_id` to each tracker's
    regions when missing, records `tracker_team_changed` per tracker (detail `change(old team path, new team path)`)
    and the tracker's existing regions-changed Activity action when a region is added.
  - Row × Remove: a POST form to `trackers.set_team` with `team_id=""`, `next="team"`, `team=<id>` and the existing
    confirmation text; `set_team` redirects to `teams.view(team_id, tab="trackers")` for that destination when the
    actor still has `manage_teams`.

- [ ] **Step 1: Failing tests** (`tests/test_team_trackers.py`):
  - `test_picker_lists_trackers_outside_the_team_with_regions_after`: archived trackers included and marked; a tracker
    in APAC shows "APAC" and "+ EMEA"; one already in EMEA shows no addition; a team with no region adds nothing.
  - `test_preview_lists_access_changes_and_confirm_moves_and_adds_the_region`: after confirming, both trackers have
    `team_id` = the team, the APAC one has regions APAC and EMEA, Activity has one `tracker_team_changed` per tracker
    and the regions entry; flash "Moved 2 trackers to Infrastructure."; redirect to `?tab=trackers`.
  - `test_move_refused_when_it_raises_own_access` (Review Focus 1).
  - `test_move_with_a_bad_tracker_id_moves_nothing` (Review Focus 2), including no tracker chosen (400, "Choose at
    least one tracker.").
  - `test_row_remove_puts_the_tracker_in_no_team_and_returns` (in `tests/test_tracker_access.py` or the new file).
- [ ] **Step 2: Run them; watch them fail.**
- [ ] **Step 3: Implement.** Lock order as `set_team` does: flush inside the guard, catch `IntegrityError` with
  `TEAM_CHOICE_ERROR`.
- [ ] **Step 4: Run** `tests/test_team_trackers.py tests/test_tracker_access.py tests/test_team_page.py`; all pass.
  Screenshots of the picker and preview.
- [ ] **Step 5: Commit** `feat: move trackers into a team from its page`
