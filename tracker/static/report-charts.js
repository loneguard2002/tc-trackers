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
      symbolSize: 6,
      connectNulls: false,
      itemStyle: { color: color },
      lineStyle: { color: color, type: type, width: type === "solid" ? 2.4 : 1.8 }
    };
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
        html += '<div class="chart-tooltip-row"><span><span class="chart-swatch chart-swatch-' +
          (SWATCH[p.seriesId] || "plan") + '"></span>' + p.seriesName + "</span><strong>" +
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
        yName: "",
        bars: true,
        series: [
          { id: "actual", name: "Actual", type: "bar", data: s.actual, barMaxWidth: 28, itemStyle: { color: p.actual } },
          lineSeries("target", "Target", s.target, p.plan, "dashed")
        ],
        gap: null
      };
    }
    return {
      yName: "",
      bars: false,
      series: [
        lineSeries("plan", "Plan", s.cum_target, p.plan, "dashed"),
        lineSeries("actual", "Actual", s.cum_actual, p.actual, "solid")
      ],
      gap: function (i) { return gapText(s.cum_target[i], s.cum_actual[i], false); }
    };
  }

  function buildOption(name, data) {
    var spec = chartSpec(name, data);
    var empty = spec.series.every(function (series) { return isEmpty(series.data); });
    var option = {
      backgroundColor: "transparent",
      grid: { left: 16, right: 24, top: 44, bottom: 56, containLabel: true },
      legend: { left: "center", top: 6 },
      tooltip: { trigger: "axis", className: "chart-tooltip", formatter: makeFormatter(data.weeks, spec.gap) },
      toolbox: { right: 8, top: 4, feature: { saveAsImage: { title: "Save as image" } } },
      dataZoom: [{ type: "inside" }, { type: "slider", height: 18, bottom: 8 }],
      xAxis: { type: "category", boundaryGap: spec.bars, data: data.weeks.map(shortDate) },
      yAxis: { type: "value", name: spec.yName, minInterval: 1 },
      series: spec.series
    };
    if (empty) option.title = { text: "No data yet", left: "center", top: "middle" };
    return { option: option, empty: empty };
  }

  function currentTheme() {
    return document.documentElement.getAttribute("data-theme") === "dark" ? "dark" : "light";
  }

  function draw(entry) {
    var theme = currentTheme();
    entry.chart = window.echarts.init(entry.host, theme === "dark" ? "dark" : null, { renderer: "svg" });
    entry.chart.group = "report";
    entry.chart.setOption(entry.built.option);
    entry.host.dataset.theme = theme;
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
      var entry = { host: host, built: buildOption(name, data), chart: null };
      if (entry.built.empty) host.dataset.empty = "true";
      draw(entry);
      charts.push(entry);
    });
    window.echarts.connect("report");

    document.addEventListener("tracker:themechange", function () {
      charts.forEach(function (entry) {
        entry.chart.dispose();
        draw(entry);
      });
      window.echarts.connect("report");
    });
    window.addEventListener("resize", function () {
      charts.forEach(function (entry) { entry.chart.resize(); });
    });
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
