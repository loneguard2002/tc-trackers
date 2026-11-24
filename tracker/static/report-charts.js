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


  // ---- The Status at a glance view's Remaining chart ------------------------------------------------------------
  // A numeric day axis (days since 1970), one tick per week ending, so a target that is not a week ending still sits at
  // its true place. Colours follow the agreed light and dark sets rather than the classic palette.
  var DAY_MS = 86400000;
  var GLANCE_COLOURS = {
    light: { actual: "#1260d0", plan: "#008f82", forecast: "#c27a00" },
    dark: { actual: "#5b8ff0", plan: "#22a596", forecast: "#b8801c" }
  };

  function dayNumber(iso) {
    var p = iso.split("-");
    return Math.round(Date.UTC(Number(p[0]), Number(p[1]) - 1, Number(p[2])) / DAY_MS);
  }

  function dayIso(day) {
    var d = new Date(day * DAY_MS);
    function two(n) { return (n < 10 ? "0" : "") + n; }
    return d.getUTCFullYear() + "-" + two(d.getUTCMonth() + 1) + "-" + two(d.getUTCDate());
  }

  function cssVar(host, name, fallback) {
    return getComputedStyle(host).getPropertyValue(name).trim() || fallback;
  }

  function leftText(value) {
    return Math.round(value).toLocaleString("en-GB") + " left";
  }

  // The tick label: the day number, with the month name under the first week ending of each month.
  function weekTick(first) {
    return function (value) {
      var d = dateParts(dayIso(value));
      var before = dateParts(dayIso(value - 7));
      return value === first || before.month !== d.month ? d.day.replace(/^0/, "") + "\n" + d.month : d.day.replace(/^0/, "");
    };
  }

  function glanceTooltip(days, s, actualAt, lastActualDay) {
    return function (params) {
      if (!params || !params.length) return "";
      var day = params[0].value[0];
      var index = days.indexOf(day);
      var html = '<div class="chart-tooltip-title">Week ending ' + longDate(dayIso(day)) + "</div>";
      function row(id, name, value) {
        return '<div class="chart-tooltip-row"><span><span class="chart-swatch chart-swatch-' + id + '"></span>' + name +
          "</span><strong>" + value + "</strong></div>";
      }
      var plan = index >= 0 ? s.planned_remaining[index] : null;
      var actual = actualAt[day];
      var forecast = index >= 0 && day >= lastActualDay ? s.forecast_remaining[index] : null;
      if (actual !== undefined) html += row("actual", "Actual", formatValue("actual", actual));
      if (plan !== null && plan !== undefined) html += row("plan", "Plan", formatValue("plan", plan));
      if (forecast !== null && forecast !== undefined && actual === undefined) {
        html += row("forecast", "Forecast", formatValue("forecast", forecast));
      }
      var gap = actual !== undefined ? gapText(plan, actual, true) : "";
      if (gap) html += '<div class="chart-tooltip-gap">' + gap + "</div>";
      return html;
    };
  }

  function buildGlance(data, entry) {
    var theme = currentTheme(entry.host);
    var c = GLANCE_COLOURS[theme];
    var ink = cssVar(entry.host, "--text", theme === "dark" ? "#e6ebf5" : "#14213d");
    var muted = cssVar(entry.host, "--muted", "#5d6b83");
    var surface = surfaceColour(entry.host);
    var s = data.series;
    var days = data.weeks.map(dayNumber);
    var reportDay = data.report_week ? dayNumber(data.report_week) : days[days.length - 1];
    var plan = [];
    var actual = [];
    var actualAt = {};
    days.forEach(function (day, i) {
      var p = s.planned_remaining[i];
      // Plan past "none left" is not drawn: it stops at the first week it reaches zero.
      if (p !== null && p !== undefined && !(plan.length && plan[plan.length - 1][1] <= 0)) plan.push([day, Math.max(0, p)]);
      var a = s.actual_remaining[i];
      if (a !== null && a !== undefined && day <= reportDay) {
        actual.push([day, a]);
        actualAt[day] = a;
      }
    });
    var last = actual.length ? actual[actual.length - 1] : null;
    var forecastEnd = data.forecast_end ? dayNumber(data.forecast_end) : null;
    var forecast = last && forecastEnd !== null && last[1] > 0 ? [last, [forecastEnd, 0]] : [];
    var targets = (data.targets || []).map(function (t) {
      return { day: dayNumber(t.date), number: t.number, current: t.current, date: t.date };
    });
    var empty = !plan.length && !actual.length;

    // The span: first week to the latest of the last week, the forecast end and every target (and back to an earlier
    // target), on the weekly grid.
    var all = days.concat(targets.map(function (t) { return t.day; }));
    if (forecastEnd !== null) all.push(forecastEnd);
    if (!all.length) all.push(reportDay);
    var anchor = days.length ? days[0] : Math.min.apply(null, all);
    var low = anchor - 7 * Math.ceil((anchor - Math.min.apply(null, all)) / 7);
    var high = anchor + 7 * Math.ceil((Math.max.apply(null, all) - anchor) / 7);
    if (high === low) high = low + 7;

    var top = 0;
    plan.concat(actual).forEach(function (p) { if (p[1] > top) top = p[1]; });
    var step = 100;
    var ticks = Math.ceil(top / 100);
    if (ticks > 12) step = 100 * Math.ceil(ticks / 10);
    var yMax = Math.max(step, Math.ceil(top / step) * step);

    // Direct labels at the report week: the higher line's label above, the lower one's below, so they never collide.
    var planAtReport = null;
    plan.forEach(function (p) { if (p[0] === reportDay) planAtReport = p[1]; });
    var actualAbove = last === null || planAtReport === null || last[1] >= planAtReport;
    function pointLabel(text, position, colour) {
      return { show: true, formatter: text, position: position, color: colour, fontWeight: 700, fontSize: 12,
        align: "left", textBorderColor: surface, textBorderWidth: 3, distance: 8 };
    }
    var actualData = actual.map(function (p, i) {
      if (i !== actual.length - 1) return p;
      return { value: p, label: pointLabel("Actual: " + leftText(p[1]), actualAbove ? "top" : "bottom", c.actual) };
    });
    var planData = plan.map(function (p) {
      if (p[0] !== reportDay) return p;
      return { value: p, label: pointLabel("Plan: " + leftText(p[1]), actualAbove ? "bottom" : "top", c.plan) };
    });
    var forecastData = forecast.map(function (p, i) {
      if (i === 0) return { value: p, symbol: "none" };
      var text = data.forecast_end ? "Forecast: none left on " + shortDate(data.forecast_end) : "";
      var label = pointLabel(text, "top", c.forecast);
      label.align = "right";
      return { value: p, symbol: "circle", symbolSize: 8, label: label };
    });

    function line(id, name, points, colour, type, width) {
      return { id: id, name: name, type: "line", data: points, clip: false, connectNulls: false, symbol: "circle",
        symbolSize: 8, lineStyle: { color: colour, type: type, width: width }, itemStyle: { color: colour } };
    }
    var actualSeries = line("actual", "Actual", actualData, c.actual, "solid", 2.6);
    actualSeries.symbolSize = 7;
    var planSeries = line("plan", "Plan", planData, c.plan, "dashed", 2);
    planSeries.itemStyle = { color: surface, borderColor: c.plan, borderWidth: 2 };
    var forecastSeries = line("forecast", "Forecast", forecastData, c.forecast, "dotted", 2.6);
    forecastSeries.itemStyle = { color: surface, borderColor: c.forecast, borderWidth: 2 };
    actualSeries.markLine = {
      silent: true, symbol: "none", animation: false,
      data: [{ xAxis: reportDay, lineStyle: { color: muted, type: "solid", width: 1.4 }, label: { show: false } }]
    };
    // "Today 16 Oct" beside the line at the head of the plot, or at its foot when the lines are still high there (the
    // forecast label sits at the foot, near the end, and the two never meet that way).
    var low_ = last !== null && last[1] > yMax * 0.8;
    actualSeries.markPoint = {
      silent: true, symbol: "circle", symbolSize: 1, itemStyle: { color: "transparent" }, animation: false,
      data: [{
        coord: [reportDay, low_ ? 0 : yMax],
        label: { show: true, position: "right", offset: [4, low_ ? -10 : 10], color: muted, fontSize: 11, fontWeight: 600,
          backgroundColor: surface, padding: [1, 3],
          formatter: (todayIsReportWeek(reportDay) ? "Today " : "Report week ") + shortDate(dayIso(reportDay)) }
      }]
    };
    var series = [actualSeries, planSeries, forecastSeries];
    if (targets.length) {
      var current = targets.filter(function (t) { return t.current; })[0];
      var targetSeries = {
        id: "targets", name: "Target", type: "line", data: [], silent: true,
        markLine: {
          silent: true, symbol: "none", animation: false,
          data: targets.map(function (t) {
            return {
              xAxis: t.day,
              lineStyle: { color: ink, type: "dashed", width: t.current ? 1.8 : 1.2, opacity: t.current ? 0.85 : 0.3 },
              label: {
                show: true, position: "end", distance: 4, color: ink,
                formatter: "{" + (t.current ? "c" : "r") + "|" + t.number + "}",
                rich: {
                  c: { backgroundColor: ink, color: surface, width: 20, height: 20, borderRadius: 10, align: "center",
                    fontWeight: 700, fontSize: 11 },
                  r: { borderColor: muted, borderWidth: 1.5, color: muted, backgroundColor: surface, width: 20, height: 20,
                    borderRadius: 10, align: "center", fontWeight: 700, fontSize: 11 }
                }
              }
            };
          })
        }
      };
      // The current target's words sit in a row of their own above the numbered badges, so no label covers another.
      if (current) {
        var right = (current.day - low) / (high - low) > 0.5;
        targetSeries.markPoint = {
          silent: true, symbol: "circle", symbolSize: 1, itemStyle: { color: "transparent" }, animation: false,
          data: [{
            coord: [current.day, yMax],
            label: { show: true, position: "top", offset: [right ? 10 : -10, -26], align: right ? "right" : "left",
              color: ink, fontSize: 12, fontWeight: 700, formatter: "Target " + shortDate(current.date) }
          }]
        };
      }
      series.push(targetSeries);
    }
    var titles = empty ? [{ text: "No data yet", left: "center", top: "middle" }] : [];
    return {
      empty: empty,
      option: {
        title: titles,
        grid: { left: 8, right: 28, top: 80, bottom: 12, containLabel: true },
        legend: { left: 8, top: 4, itemWidth: 30, itemHeight: 10, data: ["Actual", "Plan", "Forecast"], textStyle: { color: ink } },
        tooltip: {
          trigger: "axis", className: "chart-tooltip", axisPointer: { type: "line", snap: true },
          formatter: glanceTooltip(days, s, actualAt, last ? last[0] : reportDay)
        },
        xAxis: {
          type: "value", min: low, max: high, interval: 7,
          axisLabel: { formatter: weekTick(low), color: ink, hideOverlap: true, lineHeight: 15, fontSize: 12, showMinLabel: true, showMaxLabel: true },
          axisTick: { show: true }, splitLine: { show: false }
        },
        yAxis: {
          type: "value", min: 0, max: yMax, interval: step,
          axisLabel: { color: ink, fontSize: 12, formatter: function (v) { return Math.round(v).toLocaleString("en-GB"); } }
        },
        series: series
      }
    };
  }

  // Whether the report week is the week in progress now, so its marker can say "Today"; for a past week it says
  // "Report week" instead of claiming the report week is today.
  function todayIsReportWeek(reportDay) {
    var now = Math.floor(Date.now() / DAY_MS);
    return now <= reportDay && now > reportDay - 7;
  }

  function buildOption(name, data, entry) {
    if (name === "remaining-glance") return buildGlance(data, entry);
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
        entry.built = buildOption(entry.name, data, entry);
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
    if (!container) return;
    // The style sheet hides the server-drawn pictures while the charts load (they are light and a different size);
    // when the charts cannot be drawn, this brings the pictures back.
    function keepPictures() { container.classList.add("charts-failed"); }
    if (!window.echarts || !window.fetch) { keepPictures(); return; }
    window.fetch(container.getAttribute("data-chart-data"), {
      credentials: "same-origin",
      headers: { Accept: "application/json" }
    }).then(function (response) {
      var type = response.headers.get("Content-Type") || "";
      if (!response.ok || type.indexOf("application/json") === -1) return null;
      return response.json();
    }).then(function (data) {
      if (data && data.weeks && data.series) start(container, data);
      else keepPictures();
    }).catch(keepPictures);
  });
})();
