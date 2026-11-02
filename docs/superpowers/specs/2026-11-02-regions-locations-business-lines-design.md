# Regions, locations, business lines and teams under several higher teams

Status: draft for the owner's approval, 2 November 2026.

## Why

Tradition works across Asia, EMEA and the Americas, and its trackers serve either the Tradition brokerage business or
TraditionData. Today tc-trackers knows nothing of either: a team has no region or location, a tracker has no business
line, and a regional head can only see a region's trackers if someone gives them a role on each one. The capacity app
already models regions, locations (cities in countries), teams placed in them, cross-region team groups and access by
region; the owner wants the same ideas here.

## Goals

1. Administrators keep three lists: **regions**, **locations** (a city, its country and the one region it belongs to)
   and **business lines**. Other screens offer them as drop-downs.
2. Every **team** has a region and a location.
3. Every **tracker** has a business line and covers one or more regions.
4. A person given a **region** sees every tracker that covers it, at a role the grant names.
5. A team can sit under **more than one higher team**, so one team can belong to two cross-region groupings at once
   (for example "Desktop Asia" under both "Global Desktop" and "Asia Infrastructure").
6. The home page filters by business line and region, and cards and reports show both.

## Non-goals

- Access by location (city). Locations label teams only, for now.
- Linking a tracker's breakdown rows (its "groups", such as London or Geneva) to locations. They stay typed names.
- Business lines granting access. They label and filter only.
- Permissions to manage the lists or give regional access. Both are administrator-only at first (see Constraints).
- Capacity-style flat team groups (rejected; see Approaches).

## Anti-goals

- A region granting access through a **team's** region. Regional access follows only the regions a **tracker** covers;
  a team's region is a label. Otherwise a cross-region higher team placed in EMEA would leak every tracker below it to
  the EMEA regional head.
- Two ways to group teams. Grouping is done only by placing teams under higher teams.
- Losing labels when an entry is retired: retired entries keep showing where they are already used.

## How it works

### 1. The three lists (Administration)

- A new Administration screen, **Regions and locations**, lists regions with their locations beneath them, and a
  **Business lines** section (one screen or two; left to the builder).
- A region has a short name ("EMEA") and a full name ("Europe, Middle East and Africa"), each unique.
- A location has a city, a country and its region. City and country together are unique. A location belongs to
  exactly one region and can be moved to another.
- A business line has a name, unique. The migration seeds two: "Tradition brokerage" and "TraditionData" (my call;
  administrators can rename them). Regions and locations start empty.
- Entries are never deleted while anything uses them; they are **retired** instead. A retired entry is not offered in
  drop-downs for new choices but keeps showing wherever it is already used, and regional grants on a retired region
  keep working until removed. An entry nothing uses can be deleted.
- Only administrators add, rename, move, retire or delete entries. Every change goes to Activity.

### 2. Teams: region and location

- The team create and edit forms gain **Region** and **Location** drop-downs; both are required. The location
  drop-down offers the locations of the chosen region.
- A team stores only its **location**; its region is always the region of that location (my call). The Region
  drop-down narrows the choice of location and is not stored separately, so the two can never disagree. Moving a
  location to another region therefore moves its teams with it, and the move screen says how many teams that is.
- Teams that exist before the change have neither. They keep working; the Teams screen marks them "Region not set",
  and the next save of the team requires both. Nothing else depends on a team's region (see Anti-goals).
- The Teams tree and the team page show each team's region and location.

### 3. Trackers: business line and regions

- The tracker create form and tracker settings gain **Business line** (one, required) and **Regions** (one or more,
  required, as tick boxes). On a new tracker the team's region is ticked to start with.
- The workbook import confirmation asks for both as well, as it already asks for the team (my call, following the
  teams spec), so imported trackers are never left out of regional access.
- Trackers that exist before the change have neither; they show "Not set" and the next save of their settings
  requires both. A tracker with no region is reached by no regional grant.
- Changing a tracker's regions changes who can see it, so the settings screen says so beside the tick boxes, and the
  change goes to Activity with the regions before and after.
- Who may change them: whoever may change the tracker's settings today (its owners).

### 4. Regional access

- On the region's page, an administrator gives a person access to that region with a role: **Viewer**, **Editor** or
  **Owner**, the same three roles a tracker already uses. The page lists everyone with access to the region and lets
  an administrator change the role or remove it.
- A person's role on a tracker becomes the highest of: administrator, a direct role, a team role, `view_all_trackers`
  and, new, **the highest role among their grants on the regions the tracker covers**.
- Regional access applies to active people only, as every other route does.
- The tracker's access list and the person's Effective access screen show the regional route, for example
  "Region EMEA · Viewer", beside the existing routes.
- Grants and their changes go to Activity.

### 5. Teams under several higher teams

- A team has **zero or more higher teams**. A team with none is top level. This replaces the single higher team.
- The rule for team roles is unchanged in words: a member of a team holds their membership role on the trackers of
  that team and of every team below it, by any path. If several paths reach a tracker, the highest role wins.
- A team cannot be placed below itself or below any team beneath it, by any path.
- All of a team's higher teams are **equal**: none is the main one, and nothing records an order (my call).
- The **Teams tree** shows a team, with the teams below it, under each of its higher teams. Every appearance of a team
  with more than one higher team carries a mark naming the others, for example "Also under Asia Infrastructure", and
  links to the one team page.
- The **Move** screen becomes **Higher teams**: add the team under another team, or remove it from one. Each change
  shows the existing impact preview (who gains and who loses access) before it is confirmed. Removing the last higher
  team makes the team top level.
- A team that has teams below it still cannot be deleted. Deleting a team removes its links to its higher teams.
- Counts of people who reach a team count each person once, however many paths reach them.
- Labels that show a team's place (selects, Activity entries) use the team's own name, which is already unique;
  where a path is shown today, the builder may show the team's higher teams instead.
- Existing data migrates as is: each team's current higher team becomes its only higher team.

### 6. Home page, cards and reports

- The home page filters gain **Business line** and **Region** (a tracker covering several regions matches each).
  Trackers with neither set match "Not set".
- Each card and the report header show the business line and the regions.

## Constraints

- Administrator-only management of the lists and of regional grants, written so that each can later become a
  permission in the permission sets without restructuring (the owner's stated next step).
- Existing rules hold: strict CSP, CSRF on every POST, British formal copy in the active voice, works without
  JavaScript, light and dark themes, no page-level horizontal scroll at 390 px, Alembic migration for every schema
  change.
- Access stays fail-closed: anything unset grants nothing.

## Approaches considered (for grouping teams across regions)

1. **Teams under several higher teams (chosen by the owner).** Keeps the one idea admins already use; the existing
   access walk already copes with more than one path. Costs: the tree shows a team in more than one place, and moving
   becomes adding and removing higher teams.
2. **Capacity-style team groups beside nesting.** Closest to the capacity app, but gives two ways to say "these teams
   belong together" and a fourth kind of access route. Rejected.
3. **Replace nesting with team groups.** One idea, identical to capacity, but discards the teams tree and team pages
   merged this week and needs existing teams converted. Rejected.

## Build order

Three stages, each merged on its own:

1. Lists, labels and filters (sections 1, 2, 3 and 6).
2. Teams under several higher teams (section 5).
3. Regional access (section 4).

## Left to the builder

Table and column names; whether the lists share one screen; how the location drop-down narrows to the chosen region
with and without JavaScript; the exact look of filters, labels and the "Also under" marks within the existing design;
how team labels read once a team has several higher teams; query shapes, provided the access rules above hold and
people are counted once.
