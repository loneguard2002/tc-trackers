# Teams: a New view beside the Classic one

Agreed with the owner on 26 Nov 2026. Mockups: https://claude.ai/artifact/Eo4RZh5PMUPMfXeqT6ox6X (Design A boards).

## Why

People cannot see what a team membership gives. The People tab lists a role and a "Route", but not where access
comes from, which role counts when someone has two, or what a role allows. Creating a team and placing it in the
hierarchy happen in forms that do not show the hierarchy. The owner chose Design A (the access map) and wants it as a
**New view**, with today's pages kept as the **Classic view**.

## Goals

1. **A switch on every Teams page**: "New view · Classic view", the same segmented switch as the report's. The choice
   is kept in the session (`teams_view`); New is the default. Classic is today's pages, unchanged.
2. **Teams list (New)**: the hierarchy as an organisation chart, top down, with lines between teams. Each box: name,
   region colour and place, "N members · N trackers". A team under several teams shows under the first (by name) with
   "Also under X, Y". A search box highlights matching teams and people. Wide charts scroll sideways inside their box;
   at phone width the chart becomes an indented list.
3. **New team (New)**: "+ New team" opens a side panel: 1 Name; 2 Where it sits (the tree as radio choices, Top level
   first; "Also put it under a second team" adds a second choice); 3 Region and location ("Same as <team above>"
   ticked by default when the team above has one). Below: "Who reaches it straight away" (the people of the teams
   above, with their role and team). The button reads "Create <name> under <team>".
4. **Team page (New)**:
   - Header: name, place, "Edit details", and a "⋯" menu holding Where it sits and Delete (with today's refusal
     text when the team cannot be deleted).
   - **Access map** at the top: the chain of teams above (each a link with "N people reach down"), this team ("N
     members · N trackers"), and the teams below (or "None yet · Add a team below"). With several higher teams, each
     chain is shown.
   - **People tab** in two groups:
     - **Members of <team>**: each with a Viewer / Editor / Owner switch (saved on change; a Set role button without
       JavaScript) and Remove. When a higher role from a team above outranks the member's role here, a note says so:
       "Editor counts: Editor of EMEA Rates, above".
     - **Reaching this team from teams above**, grouped by team ("From EMEA Rates · team above", "From Global Markets
       · 2 levels up"), each with their role and "Change in <team>".
   - **Add a member** panel beside the list: person search, role cards each saying what the role allows (the role
     guide's words), and "<person> will be an <role> on N trackers: <first three names>". The rules that refuse an
     add today (elevated accounts, vouching, raising one's own access) still apply and show their messages.
   - Teams below and Trackers tabs: today's content, in the new header.
5. **Where it sits (New)**, replacing the Higher teams page in the New view: "Now under" chips with remove; "Put it
   under" a team; "Keep <old>: under both" or "Move it: <new> only"; Now / After diagrams (the new link dashed); then
   Gain access / Lose access / Role changes from today's preview (`move_impact`), and the confirm button. Nothing
   changes until it is confirmed, as today.

## Non-goals

No change to who can do what, to the rules of teams, or to Classic. No drag and drop.

## Approaches

- **Chosen:** new templates beside today's, picked by the switch; the routes, forms, guards and previews stay the
  same, so both views post to the same endpoints.
- Rejected: replacing today's pages (the owner wants Classic kept); a separate JavaScript app (the app is server
  rendered under a strict CSP).

## Left to the builder

Markup and class names; how the chart's lines are drawn (CSS only, no inline styles); how many teams the chart shows
before folding branches (fold below the third level when a branch has more than eight teams, with "+N teams").
