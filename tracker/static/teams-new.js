/* The Teams New view (docs/superpowers/specs/2026-11-26-teams-new-view-design.md). ES5, no inline handlers (CSP). */
(function () {
  "use strict";

  function each(list, fn) { Array.prototype.forEach.call(list, fn); }

  // The chart's search: marks the teams whose name, or whose members' names, contain the typed text, and opens any
  // folded branch holding one.
  each(document.querySelectorAll("input[data-chart-search]"), function (input) {
    var chart = document.querySelector("[data-chart]");
    if (!chart) return;
    input.hidden = false;
    input.addEventListener("input", function () {
      var text = input.value.trim().toLowerCase();
      each(chart.querySelectorAll("li[data-search]"), function (item) {
        var match = text !== "" && item.getAttribute("data-search").indexOf(text) !== -1;
        item.classList.toggle("is-match", match);
        if (match) {
          var fold = item.parentNode && item.parentNode.closest("details");
          while (fold) {
            fold.open = true;
            fold = fold.parentNode && fold.parentNode.closest("details");
          }
        }
      });
    });
  });
})();
