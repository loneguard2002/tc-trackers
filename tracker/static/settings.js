// Settings: the line under each section follows the fields as they change (labels, the weeks covered with a timeline,
// the rate and forecast for the chosen moving-average period, the schedule), the moving-average period gets minus and
// plus buttons, and the save bar counts unsaved changes. The form saves normally without JavaScript.
(function () {
  "use strict";

  var form = document.querySelector("[data-settings-form]");
  if (!form) return;

  var DAY = 864e5;
  var MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  var WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
  var SVG = "http://www.w3.org/2000/svg";
  var els = form.elements;

  function parse(value) {
    var match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value || "");
    return match ? Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3])) : null;
  }

  function fmt(t, withYear) {
    var d = new Date(t);
    return String(d.getUTCDate()).padStart(2, "0") + " " + MONTHS[d.getUTCMonth()] + (withYear === false ? "" : " " + d.getUTCFullYear());
  }

  // Python numbers weekdays from Monday (0); getUTCDay counts from Sunday (0).
  function weekdayOf(t) {
    return (new Date(t).getUTCDay() + 6) % 7;
  }

  function plural(label) {
    var lower = label.toLowerCase();
    if (!label || /s$/.test(lower)) return label;
    if (/[^aeiou]y$/.test(lower)) return label.slice(0, -1) + (label === label.toUpperCase() ? "IES" : "ies");
    if (/(x|z|ch|sh)$/.test(lower)) return label + (label === label.toUpperCase() ? "ES" : "es");
    return label + (label === label.toUpperCase() ? "S" : "s");
  }

  function value(name) {
    var field = els[name];
    if (!field) return "";
    if (field instanceof RadioNodeList) return field.value;
    if (field.type === "checkbox") return field.checked ? "on" : "";
    return field.value.trim();
  }

  function setHtml(el, parts) {
    // parts: strings and [text, className] pairs; text is never parsed as markup.
    el.textContent = "";
    parts.forEach(function (part) {
      if (typeof part === "string") {
        el.appendChild(document.createTextNode(part));
      } else {
        var strong = document.createElement("strong");
        strong.textContent = part[0];
        if (part[1]) strong.className = part[1];
        el.appendChild(strong);
      }
    });
  }

  function svg(tag, attrs, parent) {
    var node = document.createElementNS(SVG, tag);
    Object.keys(attrs).forEach(function (key) { node.setAttribute(key, attrs[key]); });
    parent.appendChild(node);
    return node;
  }

  // --- General -------------------------------------------------------------------------------------------------

  function general() {
    var unit = value("unit_label") || "units";
    form.querySelectorAll("[data-live-unit]").forEach(function (el) { el.textContent = unit; });
    var groups = form.querySelector("[data-live-groups]");
    if (groups) groups.textContent = plural(value("group_label") || "Group");
  }

  // --- Reporting period ----------------------------------------------------------------------------------------

  var periodLine = form.querySelector("[data-live='period']");
  var timeline = form.querySelector("[data-timeline]");
  var today = periodLine ? parse(periodLine.dataset.today) : Date.UTC(new Date().getFullYear(), new Date().getMonth(), new Date().getDate());

  function period() {
    var weekday = Number(value("week_ending_weekday"));
    var start = parse(value("start_date"));
    var last = parse(value("last_week_ending"));
    var target = parse(value("target_completion"));
    var plot = timeline.querySelector("svg");
    plot.textContent = "";
    timeline.hidden = false;
    // Drawn at its own width, so the labels are not stretched.
    var W = Math.max(200, Math.round(plot.getBoundingClientRect().width) || 600);
    plot.setAttribute("viewBox", "0 0 " + W + " 46");
    if (start === null || last === null || isNaN(weekday)) {
      timeline.hidden = true;
      if (periodLine) {
        periodLine.hidden = false;
        periodLine.textContent = "Set both dates to see the weeks the tracker covers.";
      }
      return;
    }
    var first = start + ((weekday - weekdayOf(start) + 7) % 7) * DAY;
    var problem = "";
    if (weekdayOf(last) !== weekday) problem = "The last week-ending must fall on a " + WEEKDAYS[weekday] + ".";
    else if (last < first) problem = "The last week-ending must be on or after the first.";
    else if (last - first > 51 * 7 * DAY) problem = "The last week-ending must be no more than 52 weeks after the first.";
    if (problem) {
      timeline.hidden = true;
      if (periodLine) {
        periodLine.hidden = false;
        setHtml(periodLine, [[problem, "tone-danger"]]);
      }
      return;
    }

    var count = Math.round((last - first) / (7 * DAY)) + 1;
    var done = 0;
    var current = -1;
    var gap = count > 40 ? 1 : 2;
    var width = (W - gap * (count - 1)) / count;
    for (var i = 0; i < count; i += 1) {
      var ending = first + i * 7 * DAY;
      var state = "future";
      if (ending <= today) {
        state = "done";
        done += 1;
      } else if (current < 0 && ending - 7 * DAY < today) {
        state = "now";
        current = i;
      }
      svg("rect", { x: (i * (width + gap)).toFixed(2), y: 18, width: width.toFixed(2), height: 10, rx: 2, class: "timeline-week timeline-" + state }, plot);
    }
    var span = last + 7 * DAY - first;
    var mark = function (t, label, cls, below) {
      if (t < first - 7 * DAY || t > last) return;
      var x = Math.max(0, Math.min(W, ((t - (first - 7 * DAY)) / span) * W));
      svg("line", { x1: x, x2: x, y1: below ? 14 : 4, y2: below ? 42 : 32, class: "timeline-mark " + cls }, plot);
      var text = svg("text", { x: x, y: below ? 44 : 10, class: "timeline-label " + cls, "text-anchor": x > W - 80 ? "end" : x < 80 ? "start" : "middle" }, plot);
      text.textContent = label;
    };
    mark(today, "Today", "is-today", false);
    if (target !== null) mark(target, "Target " + fmt(target, false), "is-target", true);
    timeline.querySelector("[data-timeline-first]").textContent = fmt(first);
    timeline.querySelector("[data-timeline-last]").textContent = fmt(last);
    if (!periodLine) return;
    periodLine.hidden = false;
    var togo = count - done - (current >= 0 ? 1 : 0);
    var parts = [[count + " weeks", ""], ": " + done + " complete, " + (current >= 0 ? "1 in progress, " : "") + togo + " to go."];
    if (target === null) {
      parts.push(" No target date, so the report cannot say whether the work is on track.");
    } else if (target > last) {
      parts.push(" ");
      parts.push(["The target date is after the last week-ending.", "tone-danger"]);
    } else if (target >= first - 6 * DAY) {
      parts.push(" Target completion falls in week " + (Math.floor((target - (first - 6 * DAY)) / (7 * DAY)) + 1) + ".");
    }
    setHtml(periodLine, parts);
  }

  // --- Progress and forecast -----------------------------------------------------------------------------------

  var forecastLine = form.querySelector("[data-live='forecast']");
  var forecasts = forecastLine ? JSON.parse(forecastLine.dataset.forecasts) : null;

  function forecast() {
    var ma = Math.max(1, Math.min(12, parseInt(value("moving_average_weeks"), 10) || 1));
    form.querySelectorAll("[data-step]").forEach(function (button) {
      button.disabled = Number(button.dataset.step) < 0 ? ma <= 1 : ma >= 12;
    });
    if (!forecastLine) return;
    var f = forecasts[String(ma)];
    if (!f || f.rate === null) {
      forecastLine.textContent = "No complete weeks yet, so there is no rate or forecast.";
      return;
    }
    var n = f.window.length;
    var parts = ["Rate now ", [f.rate.toFixed(1) + " a week", ""], ", the average of the last " + n + " week" + (n === 1 ? "" : "s") + " (" + f.window.join(", ") + (ma > n ? "; only " + n + " so far" : "") + ")."];
    if (f.forecast) {
      var when = parse(f.forecast);
      var target = parse(value("target_completion"));
      var days = target === null ? null : Math.round((when - target) / DAY);
      parts.push(" Forecast completion ");
      parts.push([fmt(when), days === null ? "" : days > 0 ? "tone-danger" : "tone-success"]);
      if (days !== null && days > 0) parts.push(", " + Math.ceil(days / 7) + " week" + (Math.ceil(days / 7) === 1 ? "" : "s") + " after target.");
      else if (days !== null) parts.push(", on or before target.");
      else parts.push(".");
    }
    if (value("completed_before_first") !== forecastLine.dataset.before) parts.push(" Save to include the new starting figure.");
    setHtml(forecastLine, parts);
  }

  form.querySelectorAll("[data-step]").forEach(function (button) {
    button.hidden = false;
    button.addEventListener("click", function () {
      var input = els.moving_average_weeks;
      var next = Math.max(1, Math.min(12, (parseInt(input.value, 10) || 1) + Number(button.dataset.step)));
      input.value = String(next);
      input.dispatchEvent(new Event("input", { bubbles: true }));
    });
  });

  // --- Scheduled sending ---------------------------------------------------------------------------------------

  var scheduleLine = form.querySelector("[data-live='schedule']");
  var scheduleSaved = scheduleLine ? scheduleLine.innerHTML : "";

  function schedule(saved) {
    if (!scheduleLine) return;
    var on = value("schedule_enabled") === "on";
    var unchanged = ["schedule_enabled", "send_time", "send_timezone", "week_ending_weekday"].every(function (name) {
      return value(name) === saved[name];
    });
    if (unchanged) {
      scheduleLine.innerHTML = scheduleSaved;
    } else if (!on) {
      scheduleLine.textContent = "Off. The report goes out only when someone sends it from the Email tab.";
    } else {
      var people = Number(scheduleLine.dataset.recipients);
      setHtml(scheduleLine, [
        "Once saved: every ",
        [WEEKDAYS[Number(value("week_ending_weekday"))] + " at " + (value("send_time") || "17:00"), ""],
        " (" + (value("send_timezone") || "Europe/London") + ") to " + people + " recipient" + (people === 1 ? "" : "s") + " on the Email tab."
      ]);
    }
  }

  // --- Save bar ------------------------------------------------------------------------------------------------

  var note = form.querySelector("[data-dirty-note]");
  var discard = form.querySelector("[data-discard]");
  var names = [];
  Array.prototype.forEach.call(els, function (el) {
    if (el.name && el.type !== "hidden" && names.indexOf(el.name) < 0) names.push(el.name);
  });
  var saved = {};
  names.forEach(function (name) { saved[name] = value(name); });

  function refresh() {
    general();
    period();
    forecast();
    schedule(saved);
    var changed = names.filter(function (name) { return value(name) !== saved[name]; }).length;
    note.textContent = changed ? changed + " setting" + (changed === 1 ? "" : "s") + " changed, not saved yet" : "No unsaved changes";
    note.classList.toggle("is-dirty", changed > 0);
    discard.hidden = changed === 0;
  }

  form.addEventListener("input", refresh);
  form.addEventListener("change", refresh);
  // The reset event fires before the fields are restored, so the refresh waits a moment.
  form.addEventListener("reset", function () { window.setTimeout(refresh, 0); });
  window.addEventListener("resize", period);
  refresh();
})();
