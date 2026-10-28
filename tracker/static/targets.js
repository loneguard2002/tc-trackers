// Weekly targets: the summary band, the month totals, the differences and two charts follow the inputs as you type;
// fill helpers and an unsaved-changes count. Charts are drawn as SVG elements with attributes and classes only
// (the Content Security Policy blocks inline styles). Without JavaScript the form saves as before.
(function () {
  "use strict";

  var form = document.querySelector("[data-targets-form]");
  if (!form) return;

  var SVG = "http://www.w3.org/2000/svg";
  var MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  var scope = Number(form.dataset.scope) || 0;
  var before = Number(form.dataset.before) || 0;
  var done = Number(form.dataset.done) || 0;
  var unit = form.dataset.unit;
  var targetDate = form.dataset.target;
  var current = form.dataset.current;
  var inputs = Array.prototype.slice.call(form.querySelectorAll("input[data-week]"));
  var note = form.querySelector("[data-dirty-note]");
  var savedNote = note ? note.textContent : "";

  function num(v) { return Math.round(v).toLocaleString("en-GB"); }
  function parts(iso) { var p = iso.split("-"); return { y: p[0], m: MONTHS[Number(p[1]) - 1], d: String(Number(p[2])) }; }
  function shortDate(iso) { var p = parts(iso); return p.d + " " + p.m; }
  function longDate(iso) { var p = parts(iso); return (p.d.length < 2 ? "0" : "") + p.d + " " + p.m + " " + p.y; }
  function daysBetween(a, b) { return Math.round((Date.parse(b) - Date.parse(a)) / 864e5); }
  function stat(name) { return form.querySelector('[data-stat="' + name + '"]'); }
  function setTone(el, tone) {
    ["tone-success", "tone-warning", "tone-danger"].forEach(function (t) { el.classList.remove(t); });
    if (tone) el.classList.add(tone);
  }

  function read() {
    return inputs.map(function (input) {
      var raw = input.value.trim();
      var value = raw === "" || !/^\d+$/.test(raw) ? null : Number(raw);
      return {
        input: input,
        week: input.dataset.week,
        month: input.dataset.month,
        value: value,
        actual: input.dataset.actual === undefined ? null : Number(input.dataset.actual)
      };
    });
  }

  function upcomingBlanks(weeks) {
    return weeks.filter(function (w) { return w.actual === null && w.value === null && (!current || w.week >= current); });
  }

  function summary(weeks) {
    var planned = 0, plannedToDate = 0, last = null;
    weeks.forEach(function (w) {
      if (w.value === null) return;
      planned += w.value;
      if (w.actual !== null) plannedToDate += w.value;
      if (w.value > 0) last = w.week;
    });
    var unplanned = scope - before - planned;
    stat("planned").textContent = num(planned);
    stat("planned-pct").textContent = scope ? Math.round((before + planned) / scope * 100) + "%" : "–";
    var sub = stat("planned-sub");
    sub.textContent = unplanned > 0 ? num(unplanned) + " " + unit + " not yet planned"
      : unplanned < 0 ? num(-unplanned) + " more than the scope" : "The plan covers the full scope";
    setTone(sub, unplanned > 0 ? "tone-warning" : unplanned < 0 ? "tone-danger" : "tone-success");
    var fill = stat("planned-bar").querySelector(".bar-fill");
    if (fill) fill.setAttribute("width", scope ? Math.max(0, Math.min(100, (before + planned) / scope * 100)).toFixed(2) : "0");

    stat("todate-planned").textContent = num(plannedToDate);
    var anyPast = weeks.some(function (w) { return w.actual !== null; });
    var diff = done - plannedToDate, toDate = stat("todate-sub");
    toDate.textContent = !anyPast ? "No completed weeks yet" : diff < 0 ? num(-diff) + " behind plan" : diff > 0 ? num(diff) + " ahead of plan" : "On plan";
    setTone(toDate, anyPast ? (diff < 0 ? "tone-danger" : "tone-success") : "");

    stat("finish").textContent = last ? longDate(last) : "No plan";
    var finish = stat("finish-sub");
    if (!last) finish.textContent = "Enter targets below";
    else if (unplanned > 0) finish.textContent = "Last planned week; the scope is not covered yet";
    else if (targetDate && last > targetDate) finish.textContent = daysBetween(targetDate, last) + " days after the " + longDate(targetDate) + " target";
    else if (targetDate) finish.textContent = "On or before the " + longDate(targetDate) + " target";
    else finish.textContent = "No target completion date";
    setTone(finish, !last ? "" : unplanned > 0 ? "tone-warning" : targetDate && last > targetDate ? "tone-danger" : targetDate ? "tone-success" : "");

    var hint = form.querySelector("[data-spread-hint]");
    var blanks = upcomingBlanks(weeks).length;
    if (hint) {
      hint.textContent = unplanned <= 0 ? "Nothing to spread" : !blanks ? "No blank upcoming weeks"
        : num(unplanned) + " across " + blanks + " blank upcoming week" + (blanks === 1 ? "" : "s");
    }
    return unplanned;
  }

  function rowsAndMonths(weeks) {
    var totals = {};
    var changed = 0;
    weeks.forEach(function (w) {
      totals[w.month] = (totals[w.month] || 0) + (w.value || 0);
      var cell = w.input.closest("tr").querySelector("[data-diff]");
      if (w.actual !== null && w.value !== null) {
        var d = w.actual - w.value;
        cell.textContent = (d > 0 ? "+" : d < 0 ? "−" : "") + Math.abs(d);
        setTone(cell, d < 0 ? "tone-danger" : "tone-success");
      } else {
        cell.textContent = "–";
        setTone(cell, "");
      }
      var isChanged = w.input.value.trim() !== w.input.defaultValue.trim();
      w.input.classList.toggle("is-changed", isChanged);
      if (isChanged) changed += 1;
    });
    Object.keys(totals).forEach(function (m) {
      var el = form.querySelector('[data-month-total="' + m + '"]');
      if (el) el.textContent = num(totals[m]) + " planned";
    });
    if (note) {
      note.textContent = changed ? changed + " week" + (changed === 1 ? "" : "s") + " changed, not saved yet" : savedNote;
      note.classList.toggle("is-dirty", changed > 0);
    }
  }

  // --- Charts --------------------------------------------------------------------------------------------------

  function el(tag, attrs, parent) {
    var node = document.createElementNS(SVG, tag);
    Object.keys(attrs).forEach(function (k) { node.setAttribute(k, attrs[k]); });
    parent.appendChild(node);
    return node;
  }

  function text(parent, x, y, value, cls, anchor) {
    el("text", { x: x, y: y, "class": cls || "plot-label", "text-anchor": anchor || "start" }, parent).textContent = value;
  }

  function niceMax(v) {
    var raw = (v || 1) / 4, mag = Math.pow(10, Math.floor(Math.log10(raw)));
    var steps = [1, 2, 2.5, 3, 4, 5, 10];
    for (var i = 0; i < steps.length; i++) if (steps[i] * mag >= raw) return steps[i] * mag * 4;
    return v;
  }

  function grid(svg, max, y, left, right) {
    for (var k = 0; k <= 4; k++) {
      var v = max / 4 * k;
      el("line", { x1: left, x2: right, y1: y(v), y2: y(v), "class": "plot-grid" }, svg);
      text(svg, left - 6, y(v) + 4, num(v), "plot-label", "end");
    }
  }

  function weekly(svg, weeks) {
    while (svg.firstChild) svg.removeChild(svg.firstChild);
    var W = 640, H = 210, L = 40, R = 6, T = 10, B = 26;
    var max = niceMax(Math.max.apply(null, weeks.map(function (w) { return Math.max(w.value || 0, w.actual || 0); }).concat([1])));
    var y = function (v) { return T + (H - T - B) * (1 - v / max); };
    grid(svg, max, y, L, W - R);
    var band = (W - L - R) / weeks.length, bw = band * 0.62;
    var labelEvery = Math.max(1, Math.ceil(weeks.length / 8));
    weeks.forEach(function (w, i) {
      var x = L + band * i + (band - bw) / 2;
      if (w.value) el("rect", { x: x, y: y(w.value), width: bw, height: y(0) - y(w.value), "class": "plot-target" }, svg);
      if (w.actual !== null) {
        el("rect", { x: x + bw * 0.25, y: y(w.actual), width: bw * 0.5, height: y(0) - y(w.actual),
          "class": "plot-actual" + (w.value !== null && w.actual < w.value ? " is-low" : "") }, svg);
      }
      if (w.week === current) {
        el("line", { x1: L + band * i, x2: L + band * i, y1: T, y2: y(0), "class": "plot-now" }, svg);
        text(svg, L + band * i + 4, T + 10, "This week");
      }
      if (i % labelEvery === 0) text(svg, L + band * i + band / 2, H - 8, shortDate(w.week), "plot-label", "middle");
    });
  }

  function cumulative(svg, weeks) {
    while (svg.firstChild) svg.removeChild(svg.firstChild);
    var W = 440, H = 210, L = 46, R = 8, T = 12, B = 26;
    var plan = [], act = [], c = before, a = before;
    weeks.forEach(function (w) {
      c += w.value || 0;
      plan.push(c);
      if (w.actual !== null) { a += w.actual; act.push(a); }
    });
    var max = niceMax(Math.max(scope, plan[plan.length - 1] || 0, 1));
    var n = Math.max(1, weeks.length - 1);
    var x = function (i) { return L + (W - L - R) * i / n; };
    var y = function (v) { return T + (H - T - B) * (1 - v / max); };
    grid(svg, max, y, L, W - R);
    var path = function (values) { return values.map(function (v, i) { return (i ? "L" : "M") + x(i).toFixed(1) + "," + y(v).toFixed(1); }).join(" "); };
    el("path", { d: "M" + x(0) + "," + y(0) + " " + path(plan).replace(/^M/, "L") + " L" + x(plan.length - 1) + "," + y(0) + " Z", "class": "plot-area" }, svg);
    el("line", { x1: L, x2: W - R, y1: y(scope), y2: y(scope), "class": "plot-scope" }, svg);
    text(svg, L + 4, y(scope) - 5, "Scope " + num(scope));
    el("path", { d: path(plan), "class": "plot-plan" }, svg);
    if (act.length) el("path", { d: path(act), "class": "plot-actual-line" }, svg);
    var last = plan.length - 1, gap = scope - plan[last];
    el("circle", { cx: x(last), cy: y(plan[last]), r: 4, "class": "plot-end" }, svg);
    if (gap > 0) {
      el("line", { x1: x(last) - 3, x2: x(last) - 3, y1: y(scope), y2: y(plan[last]), "class": "plot-gap" }, svg);
      text(svg, x(last) - 8, (y(scope) + y(plan[last])) / 2 + 4, num(gap) + " unplanned", "plot-gap-label", "end");
    }
    [0, Math.round(n / 3), Math.round(2 * n / 3), n].forEach(function (i, k) {
      text(svg, x(i), H - 8, shortDate(weeks[i].week), "plot-label", k === 0 ? "start" : k === 3 ? "end" : "middle");
    });
  }

  var charts = form.querySelector("[data-targets-charts]");

  function refresh() {
    var weeks = read();
    summary(weeks);
    rowsAndMonths(weeks);
    if (charts && weeks.length) {
      weekly(charts.querySelector('[data-chart="weekly"]'), weeks);
      cumulative(charts.querySelector('[data-chart="cumulative"]'), weeks);
    }
  }

  // --- Fill helpers -----------------------------------------------------------------------------------------------

  var tools = form.querySelector("[data-fill-tools]");
  if (tools) {
    tools.hidden = false;
    tools.querySelector("[data-fill-blank]").addEventListener("click", function () {
      var value = tools.querySelector("#fill-value").value.trim();
      if (!/^\d+$/.test(value)) { tools.querySelector("#fill-value").focus(); return; }
      upcomingBlanks(read()).forEach(function (w) { w.input.value = value; });
      refresh();
    });
    tools.querySelector("[data-spread]").addEventListener("click", function () {
      var weeks = read(), blanks = upcomingBlanks(weeks);
      var planned = weeks.reduce(function (sum, w) { return sum + (w.value || 0); }, 0);
      var gap = scope - before - planned;
      if (gap <= 0 || !blanks.length) return;
      var base = Math.floor(gap / blanks.length), rest = gap - base * blanks.length;
      blanks.forEach(function (w) { w.input.value = String(base + (rest-- > 0 ? 1 : 0)); });
      refresh();
    });
  }

  form.addEventListener("input", refresh);
  form.addEventListener("reset", function () { window.setTimeout(refresh, 0); });
  if (charts) charts.hidden = false;
  refresh();
})();
