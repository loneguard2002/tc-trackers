# Entries page: faster recording and a tidier list

Approved by the owner on 2026-11-17 from a clickable mockup (changes A and B of the Entries page review).

## Why

Editors record completions one entry at a time. Today each Record reloads the page and resets the location, so entering
a week for six locations, or several days for one location, means choosing the location every time. The page also has
two forms for the same four fields, rows twice the height they need, location chips whose numbers read like device
counts but count entries, and a Note column that breaks one letter per line on a phone.

## Goals

- **A. Faster recording**
  - One form: the quick-add form on the Entries page. "Full form" goes. `GET /entries/new` redirects to the Entries
    page so old links and bookmarks still work; the Home card's "Record completions" link points at the Entries page.
  - After Record, the page comes back with the same location and date chosen, Quantity and Note empty, the cursor in
    Quantity, and a line under the form: "Recorded 8 for London on 16 Nov 2026." The new row is highlighted briefly
    (a steady highlight when the person prefers reduced motion).
  - Record keeps the list's filters (week and location) as they were.
  - A refused entry comes back on the Entries page with the problems listed in the form and the values kept, not on a
    separate page. Status 400 as today.
  - The date field cannot go past today (`max`), the same rule the server applies; the week hint says so.
- **B. Tidier list**
  - Visible column headings: Date, Location (the tracker's group label), Quantity, Note.
  - Edit and Delete side by side.
  - Location chips count the tracker's unit (sum of quantities), under the label "<Units> recorded by <location>".
  - On a narrow screen each entry is a two-line card: location and quantity, then date and note.

## Non-goals

- A "record a week" grid (option C) — not now.
- Recording without a page reload (the mockup's script). The server round trip keeps the page working without
  JavaScript; what the person sees afterwards is the same.
- The week totals in each week heading keep counting entries ("6 entries").

## Approaches considered

1. **Server round trip with the last choice kept in the session** (chosen). The redirect after Record carries nothing in
   the address; the session remembers this tracker's last location, date, new entry and result line for the next page
   view. Works without JavaScript and keeps the list's filter links clean.
2. Pass the last location and date in the address after Record. Simple, but the address then mixes "filter" and "form"
   values, and a copied link pre-fills someone else's form.
3. Record through `fetch` without a reload (as in the mockup). Smoothest, but adds a second path for errors, totals and
   the list, and the page must still work without JavaScript.

## Builder's calls

- The session value is popped on the next Entries page view for the same tracker, so a later visit starts fresh.
- The result line is shown in the form (role="status"), not as a page flash.
