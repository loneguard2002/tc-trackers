# Design rules

Rules every page follows, in light and dark mode. Each one names what to do, why it works and where the app applies
it. Demo with before and after pairs: https://claude.ai/artifact/SaenpDkExQTsJK7RmSE21p

Contrast figures are WCAG 2 contrast ratios.

## 1. Dim the background behind a pop-up (figure and ground)

The eye splits every screen into a front and a back. Without a backdrop, the page behind a pop-up keeps full contrast
(about 16:1 for our body text) and competes with it.

- Every modal pop-up and the phone sidebar drawer dims the page behind it with the top-bar navy at 70%:
  `color-mix(in srgb, var(--topbar-bg) 70%, transparent)`.
- That leaves the page behind at about 2.5:1 (2.6:1 light, 2.5:1 dark). Do not go above 3:1 behind a pop-up, and do
  not go much below 2:1, so people can still see where they are.
- The pop-up itself keeps full contrast and its shadow.

Applied in `tracker.css`: `.list-dialog::backdrop` (Add, Edit, Delete, Reset password and Move trackers dialogs) and
`.sidebar-backdrop`.

## 2. Let the next item peek (closure)

The eye completes shapes that are cut off. A row that ends exactly at the screen edge looks finished, so people miss
what is beyond it. A cut-off item says "there is more".

- A row that scrolls sideways never relies on a scrollbar alone (ours are often hidden). The edge with more items
  behind it fades out over 40px, so the item there reads as cut off.
- When cards scroll sideways, size them so about a third (32%) of the next card shows.
- The fade appears only on an edge that has more to scroll to, and goes when the row reaches that end.

Applied in `tracker.css` and `tracker.js` to the tracker tabs (`.tabs`), the section links (`.subnav`) and the week
strip on the Weekly update page (`.week-strip`).
