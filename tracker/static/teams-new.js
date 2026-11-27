/* The Teams New view (docs/superpowers/specs/2026-11-26-teams-simple-redesign-design.md). ES5, no inline handlers (CSP). */
(function () {
  "use strict";

  function each(list, fn) { Array.prototype.forEach.call(list, fn); }

  // The New team form in the Structure card (spec 2026-11-26-teams-simple-redesign-design.md 4.3): New team opens it
  // in place and Cancel hides it; choosing Sits under fills the region and location from that team unless the person
  // chose them, and says where they came from.
  var newForm = document.getElementById("new-team-form");
  if (newForm) {
    var nameInput = newForm.querySelector("[data-new-name]");
    var sitsUnder = newForm.querySelector("[data-sits-under]");
    var region = newForm.querySelector("[data-region-select]");
    var location = newForm.querySelector("[data-location-select]");
    var hint = newForm.querySelector("[data-place-hint]");
    var placeChosen = false;
    var filling = false;

    each(document.querySelectorAll("[data-new-team]"), function (link) {
      link.addEventListener("click", function (event) {
        if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
        event.preventDefault();
        newForm.hidden = false;
        newForm.scrollIntoView({ block: "nearest" });
        nameInput.focus();
      });
    });
    each(newForm.querySelectorAll("[data-new-team-cancel]"), function (link) {
      link.addEventListener("click", function (event) {
        if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
        event.preventDefault();
        newForm.hidden = true;
      });
    });
    [region, location].forEach(function (select) {
      if (!select) return;
      select.addEventListener("change", function () {
        if (!filling) placeChosen = true;
      });
    });
    if (sitsUnder) {
      sitsUnder.addEventListener("change", function () {
        var option = sitsUnder.options[sitsUnder.selectedIndex];
        var placeRegion = option ? option.getAttribute("data-place-region") : "";
        if (placeChosen || !region || !placeRegion) {
          if (hint && !placeChosen) hint.hidden = true;
          return;
        }
        filling = true;
        region.value = placeRegion;
        region.dispatchEvent(new Event("change"));
        if (location) {
          location.value = option.getAttribute("data-place-location") || "";
          location.dispatchEvent(new Event("change"));
        }
        filling = false;
        if (hint && region.value !== placeRegion) {  // that team's region is retired, so not offered here
          hint.hidden = true;
        } else if (hint) {
          hint.querySelector("[data-place-from]").textContent = option.getAttribute("data-team-name");
          hint.hidden = false;
        }
      });
    }
  }


  // The Structure card's search also finds people (spec 4.2): up to 6 whose name or email holds the typed text, each
  // opening their person view. The list comes from data-people; the tree's own filter is admin.js's.
  each(document.querySelectorAll("input[data-people-search]"), function (input) {
    var box = document.querySelector("[data-people-results]");
    if (!box) return;
    var list = box.querySelector("ul");
    var people;
    try {
      people = JSON.parse(box.getAttribute("data-people") || "[]");
    } catch (_) {
      people = [];
    }
    input.addEventListener("input", function () {
      var text = input.value.trim().toLowerCase();
      var found = text === "" ? [] : people.filter(function (p) {
        return (p.name + " " + p.email).toLowerCase().indexOf(text) !== -1;
      }).slice(0, 6);
      while (list.firstChild) list.removeChild(list.firstChild);
      found.forEach(function (p) {
        var item = document.createElement("li");
        var link = document.createElement("a");
        link.href = p.url;
        link.textContent = p.name;
        var hint = document.createElement("span");
        hint.className = "structure-people-hint";
        hint.textContent = "See memberships and rights";
        item.appendChild(link);
        item.appendChild(hint);
        list.appendChild(item);
      });
      box.hidden = found.length === 0;
    });
  });
})();
