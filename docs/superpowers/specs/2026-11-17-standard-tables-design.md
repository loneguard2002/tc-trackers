# Standard tables

Agreed with the owner on 2026-11-17. Every list-style table in the app works the same way as the Lists → Locations
table already does, plus a few things that table does not do yet.

## Why

The tables grew one at a time, so each has a different subset of search, filters, sorting, counts and paging (Users
has most, the tracker's Locations tab has none, Activity has its own pages). People have to relearn each table, and
long tables are hard to work through. One standard makes every list predictable.

## Goals: the standard set

Every table in scope gets all of these, built once and shared:

1. **Search at the top** (left), filtering the rows as you type.
2. **Filter chips with counts** (right of the search): All plus the table's own groupings (for example Active /
   Retired), each with the number of rows it would show given the current search.
3. **Sort by any column** by clicking its heading; again to reverse. Sorting follows the column's type: dates by date,
   numbers by value, text alphabetically ignoring case, with numbers inside text in natural order (LD5 before LD10).
   Empty values go last in both directions. One column is the default sort.
4. **The count and paging footer**: "Showing 1–25 of 30 locations · 4 active". "N active" only where rows can be
   retired, disabled or archived. Rows per page 25 / 50 / 100 with Previous, page numbers and Next, shown only when
   more than 25 rows match. Search, filters and sort apply to all rows; paging then splits the result.
5. **The view kept in the page address**: search, filter, sort and page live in the query string, so Back, refresh and
   a copied link bring back the same view.
6. **Column headings that stay visible** while the page scrolls past a long table (pinned under the top bar and any
   section links).
7. **"No rows match" with a Clear filters button**, and a Clear filters button beside the chips whenever a search or
   filter is active.
8. **One phone layout**: on a narrow screen each row becomes a small card (first column as the title line, the others
   labelled underneath), as Risks and Entries do now.
9. **The same row actions**: icon buttons side by side (Edit, then Retire/Restore or Delete), with the in-row question
   for anything destructive ("Delete …? Delete / Keep").

Search and the chips appear only when they help: a table that can never have more than 10 rows (for example a person's
own access lists) gets sorting, the count line and the phone cards, but no search box.

## Non-goals

- **Download CSV** is not added anywhere (owner's decision). Entries keeps the button it already has.
- Not in scope: choosing columns, ticking several rows, editing in the table, saved views.
- Tables that are not lists stay as they are: the Targets grid (a form, rows are weeks in order), the import preview,
  and the Email page's ten most recent sends.

## Approaches considered

- **A. Grow the shared toolkit Locations already uses** (chosen). `lists/_table.html` (macros) and `lists.js` gain the
  missing parts, and every table moves onto them. Lists that load in full are searched, sorted and paged in the
  browser. Activity, which can hold thousands of rows, does the same on the server with the same look and the same
  address format.
- B. Everything on the server: works without JavaScript and gets address memory for free, but every click reloads the
  page and every route changes.
- C. A table library: the redesign removed one (Tabulator); libraries fight the strict Content Security Policy and
  bring their own look.

## How it behaves (decided)

- **Without JavaScript** every row shows, unsorted controls stay hidden (as today), and nothing breaks. Server-side
  Activity works fully without JavaScript.
- **Address format**: `q`, `filter`, `sort` (column key, `-` prefix for descending), `page`, `size`. A page with
  several tables (the Team page) prefixes each table's keys with its name, for example `people-q`. Typing updates the
  address with `replaceState`, so Back leaves the page rather than stepping through each keystroke; opening a row and
  coming back restores the view.
- **Defaults are left out of the address** (no `page=1`, no default sort), so plain links stay plain.
- **Sorting is stable**: rows equal on the sort column keep their default order.

## Tables in scope

| Table | Search | Chips (with counts) | Default sort | "N active" |
|---|---|---|---|---|
| Lists: Locations, Regions, Business lines | yes (as now) | All / Active / Retired (as now) | name | yes |
| Users | yes (as now) | as now | name | yes |
| Team page: people, teams below, trackers | yes (as now) | as now | as now | trackers: active |
| Tracker → Locations tab | name | All / Active / Retired | sort order set by the owner | yes |
| Tracker → Risks | as now | as now (All open, RAG, Not rated, Past target date) | RAG, worst first | no |
| Tracker → Access (roles) | person | All / Owner / Editor / Viewer | person | no |
| Home, List view | tracker name (also filters the cards) | the Home chips and selects, as now | as the Home Sort select | archived shown as now |
| Permission set: holders | name | All / People / Teams | name | no |
| A person's Access page (two small tables) | no | no | tracker / permission | no |
| Entries | location and note | location chips and week, as now | newest week first | no |
| Activity (server) | text in person, tracker and detail | the current selects stay; no chips | newest first | no |

**Entries** keeps its week grouping. Sorting applies within each week; paging is by weeks (10 weeks a page), so a week
is never split; the footer reads "Showing weeks 1–10 of 23 · 214 entries". The 500-row cap goes once paging is by
weeks.

**Activity** moves its paging to the standard footer on the server: total count, page numbers, 25 / 50 / 100 rows,
sortable Time, Performed by, Action and Tracker columns, and a search box, all in the address alongside today's filters.

## Build order (one PR each)

1. Toolkit: add address memory, sticky headings, Clear filters, typed sorting, the combined count and paging footer and
   phone cards to `lists/_table.html` and `lists.js`; apply to Lists, Users and the Team page.
2. Move the remaining browser-side tables onto it: tracker Locations tab, Risks, Access, Home list, Permission set
   holders, a person's Access page, Entries.
3. Activity on the server with the same look.

## Left to the builder

- Exact markup and class names, as long as they extend the existing `lists/_table.html` macros.
- Sort keys per column (each sortable cell carries its sort value, as Locations does with `data-sort-*`).
- How the phone card labels its cells (the column heading text).
- The narrow-screen breakpoint, matching the existing ones (720px).
