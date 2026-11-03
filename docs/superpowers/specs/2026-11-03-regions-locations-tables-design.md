# Regions and Locations as capacity-style tables

Status: draft for the owner's approval, 3 November 2026. Follows
`2026-11-02-regions-locations-business-lines-design.md` (stage 1, merged); that spec still holds except where this one
changes it.

## Why

The owner wants the Regions and Locations administration to look and work like the capacity app's: one table per list,
with search, filters, counts, short codes and a country flag. Today tc-trackers shows regions with their locations
beneath them on one page, edited in place, and a location's country is free text.

## Goals

1. Two pages, **Regions** and **Locations**, each a table in the capacity layout: page title and sub-title, an
   **Add** button, a search box, **All / Active / Inactive** buttons with counts, sortable columns, a footer reading
   "Showing 6 of 6 locations" with the active count.
2. **Locations** table columns: Code (badge), Name (the city), Region ("EMEA — Europe, Middle East and Africa"),
   Country (flag and name), Teams (count), Status, actions. A **region filter** sits beside the search.
3. **Regions** table columns: Code (badge, the existing short name), Name, Locations (count), Teams (count), Status,
   actions.
4. A location gains a **code** ("LON") and a **country chosen from the ISO 3166-1 alpha-2 list**. The country name
   and the flag always come from the code; nobody types a country name.
5. **Add** and **Edit** open in a pop-up window.

## Non-goals

- Tick boxes and bulk actions (the owner's call: delete is the only candidate, and it works only on unused entries).
- Business lines keep their current page.
- Any change to who may manage the lists (administrators only), or to how teams and trackers use them.

## Anti-goals

- Any request to an outside site. The capacity app loads flags from flagsapi.com; the tc-trackers security policy
  allows images from itself only, and an outside call would tell a third party who opened the page. Flags are stored
  in tc-trackers.
- One country spelt two ways. The stored value is the code alone.

## How it works

### Location fields

- **Code:** required, 2 to 6 capital letters, unique ignoring case. Typed letters are turned to capitals (my call;
  capacity allows 20 characters, which is longer than a badge holds).
- **Name:** the city, as today.
- **Region:** as today.
- **Country:** one list of every ISO 3166-1 alpha-2 country, each shown as flag, name and code ("United Kingdom
  (GB)"), sorted by name. Only the code is stored. The list and names are a fixed data file in the code (my call:
  the English short names from ISO 3166-1).
- City and country code together stay unique, ignoring case.
- Everywhere a location's country shows today (team drop-downs, the Teams tree, Activity entries such as "Geneva,
  Switzerland (EMEA)"), the name now comes from the code; a location with no country shows the city alone.

### Existing data (migration)

- Add `locations.code` and `locations.country_code`, both nullable at first; drop the free-text `country` column once
  its value is converted.
- The migration matches each typed country name to the ISO list ignoring case, plus a few common forms ("UK", "USA",
  "United States of America", "UAE"). Locations it cannot match keep no country and show **"Country not set"**; the
  next save requires one. Existing locations get no code; their badge shows the first three letters of the city in
  a muted style until an administrator sets one, and the next save requires it (my call).
- Uniqueness of city and country moves to the code-based pair; the migration refuses to run if two existing rows would
  collide, naming them, rather than guessing.

### Flags

- The flag-icons set (MIT licence, square-cornered 4:3 SVGs), one file per country, stored under the static folder
  with its licence beside it, as the charts library already is. Shown at 20 × 15 px in the table, 28 × 21 px beside
  the country list. A missing file shows a neutral flag icon.

### Tables

- Search matches code, name, region and country (Locations) or code and name (Regions), ignoring case, as the user
  types. The status buttons and the region filter combine with the search. Columns sort by clicking the header, with
  the arrow showing the direction; the default is Region then Name (Locations) and Code (Regions).
- Counts in the status buttons count the rows matching the other filters.
- Teams counts link to the Teams page. Locations counts on Regions link to Locations filtered to that region.
- Actions per row, as today: **Edit**, **Retire** or **Restore**, and **Delete** only when nothing uses the entry
  (otherwise its button is absent, as today). The in-use refusals and Activity entries stay unchanged.
- Without JavaScript the tables show every row in the default order, and the search, filters and sorting are hidden
  (my call: the lists are short).

### Pop-ups

- Add and Edit use a pop-up window built on the browser's own dialog element, with the capacity fields and layout:
  Region; Code and Name side by side; Country with the flag beside it. Errors show inside the pop-up, beside the
  field, keeping what was typed.
- Without JavaScript, Add and Edit are ordinary pages at their own addresses with the same form.
- Moving a location to another region keeps the existing note of how many teams move with it.

### Navigation

- The Administration menu entry "Regions and locations" becomes two entries, **Regions** and **Locations** (my call).

## Constraints

Existing rules hold: strict CSP (no inline scripts or styles, no outside images), CSRF on every POST, British formal
copy in the active voice, works without JavaScript, light and dark themes, no page-level horizontal scroll at 390 px
(the table scrolls inside its own frame), Alembic migration for every schema change, every change to Activity.

## Approaches considered

1. **Rebuild both pages in the tc-trackers style (chosen by the owner).** Capacity's layout, tc-trackers' colours,
   icons and dark mode, local flags, a no-JavaScript fallback.
2. **Copy the capacity page across.** Fastest to an identical look, but depends on Bootstrap and inline scripts, which
   tc-trackers does not use and its CSP blocks, and would look unlike every other screen. Rejected.
3. **Keep the single page and add the fields.** Cheapest, but not the table, search and filter look the owner asked
   for. Rejected.

## Left to the builder

File and route names; how the flag files are fetched and trimmed to the ISO list; the exact match table for common
country forms; how the pop-up and its no-JavaScript page share one template; table markup and sort implementation
within the existing design.
