// Trackers home: search, filter chips, the Business line and Region filters, sorting (the Sort select and the list's
// headings, one shared order) and the cards/list switch. The view is kept in the address (filter, line, region, sort,
// q, layout; defaults left out, bad values ignored). Without JavaScript the toolbar stays hidden and every tracker
// shows as a card, in "needs attention first" order (the server's order).
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
  var searchField = tools.querySelector("[data-search-for=home]");
  var searchInput = searchField && searchField.querySelector("[data-search-input]");
  var footer = document.querySelector("[data-home-footer]");
  var count = document.querySelector("[data-home-count]");
  var clearButton = document.querySelector("[data-clear-for=home]");
  var headings = Array.prototype.slice.call(list.querySelectorAll("thead th")).filter(function (th) {
    return th.querySelector("button.sort-button[data-sort]");
  });
  var state = { filter: "all", layout: "cards" };
  var DEFAULT_SORT = "attention";
  // How each sort key reads its value: "number" as a number, "text" as text. Target, forecast and last are ISO dates
  // (YYYY-MM-DD), which compare correctly as text; there is no separate "date" kind. A key's value is the card's
  // data-<key>; an empty one comes last in both directions.
  var KINDS = { attention: "number", name: "text", target: "text", progress: "number", forecast: "text", risks: "number", last: "text" };

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
    inputs: function (el) { return el.dataset.inputs === "true"; },
    disagree: function (el) { return el.dataset.disagree === "true"; }
  };

  // The search, the chip, the business line and the region must all match; a region matches any tracker that covers it.
  function matches(el) {
    var text = searchInput ? searchInput.value.trim().toLowerCase() : "";
    if (text && el.dataset.name.indexOf(text) === -1) return false;
    if (!TESTS[state.filter](el)) return false;
    if (lineSelect && lineSelect.value !== "all" && el.dataset.line !== lineSelect.value) return false;
    if (regionSelect && regionSelect.value !== "all" && (el.dataset.regions || "").indexOf(" " + regionSelect.value + " ") === -1) return false;
    return true;
  }

  function sortKey() {
    return sort.value.charAt(0) === "-" ? sort.value.slice(1) : sort.value;
  }

  // Natural order in the reader's language, ignoring case ("Tracker 5" before "Tracker 10"), as the Lists tables do.
  function naturally(a, b) {
    return a.localeCompare(b, undefined, { numeric: true, sensitivity: "base" });
  }

  function byName(a, b) {
    return naturally(a.dataset.name, b.dataset.name);
  }

  function compare(a, b) {
    var key = sortKey();
    var first = a.dataset[key];
    var second = b.dataset[key];
    if (first === "" || second === "") {
      if (first !== second) return first === "" ? 1 : -1;
      return byName(a, b);
    }
    var result = KINDS[key] === "number" ? Number(first) - Number(second) : (key === "name" ? naturally(first, second) : (first < second ? -1 : first > second ? 1 : 0));
    return (sort.value.charAt(0) === "-" ? -result : result) || byName(a, b);
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

  function isFiltered() {
    return Boolean((searchInput && searchInput.value.trim()) || state.filter !== "all" ||
      (lineSelect && lineSelect.value !== "all") || (regionSelect && regionSelect.value !== "all"));
  }

  function writeAddress() {
    var params = new URLSearchParams(window.location.search);
    function put(name, value, isDefault) {
      if (isDefault) params.delete(name);
      else params.set(name, value);
    }
    var text = searchInput ? searchInput.value.trim() : "";
    put("filter", state.filter, state.filter === "all");
    put("line", lineSelect ? lineSelect.value : "all", !lineSelect || lineSelect.value === "all");
    put("region", regionSelect ? regionSelect.value : "all", !regionSelect || regionSelect.value === "all");
    put("sort", sort.value, sort.value === DEFAULT_SORT);
    put("q", text, text === "");
    put("layout", state.layout, state.layout === "cards");
    var query = params.toString();
    try {
      window.history.replaceState(null, "", window.location.pathname + (query ? "?" + query : "") + window.location.hash);
    } catch (_) {
      // The page still works without an address to keep the view in.
    }
  }

  function render() {
    var shown = arrange(cards);
    arrange(rows);
    var total = rows.querySelectorAll("[data-card]").length;
    if (count) count.textContent = "Showing " + shown + " of " + total + " tracker" + (total === 1 ? "" : "s");
    if (clearButton) clearButton.hidden = !isFiltered();
    headings.forEach(function (th) {
      var key = th.querySelector("button.sort-button[data-sort]").getAttribute("data-sort");
      th.setAttribute("aria-sort", key !== sortKey() ? "none" : (sort.value.charAt(0) === "-" ? "descending" : "ascending"));
    });
    writeAddress();
    cards.hidden = state.layout !== "cards" || shown === 0;
    // The card row starts again from the left, and its faded edges follow what is left to scroll (tracker.js).
    cards.scrollLeft = 0;
    cards.dispatchEvent(new Event("scroll"));
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
  // A heading sets the Sort select to its column; a second click on the sorted heading reverses it.
  headings.forEach(function (th) {
    var button = th.querySelector("button.sort-button[data-sort]");
    var label = th.querySelector("[data-sort-label]");
    var key = button.getAttribute("data-sort");
    button.hidden = false;
    if (label) label.hidden = true;
    button.addEventListener("click", function () {
      sort.value = sort.value === key ? "-" + key : key;
      render();
    });
  });
  if (searchInput) {
    searchInput.addEventListener("input", render);
    searchField.hidden = false;
  }
  if (clearButton) {
    clearButton.addEventListener("click", function () {
      if (searchInput) searchInput.value = "";
      state.filter = "all";
      [lineSelect, regionSelect].forEach(function (select) { if (select) select.value = "all"; });
      render();
      if (searchInput) searchInput.focus();  // the button hides now, so the focus moves to the search box
    });
  }
  // The filters start at All on every visit, even when the browser restores a previous choice; the address then says
  // what to apply instead. A value the page does not offer is ignored.
  function hasOption(select, value) {
    return Array.prototype.some.call(select.options, function (option) { return option.value === value; });
  }
  var params = new URLSearchParams(window.location.search);
  [lineSelect, regionSelect].forEach(function (select) {
    if (!select) return;
    select.value = "all";
    select.addEventListener("change", render);
  });
  // A chip the page does not render (Status disagrees with forecast, when none does) is not a filter to apply.
  var wanted = params.get("filter") || "";
  if (TESTS.hasOwnProperty(wanted) && tools.querySelector('[data-filter="' + wanted + '"]')) state.filter = wanted;
  if (lineSelect && hasOption(lineSelect, params.get("line") || "")) lineSelect.value = params.get("line");
  if (regionSelect && hasOption(regionSelect, params.get("region") || "")) regionSelect.value = params.get("region");
  sort.value = hasOption(sort, params.get("sort") || "") ? params.get("sort") : DEFAULT_SORT;
  if (searchInput) searchInput.value = params.get("q") || "";
  if (params.get("layout") === "list" || params.get("layout") === "cards") state.layout = params.get("layout");

  tools.hidden = false;
  if (footer) footer.hidden = false;
  render();
})();
