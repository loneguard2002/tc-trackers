# Report page: "Status at a glance" view and target date history

Agreed with the owner on 24 Nov 2026 from the "Report dashboards" canvas
(https://claude.ai/artifact/UtLzrU4cjJzRCXKCiPtbM2, artboard "1 · Status at a glance"). The owner asked for the
redesign with a button to switch between the new and the old view.

## Why

The live report spreads its answer over a status band and four tiles, shows the same progress twice (Remaining and
Cumulative), has no trend on its figures, no status history, lists locations in a fixed order, and never shows that the
target date has moved. Readers want, at a glance: are we on course, what is needed from me, what is left and when it
finishes, and whether the goalposts moved.

## Goals

1. **Two views of the live report, switched by a button.** A segmented control in the report toolbar, "New view" and
   "Classic view". The classic view is today's page, unchanged. The choice is remembered for the person (in their
   session) so the next report they open uses it; `?view=new` or `?view=classic` in the address sets it. Without
   JavaScript the control is two links and works the same.
2. **The answer card** (new view, top): the status badge (icon + word: Green, Amber, Red, Not set), one plain sentence
   built from the figures, the headline under it, and "Needed from you" in its own panel beside it with who wrote the
   update and when. The sentence follows the existing verdict logic, for example "On course to finish on 11 Dec, a week
   before the 18 Dec target, though 30 behind plan." or "Forecast to finish on 8 Jan, 21 days after the 18 Dec target.".
3. **Four figure tiles with a small visual each:** Completed (progress bar, "75% · 125 left"); This week (sparkline of
   the weekly actuals so far, "+2 against target · next week 40"); Rate over the moving-average weeks (bar with a mark
   for the rate needed); Forecast finish (mini timeline with the forecast dot and the target mark, plus "Target moved
   twice: 4 Dec → 11 Dec → 18 Dec" when it has moved). Tones follow today's rules (success when ahead, danger when
   behind).
4. **One "Remaining" chart** (counting down to none left) replacing Remaining + Cumulative in the new view: actual
   (solid, dots per week), plan (dashed, rings per week), forecast (dotted) from the report week to none left; the
   y-axis in units left, every week ending along the bottom (day numbers with the month under the first week of each
   month); a "today" marker on the report week; the current target as a solid dashed line with badge and "Target
   18 Dec"; **earlier targets as faint dashed lines with numbered rings**. Direct labels at the report week ("Actual: 125
   left", "Plan: 95 left") and at the forecast end ("Forecast: none left on 11 Dec"). Hover shows the week's figures.
   Under the chart, **"Target date changes"**: each target with its number, date (earlier ones struck through), when it
   was set or moved, by how many days, and the reason; a heading note "moved twice, 14 days later than first set".
   Shown only when the target has changed at least once.
5. **Status, last 12 weeks:** a strip of the saved weekly statuses up to the report week, each square with its letter
   (G, A, R, – for not set) so colour is never the only signal, the report week outlined, and a one-line summary
   ("Amber for 3 weeks; Red once, on 9 Oct.").
6. **Top risks**, as today's selection (worst first, at most three), each with its RAG chip and icon, title, how far past
   its target date or its due date, location and owner; "3 of 7 open" in the heading.
7. **Locations, furthest behind first** (lowest % complete first), retired ones left out as today: RAG chip, name, "done
   of scope · %", a bar with the part done before the first week lighter, and a note line ("N left", "N done before the
   first week", planned completion date when set). A key above: "Done before the first week", "Done since". The "Not
   shown: N retired …" line and the data check note from today stay.
8. **Target date history** is recorded. Every change to a tracker's target completion date (Settings, and the tracker's
   creation if a target is given) stores the old and new date, when, who, and a reason. Settings asks for the reason in
   a field shown when the target date changes ("Why is the target moving?"); see Calls made.

## Non-goals

- No change to the PDF, PNG or emailed report in this work: they keep today's layout (see Calls made).
- No change to the Weekly and Cumulative charts in the classic view.
- No per-location plan line (the tracker has a weekly plan only for the whole tracker).

## Approaches

- **Chosen:** a second body template for the new view on the live page, sharing the report data (`build_report`) with
  the classic one; charts as interactive ECharts as today, with the server-drawn picture as the no-JavaScript fallback
  extended to show the target markers. The toggle is server-side (session + `?view=`), so it works without JavaScript.
- Rejected: rewriting the existing body in place (no way back for readers who prefer it; the owner asked for a toggle).
- Rejected: a browser-only toggle with both views in the page (twice the markup and charts on every load).

## Calls made (the owner may change these)

- The new view is the default for everyone; the classic view is one click away and remembered.
- The PDF, PNG and email keep the classic layout for now; moving them to the new layout is a follow-up once the page
  has settled.
- The reason for moving the target is **optional** (a change without one is still recorded); the history shows "No
  reason given".
- Target changes made before this ships are not known; history starts with the first change after it (the current
  target shows as ③ only once there are earlier ones).
- Status history uses the weekly updates' saved status; a week with no update shows "–". The summary line is the
  streak ending at the report week ("Amber for 3 weeks") plus the Red weeks in the 12 shown ("Red once, on 9 Oct";
  "Red 3 times" when more than two); "–" weeks break a streak and are not counted.
- **A past week shows the target as it stood then.** On the new view, the answer card, the tiles and the chart use the
  target in force at the end of the report week, and the chart and "Target date changes" list only the changes made
  up to that week. (The classic view is unchanged and keeps using the current target.)
- The chart's x-axis runs from the first week to the latest of: the last week, the forecast end and every target shown,
  so no target line is clipped.
- Counting moves: setting a target where there was none is "Set"; changing a date is a "move" (with "+N days" or
  "−N days"); removing it is "Target removed". "Moved twice" counts date-to-date changes only. Saving Settings with the
  date unchanged records nothing (a reason typed then is ignored); two changes on one day are two entries. A tracker
  created (or imported) with a target records one "Set" entry.
- "Needed from you" and "who wrote it" come from the report week's update only; with no update for that week the panel
  says "No weekly update written for this week." (as the classic view does).
- The view choice affects the live page only (`report.view`); the chart picture route serves a new picture for the new
  view's Remaining chart, and the classic pictures, PDF, PNG and email do not change.
- No backfill of target history; the reason field is in Settings only, not on the create form.

## Left to the builder

The table name and shape for target history, the session key, template and class names, how the ECharts option adds
the target lines, and the matplotlib fallback's drawing, as long as the behaviour above holds, every chart passes the
colour checks in light and dark (the palette validated on the canvas: light actual #1260d0, plan #008f82, forecast
#c27a00; dark #5b8ff0, #22a596, #b8801c, with line style and direct labels as second encodings), the page passes the
Content Security Policy, and the copy is British English without contractions.
