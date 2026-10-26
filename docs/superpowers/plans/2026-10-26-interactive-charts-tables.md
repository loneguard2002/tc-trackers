# Interactive Report Charts and Filterable Tables Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the fixed chart pictures on the live report page with interactive Apache ECharts charts (rollovers, data points, legend, linked zoom, dark mode), and make the report, Risks and Entries tables sortable and filterable with Tabulator.

**Architecture:** A new JSON route serves the same weekly series the matplotlib renderer draws. `report-charts.js` swaps each `<img data-chart>` on the live page for an ECharts chart. `tables.js` rebuilds any `<table data-table>` as a Tabulator table from its own rows. The PDF, PNG and email keep the matplotlib pictures, and `report/_body.html` stays shared by all four outputs.

**Tech Stack:** Flask, Jinja, Postgres (unchanged); Apache ECharts 6.1.0 and Tabulator 6.6.1, stored in `tracker/static/vendor/`; Playwright Chromium for browser tests.

**Spec:** `docs/superpowers/specs/2026-10-26-interactive-charts-tables-design.md`

## Global Constraints

- The Content Security Policy in `tracker/app.py` stays exactly: `default-src 'self'; style-src 'self'; font-src 'self' data:; script-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'`. No CDN, no inline scripts, no `style=` attributes, no `<style>` blocks in served templates (`tests/test_templates.py` enforces the templates).
- Library files: `tracker/static/vendor/echarts-6.1.0.min.js`, `tracker/static/vendor/tabulator-6.6.1.min.js`, `tracker/static/vendor/tabulator-6.6.1.min.css`, with each licence beside them (`LICENSE-echarts.txt`, `NOTICE-echarts.txt`, `LICENSE-tabulator.txt`). Fetch them with `npm pack` from `registry.npmjs.org` (the only network host needed).
- Chart colours, the same as matplotlib (`tracker/report/charts.py`): plan `#888888` dashed, actual `#2c7be5` solid, forecast `#d39e00` dotted.
- The PDF, PNG and email keep the matplotlib pictures. `report/print.html` loads no scripts.
- The page works without JavaScript: the server-drawn `<img>` charts and plain tables stay in the markup.
- Entries list: 50 rows a page and CSV export.
- British English in all interface text.
- `rtk .venv/bin/pytest` (with `TEST_DATABASE_URL` set) and `rtk .venv/bin/ruff check . && rtk .venv/bin/ruff format --check .` pass after every task.

## Review Focus

- A tracker with no entries or targets yet: the charts show an empty frame with "No data yet", not a script error (test in Task 2).
- The chart data request fails, for example because the session expired and the route redirects to the sign-in page: the static pictures stay in place (test in Task 2).
- Location names or the unit label containing HTML characters, such as `<i>LD5</i>`: they show as literal text in tables and charts, and are never interpreted as markup (test in Task 3).
- The week selector: the charts show the selected week's data, not the default week's (test in Task 2).
- Action cells (Delete forms, Edit links) inside enhanced tables still work, including the CSRF token (test in Task 3).

---

### Task 1: Chart series and the JSON route

**Files:**
- Modify: `tracker/report/charts.py` (add `PALETTE` and `chart_series`)
- Create: `tracker/report/chart_data.py`
- Modify: `tracker/report/views.py` (add the route)
- Test: `tests/test_report.py` (no database), `tests/test_chart_data.py` (database)

**Interfaces:**
- Produces:
  - `PALETTE: dict[str, str] = {"plan": "#888888", "actual": "#2c7be5", "forecast": "#d39e00"}` in `charts.py`, built from the existing `PLAN`, `ACTUAL` and `FORECAST` constants.
  - `chart_series(rows: list[WeekRow]) -> dict[str, list[float | None]]` in `charts.py`, with the keys `planned_remaining`, `actual_remaining`, `forecast_remaining`, `target`, `actual`, `cum_target` and `cum_actual`. Every list has `len(rows)` items, aligned to `rows`, and holds `None` wherever the matplotlib charts draw no point.
  - `chart_payload(tracker, rows: list[WeekRow]) -> dict` in `chart_data.py`, returning `{"unit_label": str, "palette": PALETTE, "weeks": [ISO date strings], "series": chart_series(rows)}`.
  - The route `report.chart_data`: `GET /trackers/<int:tracker_id>/report/data.json`, with an optional `week` parameter.

**Inclusion rules** (they must match the renderers):
- `actual_remaining` and `cum_actual` cover completed weeks only (`row.state == COMPLETE`), as `actual_series` does.
- `actual`, `target`, `planned_remaining` and `cum_target` cover every row whose value is not `None`, as `_series` does.
- `forecast_remaining` covers rows from the last week with a `moving_average` onwards, as in `remaining_chart`. If fewer than 2 such points exist, every value is `None`.

- [ ] **Step 1: Write the failing tests (no database) in `tests/test_report.py`**

```python
from tracker.report.chart_data import chart_payload
from tracker.report.charts import PALETTE, _series, actual_series, chart_series


def _points(rows, values):
    return [(r.week_ending, v) for r, v in zip(rows, values) if v is not None]


def test_chart_series_aligns_with_rows():
    rows = sample_rows()
    series = chart_series(rows)
    assert set(series) == {"planned_remaining", "actual_remaining", "forecast_remaining", "target", "actual",
                           "cum_target", "cum_actual"}
    assert all(len(values) == len(rows) for values in series.values())


def test_chart_series_matches_the_matplotlib_series():
    rows = sample_rows()
    series = chart_series(rows)
    for key in ("planned_remaining", "target", "actual", "cum_target"):
        assert _points(rows, series[key]) == list(zip(*_series(rows, key)))
    for key in ("actual_remaining", "cum_actual"):
        assert _points(rows, series[key]) == list(zip(*actual_series(rows, key)))


def test_chart_payload_shape():
    rows = sample_rows()
    payload = chart_payload(SimpleNamespace(unit_label="devices"), rows)
    assert payload["palette"] == {"plan": "#888888", "actual": "#2c7be5", "forecast": "#d39e00"} == PALETTE
    assert payload["weeks"] == [w.isoformat() for w in WEEKS]
    assert payload["unit_label"] == "devices"
```

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `rtk .venv/bin/pytest tests/test_report.py -k "chart_series or chart_payload" -q`
Expected: FAIL with an `ImportError` for `chart_payload`.

- [ ] **Step 3: Implement `PALETTE`, `chart_series` and `chart_payload`**

Implement them with the signatures and inclusion rules above. Do not change the existing matplotlib functions.

- [ ] **Step 4: Run the tests and confirm they pass**

Run: `rtk .venv/bin/pytest tests/test_report.py -q`
Expected: PASS.

- [ ] **Step 5: Write the failing route tests in `tests/test_chart_data.py`**

Use the `small_tracker`-style fixture (Core Rollout, weeks ending 4 Sep to 25 Sep 2026), plus `logged_in_user` and `grant`.

```python
def test_chart_data_requires_a_role(client, logged_in_user, small_tracker):
    assert client.get(f"/trackers/{small_tracker.id}/report/data.json").status_code == 404

def test_chart_data_returns_the_tracker_weeks(client, viewer, small_tracker):
    data = client.get(f"/trackers/{small_tracker.id}/report/data.json").get_json()
    assert data["weeks"] == ["2026-09-04", "2026-09-11", "2026-09-18", "2026-09-25"]
    assert set(data["series"]) >= {"planned_remaining", "actual_remaining", "forecast_remaining"}

def test_chart_data_bad_week(client, viewer, small_tracker):
    assert client.get(f"/trackers/{small_tracker.id}/report/data.json?week=nope").status_code == 400
    assert client.get(f"/trackers/{small_tracker.id}/report/data.json?week=2026-09-05").status_code == 404
```

- [ ] **Step 6: Implement the route `chart_data(tracker_id: int)` in `tracker/report/views.py`**

Use `@require_tracker_role("viewer")` and `_requested_week`. Build it from `compute_position(get_session(), tracker, week, today())`, not from `build_report`, so no matplotlib rendering happens. Return `jsonify(chart_payload(tracker, position.rows))`.

- [ ] **Step 7: Run the route tests and confirm they pass**

Run: `TEST_DATABASE_URL=… rtk .venv/bin/pytest tests/test_chart_data.py tests/test_report.py -q`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add tracker/report/charts.py tracker/report/chart_data.py tracker/report/views.py tests/test_report.py tests/test_chart_data.py
git commit -m "feat: chart data JSON route serving the same series as the report pictures"
```

---

### Task 2: Interactive ECharts charts on the live report page

**Files:**
- Create: `tracker/static/vendor/echarts-6.1.0.min.js`, `tracker/static/vendor/LICENSE-echarts.txt`, `tracker/static/vendor/NOTICE-echarts.txt`
- Create: `tracker/static/report-charts.js`
- Modify: `tracker/static/tracker.js` (dispatch a theme event)
- Modify: `tracker/static/tracker.css` (chart host, tooltip and swatch classes)
- Modify: `tracker/templates/base.html` (add `{% block head_extra %}{% endblock %}` after the `tracker.js` script tag)
- Modify: `tracker/templates/report/page.html`, `tracker/templates/report/_body.html`
- Modify: `tests/conftest.py` (add `live_server` and `browser_sign_in`)
- Test: `tests/test_report_page_browser.py`, `tests/test_report.py`

**Interfaces:**
- Consumes: the route `report.chart_data` and the payload shape from Task 1.
- Produces:
  - In `base.html`, a `head_extra` block that pages fill with their own `<link>` and `<script defer>` tags (Task 3 uses it).
  - The `tracker:themechange` event, dispatched on `document` with `detail: {theme: "light" | "dark"}` whenever the theme toggle changes the theme.
  - In `tests/conftest.py`:
    - `live_server(app, _db_engine) -> str`: the base URL of a threaded `werkzeug.serving.make_server("127.0.0.1", 0, app, threaded=True)` running in a background thread, shut down after the test;
    - `browser_sign_in(page, base_url: str, user) -> None`: fills `/login` with `user.email` and `TEST_PASSWORD`, then submits.

- [ ] **Step 1: Fetch ECharts**

Run in `$TMPDIR`: `npm pack echarts@6.1.0 && tar xzf echarts-6.1.0.tgz`. The network allowance needed is `registry.npmjs.org`. Copy `package/dist/echarts.min.js` to `tracker/static/vendor/echarts-6.1.0.min.js`, and copy `package/LICENSE` and `package/NOTICE` beside it.
Expected: the file starts with the ECharts licence banner and is about 1 MB.

- [ ] **Step 2: Write the failing tests**

In `tests/test_report.py`, using the database and the existing `small_tracker` and `viewer` style fixtures, add `test_report_page_points_charts_at_the_selected_week`. Request `/trackers/<id>/report?week=2026-09-11`, then assert that the HTML contains `data-chart-data="/trackers/<id>/report/data.json?week=2026-09-11"`, the script tag for `vendor/echarts-6.1.0.min.js` and the script tag for `report-charts.js`.

Also add `test_print_html_loads_no_chart_scripts`, which needs no database. Assert that `print_html(app)` contains `data-chart="remaining"` and no `<script`.

In `tests/test_report.py`, add `test_tooltip_swatches_match_palette`. Read `tracker/static/tracker.css` and assert that `.chart-swatch-plan`, `.chart-swatch-actual` and `.chart-swatch-forecast` set `background` to `PALETTE["plan"]`, `PALETTE["actual"]` and `PALETTE["forecast"]`.

In `tests/test_report_page_browser.py`, mark every test `@pytest.mark.browser`. Define the fixtures `seeded`, which returns `SimpleNamespace(tracker=…, viewer=…)`, and `seeded_empty`, the same tracker and viewer with no group, targets or entries. Seed the data with the `db` fixture:
- a tracker with weeks ending 4 Sep to 25 Sep 2026;
- one group "LD5" with baseline 100;
- a target of 10 in each week;
- completion entries of 8 in week 1 and 12 in week 2;
- a viewer with a password.

Monkeypatch `tracker.report.views.today` to `date(2026, 9, 26)`. In each test, record policy violations with `page.add_init_script("window.__csp=[];document.addEventListener('securitypolicyviolation',e=>window.__csp.push(e.violatedDirective))")`.

```python
def test_charts_render_without_policy_errors(page, live_server, seeded):
    browser_sign_in(page, live_server, seeded.viewer)
    page.goto(f"{live_server}/trackers/{seeded.tracker.id}/report")
    page.wait_for_selector(".chart-host-cumulative :is(svg, canvas)")
    assert page.locator(".chart-host").count() == 3
    assert page.locator("img[data-chart]").count() == 0
    assert page.evaluate("window.__csp") == []

def test_tooltip_on_hover(page, live_server, seeded):  # after sign-in and goto as above
    page.locator(".chart-host-remaining").hover()
    tooltip = page.locator(".chart-tooltip")
    expect(tooltip).to_be_visible()
    expect(tooltip).to_contain_text("Plan")

def test_charts_follow_the_theme(page, live_server, seeded):
    page.click("[data-theme-toggle]")
    expect(page.locator(".chart-host-remaining")).to_have_attribute("data-theme", "dark")
    page.click("[data-theme-toggle]")
    expect(page.locator(".chart-host-remaining")).to_have_attribute("data-theme", "light")

def test_empty_tracker_shows_no_data_yet(page, live_server, seeded_empty):
    expect(page.locator(".chart-host-remaining")).to_have_attribute("data-empty", "true")

def test_failed_data_request_keeps_the_pictures(page, live_server, seeded):
    page.route("**/report/data.json*", lambda route: route.fulfill(status=500, body="error"))
    page.goto(f"{live_server}/trackers/{seeded.tracker.id}/report")
    expect(page.locator("img[data-chart]")).to_have_count(3)

def test_page_without_javascript_keeps_the_pictures(browser, live_server, seeded):
    context = browser.new_context(java_script_enabled=False)  # sign in with this context's page
    ...
    expect(page.locator("img[data-chart]")).to_have_count(3)
```

The `page` and `browser` fixtures come from `pytest-playwright` if it is installed. If it is not, add simple `browser` and `page` fixtures to `tests/conftest.py` built on `playwright.sync_api.sync_playwright` with Chromium, scoped per test. Do not add a new requirement just for this.

- [ ] **Step 3: Run the tests and confirm they fail**

Run: `TEST_DATABASE_URL=… rtk .venv/bin/pytest tests/test_report_page_browser.py tests/test_report.py -q`
Expected: FAIL. There is no `data-chart-data` attribute, no `.chart-host` and no swatch classes.

- [ ] **Step 4: Update the templates**
  - **`_body.html`:** add `data-chart="remaining"`, `data-chart="weekly"` and `data-chart="cumulative"` to the three `<img class="report-chart">` tags.
  - **`page.html`:**
    - fill `head_extra` with `<script src="{{ url_for('static', filename='vendor/echarts-6.1.0.min.js') }}" defer></script>` and then `report-charts.js` (`defer`, `v=app_version`);
    - wrap the `_body.html` include in `<div class="report-live" data-chart-data="{{ url_for('report.chart_data', tracker_id=report.tracker.id, week=report.week_ending.isoformat()) }}">`.
  - **`base.html`:** add the `head_extra` block.

- [ ] **Step 5: Add the theme event to `tracker.js`**

In the theme toggle handler, after `root.setAttribute("data-theme", next)`, dispatch `tracker:themechange` with `{theme: next}`.

- [ ] **Step 6: Implement `tracker/static/report-charts.js`**

Wrap it in an IIFE in `"use strict"`, in the same style as `tracker.js`. It runs on `DOMContentLoaded`.
- **Fetch the data:** find `.report-live[data-chart-data]` and fetch its URL with `credentials: "same-origin"` and `headers: {Accept: "application/json"}`. If the response is not OK, or is not JSON (a redirect to the sign-in page), leave the images and stop. The script must log nothing and throw nothing.
- **Swap each picture:** for each `img[data-chart]`, create `<div class="chart-host chart-host-NAME" role="img">` with `aria-label` set to the image's `alt`, and replace the image with it. Then call `echarts.init(host, theme, {renderer: "svg"})`, where `theme` is `"dark"` when `<html data-theme="dark">` and `null` otherwise. Set `host.dataset.theme` to `"dark"` or `"light"`.
- **Shared options:**
  - `backgroundColor: "transparent"`;
  - `tooltip: {trigger: "axis", className: "chart-tooltip", formatter}`;
  - `legend: {}`;
  - x axis: categories, with labels as `DD Mon` from `weeks`;
  - `dataZoom: [{type: "inside"}, {type: "slider"}]`;
  - `toolbox: {feature: {saveAsImage: {}}}`;
  - every chart's `group = "report"`, then call `echarts.connect("report")`.
- **The series in each chart:**
  - Remaining: Plan from `planned_remaining`, dashed `palette.plan`; Actual from `actual_remaining`, solid `palette.actual`; Forecast from `forecast_remaining`, dotted `palette.forecast`. The y axis is named with `unit_label`.
  - Weekly actual against target: Actual as bars from `actual`; Target as a dashed line from `target`.
  - Cumulative completed: Plan from `cum_target`; Actual from `cum_actual`.
- **Line style:** every line uses `showSymbol: true` and `connectNulls: false`.
- **Tooltip formatter:** the formatter builds markup from fixed strings and numbers only. It uses CSS classes and no `style` attributes:
  - a header with the full week-ending date;
  - one `.chart-tooltip-row` per series with a value, holding `<span class="chart-swatch chart-swatch-KEY">`, the series name and the value (one decimal place for Forecast, whole numbers otherwise);
  - on Remaining and Cumulative, a gap line when both Plan and Actual exist: "Behind plan by N", "Ahead of plan by N" or "On plan". On Remaining, an actual above plan means behind; on Cumulative, an actual below plan means behind.
- **Empty charts:** when every series in a chart is all `None`, set `title: {text: "No data yet", left: "center", top: "middle"}` and set `host.dataset.empty = "true"`.
- **Theme changes:** on `tracker:themechange`, dispose each chart and initialise it again with the new theme and the same options, then update `host.dataset.theme`.
- **Resizing:** on window `resize`, call `chart.resize()` for each chart.

- [ ] **Step 7: Add the chart styles to `tracker.css`**
  - `.chart-host { width: 100%; height: 320px; }` and `.report-charts .chart-host { height: 260px; }`
  - `.chart-tooltip` sets the font size; `.chart-tooltip-row` uses `display: flex; justify-content: space-between; gap: 8px;`
  - `.chart-swatch` is a 10px round marker; `.chart-swatch-plan { background: #888888; }`, `.chart-swatch-actual { background: #2c7be5; }`, `.chart-swatch-forecast { background: #d39e00; }`

- [ ] **Step 8: Run the tests and confirm they pass**

Run: `TEST_DATABASE_URL=… rtk .venv/bin/pytest tests/test_report_page_browser.py tests/test_report.py tests/test_templates.py -q`
Expected: PASS. If `window.__csp` reports violations with the SVG renderer, switch the renderer to `"canvas"` and run the tests again. Record which renderer was kept in the commit message.

- [ ] **Step 9: Run the full suite and lint**

Run: `TEST_DATABASE_URL=… rtk .venv/bin/pytest -q && rtk .venv/bin/ruff check . && rtk .venv/bin/ruff format --check .`
Expected: all pass.

- [ ] **Step 10: Commit**

```bash
git add tracker/static tracker/templates tests
git commit -m "feat: interactive ECharts report charts with rollovers, data points, linked zoom and dark mode"
```

---

### Task 3: Filterable tables with Tabulator

**Files:**
- Create: `tracker/static/vendor/tabulator-6.6.1.min.js`, `tracker/static/vendor/tabulator-6.6.1.min.css`, `tracker/static/vendor/LICENSE-tabulator.txt`
- Create: `tracker/static/tables.js`
- Modify: `tracker/static/tracker.css` (Tabulator colours from the theme tokens)
- Modify: `tracker/templates/report/page.html`, `tracker/templates/report/_body.html`, `tracker/templates/entries/list.html`, `tracker/templates/entries/risks.html`
- Modify: `README.md` (a short "Front-end libraries" section)
- Test: `tests/test_tables_browser.py`, `tests/test_entries.py`

**Interfaces:**
- Consumes: the `head_extra` block, `live_server`, `browser_sign_in` and the browser fixtures from Task 2.
- Produces: the table markup contract, which `tables.js` reads.
  - **On `<table data-table>`:** enhance this table. Optional attributes: `data-table-page-size="N"` (paging) and `data-table-export="NAME.csv"` (a Download CSV button).
  - **On each `<th>`:**
    - `data-filter`: `text` (the default), `select` or `none`;
    - `data-sort`: `string` (the default), `number`, `date` or `none`;
    - `data-html`: present when the cells hold markup that must be kept, such as forms and links. These columns are never sorted, filtered or exported.

- [ ] **Step 1: Fetch Tabulator**

Run in `$TMPDIR`: `npm pack tabulator-tables@6.6.1 && tar xzf tabulator-tables-6.6.1.tgz`. Copy `package/dist/js/tabulator.min.js`, `package/dist/css/tabulator.min.css` and `package/LICENSE` to the vendor paths above.

- [ ] **Step 2: Write the failing tests**

In `tests/test_entries.py`, add `test_entries_table_is_enhanced`, using the database and an editor. Assert that the entries page contains:
- `data-table`;
- `data-table-page-size="50"`;
- `data-table-export="entries.csv"`;
- the script tags for `vendor/tabulator-6.6.1.min.js` and `tables.js`.

In `tests/test_tables_browser.py`, mark every test `@pytest.mark.browser`. Seed the data:
- the Task 2 tracker;
- groups "LD5" and `<i>LD6</i>`;
- entries of quantity 5 (LD5), 3 (LD5) and 9 (`<i>LD6</i>`);
- an editor.

Record policy violations as in Task 2.

```python
def test_location_filter_narrows_rows(page, live_server, seeded):
    # entries page as editor
    page.locator(".tabulator-col[tabulator-field='c2'] .tabulator-header-filter input").click()
    page.locator(".tabulator-edit-list-item", has_text="LD5").first.click()
    expect(page.locator(".tabulator-row")).to_have_count(2)

def test_quantity_sorts_numerically(page, live_server, seeded):
    page.locator(".tabulator-col[tabulator-field='c3'] .tabulator-col-title").click()
    assert page.locator(".tabulator-row .tabulator-cell[tabulator-field='c3']").all_inner_texts() == ["3", "5", "9"]

def test_markup_in_names_is_shown_as_text(page, live_server, seeded):
    expect(page.locator(".tabulator-row", has_text="<i>LD6</i>")).to_have_count(1)
    assert page.locator(".tabulator-row i").count() == 0

def test_delete_still_works_in_an_enhanced_row(page, live_server, seeded):
    page.locator(".tabulator-row", has_text="9").get_by_role("button", name="Delete").click()
    expect(page.locator(".tabulator-row")).to_have_count(2)

def test_csv_download(page, live_server, seeded):
    with page.expect_download() as info:
        page.get_by_role("button", name="Download CSV").click()
    assert info.value.suggested_filename == "entries.csv"
    assert open(info.value.path()).readline().strip() == "Date,Week ending,Location,Quantity,Note"

def test_tables_raise_no_policy_errors(page, live_server, seeded):
    # visit the entries page, the risks page and the report page
    assert page.evaluate("window.__csp") == []
```

The selectors above assume the field names `c0`, `c1` and so on, which `tables.js` assigns by column position (see Step 4). Adjust them only if Tabulator's own class names differ in 6.6.1.

- [ ] **Step 3: Run the tests and confirm they fail**

Run: `TEST_DATABASE_URL=… rtk .venv/bin/pytest tests/test_tables_browser.py tests/test_entries.py -k "enhanced or tabulator or filter or sorts or markup or delete_still or csv or policy" -q`
Expected: FAIL.

- [ ] **Step 4: Implement `tracker/static/tables.js`**

Wrap it in an IIFE in `"use strict"`, running on `DOMContentLoaded`. For each `table[data-table]`:
- **Skip** the table if any body cell has a `colspan` (an empty-state row such as "No groups yet.").
- **Columns:** read the `<th>` elements into column definitions:
  - `field` is `"c" + index` and `title` is the heading text;
  - `headerFilter` is `"input"` for text, `"list"` with `headerFilterParams: {valuesLookup: true, clearable: true}` for select, and `false` for none;
  - `sorter` is `"string"`, `"number"` or the custom date sorter;
  - `data-html` columns use `formatter: "html"`, `headerSort: false`, `headerFilter: false` and `download: false`;
  - other columns keep Tabulator's default plain-text formatter, which escapes markup.
- **Rows:** read each body row into `{c0: …, c1: …}`, using `textContent` for plain columns and `innerHTML` for `data-html` columns.
- **Build:** replace the table with a `<div class="data-table">` and construct `new Tabulator(div, {data, columns, layout: "fitColumns", placeholder: "No rows match."})`. When a page size is set, add `pagination: true, paginationSize: N`.
- **Export:** when `data-table-export` is set, insert `<button class="button" type="button">Download CSV</button>` before the div. It calls `table.download("csv", NAME)`.
- **Date sorter:** parses the `DD Mon YYYY` format produced by `fmt_date`. It treats `–` and empty cells as the lowest value, and needs no date library.

- [ ] **Step 5: Mark up the tables and load the scripts**
  - **`entries/list.html`:** `data-table data-table-page-size="50" data-table-export="entries.csv"`. Date and Week ending columns: `data-sort="date" data-filter="none"`. Location: `data-filter="select"`. Quantity: `data-sort="number"`. Note: text. The action column: `data-html`.
  - **`entries/risks.html`:** `data-table`. Location, Status and RAG: `data-filter="select"`. The Edit column: `data-html`.
  - **`report/_body.html`:**
    - the per-location table and the risks table get `data-table`;
    - location, RAG and status columns use `data-filter="select"`;
    - number columns use `data-sort="number"`, and date columns `data-sort="date"`.

    The PDF loads no scripts, so these attributes are inert there.
  - **`report/page.html`, `entries/list.html` and `entries/risks.html`:** fill `head_extra` with the Tabulator CSS link, `vendor/tabulator-6.6.1.min.js` (`defer`) and `tables.js` (`defer`, `v=app_version`).

- [ ] **Step 6: Theme the tables in `tracker.css`**

Override `.tabulator` and its header, rows, paging and header filter inputs to use `var(--surface)`, `var(--text)`, `var(--muted)` and `var(--border)`, so the tables follow light and dark mode.

- [ ] **Step 7: Document the libraries in `README.md`**

Add a "Front-end libraries" section listing ECharts 6.1.0 (Apache-2.0) and Tabulator 6.6.1 (MIT) in `tracker/static/vendor/`. Note that they are updated with `npm pack <name>@<version>`, by copying the dist files and licences, and by renaming the version in the templates.

- [ ] **Step 8: Run the tests and confirm they pass**

Run: `TEST_DATABASE_URL=… rtk .venv/bin/pytest tests/test_tables_browser.py tests/test_entries.py tests/test_templates.py -q`
Expected: PASS.

- [ ] **Step 9: Run the full suite and lint**

Run: `TEST_DATABASE_URL=… rtk .venv/bin/pytest -q && rtk .venv/bin/ruff check . && rtk .venv/bin/ruff format --check .`
Expected: all pass.

- [ ] **Step 10: Commit**

```bash
git add tracker/static tracker/templates tests README.md
git commit -m "feat: sortable, filterable report, risks and entries tables with Tabulator"
```
