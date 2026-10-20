(function () {
  var root = document.documentElement;
  var stored = null;
  try { stored = localStorage.getItem("tracker-theme"); } catch (e) {}
  var preferred = stored || (window.matchMedia && matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
  function apply(theme) {
    root.setAttribute("data-theme", theme);
    document.querySelectorAll("[data-theme-label]").forEach(function (el) {
      el.textContent = theme === "dark" ? "Light mode" : "Dark mode";
    });
  }
  apply(preferred);
  document.addEventListener("click", function (event) {
    var toggle = event.target.closest("[data-theme-toggle]");
    if (toggle) {
      var next = root.getAttribute("data-theme") === "dark" ? "light" : "dark";
      try { localStorage.setItem("tracker-theme", next); } catch (e) {}
      apply(next);
      return;
    }
    var menu = event.target.closest("[data-sidebar-toggle]");
    if (menu) {
      var open = document.body.classList.toggle("sidebar-open");
      menu.setAttribute("aria-expanded", String(open));
    } else if (event.target.closest("[data-sidebar-close]")) {
      document.body.classList.remove("sidebar-open");
    }
  });
})();
