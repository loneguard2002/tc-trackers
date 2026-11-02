// Trackers home: filter chips, the Business line and Region filters, sorting and the cards/list switch. Without
// JavaScript the toolbar stays hidden and every tracker shows as a card, in "needs attention first" order (the
// server's order).
(function () {
  "use strict";

  var tools = document.querySelector("[data-home-tools]");
  var cards = document.querySelector("[data-home-cards]");
  var list = document.querySelector("[data-home-list]");
  var empty = document.querySelector("[data-home-empty]");
  if (!tools || !cards || !list) return;

  var rows = list.querySelector("tbody");
  var sort = tools.querySelector("[data-home-sort]");
  var lineSelect = tools.querySelector("[data-home-line]");
  var regionSelect = tools.querySelector("[data-home-region]");
  var state = { filter: "all", layout: "cards" };

  try {
    state.layout = window.localStorage.getItem("tracker-home-layout") === "list" ? "list" : "cards";
  } catch (_) {
    // Cards are the default when storage is unavailable.
  }

  var TESTS = {
    all: function () { return true; },
    red: function (el) { return el.dataset.status === "red"; },
    amber: function (el) { return el.dataset.status === "amber"; },
    green: function (el) { return el.dataset.status === "green"; },
    none: function (el) { return el.dataset.status === "none"; },
    behind: function (el) { return el.dataset.behind === "true"; },
    inputs: function (el) { return el.dataset.inputs === "true"; }
  };

  // The chip, the business line and the region must all match; a region matches any tracker that covers it.
  function matches(el) {
    if (!TESTS[state.filter](el)) return false;
    if (lineSelect && lineSelect.value !== "all" && el.dataset.line !== lineSelect.value) return false;
    if (regionSelect && regionSelect.value !== "all" && (el.dataset.regions || "").indexOf(" " + regionSelect.value + " ") === -1) return false;
    return true;
  }

  function compare(a, b) {
    var key = sort.value;
    if (key === "name") return a.dataset.name.localeCompare(b.dataset.name);
    if (key === "target") return a.dataset.target.localeCompare(b.dataset.target) || a.dataset.name.localeCompare(b.dataset.name);
    return Number(a.dataset.attention) - Number(b.dataset.attention) || a.dataset.name.localeCompare(b.dataset.name);
  }

  function arrange(container) {
    var items = Array.prototype.slice.call(container.querySelectorAll("[data-card]"));
    items.sort(compare).forEach(function (item) { container.appendChild(item); });
    var shown = 0;
    items.forEach(function (item) {
      var match = matches(item);
      item.hidden = !match;
      if (match) shown += 1;
    });
    return shown;
  }

  function render() {
    var shown = arrange(cards);
    arrange(rows);
    cards.hidden = state.layout !== "cards" || shown === 0;
    list.hidden = state.layout !== "list" || shown === 0;
    if (empty) empty.hidden = shown !== 0;
    tools.querySelectorAll("[data-filter]").forEach(function (chip) {
      chip.setAttribute("aria-pressed", String(chip.dataset.filter === state.filter));
    });
    tools.querySelectorAll("[data-layout]").forEach(function (button) {
      button.setAttribute("aria-pressed", String(button.dataset.layout === state.layout));
    });
  }

  tools.querySelectorAll("[data-filter]").forEach(function (chip) {
    chip.addEventListener("click", function () {
      state.filter = chip.dataset.filter;
      render();
    });
  });
  tools.querySelectorAll("[data-layout]").forEach(function (button) {
    button.addEventListener("click", function () {
      state.layout = button.dataset.layout;
      try {
        window.localStorage.setItem("tracker-home-layout", state.layout);
      } catch (_) {
        // The layout still switches for this visit.
      }
      render();
    });
  });
  sort.addEventListener("change", render);
  // The filters start at All on every visit, even when the browser restores a previous choice.
  [lineSelect, regionSelect].forEach(function (select) {
    if (!select) return;
    select.value = "all";
    select.addEventListener("change", render);
  });

  tools.hidden = false;
  render();
})();
