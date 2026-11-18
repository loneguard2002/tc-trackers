# Permission sets page redesign

Agreed with the owner on 18 Nov 2026 from a clickable demo (local demo and the "Tracker UX Laws" artifact, section
"One row of sets, made in four steps"). Demo code, for reference only:
`/tmp/claude-1000/-home-alexkrovina/cf13b4e4-1890-473a-b9dc-06d0fca97d35/scratchpad/mockup-permsets/` (`index.html`,
`static/mockup.js`, `static/mockup.css`).

## Why

The Permission sets page wraps its cards into rows, puts creating a set in a dashed card at the end, keeps the save
bar on screen all the time, and hides rename, holders and delete on a separate page. The owner wants one row of cards
that reads straight across, a guided create, and every action reachable from the card.

## Goals

1. **Pinned head.** The title, the explanation and the buttons stay pinned under the top bar while the page scrolls,
   frosted like the save bar (`saturate(180%) blur(12px)` on a 78% page-colour background).
2. **One sideways row.** Wider than 700px the cards sit in one row that scrolls sideways: about a third of the next card
   shows (design rule 2), card width between 340px and 460px, the edge with more cards behind it fades, the row snaps to
   a card, and the permission rows stay lined up across the cards (the existing subgrid). On a phone the cards stack.
   **‹ ›** buttons in the head step the row one card at a time (drawn chevrons, centred, the height of the New button;
   disabled at either end).
3. **No count badge** on the cards (the "3/8" pill goes).
4. **⋯ menu on each set's card** (not on Administrators): Rename or edit description, Holders and details, Delete….
   Arrow keys move through it, Escape and an outside click close it.
5. **Rename pop-up** (name and description, the existing rules and messages) and **Delete pop-up**: "Delete *name*?",
   "This cannot be undone.", who holds it ("Held by 2 teams and 1 person", from the existing holder counts) and the
   permissions they lose, or "Nobody holds this set, so nobody loses anything.", then "The activity log records the
   deletion and each holder removed." with Cancel and a red **Delete set**.
6. **Holders and details side panel**, from the ⋯ menu or the card's "Holders and details" link: slides in from the
   right at full height over the dimmed page (design rule 1 backdrop). Header: name, description, its own ⋯ menu
   (Rename, Delete) and ✕. Body: **Holders** (each team with its path and each person, with Remove; an Add holder picker)
   and **Permissions** (the granted ones as chips, "Change them on the set's card."). Escape, ✕ or a click on the backdrop
   closes it and returns the focus to the card. `?set=<id>` in the address opens it on load, so a link or a redirect
   lands on it.
7. **New permission set in four steps**, in a pop-up, replacing the dashed card:
   1. Details: name (required, unique, checked as you press Next and again on the server) and description.
   2. Permissions: the same groups and rows as the cards, "N of 8 ticked", and the Manage users + Manage teams warning.
   3. Holders (optional, "Skip for now"): search teams and people, picked ones as removable chips.
   4. Review: three blocks (Set, Permissions with groups and "Not included", Holders as chips) each with an Edit button,
      then "Nothing is saved until you press Create permission set."
   The step bar is one track from the first circle to the last with the names under the circles; the green fill grows by
   a third per step; finished steps show a tick and can be clicked (or Enter) to go back. Create posts once; the set,
   its permissions and its holders are saved together, and the page reopens with the new set's panel open.
8. **The save bar appears only with unsaved changes**: it slides up with "N unsaved change(s) in M set(s)", Discard and
   Save permissions, hides when the ticks are back as saved, warns before leaving the page with unsaved changes, and
   respects reduced motion. The changed card keeps its existing "Changed" mark.

## Non-goals

- No change to which permissions exist, to who may use the page (administrators only), or to the set's own page,
  which stays as the no-JavaScript fallback for Holders and details.
- No bulk actions, no reordering of sets.

## Approaches

- **Chosen:** keep the page server-rendered and add behaviour in `admin.js`. The side panel's body is an HTML fragment
  from a new route, its forms post to the existing holder routes and come back to the page with `?set=<id>`. The
  four-step create posts once to the existing create route, which also accepts permissions and holders.
- Rejected: a JSON API with client rendering (a second way to render sets and holders); separate pages for each step
  (slow, loses the overview).

## How it behaves (decided)

- **Without JavaScript:** the head is not sticky-dependent, the cards still show (wrapping as today is acceptable), New
  permission set links to a plain create page (`/admin/permission-sets/new`, name and description), "Holders and
  details" links to the set's own page, the ⋯ menus and ‹ › buttons stay hidden, and the save bar stays visible.
- **Return to the page:** forms sent from the page carry `return_to=index`; rename and holder changes then redirect to
  `/admin/permission-sets?set=<id>`, delete to `/admin/permission-sets`. Without it the routes behave as today.
- **Create:** `permissions` (names; unknown ones ignored) and `holders` (`team:<id>` / `user:<id>`, the existing format;
  unknown, inactive or duplicate ones ignored) are saved with the set in one transaction, with the existing activity
  entries (created, permissions changed, holder added).
- **Errors:** a refused create from the pop-up comes back as the create page with the errors and values kept (status
  400); a refused rename or holder change from the panel comes back as the set's own page with its errors, as today.

## Left to the builder

Markup, class names and the split of `admin.js` (it may move the page's code to a new `permsets.js`), as long as the
behaviour above holds and the page passes the Content Security Policy.
