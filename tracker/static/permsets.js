// The Permission sets page: the ‹ › buttons that step the sideways row of cards, the faded edges, and the save bar that
// shows only while a tick differs from what was saved. Loaded after admin.js, which keeps the "Changed" marks and the
// unsaved note. Everything here renders hidden or visible without JavaScript, so the page works without it.
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
      item.addEventListener("click", function () {
        var from = openMenu ? openMenu.button : null;
        closeMenu(false);
        run(card, from);
      });
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
  var renaming = null;
  // The pop-ups give the focus back to the button that opened the menu when they close without saving.
  var returnFocus = null;
  function startRename(card, from) {
    returnFocus = from || null;
    renaming = card;
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
    var value = renameName.value.trim();
    var message = "";
    if (!value) {
      message = "Enter a permission set name.";
    } else if (Array.prototype.some.call(cards, function (card) {
      return card !== renaming && setName(card).toLowerCase() === value.toLowerCase();
    })) {
      message = "A permission set with this name already exists.";
    }
    if (!message) return;
    event.preventDefault();
    renameError.textContent = message;
    renameError.hidden = false;
    renameName.setAttribute("aria-invalid", "true");
    renameName.focus();
  });

  // The delete pop-up: who holds the set (the card's own line) and the permissions they lose (its saved ticks).
  function startDelete(card, from) {
    returnFocus = from || null;
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
    dialog.addEventListener("close", function () {
      var back = returnFocus;
      returnFocus = null;
      if (back && document.body.contains(back)) back.focus();
    });
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
    var heading = element("h2", "", setName(card));
    heading.id = "set-panel-title";
    panel.setAttribute("aria-labelledby", heading.id);
    title.appendChild(heading);
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
    // Only a short status is announced, not the whole fragment once it arrives.
    var status = element("p", "sr-only", "Loading the holders…");
    status.setAttribute("role", "status");
    body.appendChild(element("p", "empty-note", "Loading the holders…"));
    panel.appendChild(head);
    panel.appendChild(status);
    panel.appendChild(body);
    if (!panel.open) panel.showModal();
    try { history.replaceState(null, "", location.pathname + "?set=" + encodeURIComponent(id)); } catch (e) { /* ignore */ }

    function failed() {
      if (panelCard !== card) return;
      status.textContent = "The holders could not be loaded.";
      body.textContent = "";
      var note = element("p", "empty-note", "The holders could not be loaded. ");
      var link = element("a", "", "Open the set's own page");
      link.href = card.querySelector("[data-open-panel]").getAttribute("href");
      note.appendChild(link);
      body.appendChild(note);
    }
    fetch(card.getAttribute("data-panel-url"), { credentials: "same-origin", headers: { "X-Requested-With": "fetch" } })
      .then(function (response) {
        // An expired session redirects to the sign-in page, which answers 200: treat that as a failure too.
        if (!response.ok || response.redirected) throw new Error("status " + response.status);
        return response.text();
      })
      .then(function (html) {
        if (panelCard !== card) return;
        if (html.indexOf("data-panel-set") === -1) throw new Error("not the panel");
        status.textContent = "";
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
  // A click on the dimmed page closes it.
  panel.addEventListener("click", function (event) {
    // A click on the backdrop targets the dialog itself, as does one on the empty strip inside its box below short
    // content, so the point must also lie outside the box. Keyboard clicks target a button, never the dialog.
    if (event.target !== panel) return;
    var box = panel.getBoundingClientRect();
    if (event.clientX < box.left || event.clientX > box.right || event.clientY < box.top || event.clientY > box.bottom) panel.close();
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

// New permission set in four steps: a pop-up holding a real form. Next, Back and the step bar only move between the
// steps; Create submits the form once. The server checks everything again. The link in the head keeps its address, so
// without JavaScript it opens the plain create page.
(function () {
  "use strict";

  var dialog = document.getElementById("new-set-dialog");
  var opener = document.querySelector("[data-new-set]");
  if (!dialog || !opener) return;

  var CAPTIONS = ["", "Step 1 of 4: name it", "Step 2 of 4: tick its permissions", "Step 3 of 4: choose who holds it",
    "Step 4 of 4: check and create"];
  var form = dialog.querySelector("form");
  var name = document.getElementById("new-set-name");
  var description = document.getElementById("new-set-description");
  var nameError = dialog.querySelector("[data-name-error]");
  var perms = dialog.querySelector("[data-wizard-perms]");
  var count = dialog.querySelector("[data-wizard-count]");
  var warning = dialog.querySelector("[data-wizard-warning]");
  var list = dialog.querySelector("[data-holder-list]");
  var none = dialog.querySelector("[data-holder-none]");
  var picked = dialog.querySelector("[data-holder-picked]");
  var search = dialog.querySelector("[data-holder-search]");
  var back = dialog.querySelector("[data-wizard-back]");
  var next = dialog.querySelector("[data-wizard-next]");
  var skip = dialog.querySelector("[data-wizard-skip]");
  var create = dialog.querySelector("[data-wizard-create]");
  var steps = dialog.querySelector(".wizard-steps");
  var dots = dialog.querySelectorAll("[data-step-dot]");
  var sections = dialog.querySelectorAll("[data-step]");
  var review = dialog.querySelector("[data-review]");
  var boxes = perms.querySelectorAll("input");
  var step = 1;

  function each(items, fn) { Array.prototype.forEach.call(items, fn); }
  function element(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }
  function labelOf(box) { return box.closest(".perm-row").querySelector(".perm-row-label").textContent.trim(); }
  function ticked() { return Array.prototype.filter.call(boxes, function (box) { return box.checked; }); }
  function holderBoxes() { return list.querySelectorAll("input:checked"); }
  function holderName(box) { return box.parentNode.querySelector(".wizard-holder-name").textContent; }
  function isTeam(box) { return box.value.indexOf("team:") === 0; }

  // Step 2: the count and the warning.
  function refreshPerms() {
    var on = ticked().map(function (box) { return box.value; });
    count.textContent = on.length + " of " + boxes.length + " ticked";
    warning.hidden = !(on.indexOf("manage_users") >= 0 && on.indexOf("manage_teams") >= 0);
  }
  perms.addEventListener("change", refreshPerms);

  // Step 3: search filters the list; the picked ones show as chips above it, each removes its pick.
  function refreshPicked() {
    picked.textContent = "";
    each(holderBoxes(), function (box) {
      var chip = element("button", "chip", holderName(box) + " ✕");
      chip.type = "button";
      chip.setAttribute("aria-label", "Remove " + holderName(box));
      chip.addEventListener("click", function () { box.checked = false; refreshPicked(); search.focus(); });
      picked.appendChild(chip);
    });
    skip.hidden = step !== 3 || picked.children.length > 0;
    next.hidden = step === 4 || (step === 3 && picked.children.length === 0);
  }
  function filter() {
    var query = search.value.trim().toLowerCase();
    var shown = 0;
    each(list.children, function (item) {
      item.hidden = !!query && item.getAttribute("data-text").indexOf(query) < 0;
      if (!item.hidden) shown += 1;
    });
    none.hidden = shown > 0;
  }
  list.addEventListener("change", refreshPicked);
  search.addEventListener("input", filter);

  // Step 4: the three blocks, built from the draft. Text goes in with textContent, never as markup.
  function block(title, to, extra) {
    var section = element("section", "review-block");
    var head = element("div", "review-head");
    head.appendChild(element("h3", "", title));
    if (extra) head.appendChild(element("span", "chip-count", extra));
    var edit = element("button", "button button-small", "Edit");
    edit.type = "button";
    edit.setAttribute("aria-label", "Edit " + title.toLowerCase());
    edit.addEventListener("click", function () { go(to); });
    head.appendChild(edit);
    section.appendChild(head);
    return section;
  }
  function renderReview() {
    review.textContent = "";
    var set = block("Set", 1);
    set.appendChild(element("div", "review-name", name.value.trim()));
    var text = description.value.trim();
    set.appendChild(element("p", "review-desc" + (text ? "" : " is-none"), text || "No description."));
    review.appendChild(set);

    var on = ticked();
    var granted = block("Permissions", 2, on.length + " of " + boxes.length);
    if (on.length) {
      var groups = element("div", "review-groups");
      var current = null;
      each(perms.children, function (node) {
        if (node.classList.contains("perm-group")) {
          current = element("div", "review-group");
          current.appendChild(element("h4", "", node.textContent));
          current.appendChild(element("ul"));
          current.hidden = true;
          groups.appendChild(current);
        } else if (current && node.querySelector("input") && node.querySelector("input").checked) {
          current.querySelector("ul").appendChild(element("li", "", labelOf(node.querySelector("input"))));
          current.hidden = false;
        }
      });
      granted.appendChild(groups);
      var left = Array.prototype.filter.call(boxes, function (box) { return !box.checked; }).map(labelOf);
      if (left.length) granted.appendChild(element("p", "review-left", "Not included: " + left.join(", ")));
    } else {
      granted.appendChild(element("p", "review-empty", "None ticked. Holders gain nothing until you tick some, here or later on the card."));
    }
    if (!warning.hidden) {
      var note = element("p", "perm-card-warning");
      note.appendChild(warning.querySelector(".icon").cloneNode(true));
      note.appendChild(element("span", "", warning.querySelector("span").textContent));
      granted.appendChild(note);
    }
    review.appendChild(granted);

    var who = holderBoxes();
    var held = block("Holders", 3, String(who.length));
    if (who.length) {
      var chips = element("ul", "review-chips");
      each(who, function (box) {
        var chip = element("li", "", holderName(box));
        if (isTeam(box)) chip.appendChild(element("small", "", "team"));
        chips.appendChild(chip);
      });
      held.appendChild(chips);
    } else {
      held.appendChild(element("p", "review-empty", "Nobody yet. You can choose holders later on the set's panel."));
    }
    review.appendChild(held);
    review.appendChild(element("p", "review-final", "Nothing is saved until you press Create permission set."));
  }

  function nameProblem() {
    var value = name.value.trim();
    if (!value) return "Give the set a name.";
    var taken = Array.prototype.some.call(document.querySelectorAll("[data-set-card] h2"), function (heading) {
      return heading.textContent.trim().toLowerCase() === value.toLowerCase();
    });
    return taken ? "A permission set with this name already exists." : "";
  }

  function go(to) {
    step = to;
    each(sections, function (section) { section.hidden = Number(section.getAttribute("data-step")) !== step; });
    steps.style.setProperty("--progress", String((step - 1) / 3));
    each(dots, function (dot) {
      var n = Number(dot.getAttribute("data-step-dot"));
      var done = n < step;
      if (n === step) dot.setAttribute("aria-current", "step"); else dot.removeAttribute("aria-current");
      dot.classList.toggle("is-done", done);
      dot.querySelector("span").textContent = done ? "✓" : String(n);
      // A finished step can be opened again by a click or Enter on it.
      if (done) {
        dot.setAttribute("tabindex", "0");
        dot.setAttribute("role", "button");
        dot.setAttribute("aria-label", "Back to step " + n + ", " + dot.textContent.replace(/^✓/, ""));
      } else {
        dot.removeAttribute("tabindex");
        dot.removeAttribute("role");
        dot.removeAttribute("aria-label");
      }
    });
    dialog.querySelector("[data-step-caption]").textContent = CAPTIONS[step];
    back.hidden = step === 1;
    create.hidden = step !== 4;
    refreshPicked();
    if (step === 4) renderReview();
    var focus = { 1: name, 2: boxes[0], 3: search, 4: create }[step];
    if (focus) focus.focus();
  }

  function forward() {
    if (step === 1) {
      var problem = nameProblem();
      nameError.textContent = problem;
      nameError.hidden = !problem;
      if (problem) name.setAttribute("aria-invalid", "true"); else name.removeAttribute("aria-invalid");
      if (problem) { name.focus(); return; }
    }
    go(step + 1);
  }
  next.addEventListener("click", forward);
  back.addEventListener("click", function () { go(step - 1); });
  skip.addEventListener("click", function () { go(4); });
  each(dots, function (dot) {
    function open() { if (dot.classList.contains("is-done")) go(Number(dot.getAttribute("data-step-dot"))); }
    dot.addEventListener("click", open);
    dot.addEventListener("keydown", function (event) {
      if (event.key === "Enter" || event.key === " ") { event.preventDefault(); open(); }
    });
  });
  // Enter in the name goes to the next step. Only Create, on the last step, submits the form.
  form.addEventListener("submit", function (event) {
    if (step === 4) return;
    event.preventDefault();
    if (step === 1 && document.activeElement === name) forward();
  });

  // Each opening starts from step 1 with an empty draft; closing in any way discards it.
  function reset() {
    form.reset();
    nameError.hidden = true;
    name.removeAttribute("aria-invalid");
    filter();
    refreshPerms();
    go(1);
  }
  opener.addEventListener("click", function (event) {
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.button) return;
    event.preventDefault();
    reset();
    dialog.showModal();
    name.focus();
  });
  each(dialog.querySelectorAll("[data-close]"), function (button) {
    button.addEventListener("click", function () { dialog.close(); });
  });
  dialog.addEventListener("close", function () {
    if (document.body.contains(opener)) opener.focus();
  });
})();

// The three pop-up forms (New permission set, rename, delete) post once. A submit that goes ahead marks its form as
// sending and disables its buttons, so a double click cannot post twice and show the answer to the second post. A page
// restored from the back-forward cache starts clean.
(function () {
  "use strict";

  var forms = document.querySelectorAll("#new-set-dialog form, #rename-set-dialog form, #delete-set-dialog form");
  if (!forms.length) return;
  var sending = [];

  function setBusy(form, busy) {
    Array.prototype.forEach.call(form.querySelectorAll("button[type=submit]"), function (button) {
      button.disabled = busy;
    });
  }

  // Listening on the window sees the event after every listener on the form, so a submit another script cancelled
  // (a step still to finish, a name still to correct) does not count as sending.
  window.addEventListener("submit", function (event) {
    var form = event.target;
    if (Array.prototype.indexOf.call(forms, form) < 0) return;
    if (sending.indexOf(form) >= 0) {
      event.preventDefault();
    } else if (!event.defaultPrevented) {
      sending.push(form);
      setBusy(form, true);
    }
  });
  window.addEventListener("pageshow", function () {
    sending.forEach(function (form) { setBusy(form, false); });
    sending = [];
  });
})();
