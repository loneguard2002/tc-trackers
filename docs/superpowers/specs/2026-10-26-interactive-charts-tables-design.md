# Interactive report charts and filterable tables: design (short)

Date: 2026-10-26
Status: draft for approval
Size: a small change

## Intent

The report's charts are fixed matplotlib pictures (`tracker/report/charts.py`). They cannot show a value on hover, and they stay white in dark mode. The tables cannot be sorted or filtered. The owner wants rollovers on the charts, visible data points and filterable data tables on the live web page.

## Goals

1. **Charts on the live report page** (Remaining, Weekly actual against target, Cumulative completed) drawn in the browser with Apache ECharts:
   - **Rollover:** hovering on a week shows a crosshair and a tooltip with the week ending date, plan, actual and forecast, and the gap to plan where both exist.
   - **Data points:** every week's value is drawn as a dot.
   - **Legend:** clicking a legend item hides or shows that line.
   - **Zoom:** a slider zooms the date range, and the three charts zoom together.
   - **Save as image.**
   - **Dark mode:** charts follow the light or dark theme and redraw when it changes.
2. **Filterable tables** with Tabulator:
   - **Tables covered:** the report's per-location table and risks table, the Risks screen, and the Entries list.
   - **Features:** sort by clicking a column heading; a filter under each heading (a text box, or a drop-down for location, status and RAG); paging on the Entries list (50 a page); CSV export of the Entries list.
3. The numbers in the browser charts are exactly those in the PDF, PNG and email, because both come from the same report data.

## Non-goals

- Filtering a table does not change the charts, and there are no per-location charts. Both would need new per-location calculations; they can be added later.
- Interactive charts in the PDF, PNG or email. These keep the matplotlib pictures.
- Comparing trackers, or any new calculations.

## Anti-goals

- Loosening the Content Security Policy. No CDN, no inline scripts, no inline styles.
- A page that is empty without JavaScript. The server-drawn tables and chart pictures stay in the page, and the scripts enhance them.
- The web page and the PDF showing different figures.

## Constraints

- **Libraries:** ECharts and Tabulator are stored in the app as plain files under `tracker/static/vendor/`, each with its version in the file name and its licence file beside it. The versions are pinned in the plan.
- **Security policy:** under the policy (`script-src 'self'; style-src 'self'`), ECharts' default tooltip markup uses inline style attributes, which the browser blocks. The tooltip is therefore built by our own formatter with CSS classes from `tracker.css`.
  - The builder must confirm in a real browser that tooltips, the legend, zoom and Tabulator's filters work with no policy errors in the console.
  - The builder chooses ECharts' SVG or canvas renderer by that test.
- **Data:** the page fetches the chart data as JSON from a new route, `GET /trackers/<id>/report/data.json` (same `week` parameter and viewer check as the report page), built from the existing `build_report` rows. No inline data block is needed, so the existing template test for the security policy (`tests/test_templates.py`) stays as it is.
- **Templates:** `report/_body.html` is shared by the page, PDF, PNG and email, and keeps its `<img>` charts. Only the live report page loads the scripts. The scripts swap each picture for an interactive chart, with an `aria-label` and the picture's alt text kept as the accessible description.
- **Colours:** plan dashed grey, actual solid blue, forecast dotted amber, the same as matplotlib. The palette lives in one place and is passed to the page in the JSON, so both renderers match.

## Approaches

- **Apache ECharts (chosen by the owner).** It has the richest reporting features (crosshair tooltips, zoom slider, linked charts, dark theme, save as image). Its cost is the file size and the custom tooltip formatter needed for the security policy.
- **Chart.js.** Smaller and fits the policy as it is, but zooming, linked charts and dark mode need plug-ins or our own code.
- **Plotly and ApexCharts** were dropped because they conflict with the security policy. **D3** was dropped because every chart would be built by hand.
- **Tables:** Tabulator (my call, recommended alongside ECharts), rather than a small script of our own, for paging and column filters on growing lists.

## Testing

- **Without a database:** the JSON route returns the same weeks and values as the report rows, and refuses users without access (404).
- **With a database:** the route's access check and `week` parameter.
- **Browser tests** (Chromium, as the PDF tests already use) on the live report page with the real security policy:
  - no policy errors in the console;
  - the three charts render;
  - hovering shows the tooltip;
  - the theme toggle redraws the charts;
  - a column filter reduces the rows.
- **Existing tests stay green**, including the template scan for the security policy.

## Decided by the owner

- Rollovers and visible data points on the charts.
- Filterable data tables.
- A JavaScript charting library: Apache ECharts.

## Calls made by Claude (please check)

1. Tabulator for the tables.
2. Table filters do not change the charts in this change.
3. The PDF, PNG and email keep matplotlib, in the same colours.
4. Chart data comes from a JSON route rather than an inline block.
5. Zoom slider, legend toggling and save as image are included; paging (50 a page) and CSV export apply to the Entries list.

## Left to the builder

Exact tooltip layout and styling, the ECharts build (full or cut-down file), the renderer, and the Tabulator column definitions.
