# Standard tables, PR 2: the remaining browser-side tables Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move every remaining list that loads in full onto the standard table toolkit built in PR 1 (#60): the
tracker's Locations tab, Risks, the tracker's Access tab, a person's Access page, permission set holders (the set's own
page and the side panel), and the Home list view.

**Architecture:** Reuse PR 1's toolkit as it is on `main`: macros in `tracker/templates/lists/_table.html`
(`search_box`, `status_filters`, `sort_header(..., type=)`, `table_pager`, `clear_filters`, `no_match(text,
target_id)`), and `setUpTable` in `tracker/static/lists.js` (rows carry `data-search`, `data-status`, `data-sort-<key>`;
tables opt in with an `id` inside `.list-table` or with `data-sortable`; `data-state-prefix` for several tables on one
page; class `card-rows` for phone cards; sticky headings via `--sticky-top`). Page-specific scripts (`risks.js`, the row
filter in `admin.js`) give way to the toolkit where it does the same job. The Home list stays driven by `home.js`.

**Tech Stack:** Flask, Jinja, vanilla ES5 JavaScript, CSS; pytest + Playwright.

**Spec:** `docs/superpowers/specs/2026-11-17-standard-tables-design.md` (the "Tables in scope" table and "Calls made
after the builder check": items 2, 5, 6, 7, 8, 9 apply here). The PR 1 plan
`docs/superpowers/plans/2026-11-17-standard-tables-pr1-toolkit.md` describes the toolkit's copy and address rules.

## Global Constraints

- Everything in the PR 1 plan's Global Constraints still holds: CSP (no inline script/style), ES5, British English and
  no contractions, footer copy `Showing {first}–{last} of {matching} {noun}` / `Showing {matching} of {total} {noun}`
  plus ` · {active} active` where rows can be retired or archived, rows per page 25/50/100 shown past 25 rows, address
  keys `q`, `filter`, `sort` (`-` for descending), `page`, `size` (prefixed when a page has several tables), defaults
  never written, bad values ignored, without JavaScript every row shows and the controls stay hidden.
- Keep each table's existing actions and behaviour (forms, confirms, retire/restore, move up/down) working.
- Tests: browser files start `pytestmark = pytest.mark.browser`, sign in with `browser_sign_in`, add `RECORDER`, end with
  `window.__csp == []` and `window.__errors == []`. Run with
  `M=/mnt/c/Users/AlexKrovina/Documents/GitHub/tc-trackers; $M/.venv/bin/python -m dotenv -f $M/.env run --
  $M/.venv/bin/pytest <tests> -n 6 -q` (Bash sandbox disabled). Per task run only that area's tests plus
  `tests/test_templates.py` and `tests/test_lists_browser.py` when the toolkit itself changes.

## Review Focus

- A table whose rows are reordered or moved by the server (Locations Up/Down) must not show move buttons while a sort,
  search or filter is active, and must show them again when cleared.
- Several toolkit tables on one page never share address keys.
- Risks' chips keep their meaning (All open, each RAG, Not rated, Past target date) and their counts follow the search.
- The Home list's heading sort and the Sort select always show the same order, and the cards follow it.
- A table loaded after the page (the side panel's holders) gets the same behaviour as one present at load.

---

### Task 1: Toolkit follow-ups and the tracker's Locations tab

**Files:** `tracker/static/lists.js`, `tracker/templates/lists/_table.html`, `tracker/static/tracker.css`,
`tracker/templates/trackers/groups.html`, tests (`tests/test_lists_browser.py`, the Locations tab's tests — find them
with `grep -rln "groups.html\|/groups" tests`).

- [ ] Toolkit follow-ups from PR 1's review, test-first:
  - The footer is a plain `<div>` with the count; the `nav` landmark ("Pages of …") wraps only the paging controls and
    only when they show.
  - Rows marked `data-uncounted` (Team page people who are not active) are counted the same way in the footer and the
    chips, so "All N" and "Showing … of N" agree.
  - Expose `window.trackerLists = { setUp: function (table) {...} }` so a table inserted after load can be set up
    (Task 3 uses it); setting up the same table twice does nothing the second time.
  - A browser test that headings stick under the section links (`--sticky-top` with `.subnav`) on a tracker page.
- [ ] The tracker's Locations tab (spec row "Tracker → Locations tab"): search by name, chips All / Active / Retired with
  counts, sortable columns with types (name text, progress/remaining/ready numbers, planned completion date), default
  order = the owner's sort order, footer with "N active", Clear filters, cards on a phone. Up and Down show only in the
  default order with no search, filter or page change; otherwise they are hidden and a note reads "Clear the sort and
  filters to change the order." (spec call 2). If the tab has a separate totals table or retired table, keep totals out
  of sorting and make the retired rows a filter rather than a second table only if that is simpler; otherwise keep the
  tables and prefix their keys.
- [ ] Commit `feat: standard tables on the tracker's Locations tab; toolkit follow-ups`.

### Task 2: Risks

**Files:** `tracker/templates/entries/risks.html`, `tracker/static/risks.js`, `tracker/static/tracker.css`, the Risks
tests (`grep -rln "risks" tests`).

- [ ] Move the Risks register onto the toolkit, test-first: the existing search and chips (All open, each RAG, Not rated,
  Past target date) become toolkit search and status chips (the first chip is the default, so `filter` is absent for
  All open); sortable columns (RAG by severity worst first as the default, Ref natural text, Risk, location, Owner,
  Status, Target date as date); footer, paging, address memory, Clear filters, cards on a phone (Risks already uses
  `.register` cards — keep the look). Closed risks: keep their own table with a prefixed key set, or fold them in as a
  chip — whichever keeps today's page clearest; say which in the report.
- [ ] Remove whatever `risks.js` no longer needs (keep anything else it does).
- [ ] Commit `feat: standard tables on the Risks register`.

### Task 3: Access tables and permission set holders

**Files:** `tracker/templates/trackers/roles.html`, `tracker/static/admin.js` (row filter), `tracker/templates/admin/
user_access.html`, `tracker/templates/permsets/set.html`, `tracker/templates/permsets/_panel.html`,
`tracker/static/permsets.js`, tests.

- [ ] Tracker → Access (roles): search by person, chips All / Owner / Editor / Viewer with counts, sort by person and
  role, footer, Clear filters, cards on a phone; drop the old row filter if the toolkit replaces it.
- [ ] A person's Access page (two small tables): sorting, the count line and phone cards; no search or chips (spec call 8).
  Prefix the two tables' keys.
- [ ] Permission set holders on the set's own page and in the side panel: a table (Holder, Kind, Remove) with search by
  name, chips All / People / Teams, sort by name, footer, Clear filters. The panel fragment renders the same table;
  `permsets.js` calls `window.trackerLists.setUp(table)` after inserting the fragment. The panel's address memory: do
  not write the panel table's keys to the address (give it `data-state-prefix` and a `data-no-address` opt-out the
  toolkit honours), since `?set=` already owns the panel.
- [ ] Commit `feat: standard tables on Access, a person's access and permission set holders`.

### Task 4: Home list view

**Files:** `tracker/templates/home.html`, `tracker/static/home.js`, `tracker/static/tracker.css`, Home tests
(`tests/test_home*.py`).

- [ ] Test-first (spec call 5 and 7): a search box (tracker name) filters both the cards and the list; the list's column
  headings are sort buttons that set the same sort as the Sort select (and the select shows it), the cards follow the
  same order; the address keeps `filter`, `line`, `region`, `sort`, `q` and `layout` (defaults left out, bad values
  ignored); the footer under the list and the cards reads "Showing 12 of 15 trackers"; Clear filters resets search,
  chip and selects. Archived trackers count only while "Show archived" is on, as today.
- [ ] Commit `feat: Home list view: search, sortable headings, the view in the address`.

### Finish

- [ ] Full suite once, ruff; screenshots of the Locations tab, Risks, Access and Home list at 1440px light and dark and
  at 390px; push and open the PR.
