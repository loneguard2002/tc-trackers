# Permission sets redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the agreed Permission sets page: pinned head, one sideways row, ⋯ menus with rename and delete
pop-ups, a holders side panel, a four-step create, and a save bar that appears only with changes.

**Architecture:** Server-rendered page (`tracker/templates/permsets/index.html`) plus page script. The server gains a
`return_to=index` redirect, a create that also saves permissions and holders, a plain `/new` page and a `/<id>/panel`
fragment. Everything interactive is progressive enhancement; without JavaScript the page and the set's own page work.

**Tech Stack:** Flask, Jinja, SQLAlchemy, vanilla ES5 JavaScript, CSS; pytest + Playwright.

**Spec:** `docs/superpowers/specs/2026-11-18-permission-sets-redesign-design.md` (read it; it holds the exact copy and
behaviour). Reference demo (not to be copied blindly, but its behaviour and copy are agreed):
`/tmp/claude-1000/-home-alexkrovina/cf13b4e4-1890-473a-b9dc-06d0fca97d35/scratchpad/mockup-permsets/index.html`,
`static/mockup.js`, `static/mockup.css`.

## Global Constraints

- Strict Content Security Policy: no inline scripts or styles, no `style=` attributes (setting `element.style` from a
  script file is fine).
- Page script is plain ES5 like `tracker/static/admin.js` (no modules, no arrow functions).
- British English, no contractions. Copy as in the spec.
- Administrators only (`admin_required`), as today. Every change keeps writing the existing activity entries.
- Use `<dialog>` with `showModal()` for pop-ups and the side panel (the existing `.list-dialog` look); backdrop per design
  rule 1 (navy 70% light, black 65% dark).
- Respect `prefers-reduced-motion`; give every interactive element a visible focus state.
- Tests: browser files start `pytestmark = pytest.mark.browser`, sign in with `browser_sign_in`, add `RECORDER`, and end
  with `window.__csp == []` and `window.__errors == []`. Run with
  `M=/mnt/c/Users/AlexKrovina/Documents/GitHub/tc-trackers; $M/.venv/bin/python -m dotenv -f $M/.env run --
  $M/.venv/bin/pytest <tests> -n 6 -q` with the Bash sandbox disabled. Run only the tests for the area changed plus
  `tests/test_templates.py` per task.

## Review Focus

- A name already taken, or only spaces, is refused at step 1 and again by the server; the values come back.
- Holders posted with an unknown, inactive or duplicate id are ignored, never a 500.
- `?set=<id>` for a set that does not exist (or not a number) opens nothing and raises nothing.
- Deleting the set whose panel is open closes the panel; the save bar never shows ticks of a deleted card.
- Leaving the page with unsaved ticks warns; Discard and Save clear the warning.

---

### Task 1: Server: create with permissions and holders, return to the page, `/new` and `/<id>/panel`

**Files:** `tracker/permsets/views.py`, new `tracker/templates/permsets/new.html`, new
`tracker/templates/permsets/_panel.html`, `tests/test_permission_sets.py`.

**Interfaces (produced):**
- `POST /admin/permission-sets` accepts `name`, `description`, `permissions` (many), `holders` (many, `team:<id>` or
  `user:<id>`), `return_to`. With `return_to=index` success redirects to `/admin/permission-sets?set=<id>`; errors render
  `permsets/new.html` (400) with the values kept. Without it, behaviour as today.
- `GET /admin/permission-sets/new` renders `permsets/new.html` (name, description, Create).
- `GET /admin/permission-sets/<id>/panel` renders the fragment `_panel.html` (no base layout): the set's holders (team
  path or person name and email, a Remove form per holder posting to `remove_holder` with `return_to=index`), an Add
  holder form (select of free teams and active people, `holder` values as today, `return_to=index`), the granted
  permissions as chips. 404 for an unknown set.
- `rename`, `add_holder`, `remove_holder` with `return_to=index` redirect to `/admin/permission-sets?set=<id>`;
  `delete_set` with it redirects to `/admin/permission-sets` (as now).
- `index` passes to the template: per set its holder count text (existing `holder_counts`) and what the four-step
  create needs: `team_choices` (id, path) for every team and `people` (id, full name, email) for every active user.

- [ ] Tests first (server tests in `tests/test_permission_sets.py`): create with two permissions and one team + one person
  saves all and writes the activity entries (created, permissions changed, holder added ×2); unknown permission and
  unknown/inactive/duplicate holders are ignored; `return_to=index` redirects to `?set=<id>`; a taken name with
  `return_to=index` returns 400 with the new page and values; `/new` and `/<id>/panel` are admin-only (403 otherwise) and
  the panel 404s for an unknown id; panel lists holders with Remove forms carrying `return_to=index`; rename / add /
  remove with `return_to=index` redirect to `?set=<id>`.
- [ ] Implement; run `tests/test_permission_sets.py tests/test_permissions.py tests/test_templates.py`; commit
  `feat: permission sets create saves permissions and holders; the page can be returned to`.

### Task 2: The page: pinned head, one sideways row, no count badge, the save bar only with changes

**Files:** `tracker/templates/permsets/index.html`, `tracker/static/tracker.css`, `tracker/static/admin.js` (or a new
`tracker/static/permsets.js` loaded by the page), `tests/test_permsets_browser.py`.

- [ ] Tests first (browser): at 1440×900 the head stays within 2px of the top bar's bottom after scrolling 600px; the
  cards share one row (same top), between 340 and 460px wide, about a third (0.25–0.45) of the first partly hidden card
  shows; ‹ is disabled at the start and › steps the row (scrollLeft grows); the row aligned-rows test still passes; no
  `.perm-card-count`; no dashed New card; the save bar is hidden at load, appears with "1 unsaved change in 1 set" after
  one tick, hides after Discard (tick restored) and after unticking back; at 390px the cards stack.
- [ ] Implement per the spec goals 1–3 and 8; run the permsets browser and server tests plus `tests/test_templates.py`;
  commit `feat: Permission sets: pinned head, one sideways row, save bar only with changes`.

### Task 3: ⋯ menus, the rename and delete pop-ups, and the holders side panel

**Files:** `index.html`, the page script, `tracker.css`, `tests/test_permsets_browser.py`.

- [ ] Tests first (browser): the ⋯ menu opens with three items and closes on Escape (focus back on ⋯); Rename saves a new
  name (card shows it, activity unchanged in format); Delete shows "Held by …" and the permissions they lose, Delete set
  removes the card; "Holders and details" (menu and card link) opens the side panel with the holders and permissions;
  Remove and Add holder in the panel come back with the panel open (`?set=<id>`) and the change made; the panel's ⋯
  renames and deletes; Escape and the backdrop close the panel; `?set=999999` and `?set=abc` open nothing.
- [ ] Implement per spec goals 4–6; run the browser tests and `tests/test_templates.py`; commit
  `feat: Permission sets: card menus, rename and delete pop-ups, and a holders side panel`.

### Task 4: New permission set in four steps

**Files:** `index.html`, the page script, `tracker.css`, `tests/test_permsets_browser.py`.

- [ ] Tests first (browser): New permission set opens the pop-up at step 1; Next with an empty or taken name shows the
  message and stays; the step bar fills a third per step and finished steps show ✓ and go back on click; step 2 counts
  ticks and shows the warning for Manage users + Manage teams; step 3 search filters and picked chips appear; review
  shows the three blocks with Edit going back to that step; Create saves (the new card is in the row with the ticks, the
  panel opens for it with its holders); without JavaScript the New link goes to `/new`.
- [ ] Implement per spec goal 7; run the browser tests and `tests/test_templates.py`; commit
  `feat: Permission sets: a four-step New permission set`.

### Finish

- [ ] Full suite once (`pytest -n 6`), ruff; screenshots of the page, the panel and each step at 1440px light and dark and
  at 390px; push and open the PR.
