// Sidebar and theme controls. theme-init.js has already applied the saved theme and sidebar state.
// On desktop the menu button collapses the sidebar to icons; on narrow screens it opens it as a drawer.
(function () {
  "use strict";

  var root = document.documentElement;
  var sidebar = document.querySelector(".sidebar");
  var backdrop = document.querySelector(".sidebar-backdrop");
  var menuButton = document.querySelector("[data-sidebar-toggle]");
  var desktop = window.matchMedia("(min-width: 993px)");

  function isCollapsed() {
    return root.getAttribute("data-sidebar") === "collapsed";
  }

  function syncMenuButton() {
    if (!menuButton || !sidebar) return;
    if (desktop.matches) {
      menuButton.setAttribute("aria-expanded", String(!isCollapsed()));
      menuButton.setAttribute("aria-label", isCollapsed() ? "Expand navigation" : "Collapse navigation");
    } else {
      var open = sidebar.classList.contains("open");
      menuButton.setAttribute("aria-expanded", String(open));
      menuButton.setAttribute("aria-label", open ? "Close navigation" : "Open navigation");
    }
  }

  function setDrawer(open) {
    if (!sidebar) return;
    sidebar.classList.toggle("open", open);
    if (backdrop) backdrop.classList.toggle("open", open);
    syncMenuButton();
  }

  function setCollapsed(collapsed) {
    if (collapsed) {
      root.setAttribute("data-sidebar", "collapsed");
    } else {
      root.removeAttribute("data-sidebar");
    }
    try {
      window.localStorage.setItem("tracker-sidebar", collapsed ? "collapsed" : "expanded");
    } catch (_) {
      // The sidebar still collapses for this page when storage is unavailable.
    }
    syncMenuButton();
  }

  if (menuButton && sidebar) {
    menuButton.addEventListener("click", function (event) {
      event.preventDefault();
      if (desktop.matches) {
        setCollapsed(!isCollapsed());
      } else {
        setDrawer(!sidebar.classList.contains("open"));
      }
    });
  }
  if (backdrop) backdrop.addEventListener("click", function () { setDrawer(false); });
  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape") setDrawer(false);
  });
  desktop.addEventListener("change", function () { setDrawer(false); });
  syncMenuButton();

  // On narrow screens the tracker tabs scroll sideways; bring the current one into view.
  var activeTab = document.querySelector(".tab.active");
  if (activeTab && activeTab.parentNode.scrollWidth > activeTab.parentNode.clientWidth) {
    activeTab.parentNode.scrollLeft = activeTab.offsetLeft - activeTab.parentNode.offsetLeft - 16;
  }

  var themeButton = document.querySelector("[data-theme-toggle]");
  var themeLabel = document.querySelector("[data-theme-label]");
  function syncThemeLabel() {
    var text = root.getAttribute("data-theme") === "dark" ? "Light mode" : "Dark mode";
    if (themeLabel) themeLabel.textContent = text;
    if (themeButton) themeButton.setAttribute("data-label", text);
  }
  syncThemeLabel();
  if (themeButton) {
    themeButton.addEventListener("click", function () {
      var next = root.getAttribute("data-theme") === "dark" ? "light" : "dark";
      root.setAttribute("data-theme", next);
      try {
        window.localStorage.setItem("tracker-theme", next);
      } catch (_) {
        // The theme still changes for this page when storage is unavailable.
      }
      syncThemeLabel();
    });
  }
})();
