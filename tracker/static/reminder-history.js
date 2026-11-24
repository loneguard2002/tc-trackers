// The calendar reminder history side panel on the Weekly update page. The History link goes to the history page; with
// JavaScript it opens the same content as a panel instead. The panel's body is the HTML fragment the link's
// data-history-url names. Follows permsets.js. Plain ES5 style, no modules.
(function () {
  "use strict";

  var trigger = document.querySelector("[data-history-url]");
  var panel = document.getElementById("history-panel");
  if (!trigger || !panel) return;

  function element(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  // The ⋯ menu: Escape closes it first (the panel on the next press), a click elsewhere closes it, arrows move.
  var openMenu = null;
  function closeMenu(focusButton) {
    if (!openMenu) return;
    var shut = openMenu;
    openMenu = null;
    shut.menu.hidden = true;
    shut.button.setAttribute("aria-expanded", "false");
    if (focusButton) shut.button.focus();
  }
  document.addEventListener("click", function (event) {
    if (openMenu && !openMenu.menu.contains(event.target) && !openMenu.button.contains(event.target)) closeMenu(false);
  });

  function addMenu(host, button, menu) {
    button.addEventListener("click", function () {
      var wasOpen = openMenu && openMenu.menu === menu;
      closeMenu(false);
      if (wasOpen) return;
      menu.hidden = false;
      button.setAttribute("aria-expanded", "true");
      openMenu = { menu: menu, button: button };
      menu.querySelector("[role=menuitem]").focus();
    });
    menu.addEventListener("keydown", function (event) {
      var items = Array.prototype.slice.call(menu.querySelectorAll("[role=menuitem]"));
      var at = items.indexOf(document.activeElement);
      if (event.key === "ArrowDown") { event.preventDefault(); items[(at + 1) % items.length].focus(); }
      else if (event.key === "ArrowUp") { event.preventDefault(); items[(at - 1 + items.length) % items.length].focus(); }
      else if (event.key === "Escape") { event.preventDefault(); event.stopPropagation(); closeMenu(true); }
      else if (event.key === "Tab") closeMenu(false);
    });
    // Choosing an item closes the menu; a form then posts (or the confirmation is refused) and the focus is back on ⋯.
    menu.addEventListener("click", function (event) {
      if (event.target.closest && event.target.closest("[role=menuitem]")) closeMenu(true);
    });
    host.appendChild(button);
    host.appendChild(menu);
  }

  // Posting leaves the page, so while the update form has unsaved changes the panel's forms do not post. inputs.js owns
  // the question; the answer is shown in the panel, because the page behind the modal is inert.
  function blocked(message) {
    var guard = window.trackerReminderGuard;
    var stop = !!guard && guard.blocked();
    if (message) message.hidden = !stop;
    return stop;
  }

  var opening = 0;
  function openPanel() {
    closeMenu(false);
    var mine = opening += 1;
    panel.textContent = "";
    var head = element("header", "drawer-head");
    var title = element("div", "perm-detail-title");
    var heading = element("h2", "", "Calendar reminder");
    heading.id = "history-panel-title";
    panel.setAttribute("aria-labelledby", heading.id);
    title.appendChild(heading);
    var sub = element("p", "");
    sub.hidden = true;
    title.appendChild(sub);
    head.appendChild(title);
    var cross = element("button", "tool-button", "✕");
    cross.type = "button";
    cross.title = "Close";
    cross.setAttribute("aria-label", "Close");
    cross.addEventListener("click", function () { panel.close(); });
    head.appendChild(cross);
    var body = element("div", "drawer-body");
    var status = element("p", "sr-only", "Loading the history…");
    status.setAttribute("role", "status");
    body.appendChild(element("p", "empty-note", "Loading the history…"));
    panel.appendChild(head);
    panel.appendChild(status);
    panel.appendChild(body);
    if (!panel.open) panel.showModal();

    function failed() {
      if (opening !== mine) return;
      status.textContent = "The history could not be loaded.";
      body.textContent = "";
      var note = element("p", "empty-note", "The history could not be loaded. ");
      var link = element("a", "", "Open the history page");
      link.href = trigger.getAttribute("href");
      note.appendChild(link);
      body.appendChild(note);
    }
    fetch(trigger.getAttribute("data-history-url"), { credentials: "same-origin", headers: { "X-Requested-With": "fetch" } })
      .then(function (response) {
        // An expired session redirects to the sign-in page, which answers 200: treat that as a failure too.
        if (!response.ok || response.redirected) throw new Error("status " + response.status);
        return response.text();
      })
      .then(function (html) {
        if (opening !== mine) return;
        if (html.indexOf("data-panel-history") === -1) throw new Error("not the panel");
        status.textContent = "";
        body.innerHTML = html;
        var root = body.querySelector("[data-panel-history]");
        sub.textContent = root.getAttribute("data-subtitle") || "";
        sub.hidden = !sub.textContent;
        var holder = root.querySelector("[data-history-menu]");
        if (holder) {
          addMenu(head, holder.querySelector(".perm-more"), holder.querySelector(".perm-menu"));
          head.insertBefore(head.querySelector(".perm-more"), cross);
          head.insertBefore(head.querySelector(".perm-menu"), cross);
          holder.remove();
          // On the form itself, so it runs before tracker.js asks "Are you sure?" and stops the event reaching it.
          var message = body.querySelector("[data-history-guard]");
          Array.prototype.forEach.call(head.querySelectorAll("[data-history-form]"), function (form) {
            form.addEventListener("submit", function (event) {
              if (!blocked(message)) return;
              event.preventDefault();
              event.stopPropagation();
            });
          });
        }
        if (window.trackerLists) {
          Array.prototype.forEach.call(body.querySelectorAll("table[data-sortable][id]"), window.trackerLists.setUp);
        }
      })
      .catch(failed);
  }

  panel.addEventListener("close", function () {
    opening += 1;
    closeMenu(false);
    trigger.focus();
  });
  panel.addEventListener("cancel", function (event) {
    if (openMenu) { event.preventDefault(); closeMenu(true); }
  });
  // A click on the dimmed page closes it: the click targets the dialog itself, outside its box.
  panel.addEventListener("click", function (event) {
    if (event.target !== panel) return;
    var box = panel.getBoundingClientRect();
    if (event.clientX < box.left || event.clientX > box.right || event.clientY < box.top || event.clientY > box.bottom) panel.close();
  });
  trigger.addEventListener("click", function (event) {
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.button) return;
    event.preventDefault();
    openPanel();
  });
})();
