# Teams New view Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A New view of the Teams pages (Design A, the access map) beside today's pages, which stay as the Classic view.

**Architecture:** One switch picks the view per session; the Teams list, a team's page and its Where it sits page
render a `*_new.html` template in the New view and today's template in Classic. Both post to the same routes; the only
route change is a "move" action on the Higher teams routes. New data helpers live in `tracker/teams/overview.py`; the
New view's behaviour lives in `tracker/static/teams-new.js` (ES5, CSP-safe) and its styles in `tracker.css`.

**Tech Stack:** Flask, Jinja (StrictUndefined in tests), SQLAlchemy, vanilla ES5, strict CSP, pytest + Playwright.

**Spec:** `docs/superpowers/specs/2026-11-26-teams-new-view-design.md`

## Global Constraints

- Switch labels "New view" and "Classic view"; session key `teams_view`; New is the default.
- Classic pages render exactly as today apart from the switch.
- No inline `style` or `<script>`; colours are tracker.css tokens; ES5 only.
- Every guard and message of today's routes applies unchanged in the New view.
- British English, plain words; button copy as the spec gives it ("Create <name> under <team>", "Add a member").
- Fold rule: below the third level, a team with more than 8 teams below it shows them folded as "+N teams".

## Rulings (decisions the spec left open)

- **R1 Tests default to Classic.** `TEAMS_DEFAULT_VIEW` config (default `"new"`); the test app sets `"classic"`, so
  existing team tests keep testing Classic; New-view tests ask with `?view=new`.
  Cost if wrong: one conftest line.
- **R2 No second higher team at creation.** The create route takes one `parent_id`. The panel says "You can put it under a second team from its Where it sits page." A second parent is added there. Cost: one extra step for a rare case.
- **R3 Region and location fill from the team above.** When a higher team with a place is chosen, the panel's
  Region and Location are filled from it by JavaScript, unless the person has changed them. The hint reads "Filled
  from <team>". Without JavaScript they are chosen by hand.
- **R4 "Move it" replaces every higher team.** The new `move` action sets the higher teams to the chosen one alone,
  logging `team_parent_removed` for each one dropped and `team_parent_added` for the new one.
- **R5 Counts.**
  - "N members" counts a team's active direct members.
  - "N trackers" counts its own active trackers.
  - "N people reach down" counts the active direct members of that higher team.
  - The Add a member preview counts the active trackers of the team and every team below it.

## Review Focus

1. A team under two teams: the chart shows it once (under the first higher team by name) with "Also under", and the
   access map shows one chain per path. Test in Task 1 and Task 3.
2. Cycles in corrupted data: the chart and the chains end. Test in Task 1.
3. Without JavaScript, the role switch saves through a Set role button, the add panel posts, and the switch links work. Test in Task 3 and Task 4.
4. A refused create or add in the New view shows the New view again, with the errors and the person's input. Test in Task 2 and Task 4.
5. "Move it" when the team sits under several teams drops them all, and the preview shows the losses. Test in Task 5.

---

### Task 1: The switch and the Teams chart

**Files:**
- Create: `tracker/teams/view_choice.py`, `tracker/teams/overview.py`, `tracker/templates/teams/_view_switch.html`,
  `tracker/templates/teams/index_new.html`, `tracker/templates/teams/_chart.html`, `tracker/static/teams-new.js`
- Modify: `tracker/teams/views.py` (`_render_index`), `tracker/config.py` (`TEAMS_DEFAULT_VIEW`), `tests/conftest.py`
  (app config `"TEAMS_DEFAULT_VIEW": "classic"`), `tracker/templates/teams/index.html`, `team.html`, `parents.html`
  (include the switch), `tracker/static/tracker.css`
- Test: `tests/test_teams_new_view.py`

**Interfaces:**
- Produces:
  - `chosen_view() -> str` ("new" | "classic"): `?view=` is kept in `session["teams_view"]`, which is written only when it changes; otherwise the stored choice; otherwise `current_app.config["TEAMS_DEFAULT_VIEW"]`.
  - `switch_urls() -> dict[str, str]`: the current endpoint and arguments, with `view` set to each key.
  - In `overview.py`:
    - `ChartNode(NamedTuple)`: `row: TeamRow`, `children: list[ChartNode]`, `also_under: list[str]`, `folded: bool`.
    - `chart(rows: list[TeamRow]) -> list[ChartNode]`.
    - `member_counts(session) -> dict[int, int]`.
    - `tracker_counts(session) -> dict[int, int]`.

- [ ] **Step 1: Write the failing tests**

```python
def test_the_switch_keeps_the_choice_and_classic_is_unchanged(client, logged_in_admin):
    assert 'aria-current="page">New view' in page(client, "/admin/teams?view=new")
    assert 'aria-current="page">New view' in page(client, "/admin/teams")  # kept in the session
    html = page(client, "/admin/teams?view=classic")
    assert 'aria-current="page">Classic view' in html and 'class="teams-tree-card' in html

def test_a_team_under_two_teams_shows_once_with_also_under(db, team_factory):
    a, b = team_factory("Alpha"), team_factory("Beta")
    team_factory("Shared", parents=(a, b))
    nodes = chart(load_team_rows(db))
    shared = [n for n in walk(nodes) if n.row.name == "Shared"]
    assert len(shared) == 1 and shared[0].also_under == ["Beta"]  # under Alpha, the first by name

def test_the_chart_ends_on_a_cycle(db, team_factory):  # corrupted data: A at the top, B under A and C, C under B
    ...  # insert TeamParent rows directly as test_team_tree.py does; assert chart() returns and lists A, B, C once

def test_deep_wide_branches_fold(db, team_factory):  # level 4 with 9 children: folded; with 8: not
    ...

def test_the_chart_page_shows_each_team_with_its_counts(client, logged_in_admin, db, team_factory, user_factory):
    # one team with 2 active members and 1 inactive, 1 active and 1 archived tracker
    html = page(client, "/admin/teams?view=new")
    assert "2 members · 1 tracker" in html and 'data-chart' in html
```

- [ ] **Step 2: Run them; they fail** — `pytest tests/test_teams_new_view.py -n 6 -q`
- [ ] **Step 3: Implement.**
  - `chart()` places a team with several higher teams under the first by name; `also_under` names the others.
  - It walks with a path set, so it ends on a cycle.
  - `folded` is true when the depth is 3 or more and the team has more than 8 children.
  - `index_new.html` renders `_chart.html` as nested `<ul class="org-chart">`. The lines are CSS pseudo-elements; at
    phone width the same markup becomes an indented list.
  - Folded children sit in `<details><summary>+N teams</summary>`.
  - The search box (`data-chart-search`, wired in `teams-new.js`) adds `is-match` to matching nodes and
    `has-search` to the chart, using the existing `data-search` text.
- [ ] **Step 4: Run them; they pass. Also run `tests/test_teams.py tests/test_team_tree.py tests/test_templates.py`.**
- [ ] **Step 5: Commit** `feat: Teams New view switch and the hierarchy chart`

### Task 2: New team panel

**Files:**
- Modify: `index_new.html`, `tracker/teams/views.py` (`_render_index`, `create` error path keeps the view),
  `overview.py`, `teams-new.js`, `tracker.css`
- Test: `tests/test_teams_new_view.py`

**Interfaces:**
- Consumes: `chart`, `chosen_view` (Task 1).
- Produces:
  - `ReachPerson(NamedTuple)`: `name: str`, `role: str`, `team_name: str`.
  - `reach_people(session, rows) -> dict[int, list[ReachPerson]]`: for each team, every active person in it or in a team above it, once each, with their highest role. Within a role, people are sorted by name.

- [ ] **Step 1: Failing tests**
  - `test_the_panel_lists_where_a_team_can_sit`: radios `name="parent_id"`, "Top level" first, then each team indented by depth.
  - `test_the_panel_says_who_reaches_the_new_team`: the hidden list for EMEA Rates holds "Priya Nair · Owner · EMEA Rates" and "Sam Ortiz · Viewer · Global Markets" (`data-reach-for="<id>"`).
  - `test_a_refused_create_shows_the_new_view_with_the_panel_open_and_the_input_kept`: post a duplicate name with `view` kept in the session; the 400 page has `id="new-team-panel"` open, the name typed, and the error.
  - `test_the_button_names_the_team_and_where_it_goes`: the server render reads "Create team"; `teams-new.js` sets "Create <name> under <team>" (checked in Task 6's browser test).
- [ ] **Step 2: Run; fail.**
- [ ] **Step 3: Implement.**
  - "+ New team" is a link to `?view=new&new=1#new-team-panel`. JavaScript opens the panel in place; without it, the link opens the page with the panel open.
  - The panel has three numbered steps (spec goal 3) and posts to `teams.create` unchanged.
  - Region and location follow R3: `data-place-region` and `data-place-location` on each radio.
  - "Who reaches it straight away" shows the chosen team's `data-reach-for` list, at most 5 names and then "and N more"; for Top level it reads "Only the members you add".
  - R2's sentence sits under the radios.
- [ ] **Step 4: Run; pass, with `tests/test_teams.py`.**
- [ ] **Step 5: Commit** `feat: Teams New view: New team panel`

### Task 3: The team page: header, access map and People

**Files:**
- Create: `tracker/templates/teams/team_new.html`, `tracker/templates/teams/_tab_below.html`,
  `tracker/templates/teams/_tab_trackers.html`
- Modify: `team.html` (its Teams below and Trackers sections move into the two partials, with the same markup), `views.py` (`_render_team` picks the template; the New context below), `overview.py`, `teams-new.js`, `tracker.css`
- Test: `tests/test_teams_new_view.py`, existing `tests/test_team_page.py` (must pass unchanged)

**Interfaces:**
- Consumes: `member_counts`, `tracker_counts` (Task 1).
- Produces:
  - `paths_to(rows, team_id, parent_ids: frozenset[int] | None = None) -> list[list[TeamRow]]`: each chain from the top level down to just above the team. `parent_ids` replaces the team's own higher teams, for Task 5's After diagram. At most 6 chains, sorted by their names; the walk ends on a cycle.
  - New context keys:
    - `chains`;
    - `members`, the direct `PersonRow`s;
    - `from_above: list[tuple[str, str, list[PersonRow]]]`, as (team name, "team above" | "N levels up", rows), nearest first;
    - `reach_down: dict[int, int]`.

- [ ] **Step 1: Failing tests**
  - `test_the_map_shows_each_chain_and_this_team`: in a team under two chains, both chains appear in `<ol class="access-chain">`, and "4 members · 1 tracker" appears on this team.
  - `test_people_are_split_into_members_and_from_teams_above`: "Members of London Swaps" lists 4. "From EMEA Rates · team above" lists Priya and Tom. "From Global Markets · 2 levels up" lists Sam.
  - `test_a_member_outranked_from_above_is_told`: "Editor counts: Editor of EMEA Rates, above".
  - `test_the_role_switch_posts_to_update_member_and_works_without_javascript`: the radios are named `role` in a form posting to `teams.update_member`, with a `Set role` button. Posting `role=editor` changes the role.
  - `test_the_menu_holds_where_it_sits_and_delete`: the "⋯" menu (`<details class="team-menu">`) links to `teams.parents`. Delete is a form, or the refusal text when the team cannot be deleted.
  - `test_the_other_tabs_render_in_the_new_view`: `?tab=below` and `?tab=trackers` show today's tables.
- [ ] **Step 2: Run; fail.**
- [ ] **Step 3: Implement** per spec goal 4 and the Design A board. The role switch submits on change through a `data-autosubmit` radio group; extend the existing autosubmit handler to radios if it only handles selects. The Remove button keeps today's confirm text.
- [ ] **Step 4: Run; pass, with `tests/test_team_page.py tests/test_team_people.py tests/test_team_places.py tests/test_team_trackers.py`.**
- [ ] **Step 5: Commit** `feat: Teams New view: the team page with its access map`

### Task 4: Add a member panel

**Files:** Modify `team_new.html`, `views.py` (`add_member` error path keeps the view), `overview.py`, `teams-new.js`, `tracker.css`. Test: `tests/test_teams_new_view.py`.

**Interfaces:** Produces `reach_trackers(session, rows, team_id) -> list[str]`: the names of the active trackers of the team and every team below it, sorted by name.

- [ ] **Step 1: Failing tests**
  - `test_the_panel_explains_each_role`: three radio cards with the role guide's words (Viewer: "Opens the report and downloads it."; Editor: "Also records entries, writes the weekly update, keeps risks and targets."; Owner: "Also changes locations, settings and sends the report email.").
  - `test_the_preview_names_the_trackers`: the server render reads "will be a … on 2 trackers: Rates laptop refresh, Swaps desk rollout". JavaScript fills in the person and the role.
  - `test_a_refused_add_shows_the_new_view_with_the_message`: adding an existing member gives the 400 page in the New view with `ALREADY_MEMBER_MESSAGE` and the panel open.
  - `test_a_team_holding_sets_shows_the_refusal_instead_of_the_panel`: `TEAM_WITH_SETS_MESSAGE`.
- [ ] **Step 2: Run; fail. Step 3: Implement.** The person picker is today's select plus its `data-select-filter` box, and it posts to `teams.add_member` unchanged.
- [ ] **Step 4: Run; pass, with `tests/test_team_people.py tests/test_teams.py`. Step 5: Commit** `feat: Teams New view: Add a member panel`

### Task 5: Where it sits

**Files:**
- Create: `tracker/templates/teams/parents_new.html`
- Modify: `views.py` (`_judge_change`, `parents`, and `change_parents` gain `move`; `_render_parents` picks the template and passes `chains_now` and `chains_after`), `tracker.css`
- Test: `tests/test_teams_new_view.py`, `tests/test_team_parents.py` (unchanged, passes)

**Interfaces:** Consumes `paths_to` (Task 3). GET `?move=<id>` and POST `action=move` with `parent_id`.

- [ ] **Step 1: Failing tests**
  - `test_keep_shows_both_chains_after`: GET `?add=<APAC>` in the New view shows the Now chains, the After chains with the new link marked `is-new`, and "Gain access".
  - `test_move_replaces_every_higher_team`: a team under A and B, POST `action=move&parent_id=C`. It ends under C alone, logs two `team_parent_removed` entries and one `team_parent_added`, and the preview (GET `?move=C`) lists the losses.
  - `test_move_to_the_only_higher_team_is_a_notice`: moving to the team it is already only under gives the "already under" notice.
  - `test_move_is_refused_when_it_would_raise_own_access`: `SELF_PROMOTION_MESSAGE`, as for add.
  - `test_move_into_a_team_below_is_a_cycle`: `CYCLE_MESSAGE`.
- [ ] **Step 2: Run; fail. Step 3: Implement** per spec goal 5. "Keep <old>: under both" posts `add`; "Move it: <new> only" posts `move`. Both are radio choices that re-show the preview through a GET form.
- [ ] **Step 4: Run; pass, with `tests/test_team_parents.py tests/test_activity_labels.py`. Step 5: Commit** `feat: Teams New view: Where it sits, with move`

### Task 6: Browser checks and the full suite

**Files:** Test: `tests/test_teams_new_view_browser.py`

- [ ] **Step 1: Write the browser tests**, with `RECORDER` and `browser_sign_in`, and no CSP violations or errors on any page:
  - The chart search highlights a matched team.
  - The New team panel opens, fills the region from EMEA Rates, lists who reaches the team, and its button reads "Create Rates Ops under EMEA Rates".
  - A role radio saves on change.
  - The Add a member preview follows the person and the role.
  - At 390px width, no page scrolls sideways (the index, a team, and Where it sits).
- [ ] **Step 2: Run them; fix until they pass. Step 3: Run the full suite once (`-n 6`, in the background). Step 4: Commit** `test: Teams New view in the browser`
