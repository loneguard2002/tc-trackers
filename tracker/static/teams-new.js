/* The Teams New view (docs/superpowers/specs/2026-11-26-teams-new-view-design.md). ES5, no inline handlers (CSP). */
(function () {
  "use strict";

  function each(list, fn) { Array.prototype.forEach.call(list, fn); }

  // The chart's search: marks the teams whose name, or whose members' names, contain the typed text, and opens any
  // folded branch holding one.
  each(document.querySelectorAll("input[data-chart-search]"), function (input) {
    var chart = document.querySelector("[data-chart]");
    if (!chart) return;
    input.hidden = false;
    input.addEventListener("input", function () {
      var text = input.value.trim().toLowerCase();
      each(chart.querySelectorAll("li[data-search]"), function (item) {
        var match = text !== "" && item.getAttribute("data-search").indexOf(text) !== -1;
        item.classList.toggle("is-match", match);
        if (match) {
          var fold = item.parentNode && item.parentNode.closest("details");
          while (fold) {
            fold.open = true;
            fold = fold.parentNode && fold.parentNode.closest("details");
          }
        }
      });
    });
  });

  // The New team panel: opened in place by New team; Where it sits shows who reaches the new team, fills its region
  // and location from the team above unless the person chose them, and names both on the button.
  var panel = document.getElementById("new-team-panel");
  if (panel) {
    var form = panel.querySelector("form");
    var nameInput = form.querySelector("[data-new-name]");
    var region = form.querySelector("[data-region-select]");
    var location = form.querySelector("[data-location-select]");
    var hint = form.querySelector("[data-place-hint]");
    var label = form.querySelector("[data-create-label] span");
    var placeChosen = Boolean(region && region.value);
    var filling = false;

    each(document.querySelectorAll("[data-new-team]"), function (link) {
      link.addEventListener("click", function (event) {
        if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
        event.preventDefault();
        panel.hidden = false;
        panel.scrollIntoView({ block: "nearest" });
        nameInput.focus();
      });
    });
    each(panel.querySelectorAll("[data-panel-close]"), function (link) {
      link.addEventListener("click", function (event) {
        event.preventDefault();
        panel.hidden = true;
      });
    });
    [region, location].forEach(function (select) {
      if (!select) return;
      select.addEventListener("change", function () {
        if (!filling) placeChosen = true;
      });
    });

    function chosen() {
      return form.querySelector("input[name='parent_id']:checked");
    }

    function update() {
      var radio = chosen();
      var id = radio ? radio.value : "";
      var teamName = radio ? radio.getAttribute("data-team-name") : "";
      each(form.querySelectorAll("[data-reach-for]"), function (list) {
        list.hidden = list.getAttribute("data-reach-for") !== id;
      });
      var name = nameInput.value.trim() || "team";
      label.textContent = "Create " + name + (teamName ? " under " + teamName : "");
    }

    function fillPlace() {
      var radio = chosen();
      var placeRegion = radio ? radio.getAttribute("data-place-region") : "";
      if (placeChosen || !region || !placeRegion) {
        if (hint && !placeChosen) hint.hidden = true;
        return;
      }
      filling = true;
      region.value = placeRegion;
      region.dispatchEvent(new Event("change"));
      if (location) {
        location.value = radio.getAttribute("data-place-location") || "";
        location.dispatchEvent(new Event("change"));
      }
      filling = false;
      if (hint) {
        hint.querySelector("[data-place-from]").textContent = radio.getAttribute("data-team-name");
        hint.hidden = false;
      }
    }

    each(form.querySelectorAll("input[name='parent_id']"), function (radio) {
      radio.addEventListener("change", function () {
        update();
        fillPlace();
      });
    });
    nameInput.addEventListener("input", update);
    update();
  }
})();
