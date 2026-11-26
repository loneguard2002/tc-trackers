# Teams area: simple redesign

Date: 26 November 2026. Status: for the owner's approval (builder check done; owner's rulings on visibility and counts
added).

- Mock-up (approved in the conversation): https://claude.ai/artifact/5DX3zD9KumoaDUQUQ85vrZ
- Research behind it: https://claude.ai/artifact/6GyeyQM4TbNJixHkqXoaGV
- Replaces: the Teams New view of `2026-11-26-teams-new-view-design.md` (PR #133) and the dotted chart lines of PR #134.

## 1. Why

The owner finds the current New view too complex. It has an access map, two member lists, a separate Where it sits
page with before-and-after diagrams, and an org chart as the landing page. The Classic view's logic is clear to them:
click a team in the structure on the left, and see its members and its higher and lower teams on the right. That
view still has problems:

- the right-hand side opens on a New team form;
- a team under two teams appears twice in the tree;
- the screens use the app's own words ("Route", "Higher teams", "reach");
- there is no place in Teams that answers "what can this person do, and why".

The goal is the Classic layout, made clearer with the patterns from the research:

- where each person's access comes from (GitLab);
- separate counts for members and for everyone who can see the trackers (Microsoft Entra);
- one person's memberships in one place (Google Inspect Groups);
- a yes or no access check that gives the reason (Entra, Google);
- a structure chart in which a shared team's second link is a dotted line (Workday).

## 2. Goals, non-goals, anti-goals

Goals
- One screen: the structure on the left, the chosen team (or person) on the right.
- Every team appears once in the structure. A shared team sits under its main team and is marked "Also under …".
- A team's place reads as an indented ladder: the path to the top, this team, then the teams just below.
- The People list says in plain words how each person gets access.
- Setting up a shared team is simple, and choosing its main team is explicit.
- A full-screen Whole structure picture that fits the screen, reads left to right and can fold branches.
- A person view that answers which teams someone is in, which trackers they can see and why, and what rights they
  hold.

Non-goals
- No change to who can see what. Access rules, guards and the activity log stay as they are.
- No change to the Classic view, which stays as the fallback behind the New/Classic switch.
- No drag and drop in the structure.
- No change to Users › Access. The person view links to it for account actions.

Anti-goals (a failure even if it works)
- Bringing back the complexity of the current New view: extra pages, diagrams or terms to learn.
- Any screen implying access that the rules do not give, or hiding access that they do give.
- A tree, ladder or dropdown that loses track of tiers.

## 3. Approaches considered

- **A. Replace the current New view with this design and keep Classic (chosen by the owner).** The New/Classic
  switch stays, and New becomes this design. The current New view's templates, the access map, the two member lists,
  the Where it sits page and the chart landing page are removed. Classic stays untouched until the owner retires it.
  This matches how the report redesign was handled and reuses the routes, guards and tests.
- B. Rework the Classic view in place and drop the switch. Least code, but nothing to fall back on, and every Classic
  test changes at once.
- C. Add a third view. Rejected, because it keeps the confusing view alive and triples the pages to maintain.

PR #134 was merged before the owner asked to close it. Its dotted lines are removed with the current chart in PR 3.

## 4. The design

The wording below is the wording to use. The New view keeps `chosen_view()` and the `teams_view` session key. The
test app keeps `TEAMS_DEFAULT_VIEW = "classic"`.

### 4.1 Page frame

- Title "Teams" with the team count, the lede "Members of a team can see its trackers, and the trackers of every team
  below it.", the New/Classic switch, and a **Whole structure** button.
- Below that, two columns: the **Structure** card on the left (sticky on wide screens) and the chosen team or person
  on the right. At phone width the structure stacks above.
- `/admin/teams` opens on the first top-level team by name, so the right-hand side is never a form. With no teams it
  shows an empty state that offers New team.

### 4.2 Structure card (left)

- Header: "Structure", a **+ New team** button, and a search box ("Find a team or person").
- Tree: each team once, under its **main** higher team (section 4.6). Each node shows:
  - the name;
  - the region mark and region or city (as today);
  - the count of people who reach it through teams, as "N people";
  - "Also under X, Y" when it has other higher teams.
- The current team is highlighted.
- Search filters the tree to teams matching the text (by team name or a member's name), keeping their parents
  visible. When the text matches people, a **People** list appears above the tree: up to 6 people, with "See
  memberships and rights". Choosing one opens the person view (4.8). The people offered are every active user, so
  someone in no team can still be looked up.
- Foot note: "The number is how many people reach a team through teams. A team under two teams shows once, under
  its main team."
- In person view (4.8) the tree marks that person's teams:
  - green "Member · Editor" for a member;
  - blue "Through EMEA" for a team reached through a team above;
  - every other team faded.
  A strip above the tree reads "Showing <name>'s teams", with a "Back to teams" link.

### 4.3 New team form

- **+ New team** opens a small form at the top of the Structure card. Without JavaScript the button is a link to the
  same form.
- Fields:
  - Name (required);
  - **Sits under** (Top level, or a team);
  - **Also under** (optional; "makes it a shared team");
  - Region and location (required as today, filled from the Sits under team unless changed);
  - Description (optional).
- Both team dropdowns list teams in structure order, indented by tier (4.7). Sits under starts on the team being
  viewed.
- Creating a team under a second team counts as a change of where a team sits. It applies the same rules as the Where
  it sits editor (4.6), including the self-promotion guard. The Sits under team becomes the main team.

### 4.4 Team panel (right): header

- The name, the region pill, **Edit** (the existing edit-in-place form) and **Delete** (the existing confirm and
  blocker).
- The description, when there is one.
- Three figures: "N members" (active direct members), "N people through teams" (active people from this team and
  every team above; owner's ruling: count through teams only, and say so), and "N trackers" (not archived). The members count and the People list's count must agree:
  both count active people only.
- **Where it sits**, an indented ladder:
  - the main path to the top, one step in per level, every team a link;
  - this team, highlighted and marked "this team" (or "this team · top level");
  - the teams directly below, one step further in, each a link with "+N below" when it has teams of its own. A team
    below whose main team is elsewhere also shows "shared, mainly under <team>". With none, the ladder reads "No
    teams below".
  - for each other higher team, an "Also sits under" line with that team's path, for example "Group › EMEA".
  - at the foot, **Change where it sits** (opens 4.6) and **Put an existing team below** (the existing `add_below`
    flow, which now lands in the editor of the team being placed).
- Two tabs: **People** and **Trackers**, with counts. The Teams below tab and the Higher teams button go, because the
  ladder replaces them.

### 4.5 People tab and Trackers tab

- An add row at the top: Person, Role, **Add member**. It keeps today's rules, refusals and messages, including the
  self-promotion guard and "This team holds permission sets…".
- Filters: Everyone, Members of this team, Through a team above, each with a count. A filter is hidden when its count
  is 0.
- The table has one row per person. Columns:
  - **Person**: avatar, name (a link to the person view), email, and an Inactive badge where it applies;
  - **How they get access**: one line per route, with a coloured dot. Green "Member of this team". Blue "Through
    <team> (<Role>)", with the team as a link;
  - **Role**: for a direct member, the role select (saves at once, as today), plus "Sees as <Role> through a team
    above" when an inherited role is higher. For anyone else, the role as text, with "Change in <team>";
  - remove (direct members only, with today's confirmation).
- A legend under the table explains the dots.
- A note under the legend (owner's ruling): "Administrators, people with View all trackers, regional access and roles
  given on a single tracker are not listed here. See a person's page, or a tracker's Access page."
- Regional access is not in the People list. A region grant covers trackers in a region, not teams, so listing it
  against a team would be wrong. It appears in the person view (4.8), against each tracker. This differs from the
  mock-up, which showed it in the People list.
- The Trackers tab stays as today (Move trackers here, the table, archive question), plus a line under the table: "Members also see N trackers of the M teams below."

### 4.6 Where it sits editor and the main team

- **Change where it sits** opens an editor in the team card. Without JavaScript, the link goes to the same editor as a
  page.
- The editor:
  - lists each higher team on its own row, with a **Main team** / **Make main** choice and a ✕ to take it out ("Top
    level: no team above it." when none);
  - offers **Add a team above** as an indented dropdown (4.7). The team itself, teams below it and teams already
    above stay in the list, disabled, with the reason: "this team", "below this team, would make a loop", "already
    above";
  - shows a preview before saving: "N gain access: …" in green and "N lose access: …" in red, or "No change in who
    can see its trackers.", plus "The same applies to the teams below it." when anything changes. This is the
    existing `move_impact` result, worded this way;
  - has **Cancel** and **Save**. Changes are made together and saved together, as in the approved mock-up. You can
    take one team out, add another and change the main team, then press Save once. Making a team main, adding and
    taking out change only the draft until Save, and the preview always shows the whole draft against what is saved
    now.
  - Save posts the full set of higher teams and the main team to one new endpoint, which:
    - validates each team as today (no loops, no unknown teams, no duplicates);
    - runs the self-promotion guard once over the combined change, so a combination can be refused even when each
      step alone would pass;
    - writes one activity entry per link added or taken out, plus "main team set" when the main changed.
  - Without JavaScript the editor is a page whose draft lives in the form, with an **Update preview** button and
    Save.
  - The current one-action-per-post `change_parents` stays for Classic.
- Main team (new data):
  - `team_parents` gains `is_main boolean not null default false`, with a partial unique index of one main per team.
  - The migration sets, for each team with higher teams, the first by name as main. That matches what the tree
    shows today.
  - Every team with higher teams has exactly one main. Taking out the main makes the next by name main. The first
    higher team a team is given is its main.
  - Changing only the main changes no access. It needs no self-promotion check, but writes an activity entry ("main
    team set").
  - The tree, ladder, dropdowns and Whole structure use the main team. Classic keeps its own display.

### 4.7 Dropdowns in structure order

Every team dropdown in the New view uses this pattern: Sits under, Also under, Add a team above, and Put an
existing team below.

- Teams appear in structure order, indented by tier with no-break spaces and "└ ".
- Each team appears once, under its main team.
- Teams that cannot be chosen stay in the list, disabled, with the reason, so the tiers never jump around.

It stays a native `<select>`.

### 4.8 Person view

- Address: `/admin/teams/people/<user_id>`, guarded by `manage_teams` like every Teams page. It opens from the People
  search results or a name in a People list.
- Header:
  - avatar, name, email, status badge;
  - **Open in Users** (to `admin.access`, shown only to `manage_users` holders);
  - four figures: teams they are in, more teams they reach, trackers they can see, sets of rights.
- **Can <first name> see…**: a dropdown of every tracker. Choosing one shows the answer without JavaScript, through
  `?check=<tracker_id>`, and auto-submits with JavaScript.
  - Yes: "Yes, as Editor." and each route, for example "Member of EMEA › London Desk (Editor)", with "the highest
    role wins" when there are several.
  - No: "<Tracker> belongs to <team>. <Name> is not in that team or any team above it, and has no other access to
    it."
- **Teams**: Team (link) | How (Member / Through <team> (team above)) | Role.
- **Trackers they can see**: Tracker | Role | Why. Why lists every route from `tracker_access_routes`, in plain
  words:
  - "Member of <path>";
  - "<Region> regional access";
  - "Given directly on this tracker";
  - "Administrator";
  - "View all trackers".
  Tracker names follow today's rule: `manage_teams` holders see them all. Owner's ruling: every `manage_teams`
  holder sees every route that explains tracker access (teams, regional access, direct roles, Administrator, View all
  trackers), so the "Can … see" answer is never partial.
- **Rights in the app** (owner's ruling: shown only to administrators and `manage_users` holders, as on Users ›
  Access; for everyone else the section and its figure are left out): each permission set held, directly or through
  a team ("held by team X"), with what it allows. With none: "None. <first name> can only work in the trackers above." Administrators read "Administrator:
  every permission."
- An inactive person shows today's inactive note, and their lists say they give no access while inactive.

### 4.9 Whole structure

- **Whole structure** opens a full-screen layer over the Teams page. Close, Escape or the backdrop closes it.
  Without JavaScript the button links to the Teams page.
- Header: "Whole structure", a line such as "15 teams · 5 levels shown · 3 shared", search ("Find a team"),
  Direction (**Left to right** default | Top to bottom), zoom (− | Fit | percentage, which returns to 100% | +), and
  **Fold all** / **Unfold all**.
- Layout:
  - computed in the page's script from data the server embeds. There is no new library: the layout is a simple
    tidy tree on main teams;
  - left to right gives one labelled column per level (Top, Level 2, …), and boxes are placed so each parent centres
    on its children;
  - solid lines run from the main team, and dotted amber lines from each other higher team, ending in a dot;
  - a shared team's box has an amber edge.
- Fit (on when opened) scales the chart to show every team. − and + zoom from there, and the viewport scrolls.
- Each box:
  - the name and "Region · City · N people" (through teams, as in the tree);
  - − / +N to fold or unfold its branch;
  - pointing at or focusing it lights its lines and outlines the teams at their other end;
  - clicking the name closes the layer and opens the team.
- Search unfolds the branches leading to matches, outlines the matches and fades the rest.
- The legend at the foot: solid "Where a team sits", dotted "Also sits under (shared team)", and how to use it.
- The page CSP stays as it is: no inline script, styles through classes or the CSSOM, and the data in a data
  attribute or a JSON element that is not run.

## 5. Delivery: four PRs

Each PR is usable on its own and follows the usual branch, PR and rebase-merge hand-over. Only the tests for the
changed areas run, plus `tests/test_templates.py`.

1. **Layout.**
   - Covers the page frame, the Structure card (each team once, main = first by name until PR 2), the team panel
     with the ladder, the People tab and the Trackers tab, the New team form (with Also under), and the indented
     dropdowns.
   - Removes the current New view's index chart landing page, access map and two-list People. Until PR 3, the Whole
     structure button opens the existing chart.
2. **Where it sits and the main team.** The editor (4.6) in the team card, migration `is_main`, the main-team choice
   and its activity entry. Removes the old New view Where it sits page.
3. **Whole structure.** The full-screen layer (4.9). Removes the old chart, `_chart.html`, and the dotted-line code
   from PR #134.
4. **Person view.** The route and page (4.8), People search in the Structure card, and names as links.

## 6. Calls made while writing this up (for the owner to check)

- Regional access is left out of a team's People list and shows in the person view instead (4.5).
- `set_team_parents`, which Classic's move uses, keeps exactly one main team: the current main if it is still a
  higher team, otherwise the first by name. Classic's screens do not change.
- "Also under" on the New team form takes one team. More can be added in the editor.
- Inactive direct members are listed with the Inactive badge, but no count includes them.
- Archived trackers and the "Member of <path>" wording follow the current helpers.
- The four PRs start from `main` (e1d2939, which holds the merged report-email fix #135).

## 7. Left to the builder

- Template and macro structure, and whether the editor and New team form are a `<details>` or a script-toggled block.
- The exact tidy-tree arithmetic and spacing in Whole structure, within the look of the mock-up.
- How the person search gets its list (embedded or a small JSON route), keeping to the CSP and `manage_teams`.
- Test names and fixtures. Reuse the existing Teams fixtures (`swaps` and others).
- Handling the deferred minors from the New view build that this design removes. Drop them where the code they
  refer to is gone.
