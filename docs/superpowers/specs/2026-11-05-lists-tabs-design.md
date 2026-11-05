# Lists: one menu entry with tabs

Status: approved by the owner in conversation, 5 November 2026 ("ok go for it"). Small change; follows
`2026-11-03-regions-locations-tables-design.md`, which still holds except where this note changes it.

## Why

The Administration menu has three entries for the reference lists (Regions, Locations, Business lines). The owner
asked for regions and locations on one page. The tables stay separate, because searching, sorting and filtering all
locations at once is why the capacity-style tables were built; a tab bar joins them under one entry instead.

## What changes

1. **Menu.** The three entries become one, **Lists** (globe icon), shown to administrators as today. It links to the
   Regions tab and shows as current on any of the three tabs.
2. **Tab bar.** Every list page starts with a tab bar: **Regions**, **Locations**, **Business lines**, each with its
   number of entries (all statuses), for example "Regions 3".
   - Each tab is an ordinary link to the page's existing address (`/admin/regions`, `/admin/locations`,
     `/admin/business-lines`). The current tab carries `aria-current="page"`, and the bar is a `<nav>` labelled
     "Lists". Addresses, Back, bookmarks and the region location-count link to a filtered Locations tab are
     unchanged, and the bar works without JavaScript.
   - Beneath the bar each page keeps its own heading, lede and Add button ("Add region", "Add location", "Add
     business line").
   - At 390 px the bar fits or scrolls inside itself; the page never scrolls sideways.
3. **Business lines in the table layout.** The page takes the same layout as Regions:
   - search box, All / Active / Retired buttons with counts, sortable columns (Name, Trackers, Status) and the footer;
   - the same row actions (Edit, Retire or Restore, Delete only when unused);
   - Add and Edit in a pop-up, with no-JavaScript pages at `/admin/business-lines/new` and
     `/admin/business-lines/<id>/edit` that render the table with that dialog open.
   - Field errors show beside the Name field, and the typed value is kept.
   - The rules, wording of refusals and Activity entries stay as today.

## Not changing

Regions and Locations tables, routes and behaviour; who may manage the lists (administrators only); Activity.

## Constraints

Strict CSP (no inline script or style), CSRF on every POST, works without JavaScript, light and dark themes, no
page-level horizontal scroll at 390 px, British formal copy in the active voice, every change to Activity.

## Approaches considered

1. **Link tabs over the existing pages (chosen).** One menu entry; each tab keeps its own address, so deep links and
   Back work and nothing needs JavaScript.
2. **One page, JavaScript tabs.** One address for three views, so links and Back lose the tab. Rejected.
3. **Regions with their locations beneath them.** Loses the cross-region search, sort and filter. Rejected.
