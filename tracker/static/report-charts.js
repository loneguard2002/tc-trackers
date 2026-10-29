// Interactive report charts (Apache ECharts) on the live report page.
// The page keeps the server-drawn pictures; this script swaps them for charts only once the data has loaded, so a
// failed request or a browser without JavaScript still shows the pictures. Tooltip markup uses CSS classes only:
// the Content Security Policy blocks inline style attributes.
(function () {
  "use strict";

  var MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  var SWATCH = { plan: "plan", target: "plan", actual: "actual", forecast: "forecast" };
  var charts = [];

  function dateParts(iso) {
    var parts = iso.split("-");
    return { year: parts[0], month: MONTHS[Number(parts[1]) - 1], day: parts[2] };
  }

  function shortDate(iso) {
    var d = dateParts(iso);
    return d.day + " " + d.month;
  }

  function longDate(iso) {
    var d = dateParts(iso);
    return d.day + " " + d.month + " " + d.year;
  }

  function formatValue(id, value) {
    if (id === "forecast") return Number(value).toFixed(1);
    return Math.round(Number(value)).toLocaleString("en-GB");
  }

  function isEmpty(values) {
    return values.every(function (v) { return v === null || v === undefined; });
  }

  function lineSeries(id, name, values, color, type) {
    return {
      id: id,
      name: name,
      type: "line",
      data: values,
      showSymbol: true,
      showAllSymbol: true,
      symbolSize: 6,
      connectNulls: false,
      itemStyle: { color: color },
      lineStyle: { color: color, type: type, width: type === "solid" ? 2.4 : 1.8 }
    };
  }

  // The week in progress is a part-week figure: its bar is paler and its tooltip says "so far".
  function weeklyBars(values, inProgress) {
    return values.map(function (value, i) {
      if (!inProgress || !inProgress[i] || value === null || value === undefined) return value;
      return { value: value, partWeek: true, itemStyle: { opacity: 0.4 } };
    });
  }

  // The gap line: on Remaining an actual above plan is behind; on Cumulative an actual below plan is behind.
  function gapText(plan, actual, higherIsBehind) {
    if (plan === null || plan === undefined || actual === null || actual === undefined) return "";
    var diff = Math.round(actual - plan);
    if (diff === 0) return "On plan";
    var behind = higherIsBehind ? diff > 0 : diff < 0;
    return (behind ? "Behind plan by " : "Ahead of plan by ") + Math.abs(diff).toLocaleString("en-GB");
  }

  function makeFormatter(weeks, gap) {
    return function (params) {
      if (!params || !params.length) return "";
      var index = params[0].dataIndex;
      var html = '<div class="chart-tooltip-title">Week ending ' + longDate(weeks[index]) + "</div>";
      params.forEach(function (p) {
        if (p.value === null || p.value === undefined || p.value === "-") return;
        var name = p.seriesName + (p.data && p.data.partWeek ? " so far" : "");
        html += '<div class="chart-tooltip-row"><span><span class="chart-swatch chart-swatch-' +
          (SWATCH[p.seriesId] || "plan") + '"></span>' + name + "</span><strong>" +
          formatValue(p.seriesId, p.value) + "</strong></div>";
      });
      var text = gap ? gap(index) : "";
      if (text) html += '<div class="chart-tooltip-gap">' + text + "</div>";
      return html;
    };
  }

  function chartSpec(name, data) {
    var s = data.series;
    var p = data.palette;
    if (name === "remaining") {
      return {
        title: "Remaining",
        yName: data.unit_label,
        bars: false,
        series: [
          lineSeries("plan", "Plan", s.planned_remaining, p.plan, "dashed"),
          lineSeries("actual", "Actual", s.actual_remaining, p.actual, "solid"),
          lineSeries("forecast", "Forecast", s.forecast_remaining, p.forecast, "dotted")
        ],
        gap: function (i) { return gapText(s.planned_remaining[i], s.actual_remaining[i], true); }
      };
    }
    if (name === "weekly") {
      return {
        title: "Weekly actual against target",
        yName: "",
        bars: true,
        series: [
          { id: "actual", name: "Actual", type: "bar", data: weeklyBars(s.actual, data.in_progress), barMaxWidth: 28,
            itemStyle: { color: p.actual } },
          lineSeries("target", "Target", s.target, p.plan, "dashed")
        ],
        gap: null
      };
    }
    return {
      title: "Cumulative completed",
      yName: "",
      bars: false,
      series: [
        lineSeries("plan", "Plan", s.cum_target, p.plan, "dashed"),
        lineSeries("actual", "Actual", s.cum_actual, p.actual, "solid")
      ],
      gap: function (i) { return gapText(s.cum_target[i], s.cum_actual[i], false); }
    };
  }

  // Saves this chart alone (ECharts' own Save as image composes every connected chart into one picture).
  function saveChart(entry) {
    var link = document.createElement("a");
    link.href = entry.chart.getDataURL({ type: "svg" });
    link.download = entry.name + ".svg";
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  }

  function buildOption(name, data, entry) {
    var spec = chartSpec(name, data);
    var empty = spec.series.every(function (series) { return isEmpty(series.data); });
    var titles = [{ text: spec.title, left: 8, top: 6, textStyle: { fontSize: 13, fontWeight: 600 } }];
    if (empty) titles.push({ text: "No data yet", left: "center", top: "middle" });
    var option = {
      title: titles,
      grid: { left: 16, right: 24, top: 64, bottom: 56, containLabel: true },
      legend: { left: "center", top: 30 },
      tooltip: { trigger: "axis", className: "chart-tooltip", formatter: makeFormatter(data.weeks, spec.gap) },
      toolbox: {
        right: 8,
        top: 4,
        feature: {
          myDownload: {
            show: true,
            title: "Save as image",
            icon: "path://M12 3v12M7 10l5 5 5-5M4 20h16",
            onclick: function () { saveChart(entry); }
          }
        }
      },
      // The slider zooms the dates. No "inside" zoom: in ECharts 6 it captures the mouse wheel even when limited to
      // Ctrl, so the page would stop scrolling over a chart.
      dataZoom: [{ type: "slider", height: 18, bottom: 8 }],
      xAxis: { type: "category", boundaryGap: spec.bars, data: data.weeks.map(shortDate) },
      yAxis: { type: "value", name: spec.yName, minInterval: 1 },
      series: spec.series
    };
    return { option: option, empty: empty };
  }

  // The chart background is the surface colour around the chart, so a saved picture is readable in either theme.
  function surfaceColour(host) {
    return getComputedStyle(host).getPropertyValue("--surface").trim() || "#ffffff";
  }

  // The PDF and PNG previews (report-view.js) are always light, whatever the page theme.
  function currentTheme(host) {
    if (host.closest(".is-paper")) return "light";
    return document.documentElement.getAttribute("data-theme") === "dark" ? "dark" : "light";
  }

  function draw(entry) {
    var theme = currentTheme(entry.host);
    entry.chart = window.echarts.init(entry.host, theme === "dark" ? "dark" : null, { renderer: "svg" });
    entry.chart.group = "report";
    entry.chart.setOption(entry.built.option);
    entry.chart.setOption({ backgroundColor: surfaceColour(entry.host) });
    // Not "data-theme": the style sheet's [data-theme="dark"] rule would give the host the dark colours.
    entry.host.dataset.chartTheme = theme;
  }

  function start(container, data) {
    var images = container.querySelectorAll("img[data-chart]");
    Array.prototype.forEach.call(images, function (img) {
      var name = img.getAttribute("data-chart");
      var host = document.createElement("div");
      host.className = "chart-host chart-host-" + name;
      host.setAttribute("role", "img");
      host.setAttribute("aria-label", img.getAttribute("alt") || "");
      img.parentNode.replaceChild(host, img);
      var entry = { name: name, host: host, built: null, chart: null };
      entry.built = buildOption(name, data, entry);
      if (entry.built.empty) host.dataset.empty = "true";
      draw(entry);
      charts.push(entry);
    });
    window.echarts.connect("report");

    function redraw() {
      charts.forEach(function (entry) {
        entry.chart.dispose();
        draw(entry);
      });
      window.echarts.connect("report");
    }
    document.addEventListener("tracker:themechange", redraw);
    document.addEventListener("tracker:reportview", redraw);
    // Resize with the host, not just the window: collapsing the sidebar changes the width without a resize event.
    if (window.ResizeObserver) {
      var observer = new window.ResizeObserver(function () {
        charts.forEach(function (entry) { entry.chart.resize(); });
      });
      charts.forEach(function (entry) { observer.observe(entry.host); });
    } else {
      window.addEventListener("resize", function () {
        charts.forEach(function (entry) { entry.chart.resize(); });
      });
    }
  }

  document.addEventListener("DOMContentLoaded", function () {
    var container = document.querySelector(".report-live[data-chart-data]");
    if (!container || !window.echarts || !window.fetch) return;
    window.fetch(container.getAttribute("data-chart-data"), {
      credentials: "same-origin",
      headers: { Accept: "application/json" }
    }).then(function (response) {
      var type = response.headers.get("Content-Type") || "";
      if (!response.ok || type.indexOf("application/json") === -1) return null;
      return response.json();
    }).then(function (data) {
      if (data && data.weeks && data.series) start(container, data);
    }).catch(function () {
      // Keep the server-drawn pictures.
    });
  });
})();
