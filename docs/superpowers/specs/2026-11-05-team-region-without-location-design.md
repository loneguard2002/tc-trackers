# A team's location becomes optional

Status: approved by the owner in conversation, 5 November 2026 (option 2, "i need global to not need a location").
Small change; amends section 2 of `2026-11-02-regions-locations-business-lines-design.md`, which still holds except
where this note changes it.

## Why

The owner added a region, Global, with no location, and could not place a team in it: a team stored only its
location, so the team forms offered only regions that have locations. Some teams belong to a region, such as Global,
without working from one city.

## What changes

1. **A team stores its region**, and its location becomes optional. When a team has a location, the location is in
   the team's region; the database keeps the two in step, so moving a location to another region still moves its
   teams with it, as today.
2. **Team forms (New team, Edit details).**
   - Region: every active region, including those with no locations; a retired region appears only on the team that
     already uses it. Required.
   - Location: optional. Its first entry reads **"No specific location"**. A chosen location must be in the chosen
     region, as today.
   - Help text: Region "Choose it first to narrow the locations."; Location "The city and country the team works in,
     if it works from one."
3. **Where the place shows.** The Teams tree and the team page show "Global" alone when a team has no location, and
   "EMEA · Geneva" as today when it has one. Activity names the place "EMEA" alone, or "Geneva, Switzerland (EMEA)".
4. **Counts and deleting.** The Regions table's Teams count counts teams in the region, with or without a location.
   A region that teams use counts as in use, so it can only be retired.
5. **Existing teams.** The migration gives each team with a location the region of that location. Teams with neither
   stay "Region not set", as today, until their next save.
6. A new tracker still starts with its team's region ticked.

## Not changing

Access: a team's region still grants nothing (the anti-goal). Locations and their screen. The rule that a retired
region or location cannot be chosen anew.

## Approaches considered

1. **Give Global a made-up location.** No code, but every location needs a city and a country, so the team would
   appear to sit in that city. Rejected.
2. **Store the region on the team and make the location optional (chosen).** One migration; the forms and labels
   change slightly; the database keeps a team's region equal to its location's region.
3. **Store the region on the team only when it has no location.** Avoids keeping two values in step, but every reader
   must look in two places for a team's region. Rejected.
