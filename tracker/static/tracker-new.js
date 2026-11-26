// New tracker: choosing a team ticks the region of the team's location (and unticks it again when the team
// changes), until a region box has been changed by
// hand; after that the ticks are left to the user. Without JavaScript nothing is pre-ticked.
(function () {
  "use strict";

  var team = document.getElementById("team_id");
  if (!team || !team.form) return;
  var boxes = team.form.querySelectorAll("input[type='checkbox'][name='region_ids']");
  var touched = false;

  Array.prototype.forEach.call(boxes, function (box) {
    box.addEventListener("change", function () { touched = true; });
  });

  var ticked = null;

  team.addEventListener("change", function () {
    if (touched) return;
    if (ticked) ticked.checked = false;
    ticked = null;
    var option = team.options[team.selectedIndex];
    var region = option ? option.getAttribute("data-region") : null;
    if (!region) return;
    Array.prototype.forEach.call(boxes, function (box) {
      if (box.value === region) {
        box.checked = true;
        ticked = box;
      }
    });
  });
})();

// New tracker in five steps, like New permission set: one real form shown a step at a time. Next checks the step it
// leaves (the server checks everything again); Back and the finished steps in the step bar move freely; Create
// tracker, on the review, submits once. Without JavaScript every step shows and Create tracker submits the form.
(function () {
  "use strict";

  var form = document.querySelector("[data-tracker-wizard]");
  if (!form) return;

  var LAST = 5;
  var CAPTIONS = ["", "Step 1 of 5: name it and say what it counts", "Step 2 of 5: choose who sees it",
    "Step 3 of 5: set the weeks it covers", "Step 4 of 5: tune the forecast (optional)", "Step 5 of 5: check and create"];
  var DAY = 864e5;
  var MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  var WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
  var els = form.elements;
  var sections = form.querySelectorAll("[data-wizard-step]");
  var dots = form.querySelectorAll("[data-step-dot]");
  var bar = form.querySelector(".wizard-steps");
  var caption = form.querySelector("[data-step-caption]");
  var back = form.querySelector("[data-wizard-back]");
  var next = form.querySelector("[data-wizard-next]");
  var skip = form.querySelector("[data-wizard-skip]");
  var create = form.querySelector("[data-wizard-create]");
  var review = form.querySelector("[data-review]");
  var step = 1;
  var sending = false;

  function each(items, fn) { Array.prototype.forEach.call(items, fn); }
  function element(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }
  function value(name) { return els[name] ? String(els[name].value || "").trim() : ""; }
  function chosenText(name) {
    var select = els[name];
    return select && select.value ? select.options[select.selectedIndex].textContent.trim() : "";
  }
  function regionLabels() {
    return Array.prototype.filter.call(form.querySelectorAll("input[name='region_ids']"), function (box) {
      return box.checked;
    }).map(function (box) { return box.parentNode.textContent.trim(); });
  }
  function parse(text) {
    var match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(text || "");
    return match ? Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3])) : null;
  }
  function fmt(t) {
    var d = new Date(t);
    return d.getUTCDate() + " " + MONTHS[d.getUTCMonth()] + " " + d.getUTCFullYear();
  }
  function weekdayOf(t) { return (new Date(t).getUTCDay() + 6) % 7; }
  function plural(n, word) { return n + " " + word + (n === 1 ? "" : "s"); }

  // The weeks as the server will store them: the first date moves forward to the week-ending day.
  function weeks() {
    var weekday = Number(value("week_ending_weekday"));
    var start = parse(value("start_date"));
    var last = parse(value("last_week_ending"));
    if (start === null || last === null || isNaN(weekday)) {
      return { problem: "Enter the first and the last week-ending.", field: start === null ? "start_date" : "last_week_ending" };
    }
    var first = start + ((weekday - weekdayOf(start) + 7) % 7) * DAY;
    if (weekdayOf(last) !== weekday) return { problem: "The last week-ending must fall on a " + WEEKDAYS[weekday] + ".", field: "last_week_ending" };
    if (last < first) return { problem: "The last week-ending cannot be before the first.", field: "last_week_ending" };
    if (last - first > 51 * 7 * DAY) return { problem: "The last week-ending must be at most 52 weeks after the first.", field: "last_week_ending" };
    return { first: first, last: last, count: Math.round((last - first) / (7 * DAY)) + 1, weekday: weekday };
  }

  // Step 3: the weeks covered, as a strip with the target week marked.
  var strip = form.querySelector("[data-weeks]");
  function drawWeeks() {
    var span = weeks();
    var target = parse(value("target_completion"));
    var sum = strip.querySelector("[data-weeks-sum]");
    var row = strip.querySelector("[data-weeks-bar]");
    row.textContent = "";
    strip.hidden = false;
    if (span.problem) {
      sum.textContent = span.problem;
      strip.querySelector("[data-weeks-first]").textContent = "";
      strip.querySelector("[data-weeks-target]").textContent = "";
      strip.querySelector("[data-weeks-last]").textContent = "";
      return;
    }
    for (var i = 0; i < span.count; i += 1) {
      var ending = span.first + i * 7 * DAY;
      var cls = "wizard-week";
      if (target !== null && target > ending - 7 * DAY && target <= ending) cls += " is-target";
      else if (target !== null && ending > target) cls += " is-after-target";
      row.appendChild(element("span", cls));
    }
    sum.textContent = plural(span.count, "week") + ", " + fmt(span.first) + " to " + fmt(span.last) + ".";
    if (target !== null && target > span.last) sum.textContent += " The target is after the last week-ending.";
    strip.querySelector("[data-weeks-first]").textContent = fmt(span.first);
    strip.querySelector("[data-weeks-target]").textContent = target !== null ? "Target " + fmt(target) : "";
    strip.querySelector("[data-weeks-last]").textContent = fmt(span.last);
  }

  // Step 4: the minus and plus buttons beside the moving-average period.
  var average = els.moving_average_weeks;
  function averageButtons() {
    var n = parseInt(average.value, 10) || 0;
    each(form.querySelectorAll("[data-stepper] [data-step]"), function (button) {
      button.disabled = Number(button.dataset.step) < 0 ? n <= 1 : n >= 12;
    });
  }
  each(form.querySelectorAll("[data-stepper] [data-step]"), function (button) {
    button.hidden = false;
    button.addEventListener("click", function () {
      var n = Math.max(1, Math.min(12, (parseInt(average.value, 10) || 3) + Number(button.dataset.step)));
      average.value = String(n);
      averageButtons();
    });
  });
  average.addEventListener("input", averageButtons);
  form.addEventListener("input", function (event) {
    if (event.target.name === "unit_label") {
      each(form.querySelectorAll("[data-live-unit]"), function (el) { el.textContent = value("unit_label") || "units"; });
    }
  });

  // What stops each step, as [message, the field to fix]; nothing when the step is complete.
  function problem(n) {
    if (n === 1 && !value("name")) return ["Enter a name to go on.", "name"];
    if (n === 2 && !value("business_line_id")) return ["Choose a business line to go on.", "business_line_id"];
    if (n === 2 && !regionLabels().length) {
      return ["Tick at least one region to go on.", "region_ids"];
    }
    if (n === 3) {
      var span = weeks();
      if (span.problem) return [span.problem, span.field];
      if (value("target_completion") && parse(value("target_completion")) === null) {
        return ["Enter a valid target completion date, or leave it empty.", "target_completion"];
      }
    }
    if (n === 4) {
      var before = value("completed_before_first");
      if (before && !/^\d+$/.test(before)) return ["Enter zero or more for the quantity completed before the first week.", "completed_before_first"];
      var weeksAveraged = Number(value("moving_average_weeks"));
      if (!/^\d+$/.test(value("moving_average_weeks")) || weeksAveraged < 1 || weeksAveraged > 12) {
        return ["The moving-average period must be between 1 and 12 weeks.", "moving_average_weeks"];
      }
    }
    return null;
  }

  function clearProblems() {
    each(form.querySelectorAll("[data-step-error]"), function (note) { note.hidden = true; note.textContent = ""; });
    each(form.querySelectorAll("[aria-invalid]"), function (field) { field.removeAttribute("aria-invalid"); });
  }

  function show(n, found) {
    var section = form.querySelector("[data-wizard-step='" + n + "']");
    var note = section.querySelector("[data-step-error]");
    note.textContent = found[0];
    note.hidden = false;
    var field = els[found[1]];
    if (field instanceof RadioNodeList) field = field[0];
    if (field && field.focus) {
      field.setAttribute("aria-invalid", "true");
      field.focus();
    }
  }

  // Step 5: one block per step, each with Edit. Text goes in with textContent, never as markup.
  function block(title, to) {
    var box = element("section", "review-block");
    var head = element("div", "review-head");
    head.appendChild(element("h3", "", title));
    var edit = element("button", "button button-small", "Edit");
    edit.type = "button";
    edit.setAttribute("aria-label", "Edit " + title.toLowerCase());
    edit.addEventListener("click", function () { go(to); });
    head.appendChild(edit);
    box.appendChild(head);
    return box;
  }
  function rows(box, pairs) {
    var list = element("dl", "review-list");
    pairs.forEach(function (pair) {
      list.appendChild(element("dt", "", pair[0]));
      list.appendChild(element("dd", pair[2] ? "is-none" : "", pair[1]));
    });
    box.appendChild(list);
  }
  function renderReview() {
    review.textContent = "";
    var unit = value("unit_label") || "units";
    var details = block("Details", 1);
    details.appendChild(element("div", "review-name", value("name")));
    rows(details, [
      ["Counts", unit],
      ["Groups are called", value("group_label") || "Group"],
      ["Description", value("description") || "No description", !value("description")]
    ]);
    review.appendChild(details);

    var regions = regionLabels();
    var access = block("Who sees it", 2);
    rows(access, [
      ["Business line", chosenText("business_line_id")],
      ["Regions", regions.join(", ")],
      ["Team", chosenText("team_id") || "No team", !value("team_id")]
    ]);
    review.appendChild(access);

    var span = weeks();
    var target = parse(value("target_completion"));
    var period = block("Weeks", 3);
    rows(period, [
      ["Week ends on", WEEKDAYS[span.weekday]],
      ["Covers", plural(span.count, "week") + ", " + fmt(span.first) + " to " + fmt(span.last)],
      ["Target", target !== null ? fmt(target) : "No target", target === null]
    ]);
    review.appendChild(period);

    var forecast = block("Forecast", 4);
    rows(forecast, [
      ["Before the first week", (value("completed_before_first") || "0") + " " + unit],
      ["Rate averaged over", plural(Number(value("moving_average_weeks")), "week")]
    ]);
    review.appendChild(forecast);
  }

  function go(to) {
    step = to;
    clearProblems();
    each(sections, function (section) { section.hidden = Number(section.getAttribute("data-wizard-step")) !== step; });
    bar.style.setProperty("--progress", String((step - 1) / (LAST - 1)));
    each(dots, function (dot) {
      var n = Number(dot.getAttribute("data-step-dot"));
      var done = n < step;
      if (n === step) dot.setAttribute("aria-current", "step"); else dot.removeAttribute("aria-current");
      dot.classList.toggle("is-done", done);
      dot.querySelector("span").textContent = done ? "✓" : String(n);
      // A finished step can be opened again by a click or Enter on it.
      if (done) {
        dot.setAttribute("tabindex", "0");
        dot.setAttribute("role", "button");
        dot.setAttribute("aria-label", "Back to step " + n + ", " + dot.textContent.replace(/^✓/, ""));
      } else {
        dot.removeAttribute("tabindex");
        dot.removeAttribute("role");
        dot.removeAttribute("aria-label");
      }
    });
    caption.textContent = CAPTIONS[step];
    back.hidden = step === 1;
    skip.hidden = step !== 4;
    next.hidden = step === LAST;
    create.hidden = step !== LAST;
    if (step === 3) drawWeeks();
    if (step === LAST) renderReview();
  }

  // Forward, checking each step on the way; it stops on the first one with something to fix.
  function forward(to) {
    for (var n = step; n < to; n += 1) {
      var found = problem(n);
      if (found) {
        if (n !== step) go(n);
        show(n, found);
        return;
      }
    }
    go(to);
    var heading = form.querySelector("[data-wizard-step='" + step + "'] .wizard-step-title");
    if (heading) heading.focus();
  }

  form.noValidate = true;  // each step is checked on Next; the browser's checks would point at hidden fields
  bar.hidden = false;
  next.addEventListener("click", function () { forward(step + 1); });
  back.addEventListener("click", function () { go(step - 1); form.querySelector("[data-wizard-step='" + step + "'] .wizard-step-title").focus(); });
  skip.addEventListener("click", function () {
    els.completed_before_first.value = "0";
    average.value = "3";
    averageButtons();
    forward(LAST);
  });
  each(dots, function (dot) {
    function open() { if (dot.classList.contains("is-done")) go(Number(dot.getAttribute("data-step-dot"))); }
    dot.addEventListener("click", open);
    dot.addEventListener("keydown", function (event) {
      if (event.key === "Enter" || event.key === " ") { event.preventDefault(); open(); }
    });
  });
  ["week_ending_weekday", "start_date", "last_week_ending", "target_completion"].forEach(function (name) {
    var field = els[name];
    var list = field instanceof RadioNodeList ? Array.prototype.slice.call(field) : [field];
    list.forEach(function (one) {
      one.addEventListener("input", function () { if (step === 3) drawWeeks(); });
      one.addEventListener("change", function () { if (step === 3) drawWeeks(); });
    });
  });
  // Enter in a field goes to the next step. Only Create tracker, on the review, submits, and only once.
  form.addEventListener("submit", function (event) {
    if (step !== LAST) {
      event.preventDefault();
      forward(step + 1);
      return;
    }
    for (var n = 1; n < LAST; n += 1) {
      var found = problem(n);
      if (found) {
        event.preventDefault();
        go(n);
        show(n, found);
        return;
      }
    }
    if (sending) { event.preventDefault(); return; }
    sending = true;
    create.disabled = true;
  });
  window.addEventListener("pageshow", function () { sending = false; create.disabled = false; });

  // After the server refused the form: the first step with something to fix, else the review under its list.
  averageButtons();
  if (Number(form.getAttribute("data-start-step")) === LAST) {
    for (var n = 1; n < LAST; n += 1) {
      var found = problem(n);
      if (found) { go(n); show(n, found); return; }
    }
    go(LAST);
  } else {
    go(1);
  }
})();
