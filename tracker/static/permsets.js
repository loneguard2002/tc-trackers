// The Permission sets page: the ‹ › buttons that step the sideways row of cards, the faded edges, and the save bar that
// shows only while a tick differs from what was saved. Loaded after admin.js, which keeps the per-card counts and
// "Changed" marks. Everything here renders hidden or visible without JavaScript, so the page works without it.
// Plain ES5 style, no modules.
(function () {
  "use strict";

  function each(list, fn) {
    Array.prototype.forEach.call(list, fn);
  }

  // The row: ‹ › step it one card at a time; the buttons disable at either end and .more-before / .more-after fade the
  // edge that has more cards behind it.
  var row = document.querySelector("[data-permission-cards]");
  var arrows = document.querySelectorAll("[data-scroll]");
  if (row) {
    var sync = function () {
      var rest = row.scrollWidth - row.clientWidth - row.scrollLeft;
      row.classList.toggle("more-before", row.scrollLeft > 1);
      row.classList.toggle("more-after", rest > 1);
      if (arrows.length === 2) {
        arrows[0].disabled = row.scrollLeft <= 1;
        arrows[1].disabled = rest <= 1;
      }
    };
    each(arrows, function (button) {
      button.hidden = false;
      button.addEventListener("click", function () {
        var card = row.querySelector(".perm-card");
        var step = card ? card.getBoundingClientRect().width + 20 : 400;
        var reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
        row.scrollBy({ left: step * Number(button.getAttribute("data-scroll")), behavior: reduce ? "auto" : "smooth" });
      });
    });
    row.addEventListener("scroll", sync, { passive: true });
    window.addEventListener("resize", sync);
    sync();
  }

  // The save bar: shown only while some tick differs from its saved state (defaultChecked). Discard puts every tick
  // back and fires the same change event, so admin.js updates the counts, marks and note.
  var bar = document.querySelector("[data-save-bar]");
  if (!bar) return;
  var count = bar.querySelector("[data-save-count]");
  var discard = bar.querySelector("[data-discard]");
  var boxes = document.querySelectorAll("input[form=permission-cards-form]");

  function changed() {
    return Array.prototype.filter.call(boxes, function (box) { return box.checked !== box.defaultChecked; });
  }

  function refresh() {
    var list = changed();
    var sets = {};
    list.forEach(function (box) { sets[box.name] = true; });
    var n = Object.keys(sets).length;
    count.textContent = list.length === 0 ? ""
      : list.length + " unsaved change" + (list.length === 1 ? "" : "s") + " in " + n + " set" + (n === 1 ? "" : "s");
    bar.classList.toggle("is-shown", list.length > 0);
  }

  bar.classList.add("is-armed");
  discard.hidden = false;
  document.addEventListener("change", function (event) {
    if (event.target.getAttribute && event.target.getAttribute("form") === "permission-cards-form") refresh();
  });
  discard.addEventListener("click", function () {
    var first = changed()[0];
    changed().forEach(function (box) {
      box.checked = box.defaultChecked;
      box.dispatchEvent(new Event("change", { bubbles: true }));
    });
    refresh();
    // The bar hides, so the focus moves to the first tick that was restored rather than falling to the page.
    if (first) first.focus();
  });
  // A submit that goes ahead is the way out that saves, so it does not warn. A page restored from the back-forward
  // cache starts clean.
  var saving = false;
  var form = document.getElementById("permission-cards-form");
  // Listening on the window sees the event after every listener on the form, so a submit another script cancels counts
  // as not going ahead.
  window.addEventListener("submit", function (event) {
    if (event.target === form) saving = !event.defaultPrevented;
  });
  window.addEventListener("pageshow", function () { saving = false; });
  window.addEventListener("beforeunload", function (event) {
    if (!saving && changed().length) {
      event.preventDefault();
      event.returnValue = "";
    }
  });
  refresh();
})();

// The ⋯ menus on the cards, the rename and delete pop-ups, and the holders side panel. The markup comes from index.html
// (a template for the menu, three dialogs); the panel's body is the HTML fragment from /<id>/panel. Without JavaScript
// none of it shows and "Holders and details" goes to the set's own page.
(function () {
  "use strict";

  var template = document.getElementById("perm-menu-template");
  var panel = document.getElementById("set-panel");
  var renameDialog = document.getElementById("rename-set-dialog");
  var deleteDialog = document.getElementById("delete-set-dialog");
  var cards = document.querySelectorAll("[data-set-card]");
  if (!template || !panel || !renameDialog || !deleteDialog || !cards.length) return;

  function setName(card) { return card.querySelector("h2").textContent.trim(); }
  function setDescription(card) {
    var note = card.querySelector(".perm-card-title p");
    return note && !note.classList.contains("perm-card-none") ? note.textContent.trim() : "";
  }
  function element(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  // Menus: one open at a time. Arrow keys move through the items, Escape and a click elsewhere close it.
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

  // Puts a ⋯ button and its menu into host. The items run the actions, each on the card the menu belongs to.
  function addMenu(host, card, actions) {
    var parts = template.content.cloneNode(true);
    var button = parts.querySelector(".perm-more");
    var menu = parts.querySelector(".perm-menu");
    button.setAttribute("aria-label", "More for " + setName(card));
    Array.prototype.forEach.call(menu.querySelectorAll("[data-act]"), function (item) {
      var run = actions[item.getAttribute("data-act")];
      if (!run) {
        if (item.nextElementSibling && item.nextElementSibling.tagName === "HR" && item.getAttribute("data-act") === "details") {
          item.nextElementSibling.remove();
        }
        item.remove();
        return;
      }
      item.addEventListener("click", function () { closeMenu(false); run(card); });
    });
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
    host.appendChild(button);
    host.appendChild(menu);
    return button;
  }

  // The rename pop-up: a real form posting to the rename route; the server checks the name again and says why it refuses.
  var renameName = document.getElementById("rename-set-name");
  var renameDescription = document.getElementById("rename-set-description");
  var renameError = renameDialog.querySelector("[data-name-error]");
  function startRename(card) {
    var form = renameDialog.querySelector("form");
    form.action = card.getAttribute("data-rename-url");
    renameDialog.querySelector("[data-dialog-sub]").textContent = setName(card);
    renameName.value = setName(card);
    renameDescription.value = setDescription(card);
    renameError.hidden = true;
    renameName.removeAttribute("aria-invalid");
    renameDialog.showModal();
    renameName.select();
  }
  renameDialog.querySelector("form").addEventListener("submit", function (event) {
    if (renameName.value.trim()) return;
    event.preventDefault();
    renameError.textContent = "Enter a permission set name.";
    renameError.hidden = false;
    renameName.setAttribute("aria-invalid", "true");
    renameName.focus();
  });

  // The delete pop-up: who holds the set (the card's own line) and the permissions they lose (its saved ticks).
  function startDelete(card) {
    var held = card.querySelector(".perm-card-foot span").textContent.trim();
    var nobody = held.indexOf("Held by") !== 0;
    var lose = Array.prototype.filter.call(card.querySelectorAll(".perm-row input"), function (box) {
      return box.defaultChecked;
    }).map(function (box) { return box.closest(".perm-row").querySelector(".perm-row-label").textContent.trim(); });
    deleteDialog.querySelector("form").action = card.getAttribute("data-delete-url");
    deleteDialog.querySelector("#delete-set-title").textContent = "Delete " + setName(card) + "?";
    var body = deleteDialog.querySelector("[data-delete-body]");
    body.textContent = "";
    if (nobody) {
      body.appendChild(element("p", "delete-impact", "Nobody holds this set, so nobody loses anything."));
    } else if (!lose.length) {
      body.appendChild(element("p", "delete-impact", held + ". It grants no permissions, so nobody loses anything."));
    } else {
      body.appendChild(element("p", "delete-impact", held + ". They lose:"));
      var list = element("ul", "delete-lose");
      lose.forEach(function (label) { list.appendChild(element("li", "", label)); });
      body.appendChild(list);
    }
    body.appendChild(element("p", "delete-note", "The activity log records the deletion and each holder removed."));
    deleteDialog.showModal();
    deleteDialog.querySelector("[data-close]:not(.tool-button)").focus();
  }

  [renameDialog, deleteDialog].forEach(function (dialog) {
    Array.prototype.forEach.call(dialog.querySelectorAll("[data-close]"), function (button) {
      button.addEventListener("click", function () { dialog.close(); });
    });
  });

  // The side panel. Its header is built from the card; its body is fetched. ?set=<id> follows the open panel.
  var panelCard = null;
  function openPanel(card) {
    closeMenu(false);
    panelCard = card;
    var id = card.getAttribute("data-set-id");
    panel.textContent = "";
    var head = element("header", "drawer-head");
    var title = element("div", "perm-detail-title");
    title.appendChild(element("h2", "", setName(card)));
    if (setDescription(card)) title.appendChild(element("p", "", setDescription(card)));
    head.appendChild(title);
    addMenu(head, card, { rename: startRename, "delete": startDelete });
    var cross = element("button", "tool-button", "✕");
    cross.type = "button";
    cross.title = "Close";
    cross.setAttribute("aria-label", "Close");
    cross.addEventListener("click", function () { panel.close(); });
    head.appendChild(cross);
    var body = element("div", "drawer-body");
    body.setAttribute("aria-live", "polite");
    body.appendChild(element("p", "empty-note", "Loading the holders…"));
    panel.appendChild(head);
    panel.appendChild(body);
    if (!panel.open) panel.showModal();
    try { history.replaceState(null, "", location.pathname + "?set=" + encodeURIComponent(id)); } catch (e) { /* ignore */ }

    function failed() {
      if (panelCard !== card) return;
      body.textContent = "";
      var note = element("p", "empty-note", "The holders could not be loaded. ");
      var link = element("a", "", "Open the set's own page");
      link.href = card.querySelector("[data-open-panel]").getAttribute("href");
      note.appendChild(link);
      body.appendChild(note);
    }
    fetch(card.getAttribute("data-panel-url"), { credentials: "same-origin", headers: { "X-Requested-With": "fetch" } })
      .then(function (response) {
        if (!response.ok) throw new Error("status " + response.status);
        return response.text();
      })
      .then(function (html) {
        if (panelCard !== card) return;
        body.innerHTML = html;
      })
      .catch(failed);
  }
  panel.addEventListener("close", function () {
    var card = panelCard;
    panelCard = null;
    closeMenu(false);
    try { history.replaceState(null, "", location.pathname); } catch (e) { /* ignore */ }
    var link = card && card.querySelector("[data-open-panel]");
    if (link) link.focus();
  });
  // Escape closes an open panel menu first, and the panel the next time.
  panel.addEventListener("cancel", function (event) {
    if (openMenu) { event.preventDefault(); closeMenu(true); }
  });
  // A click on the dimmed page (outside the panel's own box) closes it.
  panel.addEventListener("click", function (event) {
    var box = panel.getBoundingClientRect();
    var outside = event.clientX < box.left || event.clientX > box.right || event.clientY < box.top || event.clientY > box.bottom;
    if (outside) panel.close();
  });

  var actions = { rename: startRename, details: openPanel, "delete": startDelete };
  Array.prototype.forEach.call(cards, function (card) {
    addMenu(card.querySelector(".perm-card-head"), card, actions);
    card.querySelector("[data-open-panel]").addEventListener("click", function (event) {
      if (event.metaKey || event.ctrlKey || event.shiftKey || event.button) return;
      event.preventDefault();
      openPanel(card);
    });
  });

  // ?set=<id> opens that set's panel; anything that is not the id of a card here is ignored.
  var wanted = /^\?set=(\d+)$/.exec(location.search);
  if (wanted) {
    Array.prototype.forEach.call(cards, function (card) {
      if (card.getAttribute("data-set-id") === String(Number(wanted[1])) && !panel.open) openPanel(card);
    });
  }
})();
