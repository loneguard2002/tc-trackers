// Risks: filter chips (RAG, not rated, past target date) and a search box over the open risks. Without JavaScript
// the toolbar stays hidden and every open risk is listed.
(function () {
  "use strict";

  var tools = document.querySelector("[data-risk-tools]");
  var rows = document.querySelector("[data-risk-rows]");
  if (!tools || !rows) return;

  var empty = document.querySelector("[data-risk-empty]");
  var search = tools.querySelector("[data-risk-search]");
  var filter = "all";

  function matches(row) {
    if (filter === "overdue") return row.dataset.overdue === "true";
    return filter === "all" || row.dataset.rag === filter;
  }

  function render() {
    var words = search.value.trim().toLowerCase().split(/\s+/).filter(Boolean);
    var shown = 0;
    rows.querySelectorAll("[data-risk]").forEach(function (row) {
      var text = row.dataset.search;
      var match = matches(row) && words.every(function (word) { return text.indexOf(word) !== -1; });
      row.hidden = !match;
      if (match) shown += 1;
    });
    if (empty) empty.hidden = shown !== 0;
    tools.querySelectorAll("[data-filter]").forEach(function (chip) {
      chip.setAttribute("aria-pressed", String(chip.dataset.filter === filter));
    });
  }

  tools.querySelectorAll("[data-filter]").forEach(function (chip) {
    chip.addEventListener("click", function () {
      filter = chip.dataset.filter;
      render();
    });
  });
  search.addEventListener("input", render);
  tools.hidden = false;
  render();
})();
