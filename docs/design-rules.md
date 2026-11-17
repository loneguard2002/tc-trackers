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

## 3. Boxes and fields you can see

A box that is barely lighter or darker than the page disappears, and a field with a faint border does not look like
something to type into. Before this rule, card edges stood only 1.1 to 1.4:1 from the page and field borders 1.3:1.

- **Every box edge stands at least 1.5:1 from the page behind it.** `--border` is #b4c1d3 in light mode (1.8:1 on
  white) and #3b4350 in dark mode (1.6:1 on the card, 1.9:1 on the page).
- **Light mode lifts with shadow, dark mode with lightness.** Light: the page is #dfe6f1, boxes are white and carry
  `--card-shadow`, a faint two-layer shadow. Dark: shadows do not show, so `--card-shadow` is none and surfaces get
  lighter as they rise: page #0f1115, card `--surface` #1d222a, pop-up and sign-in panel `--raised` #252b35.
- **Fields people type into get a border of at least 3:1** (the WCAG minimum for form controls): `--field-border` is
  #7d8ca2 light (3.4:1) and #737e90 dark (3.9:1). This covers inputs, dropdowns, text areas, the number stepper and
  input suffixes. Checkboxes use the browser's own border, which already meets 3:1.
- **No box inside a box.** Only top-level boxes (cards, sections, panels, lists) get a border, shadow and white
  surface. Something inside a box uses a tinted fill or no frame at all, not another bordered white box. Charts inside
  report panels therefore have no frame of their own. Tables keep their frame, because it marks where rows start and
  end.
- **Text keeps at least 4.5:1** on every surface. To keep it on the deeper light page, light-mode amber `--warning`
  moved from #9a5b00 to #925600 (4.7:1 on the page, 5.9:1 on white).

The PDF and PNG report keeps its own white palette, with the stronger border but no shadows.
