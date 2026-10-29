// The report page's Screen | PDF | PNG switch: previews the report at the width, and in the light colours, that the
// PDF (an A4 page) and the PNG are drawn at. Without JavaScript the switch stays hidden.
(function () {
  "use strict";

  var VIEWS = ["screen", "pdf", "png"];

  document.addEventListener("DOMContentLoaded", function () {
    var group = document.querySelector("[data-report-view]");
    var report = document.querySelector(".report-live");
    if (!group || !report) return;
    var buttons = group.querySelectorAll("button[data-view]");

    function show(view) {
      VIEWS.forEach(function (name) {
        report.classList.toggle("is-" + name, name === view && name !== "screen");
      });
      report.classList.toggle("is-paper", view !== "screen");
      Array.prototype.forEach.call(buttons, function (button) {
        button.setAttribute("aria-pressed", String(button.getAttribute("data-view") === view));
      });
      // The interactive charts redraw in the paper's light colours.
      document.dispatchEvent(new CustomEvent("tracker:reportview", { detail: { view: view } }));
    }

    Array.prototype.forEach.call(buttons, function (button) {
      button.addEventListener("click", function () { show(button.getAttribute("data-view")); });
    });
    group.hidden = false;
  });
})();
