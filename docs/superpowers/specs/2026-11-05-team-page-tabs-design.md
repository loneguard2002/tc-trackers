# Team page: actions in the header, tabs below

Status: draft for the owner's approval, 5 November 2026. Mockup: https://claude.ai/artifact/5cbGV5ew2jWLLCtHRzzJSy
(version 5).

## Why

On a team's page, Edit details scrolls to a Details section at the bottom, and Delete is hidden inside it. People,
Teams below and Trackers sit one under another, so the page is long. The owner wants the actions in one place, editing
where the details are shown, and the three lists as tabs. Placing an existing team under this one should also be
possible from here, so teams are easier to rearrange.

## What changes

1. **Header card.** The name, the place line, the "Under …" line and the description, then one action row: **Edit
   details**, **Higher teams…**, **Delete team…** (red outline). A summary line follows: "5 people · 3 trackers · 2
   teams below".
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
6. **Tables on every tab**, built like the Lists tables (search box, column headings that sort, a footer "Showing n
   of n …"):
   - **People:** Person (name and email), Route, Role, then Remove for direct members; All / Direct / From teams above
     filters; the Add member form below the table.
   - **Teams below:** Team, Place, People, Trackers, then × Remove; New team beside the search; the Existing team form
     below the table.
   - **Trackers:** Tracker, Business line, Regions, Status, then Access; All / Active / Archived filters.
   - Pagination is left for later (owner, 5 November 2026).
7. **Unchanged:** the team tree on the left, roles and access rules.

## Constraints

Strict CSP (no inline script or style), CSRF on every POST, works without JavaScript, light and dark themes, no
page-level horizontal scroll at 390 px, British formal copy in the active voice, every change to Activity.

## Approach

One sensible way, matching the rest of the app: each tab and the edit form have their own address
(`?tab=below`, `?edit=1`), rendered by the server. Tabs and Edit details are links, so Back, bookmarks and pages
without JavaScript all work; a failed save re-renders the header in edit mode. A JavaScript-only toggle was rejected
because the app must work without JavaScript and Back would lose the tab.
