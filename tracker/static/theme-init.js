// Runs before the stylesheet so dark-mode users never see a light flash.
// A saved choice wins; otherwise follow the operating system's colour scheme.
(function () {
  "use strict";

  var theme = null;
  try {
    theme = window.localStorage.getItem("tracker-theme");
  } catch (_) {
    // Storage can be blocked in private windows.
  }
  if (theme !== "dark" && theme !== "light") {
    theme = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }
  document.documentElement.setAttribute("data-theme", theme);
  // Marks that scripts run, so the style sheet can hold back content a script replaces (the report's chart pictures).
  document.documentElement.classList.add("has-js");

  // The desktop sidebar's collapsed state is applied here too, so the layout does not jump on load.
  try {
    if (window.localStorage.getItem("tracker-sidebar") === "collapsed") {
      document.documentElement.setAttribute("data-sidebar", "collapsed");
    }
  } catch (_) {
    // Without storage the sidebar starts expanded.
  }
})();
