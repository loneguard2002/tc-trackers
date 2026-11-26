# Standard tables, part 3: Activity and Entries on the server — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give Activity and Entries the standard table's search, sortable headings and count-and-paging footer, worked
out on the server so both stay fast with thousands of rows, and remove Entries' 500-entry cap.

**Architecture:** A small shared module (`tracker/servertable.py`) reads `q`, `sort`, `page` and `size` from the
address against each table's allowed keys and builds page links; two new macros in `lists/_table.html` draw the
sortable heading links and the standard footer from it, with the classes the browser-side tables already use, so
both look identical. Activity and Entries then query with LIMIT/OFFSET (Entries by weeks) and render the same pieces.
Everything works without JavaScript.

**Tech Stack:** Flask, Jinja, SQLAlchemy, PostgreSQL, vanilla ES5, CSS; pytest + Playwright.

**Spec:** `docs/superpowers/specs/2026-11-17-standard-tables-design.md` (approved 17 Nov 2026): Goals 1–9, "How it
behaves", the Activity and Entries rows of "Tables in scope", and Calls 1, 3 and 4.

## Global Constraints

- Address keys: `q`, `sort` (column key, `-` prefix for descending), `page`, `size`; defaults are left out of the
  address (no `page=1`, no default sort, no `size=25`). Activity keeps `person`, `action`, `from`, `to`, `page`;
  Entries keeps `group` and `week`.
- Rows per page 25 / 50 / 100 (default 25); any other `size` is ignored. A `page` past the last shows the last page;
  a `page` that is not a number is ignored. A `sort` key not in the table's list is ignored.
- The footer copy is the standard one: "Showing 26–50 of 312 entries" (Activity); "Showing weeks 1–10 of 23 · 214
  entries" (Entries). The page controls (Rows per page, Previous, page numbers with gaps, Next) show only when more
  than one page exists, with the classes `.pager`, `.pager-count`, `.pager-controls`, `.pager-button`,
  `.pager-pages`, `.pager-gap`, `aria-current="page"` as the browser-side pager.
- Sortable headings use the browser tables' look (`.sort-button` with the sort icon, `aria-sort` on the `th`) but are
  links; clicking a sorted column reverses it.
- Search uses SQL `ILIKE` with `%` and `_` in the typed text escaped.
- Strict CSP: no inline script or style, no `style=`; ES5. British English, no contractions.
- Phone cards: server-rendered cells carry `data-label` (do not rely on `lists.js` `labelCells`, which breaks on
  `colspan` rows).
- Tests: browser files start `pytestmark = pytest.mark.browser`, use `RECORDER`, end with `window.__csp == []` and
  `window.__errors == []`; POSTs use `conftest.post`. Run each task's tests plus `tests/test_templates.py` with
  `M=/mnt/c/Users/AlexKrovina/Documents/GitHub/tc-trackers; $M/.venv/bin/python -m dotenv -f $M/.env run --
  $M/.venv/bin/pytest <tests> -n 6 -q` (sandbox disabled). Main has 7 `mail/access/*.html` CSP failures.

## Review Focus

- A viewer who cannot open a tracker searches Activity for words that appear only in that tracker's entry detail:
  those entries must not match (spec Call 1; Task 2 test).
- `q` containing `%`, `_` or a quote matches literally and never errors (Task 1 test).
- `page=999` on a short list shows the last page, not an empty table; `size=7` falls back to 25 (Task 1 test).
- Entries filtered to one location with a search still counts weeks and entries for the filtered set only, and a week
  is never split across pages (Task 3 test).
- Without JavaScript, the search, sort links, page links and rows-per-page work on both pages (Tasks 2 and 3 tests).

---

### Task 1: The shared server-side table pieces

**Files:** create `tracker/servertable.py`; modify `tracker/templates/lists/_table.html`, `tracker/static/tracker.css`
(only if a link needs the button look), `tracker/static/lists.js` only if the size select needs auto-submit (prefer
the existing `data-autosubmit`); tests `tests/test_servertable.py`.

**Interfaces (produced):**
- `@dataclass(frozen=True) class TableState: q: str; sort: str; descending: bool; page: int; size: int`.
- `read_state(args, sort_keys: tuple[str, ...], default_sort: str, default_descending: bool) -> TableState` — `q`
  stripped and capped at 200 characters; `size` in (25, 50, 100) else 25; `page` ≥ 1.
- `like_pattern(text: str) -> str` — `%` + text with `\`, `%`, `_` escaped + `%`, for `ILIKE ... ESCAPE '\'`.
- `clamp_page(state: TableState, total: int) -> TableState` — page within 1..last (last = 1 when total is 0).
- `page_numbers(page: int, last: int) -> list[int | None]` — the same window `lists.js` shows (first, last, current
  ±1, `None` for a gap).
- `state_args(state: TableState, default_sort: str, default_descending: bool, **changes) -> dict` — the address
  arguments with defaults left out, for `url_for(endpoint, **other_keys, **state_args(...))`.
- Macros in `lists/_table.html`: `server_sort_header(label, key, state, url, class_name='')` (`url` is the link to
  this column's next sort) and `server_pager(state, total, noun_plural, noun_one, page_url, size_form, first, last,
  extra='')` — renders the standard footer; `page_url(n)` is a macro/callable argument giving each page's link,
  `size_form` the hidden inputs that keep the other keys when Rows per page changes, `first`/`last` the shown range,
  `extra` the text after "·" (Entries' entry count).

- [ ] Tests first: `read_state` defaults, a bad `size` → 25, `sort=-time` → descending, an unknown key → default,
  `page=abc` → 1; `like_pattern("50%_a\\b")` escapes all three; `clamp_page` for page past last and total 0;
  `page_numbers(1, 1) == [1]`, `page_numbers(5, 20) == [1, None, 4, 5, 6, None, 20]`, `page_numbers(2, 3) == [1, 2,
  3]`; `state_args` leaves out page 1, size 25 and the default sort; the two macros render (in a test request
  context): links with `aria-sort`, the "Showing 26–50 of 312 entries" text, the controls only when last > 1,
  `aria-current="page"` on the current page, a gap marker, and a GET size form with the kept keys.
- [ ] Implement; run `tests/test_servertable.py tests/test_templates.py`; commit `feat: server-side table state and
  footer for long lists`.

### Task 2: Activity on the server

**Files:** `tracker/activity/views.py`, `tracker/templates/activity/index.html`, `tracker/static/tracker.css` (sticky
headings and phone cards as the other standard tables); tests `tests/test_activity.py`,
`tests/test_activity_browser.py`.

**Interfaces:** consumes Task 1. Sort keys: `time` (default, newest first), `actor` (Performed by, by name), `action`
(by its label, an SQL `CASE` built from `ACTION_LABELS`), `tracker` (by name). `PAGE_SIZE = 50` goes; the Newer/Older
links go.

- [ ] Tests first: default 25 rows newest first with the footer "Showing 1–25 of N entries" and page links; `size=50`
  and `page=2`; old `?page=3` links still work; each sort key both ways; `q` matches the actor's name or email, the
  affected person's name or email, the tracker name and the detail text; **a viewer without access to a tracker does
  not match on that tracker's detail but does on its name** (spec Call 1, the access applied in the query);
  admins match every detail; the filters (`person`, `action`, `from`, `to`) combine with `q` and stay in every
  sort/page/size link; Clear filters clears `q` too; `page` past the last shows the last page; the cells carry
  `data-label`. Browser: typing a search and pressing Enter filters; a heading click sorts; page 2 link; no CSP or
  script errors; at 390px the rows are cards and nothing scrolls sideways.
- [ ] Implement (one counted query for the total with the same conditions; the detail search as
  `AuditLog.detail.cast(Text).ilike(pattern, escape="\\")` limited to rows whose tracker the viewer can open, or with
  no tracker); run `tests/test_activity.py tests/test_activity_browser.py tests/test_activity_labels.py
  tests/test_servertable.py tests/test_templates.py`; commit `feat: Activity pages, sorts and searches on the
  server`.

### Task 3: Entries on the server

**Files:** `tracker/entries/views.py` (`_render_list`, `entries_csv`), `tracker/templates/entries/list.html`,
`tracker/static/tracker.css`; tests `tests/test_entries.py`, plus the Entries browser test file if one exists (else
add to `tests/test_entries.py` server tests and a small `tests/test_entries_browser.py`).

**Interfaces:** consumes Task 1. Paging is by weeks: `WEEKS_PER_PAGE = 10`; `size` does not apply (no Rows per page
control). Sort keys inside each week: `date` (default, newest first), `location`, `quantity`, `note`. Search `q`
over the location name and the note. `LIST_LIMIT = 500`, the "Showing the latest 500 entries only" note and the
"Showing the latest N of M entries this week" note go.

- [ ] Tests first: 23 weeks of entries → page 1 shows the 10 newest weeks, footer "Showing weeks 1–10 of 23 · N
  entries", page 3 shows weeks 21–23; every entry of a shown week is listed (no cap; a week with 600 entries shows all
  600); `q` on a location name and on a note; `group` and `week` combine with `q` and the footer counts only the
  matching weeks and entries; the location chips' counts follow `q` and `week` as today; `sort=quantity` orders rows
  inside each week while the weeks stay newest first; the week totals and targets still show; the quick-add form and
  a refused Record keep the filters (existing tests stay green); Download CSV takes `q` as well as `group` and `week`;
  cells carry `data-label`. Browser: search, a heading sort and page 2 without JavaScript errors; at 390px no sideways
  scroll.
- [ ] Implement (first a grouped query for the matching weeks, newest first, with counts, to page the weeks; then the
  entries of the page's weeks only); run `tests/test_entries.py tests/test_entries_forms.py` and the Entries browser
  tests plus `tests/test_servertable.py tests/test_templates.py`; commit `feat: Entries pages by weeks and searches on
  the server`.

### Finish

- [ ] Full suite once (`-n 6`) and ruff; screenshots of Activity and Entries at 1440px light and dark and 390px; push
  and open the PR.
