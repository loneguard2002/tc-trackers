# Teams redesign PR 4: Person view — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** The person view (spec 4.8), People search in the Structure card (4.2), and names as links (4.5).

**Architecture:** `tracker/teams/person.py` builds everything the page shows from the existing access helpers;
`tracker_access_routes` gains a structured `kind`/`subject` on each `Route` so the page can word routes in plain
language without parsing text. One route, `/admin/teams/people/<user_id>`, renders `teams/person_new.html` beside the
Structure card, which marks the person's teams. The search list of people is a JSON attribute read by `teams-new.js`.

**Tech Stack:** Flask, Jinja, SQLAlchemy, ES5, strict CSP, pytest + Playwright.

**Spec:** `docs/superpowers/specs/2026-11-26-teams-simple-redesign-design.md` (4.2, 4.5, 4.8).

## Global Constraints

- Address `/admin/teams/people/<user_id>`, guarded by `manage_teams`; 404 for an unknown or deleted user.
- "Open in Users" (to `admin.access`) only for `manage_users` holders.
- "Rights in the app" and its figure only for administrators and `manage_users` holders.
- Every route explaining tracker access is shown to every `manage_teams` holder (owner's ruling).
- Route wording: "Member of <main path>", "<Region> regional access", "Given directly on this tracker",
  "Administrator", "View all trackers"; each with its role in brackets.
- "Can <first name> see…": `?check=<tracker_id>`, works without JavaScript; auto-submits with it.
- No inline script or style; ES5.

## Rulings

- R1 The person view has no Classic version: it renders the New view's frame whichever view is chosen (the switch
  links back to Teams). Cost: none; Classic never had it.
- R2 `Route` gains `kind` ("admin" | "direct" | "team" | "region" | "all") and `subject` (team id or region code, as
  text), with defaults, so Users › Access is unchanged.
- R3 "More teams they reach": the teams below each team they are a member of, minus those teams, each with "Through
  <nearest member team above>" and the highest role among their member teams above it.
- R4 The people search offers every active user (spec 4.2), embedded once per New view page as JSON in a data
  attribute (escaped, never run), up to 6 matches shown.

## Review Focus

1. A person in no team: page shows "No teams", trackers from other routes, and the check answer is right.
2. Inactive person: inactive note; lists say they give no access while inactive; no tracker list.
3. A tracker in no team: the "No" answer still reads correctly.
4. Several routes to one tracker: all listed, "the highest role wins".
5. A non-`manage_users` holder sees neither the Rights section/figure nor Open in Users.

### Task 1: The person model (`tracker/teams/person.py`) and structured routes
Tests in `tests/test_teams_person.py`: route kinds; teams and reached teams (R3); trackers with plain routes; check
answers (yes with several routes; no with a team; no without a team); rights (sets with labels; administrator; none);
inactive person.

### Task 2: The route and page
`teams.person` in `views.py`; `teams/person_new.html`; Structure card marks (member green "Member · Editor", reached
blue "Through X", others faded) with the "Showing <name>'s teams · Back to teams" strip. Tests: page sections and
figures, guards (403/404), Rights and Open in Users visibility, `?check=`.

### Task 3: People search and names as links
JSON of active users on the Structure card; `teams-new.js` shows up to 6 matching people above the tree, each linking
to the person view. People-list names and the add row's people link to the person view. Tests: server JSON, links;
browser: search shows people and opens the view; check auto-submits; no CSP errors; 390px width.
