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
      document.dispatchEvent(new CustomEvent("tracker:themechange", { detail: { theme: next } }));
      try {
        window.localStorage.setItem("tracker-theme", next);
      } catch (_) {
        // The theme still changes for this page when storage is unavailable.
      }
      syncThemeLabel();
    });
  }

  // Forms marked data-confirm ask before they submit, as deletes cannot be undone. The listener sits on the document
  // because tables.js redraws table rows after this runs.
  document.addEventListener("submit", function (event) {
    var message = event.target.getAttribute("data-confirm");
    if (message && !window.confirm(message)) event.preventDefault();
  });

  // Section links (.subnav): underline the section in view and outline that section. With sections in two columns,
  // two share a row; a clicked link keeps the underline while the page scrolls to it and once it arrives.
  var subnav = document.querySelector(".subnav");
  if (subnav) {
    var links = Array.prototype.slice.call(subnav.querySelectorAll("a[href^='#']"));
    var targets = links.map(function (link) { return document.getElementById(link.getAttribute("href").slice(1)); });
    var current = -1;
    var settling = false;
    var settleTimer = null;
    var ticking = false;

    var setCurrent = function (index) {
      current = index;
      links.forEach(function (link, i) {
        if (i === index) {
          link.setAttribute("aria-current", "location");
        } else {
          link.removeAttribute("aria-current");
        }
        if (targets[i]) targets[i].classList.toggle("is-current", i === index);
      });
    };

    // The row in view: the lowest row whose top has passed under the links, the last row once the page is scrolled
    // to the bottom, or the first row before anything has passed.
    var update = function () {
      if (settling) return;
      var line = subnav.getBoundingClientRect().bottom + 24;
      var tops = targets.map(function (t) { return t ? Math.round(t.getBoundingClientRect().top) : Infinity; });
      var present = tops.filter(isFinite);
      if (!present.length) return;
      var scrolledToBottom = window.scrollY > 0 &&
        window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 2;
      var passed = present.filter(function (top) { return top <= line; });
      var rowTop;
      if (scrolledToBottom) {
        rowTop = Math.max.apply(null, present);
      } else if (passed.length) {
        rowTop = Math.max.apply(null, passed);
      } else {
        rowTop = Math.min.apply(null, present);
      }
      var row = [];
      tops.forEach(function (top, i) { if (Math.abs(top - rowTop) <= 2) row.push(i); });
      setCurrent(row.indexOf(current) !== -1 ? current : row[0]);
    };

    var settle = function () {
      settling = false;
      update();
    };
    // Hold the chosen link until the page stops scrolling (no scroll for 150 ms, or none starting within 300 ms).
    var hold = function (index) {
      setCurrent(index);
      settling = true;
      window.clearTimeout(settleTimer);
      settleTimer = window.setTimeout(settle, 300);
    };

    links.forEach(function (link, i) {
      link.addEventListener("click", function () { hold(i); });
    });
    window.addEventListener("scroll", function () {
      if (settling) {
        window.clearTimeout(settleTimer);
        settleTimer = window.setTimeout(settle, 150);
      } else if (!ticking) {
        ticking = true;
        window.requestAnimationFrame(function () { ticking = false; update(); });
      }
    }, { passive: true });
    window.addEventListener("resize", update);

    var linked = links.map(function (link) { return link.getAttribute("href"); }).indexOf(window.location.hash);
    if (linked !== -1) {
      hold(linked);
    } else {
      update();
    }
  }
})();
