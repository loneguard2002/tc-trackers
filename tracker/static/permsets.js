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
    changed().forEach(function (box) {
      box.checked = box.defaultChecked;
      box.dispatchEvent(new Event("change", { bubbles: true }));
    });
    refresh();
  });
  // A submit is the way out that saves, so it does not warn.
  var saving = false;
  var form = document.getElementById("permission-cards-form");
  if (form) form.addEventListener("submit", function () { saving = true; });
  window.addEventListener("beforeunload", function (event) {
    if (!saving && changed().length) {
      event.preventDefault();
      event.returnValue = "";
    }
  });
  refresh();
})();
