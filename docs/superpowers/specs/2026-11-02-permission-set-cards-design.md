# Permission sets: one card per set

Status: draft for the owner's approval, 2 November 2026.

Mockup: https://claude.ai/artifact/MWkKcUoS5RzxaP4xRcYWGP (light, dark and phone width; the set names and holder
counts in it are invented).

## Why

The owner wants the Permission sets screen (`/admin/permission-sets`) to look and feel like the capacity app's "Roles &
Permissions" tab: one card per role, permissions grouped under small headings, a count on each card, a locked system
role, and one save for everything. Today the screen is a table with permissions as rows and sets as columns, which
reads as a spreadsheet rather than as a description of each set.

## What changes

1. **Cards, not a table.** The Permissions section becomes a grid of cards that wraps onto further rows (two or three
   across on a desktop, one on a phone). No sideways carousel.
2. **The Administrators card comes first, locked.** It is not a permission set: it stands for the administrator flag on
   each person. It shows every permission with a padlock instead of a tick box, a "Built in" badge, the count "7/7",
   the line "Every permission, always. Only administrators change this screen.", and a footer "Held by N people"
   (active administrators) with a link to Users. It posts nothing.
3. **Each set's card**, in name order as today:
   - Header: a key icon in a tinted square, the set's name, its count of granted permissions ("3/7"), and its
     description (or "No description." in muted text).
   - Body: the permissions under three uppercase group headings, in the order of `PERMISSIONS`:
     - People and teams: Manage users, Manage teams.
     - Trackers: Create trackers, Import workbooks, View all trackers.
     - Application: Manage email settings, View activity.
     Each row shows the label, the existing description in small muted text, and the tick box on the right; the whole
     row is the tick box's label. The tick boxes keep today's names and values (`set-<id>`, the permission name), and
     each keeps an accessible name of the form "<permission> for <set>".
   - A warning on any card that grants both Manage users and Manage teams: "Holding both Manage users and Manage
     teams gives reach close to an administrator's."
   - Footer: "Held by 1 team and 2 people" (or "Nobody holds this set yet."), and a "Holders and details" link to the
     set's page.
4. **A "New permission set" card** ends the grid, dashed, holding today's create form (name, description, "Create
   permission set"). The page header gains a "New permission set" link that jumps to it. The separate "New permission
   set" section goes.
5. **One save bar** at the bottom of the grid, using the existing sticky `.settings-actions` bar: a padlock and
   "Administrators always hold every permission." on the left, the unsaved-changes note and "Save permissions" on the
   right.
6. **With JavaScript** (in `admin.js`, revealed controls only): ticking updates the card's count, marks a changed card
   (primary border and a "Changed" badge) and sets the note to "Unsaved changes in N sets"; untick back and the mark
   goes. Without JavaScript the note reads "Saving applies every card at once." and everything else works.

The page lede keeps the sentence about Manage users and Manage teams, so the screen states it even when no card holds
both.

## Approaches considered

- **One save for every card (chosen by the owner).** The grid form, its field names, the save action, its checks and
  its Activity entries stay exactly as they are; only the template, the styles and a little page data change.
- **A save button on each card.** Rejected: it needs a new save action and a change to the Activity entries, and
  unsaved ticks on one card are lost when another card is saved.
- **The capacity app's sideways carousel.** Rejected in conversation: with a handful of sets it hides most of them
  behind arrows; wrapping cards show every set at once.

## Out of scope

The set's own page (details, holders, deletion), the permission rules, the database schema and every POST endpoint.
Icons per set (sets have no icon field; every set gets the key icon).

## Constraints

Strict CSP (no inline scripts, styles or event handlers); CSRF on the form; British formal copy in the active voice;
works without JavaScript; no page-level horizontal scroll at 390 px; light and dark themes from the existing tokens;
touch targets at least 44 px high for the tick-box rows.

## Left to the builder

Where the permission groups live (next to `PERMISSIONS` is the natural place), how the holder counts are queried (one
grouped query, not one per set), class names, and the exact spacing, within the look of the mockup.
