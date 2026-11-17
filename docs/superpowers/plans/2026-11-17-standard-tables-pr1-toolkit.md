# Standard tables, PR 1: the toolkit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Grow the shared table toolkit (`lists/_table.html` + `lists.js`) to the full standard set and apply it to the
tables that already use it: Lists (Locations, Regions, Business lines), Users and the Team page.

**Architecture:** Every behaviour stays in `setUpTable` in `tracker/static/lists.js` (browser-side, ES5, revealed by
JavaScript, everything visible without it) and the macros in `tracker/templates/lists/_table.html`. The two footers
(`table_foot`, `pager`) merge into one `table_pager` macro. View state goes into the query string through
`history.replaceState`. Sticky headings and phone cards are CSS in `tracker/static/tracker.css`, with `lists.js`
labelling each cell from its column heading. PRs 2 and 3 get their own plans once this lands.

**Tech Stack:** Flask, Jinja, vanilla ES5 JavaScript, CSS; pytest + Playwright (Chromium) browser tests.

**Spec:** `docs/superpowers/specs/2026-11-17-standard-tables-design.md`

## Global Constraints

- Strict Content Security Policy: no inline scripts, no inline styles, no `style=` attributes.
- `lists.js` stays plain ES5 (no modules, no arrow functions), like the rest of the file.
- Without JavaScript every row shows, the controls stay `hidden`, and nothing breaks.
- Copy in British English, no contractions. Footer copy exactly: `Showing {first}–{last} of {matching} {noun}` when
  more than one page matches, `Showing {matching} of {total} {noun}` otherwise, followed by ` · {active} active` on
  tables that pass an active count. Button copy: `Clear filters`.
- Rows per page: 25 (default), 50, 100; the rows-per-page select, Previous, page numbers and Next show only when more
  than 25 rows match.
- Address keys: `q`, `filter`, `sort` (`name` ascending, `-name` descending), `page`, `size`; a table with
  `data-state-prefix="people-"` reads and writes `people-q`, `people-filter` and so on. Defaults are never written
  (no `page=1`, no `size=25`, no default sort, no `filter=all`, no empty `q`). Locations keeps its existing `region`.
- Sorting: by `data-sort-type` on the heading (`text` default, `number`, `date` as ISO `YYYY-MM-DD`); text ignores case
  with natural numbers (LD5 before LD10); empty values last in both directions; ties keep the server's order.
- Row actions: the PR 1 tables already have the standard (icon buttons side by side, in-row question via
  `row_actions` and Users' `button-icon`); PR 2 brings the other tables to it. Do not change them here.
- Every new browser test file starts `pytestmark = pytest.mark.browser`, signs in with `browser_sign_in`, adds
  `RECORDER` and ends by asserting `window.__csp == []` and `window.__errors == []`.
- Run tests with the main `.venv` and `.env`: `M=/mnt/c/Users/AlexKrovina/Documents/GitHub/tc-trackers;
  $M/.venv/bin/python -m dotenv -f $M/.env run -- $M/.venv/bin/pytest <tests> -n 6 -q` (database tests need the
  sandbox off).

## Review Focus

- An address with bad values (`?sort=nonsense&page=999&size=7&filter=unknown&q=`) falls back to the defaults, with no
  script error, and the bad keys are dropped from the address on the first change.
- Search text with quotes, `%`, `&`, `+` and regex characters survives a reload exactly.
- Two tables on one page (Team page) never read or overwrite each other's keys.
- The in-row Retire / Delete question still opens and works when the row is shown as a phone card.
- Sorting, searching or filtering while on page 3 returns to page 1 and removes `page` from the address.

---

### Task 1: One footer, and sorting by type

**Files:**
- Modify: `tracker/templates/lists/_table.html` (replace `table_foot` and `pager` with `table_pager`; `sort_header`
  gains `type`)
- Modify: `tracker/static/lists.js` (`setUpTable`: footer and sort)
- Modify: `tracker/templates/lists/locations.html`, `regions.html`, `business_lines.html` (use `table_pager`; Code
  column `type='text'`, counts `type='number'`)
- Modify: `tracker/static/tracker.css` (footer layout: count on the left, controls on the right; reuse `.pager` rules)
- Test: `tests/test_lists_browser.py`

**Interfaces:**
- Produces: `table_pager(table_id, noun_plural, noun_one, total, active=None)` — one `<nav class="pager"
  data-pager-for=table_id>` with `[data-pager-count]` (the copy above, server-rendered as `Showing {total} of {total}`
  for no-JavaScript) and `[data-pager-controls]` (hidden by default). `active=None` leaves out the active part.
- Produces: `sort_header(label, key, class_name='', default=False, type='text')` writing `data-sort-type`.

- [ ] **Step 1: Write the failing tests** in `tests/test_lists_browser.py` (use the `places` fixture style; add
  locations with `location_factory`):
  - `test_footer_counts_and_pages_appear_only_past_25_rows`: 3 locations → footer text `Showing 3 of 3 locations · 3
    active` and `[data-pager-controls]` hidden; 30 locations (2 retired) → `Showing 1–25 of 30 locations · 28 active`,
    controls visible; click Next → `Showing 26–30 of 30 locations · 28 active`; search `zzz` (no match) → `Showing 0
    of 30 locations · 28 active`.
  - `test_codes_sort_naturally_with_blanks_last`: codes `LD10`, `LD5`, none, `AB1` → ascending `AB1, LD5, LD10, (none)`;
    descending `LD10, LD5, AB1, (none)`.
  - Update `_foot()` and every assertion that read `.list-foot` to read `[data-pager-count]`.
- [ ] **Step 2: Run** `tests/test_lists_browser.py` — new tests FAIL (no `[data-pager-count]`).
- [ ] **Step 3: Implement** `table_pager` and `sort_header(type=)` in `_table.html`; in `setUpTable` write the footer
  copy, show `[data-pager-controls]` only when `matching > 25`, and sort by `data-sort-type` with blanks last. Replace
  the three `table_foot` calls; leave `pager` callers (Team page) for Task 2 but keep `pager` working until then.
- [ ] **Step 4: Run** `tests/test_lists_browser.py tests/test_lists*.py` — PASS.
- [ ] **Step 5: Commit** `feat: one table footer with counts and paging, and sorting by type`.

### Task 2: Users and the Team page on the same footer

**Files:**
- Modify: `tracker/templates/admin/users.html` (add `table_pager('people-table', 'people', 'person', total,
  active=active_count)`; give the Last sign-in style columns their `type`)
- Modify: `tracker/admin/users.py` (pass `active_count`: users with status `active` among those listed)
- Modify: `tracker/templates/teams/team.html`, `tracker/templates/teams/_tracker_picker.html` (`pager` →
  `table_pager`; trackers table passes `active` = active trackers)
- Modify: `tracker/templates/lists/_table.html` (delete `pager` and `table_foot`)
- Test: `tests/test_users_browser.py`, `tests/test_teams_browser.py`

**Interfaces:**
- Consumes: `table_pager`, `sort_header(type=)` from Task 1.

- [ ] **Step 1: Failing tests:**
  - `test_users_list_pages_past_25_people` (users browser): 30 users → `Showing 1–25 of 30 people · 30 active` (count
    what the fixture creates), Next shows the rest.
  - `test_team_trackers_footer_counts_active` (teams browser): 3 trackers, 1 archived → `Showing 3 of 3 trackers · 2
    active`.
- [ ] **Step 2: Run** — FAIL.
- [ ] **Step 3: Implement** as listed; remove the old macros once nothing calls them (`grep -rn "table_foot\|pager("
  tracker/templates` returns only `table_pager`).
- [ ] **Step 4: Run** `tests/test_users*.py tests/test_team*.py tests/test_lists*.py` — PASS.
- [ ] **Step 5: Commit** `feat: Users and the Team page use the standard table footer`.

### Task 3: The view kept in the address

**Files:**
- Modify: `tracker/static/lists.js` (read state on set-up, write it on every change)
- Modify: `tracker/templates/teams/team.html` (`data-state-prefix="people-"`, `"below-"`, `"trackers-"` on the three
  tables), `tracker/templates/teams/_tracker_picker.html` (`"pick-"`)
- Test: `tests/test_lists_browser.py`, `tests/test_teams_browser.py`, `tests/test_users_browser.py`

**Interfaces:**
- Produces: tables read `data-state-prefix` (empty when absent). Users keeps its server keys (`q`, `status`,
  `sign_in`, `admin`, `team`, `set`) untouched; only `sort`, `page` and `size` are added for it by `lists.js`.

- [ ] **Step 1: Failing tests:**
  - `test_the_view_survives_a_reload` (lists): on Locations type `gen`, press Retired, sort Name descending, size 50 →
    address contains `q=gen`, `filter=retired`, `sort=-name`, `size=50` and no `page`; `page.reload()` → the same
    search text, pressed chip, `aria-sort="descending"` on Name and size 50.
  - `test_bad_address_values_fall_back` (lists): open `?sort=nonsense&page=999&size=7&filter=unknown` → default order,
    page 1, size 25, All pressed, no script errors; one search keystroke → none of those keys left in the address.
  - `test_search_text_round_trips` (lists): search `a&b "c" 50%+` → reload → the input holds exactly that text.
  - `test_page_three_returns_to_one_on_change` (lists): 80 locations, go to page 3 (`page=3` in the address), sort
    Name → `page` gone and footer starts `Showing 1–25`.
  - `test_team_tables_keep_their_own_keys` (teams): search people `ann`, filter trackers Archived → address has
    `people-q=ann` and `trackers-filter=archived`, no bare `q`; reload restores both.
  - `test_users_sort_is_kept_with_server_filters` (users): open `?status=active`, sort by Name descending → address
    keeps `status=active` and adds `sort=-name`; reload keeps both.
- [ ] **Step 2: Run** — FAIL.
- [ ] **Step 3: Implement** in `setUpTable`: on set-up read `q`, `filter`, `sort`, `page`, `size` (prefixed) and apply
  any valid value (a filter must match a chip, a sort key a heading, a size one of 25/50/100, a page a positive
  integer; anything else is ignored); after every change rebuild those keys with `URLSearchParams` (keeping all other
  keys) and `history.replaceState`, writing only non-defaults.
- [ ] **Step 4: Run** the three browser test files — PASS.
- [ ] **Step 5: Commit** `feat: tables keep their search, filter, sort and page in the address`.

### Task 4: Clear filters

**Files:**
- Modify: `tracker/templates/lists/_table.html` (new `clear_filters(target_id)` macro: a hidden
  `<button type="button" class="button button-small" data-clear-for=…>Clear filters</button>`; `no_match(text,
  target_id)` gains the same button)
- Modify: `tracker/static/lists.js` (show the button when the search is not empty, the chip is not All, or a region
  is chosen; clicking resets all three, keeps the sort, and returns to page 1)
- Modify: `tracker/templates/lists/locations.html`, `regions.html`, `business_lines.html`, `teams/team.html` (place
  `clear_filters` right of the chips); `tracker/templates/admin/users.html` (a server link `Clear filters` to
  `url_for('admin.users')` shown when any server filter is set)
- Test: `tests/test_lists_browser.py`, `tests/test_users_admin.py`

- [ ] **Step 1: Failing tests:**
  - `test_clear_filters_resets_search_chip_and_region` (lists browser): button hidden at first; search `zzz` → button
    shown beside the chips and inside the "no match" line; click → empty search, All pressed, region All, every row
    shown, sort unchanged, button hidden, address without `q`/`filter`/`region`.
  - `test_users_clear_filters_link` (users, server test): `GET /admin/users?status=disabled` → contains
    `href="/admin/users">Clear filters`; `GET /admin/users` → no `Clear filters`.
- [ ] **Step 2: Run** — FAIL.
- [ ] **Step 3: Implement** as listed.
- [ ] **Step 4: Run** `tests/test_lists_browser.py tests/test_users_admin.py tests/test_teams_browser.py` — PASS.
- [ ] **Step 5: Commit** `feat: a Clear filters button beside the filters and in the no-match line`.

### Task 5: Headings that stay visible, and cards on a phone

**Files:**
- Modify: `tracker/static/tracker.css`:
  - `:root { --sticky-top: var(--topbar-height); }` and `main:has(.subnav) { --sticky-top: calc(var(--topbar-height)
    + var(--subnav-height)); }`; `thead th` of tables in `.list-table`, `.user-table` and the Team page tables are
    `position: sticky; top: var(--sticky-top); z-index: 2; background: var(--surface)`. No ancestor of these tables
    may create a scroll container above 720px (use `overflow: clip` where clipping is needed).
  - Generalise the `.register` phone-card rules (the `@media (max-width: 720px)` block) to `:is(.register,
    .card-rows)`, so any table with class `card-rows` becomes one card per row with each `td[data-label]` labelled.
- Modify: `tracker/static/lists.js` (on set-up, give each body cell without one a `data-label` equal to its column
  heading's visible text; skip the actions column)
- Modify: the PR 1 tables' `<table>` tags: add class `card-rows`
- Test: `tests/test_lists_browser.py`

- [ ] **Step 1: Failing tests:**
  - `test_headings_stay_visible_while_scrolling` (lists browser, 1280×700, 40 locations, size 50): scroll the window
    by 1200px → the Name heading's `getBoundingClientRect().top` is within 2px of the top bar's bottom and the heading
    is visible.
  - `test_rows_are_cards_on_a_phone` (lists browser, 390×844): a row's computed `display` is not `table-row`; the
    Region cell's `data-label` is `Region`; the page has no sideways scroll
    (`document.documentElement.scrollWidth <= 390`); Retire on a card opens its in-row question and Keep closes it.
- [ ] **Step 2: Run** — FAIL.
- [ ] **Step 3: Implement** as listed.
- [ ] **Step 4: Run** `tests/test_lists_browser.py tests/test_users_browser.py tests/test_teams_browser.py
  tests/test_registers_browser.py` — PASS (Risks still uses `.register`).
- [ ] **Step 5: Commit** `feat: table headings stay visible, and rows become cards on a phone`.

### Finish

- [ ] Full suite `pytest -n 6` passes; ruff check and format pass.
- [ ] Screenshots of Locations, Users and a Team page at 1440px (light and dark) and 390px look right.
- [ ] Push `feat/standard-tables` and open PR 1 with the spec link and a list of what each table gained.
