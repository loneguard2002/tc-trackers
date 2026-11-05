# Team page: actions in the header, tabs below

Status: approved by the owner, 5 November 2026 ("fine. Let's implement this change"). Mockup: https://claude.ai/artifact/5cbGV5ew2jWLLCtHRzzJSy
(version 13; the row Remove buttons are icon-only in the build).

## Why

On a team's page, Edit details scrolls to a Details section at the bottom, and Delete is hidden inside it. People,
Teams below and Trackers sit one under another, so the page is long. The owner wants the actions in one place, editing
where the details are shown, and the three lists as tabs. Placing an existing team under this one should also be
possible from here, so teams are easier to rearrange.

## What changes

1. **Header card, compact** (owner, 5 November 2026: the first version wasted space).
   - Left: the name (26 px) with the description in grey to its right on the same line (it wraps below on a narrow
     screen), then one line of small pills: the region code with the location ("EMEA · London, United Kingdom", or
     "GLOBAL" alone) and "Under Group technology" (links).
   - Right, on the same row: **Edit details** (pencil) and **Higher teams** (tree icon), a thin divider, then
     **Delete team** as a red-outlined trash icon button with the label "Delete team" for screen readers and as a
     tooltip. On a phone the row wraps under the name.
   - No separate summary line: the counts sit on the tabs.
   - The tab bar is the bottom edge of the header card, so the header and tabs read as one block; the tab content
     is its own card below.
2. **Edit details in place.** The header card becomes the form: Name, Region, Location ("No specific location"
   first), Description, then **Cancel** and **Save details**. Errors show in the card, with the typed values kept. The
   Details section at the foot of the page is removed.
3. **Delete in the header.** **Delete team…** opens a confirmation strip inside the header card ("Delete
   Infrastructure? Its members lose the access it gives. This cannot be undone." with **Cancel** and **Delete**).
   When the team has teams below, the button is shown disabled with the reason beside it (today's
   `HAS_CHILDREN_MESSAGE`).
4. **Tabs.** **People (n)**, **Teams below (n)**, **Trackers (n)**, styled as the Lists tabs. People is the default.
5. **Teams below tab.**
   - **+ New team** (a plus icon and "New team"), opening the New team form with this team as its higher team, as
     today.
   - Each lower team has a small **× Remove** button, which takes it out from under this team (the team itself stays).
   - **Existing team**: a drop-down ("Choose a team") and **+ Add selected team**. The chosen team is placed under this
     one and keeps its other higher teams (my call: a team can already sit under several, and Remove takes it out of
     one). The drop-down leaves out this team, teams already below it, and any team that would make a loop.
   - Add selected team and Remove first show the same access preview as the Higher teams screen (who gains or loses
     which trackers), then save on confirmation. They go to Activity as `team_parent_added` and
     `team_parent_removed`, with the same checks.
6. **Tree help** sits to the right of the tree card's "Teams" title, in small grey text, and reads: "A team in several groups shows under each, marked “Also under”. Numbers count
   the people who reach a team." (owner: shorter and more informative).
7. **Tables on every tab**, built like the Lists tables (search box, column headings that sort, a footer "Showing n
   of n …"):
   - **People:** Person (name and email), Route, Role, then Remove for direct members; All / Direct / From teams above
     filters. The Add member form (Person, Role, Add member) sits at the top of the tab, above the search, so no
     scrolling is needed to administer (owner, 5 November 2026).
   - **Teams below:** Team, Place, People, Trackers, then × Remove; then a panel at the top of the tab, above the search, as on
     People: Existing team, + Add selected team, "or", + New team.
   - **Trackers:** Tracker, Business line, Regions, Status, then Access and × Remove; All / Active / Archived filters;
     **+ Add trackers** beside the filters.
   - **Search and pages on every table** (owner, 5 November 2026). Each table has a search box above it and a pager
     below it: "Showing 1–25 of 40 people", Rows per page (25, 50, 100; 25 to start), Previous, the page numbers and
     Next. Search, filters and sorting apply before paging, and a change of search or filter returns to page 1.
   - My call: every row is sent with the page and the script pages them, as the Lists tables already search and sort.
     Without JavaScript all rows show and the pager is hidden. A team holds tens of rows, not thousands, so the page
     stays light; server-side paging can follow if a team grows past a few hundred.
8. **Moving trackers into the team** (owner, 5 November 2026).
   - **+ Add trackers** opens a picker of the trackers not in this team: search, then a table with a tick box,
     Tracker, Current team and "Regions after the move". The button reads "Move 2 trackers here".
   - A tracker belongs to one team, so it moves here from its current team (or from no team).
   - **Regions:** a moved tracker keeps every region it has and gains this team's region when it lacks it, so people
     who reach it by region keep their access and the team's region is covered. Nothing is ever removed. A team with
     no region adds nothing. A new tracker already starts with its team's region ticked; that stays.
   - Before saving, the screen shows who gains or loses access (by team and by region), then the owner confirms. The
     existing rule stays: a person may not move a tracker so that they gain access themselves.
   - **× Remove** takes a tracker out of this team into no team; its regions stay.
   - Moves and removals go to Activity as `tracker_team_changed`; an added region goes as the tracker's regions change.
   - Who may do it: anyone with `manage_teams`, as for moving a tracker today.
9. **Unchanged:** the team tree on the left, roles and access rules.

## Buttons (owner, 5 November 2026)

- Main actions carry an icon and a label: Edit details, Higher teams, Add member, Add selected team, New team, Add
  trackers, Access.
- Destructive or secondary actions are icon-only, set apart, with their full name as a tooltip and for screen readers,
  as the Lists tables' Retire and Delete already are: Delete team (bin) in the header and Remove (×) on every row, for
  example "Remove Sam from Infrastructure".
- Not built: the optional "In teams below" view on a top team (offered, not chosen). The People tab lists who reaches
  the team's trackers, as today.

## Constraints

Strict CSP (no inline script or style), CSRF on every POST, works without JavaScript, light and dark themes, no
page-level horizontal scroll at 390 px, British formal copy in the active voice, every change to Activity.

## Approach

One sensible way, matching the rest of the app: each tab and the edit form have their own address
(`?tab=below`, `?edit=1`), rendered by the server. Tabs and Edit details are links, so Back, bookmarks and pages
without JavaScript all work; a failed save re-renders the header in edit mode. A JavaScript-only toggle was rejected
because the app must work without JavaScript and Back would lose the tab.
