# Access screens: usability redesign

Status: approved 1 November 2026 (the owner chose the recommended options from the design canvas
https://claude.ai/artifact/1wnuvNzc6d4JQNeDPaAFXP: "ok do you recommendation please").

## Why

The Teams, team, Users, Effective access and tracker Access screens shipped with backlog item 1 work, but share the
complaint most often raised about comparable products (GitLab, GitHub nested teams, Confluence, Google Workspace
organisational units): people cannot tell where someone's access comes from. Specifically:

- A team's member count leaves out people who reach it from the teams above (Patching shows "0 members" while three
  people can open its trackers).
- A team page lists only direct members, mentions its child teams only inside the delete message, and puts the edit
  form above the members people come for. A role change takes a choice and a "Set role" click.
- Moving a team changes who can open trackers, but the screen does not say what will change before it happens.
- The Users table overflows at 1,440 px (the actions column is cut off), wraps names and addresses, and has no search.
- Tracker Access splits one question ("who can open this?") across three sections.

## What changes

1. **Teams: the tree beside the team.** `/admin/teams` and `/admin/teams/<id>` share one layout: the team tree on the
   left, the chosen team (or, on the index, the New team form) on the right. The tree marks the chosen team and shows,
   for each team, how many active people reach it: its own members plus active members of every team above it. A
   filter box above the tree narrows it to teams whose name, or one of whose people, matches (JavaScript only; without
   it the whole tree shows).
2. **Team page: people first.** In order: a header (path, name, description, counts, "Edit details" and "Move…"); People;
   Teams below; Trackers; Details and deletion.
   - People lists direct members (role select that saves on change, with the "Set role" button kept as the no-script
     fallback; Remove) and then everyone who reaches the team from a team above, each labelled "From <team path>" with
     a link to that team, and no controls. A person who is both shows once as a direct member, with the inherited role
     noted when it is higher. Buttons filter the list to All, Direct or From teams above (JavaScript only).
   - Adding a member keeps one form (person and role); a filter box narrows the person list as you type.
   - Teams below lists the direct child teams with their people counts and offers "New team below <name>", which
     opens the index with that parent chosen.
   - Trackers link to each tracker's Access tab.
   - Name and description sit in a collapsed section that opens when it has errors. The "Place in the tree" section is
     replaced by the Move… button.
3. **Moving a team: preview first.** "Move…" opens `/admin/teams/<id>/move`, where the person chooses where the team
   goes and sees, before confirming, every change to tracker access it causes: who loses access, who gains it and
   whose role changes, per tracker, and which trackers move with it. Administrators and inactive accounts are left out
   (their access does not change). The preview changes nothing; confirming posts to the existing move action, whose
   guards and activity entry are unchanged.
4. **Users: fits the screen.** One line per person (name and email do not wrap); columns Person, Status (with an
   Administrator badge), Teams, Permission sets and actions. An "Access" button opens the person's page; the other
   actions move into a "More" menu that works without JavaScript. Search (name or email), Status, Team and Permission
   set filters are a GET form, so a filtered list can be bookmarked. The table never overflows the page at 1,440 px;
   below that it scrolls inside its own box. The Awaiting approval section stays above the list.
5. **A person's access: the reason.** The Effective access page shows the sign-in method in its header, marks the
   route or routes that set each tracker role, and lists the person's teams (linked) and permission sets.
6. **Tracker Access: one list.** "Who can open this tracker" lists every active person with access, once, with their
   effective role and every route ("Direct role", "Team <path>", "Permission set <name>: View all trackers",
   "Administrator"). Direct roles keep a role select (saves on change) and Remove. One "Give a direct role" form (person
   with a filter box, role) replaces the "Add people" list. Buttons filter the list by route (JavaScript only). The
   Team section stays.

## Out of scope

The "Check one tracker" box, a limit on tree depth, bulk actions on users, and any change to who may do what. Every
POST endpoint keeps its fields, guards and activity entries.

## Rules carried over

Strict CSP (no inline scripts, styles or event handlers); CSRF on every POST; British formal copy in the active voice;
every screen works without JavaScript; layouts work at 390 px with no page-level horizontal scroll.
