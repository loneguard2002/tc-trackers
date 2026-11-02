// Behaviours for the access screens (Teams, tracker Access and Permission sets). Every control here renders with the `hidden`
// attribute, because it does nothing without JavaScript; this script reveals it. Plain ES5 style, no modules.
(function () {
  "use strict";

  function each(list, fn) {
    Array.prototype.forEach.call(list, fn);
  }

  // input[data-tree-filter] narrows [data-tree] li[data-search]: a team stays shown when its own search text contains
  // the typed text, or when a team below it does. Empty text shows everything.
  each(document.querySelectorAll("input[data-tree-filter]"), function (input) {
    var items = document.querySelectorAll("[data-tree] li[data-search]");
    input.hidden = false;
    input.addEventListener("input", function () {
      var text = input.value.trim().toLowerCase();
      each(items, function (item) { item.hidden = text !== ""; });
      each(items, function (item) {
        if (text === "") return;
        if ((item.getAttribute("data-search") || "").indexOf(text) === -1) return;
        var node = item;
        while (node) {
          node.hidden = false;
          node = node.parentNode.closest("li[data-search]");
        }
      });
    });
  });

  // [data-row-filter="<id>"] holds button[data-show]; a click shows the rows of table[data-row-filter-target="<id>"]
  // whose space-separated data-route contains the value ("all" shows every row).
  each(document.querySelectorAll("[data-row-filter]"), function (group) {
    var id = group.getAttribute("data-row-filter");
    var buttons = group.querySelectorAll("button[data-show]");
    group.hidden = false;
    each(buttons, function (button) {
      button.addEventListener("click", function () {
        var show = button.getAttribute("data-show");
        each(buttons, function (other) { other.setAttribute("aria-pressed", other === button ? "true" : "false"); });
        each(document.querySelectorAll('table[data-row-filter-target="' + id + '"] tr[data-route]'), function (row) {
          var routes = (row.getAttribute("data-route") || "").split(" ");
          row.hidden = show !== "all" && routes.indexOf(show) === -1;
        });
      });
    });
  });

  // input[data-select-filter="<select id>"] hides the options of that select whose text does not contain the typed
  // text, and selects the first option still shown.
  each(document.querySelectorAll("input[data-select-filter]"), function (input) {
    var select = document.getElementById(input.getAttribute("data-select-filter"));
    if (!select) return;
    input.hidden = false;
    input.addEventListener("input", function () {
      var text = input.value.trim().toLowerCase();
      var first = null;
      each(select.options, function (option) {
        var match = option.text.toLowerCase().indexOf(text) !== -1;
        option.hidden = !match;
        option.disabled = !match;
        if (match && !first) first = option;
      });
      if (text === "") return;
      if (first) {
        first.selected = true;
      } else {
        select.selectedIndex = -1;
      }
    });
  });

  // A <details> holding the target of the address (or of an a[data-open-details] link) opens, so the section is seen.
  function openFor(target) {
    var details = target && target.closest ? target.closest("details") : null;
    if (details) details.open = true;
  }

  function openHash() {
    if (window.location.hash.length > 1) openFor(document.getElementById(window.location.hash.slice(1)));
  }

  each(document.querySelectorAll("a[data-open-details]"), function (link) {
    link.addEventListener("click", function () {
      openFor(document.getElementById((link.getAttribute("href") || "").slice(1)));
    });
  });

  // [data-permission-cards] holds article[data-set-card] cards whose tick boxes belong to one save form. Each change
  // updates the card's [data-count] ("2/7"), marks a card whose boxes differ from the saved state (defaultChecked, so
  // ticks a browser restores after a reload or Back count as unsaved) with .is-changed and its [data-changed] badge,
  // and sets [data-dirty-note] to how many sets have unsaved changes.
  each(document.querySelectorAll("[data-permission-cards]"), function (grid) {
    var cards = grid.querySelectorAll("article[data-set-card]");
    var note = document.querySelector("[data-dirty-note]");

    function refresh() {
      var changed = 0;
      each(cards, function (card) {
        var inputs = card.querySelectorAll("input[type=checkbox]");
        var ticked = 0;
        var differs = false;
        each(inputs, function (box) {
          if (box.checked) ticked += 1;
          if (box.checked !== box.defaultChecked) differs = true;
        });
        card.querySelector("[data-count]").textContent = ticked + "/" + inputs.length;
        card.classList.toggle("is-changed", differs);
        card.querySelector("[data-changed]").hidden = !differs;
        if (differs) changed += 1;
      });
      if (!note) return;
      note.textContent = changed === 0 ? "No unsaved changes"
        : "Unsaved changes in " + changed + " set" + (changed === 1 ? "" : "s");
      note.classList.toggle("is-dirty", changed > 0);
    }

    grid.addEventListener("change", refresh);
    refresh();
  });
  window.addEventListener("hashchange", openHash);
  openHash();
})();
