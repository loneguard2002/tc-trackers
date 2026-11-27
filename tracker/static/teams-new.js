/* The Teams New view (docs/superpowers/specs/2026-11-26-teams-simple-redesign-design.md). ES5, no inline handlers (CSP). */
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

  // The chart's dotted lines: a team under several teams sits under one of them, so a dotted line runs to it from
  // each other higher team (data-also-ids). They are drawn in the SVG behind the boxes, follow any change of layout,
  // light up with the team pointed at or focused, and can be switched off (remembered in this browser). At phone
  // width the chart is an outline and tracker.css hides them; the "Also under" label says the same in words.
  each(document.querySelectorAll("[data-chart-stage]"), function (stage) {
    var svg = stage.querySelector("[data-chart-links]");
    var shared = stage.querySelectorAll(".org-node[data-also-ids]");
    if (!svg || !shared.length) return;
    var SVG_NS = "http://www.w3.org/2000/svg";
    var KEY = "tc.teams.chartLines";
    var toggle = document.querySelector("[data-links-toggle]");
    var box = toggle && toggle.querySelector("input");

    function shown(el) { return el && el.getClientRects().length > 0; }  // not inside a folded branch
    function node(id) { return stage.querySelector('.org-node[data-team-id="' + id + '"]'); }
    function add(name, attrs) {
      var el = document.createElementNS(SVG_NS, name);
      for (var key in attrs) el.setAttribute(key, attrs[key]);
      svg.appendChild(el);
    }

    function draw() {
      while (svg.firstChild) svg.removeChild(svg.firstChild);
      if (window.getComputedStyle(svg).display === "none") return;
      var base = stage.getBoundingClientRect();
      each(shared, function (child) {
        if (!shown(child)) return;
        var to = child.getAttribute("data-team-id");
        child.getAttribute("data-also-ids").split(" ").forEach(function (from) {
          var parent = node(from);
          if (!shown(parent)) return;
          var p = parent.getBoundingClientRect(), c = child.getBoundingClientRect();
          var x1 = p.left + p.width / 2 - base.left;
          // End off-centre, on the side the line comes from, clear of the solid line into the box's top.
          var x2 = c.left - base.left + c.width * (x1 > c.left + c.width / 2 - base.left ? 0.8 : 0.2);
          var y1, y2, d;
          if (p.bottom <= c.top) {  // the usual case: the other higher team is above
            y1 = p.bottom - base.top;
            y2 = c.top - base.top;
            var bend = Math.max(y1 + 24, (y1 + y2) / 2);
            d = "M" + x1 + " " + y1 + " C " + x1 + " " + bend + ", " + x2 + " " + (y2 - 36) + ", " + x2 + " " + y2;
          } else {  // on the same level or lower: loop underneath, bottom to bottom
            y1 = p.bottom - base.top;
            y2 = c.bottom - base.top;
            var low = Math.max(y1, y2) + 30;
            d = "M" + x1 + " " + y1 + " C " + x1 + " " + low + ", " + x2 + " " + low + ", " + x2 + " " + y2;
          }
          add("path", { d: d, "data-from": from, "data-to": to });
          add("circle", { cx: x2, cy: y2, r: 3.5, "data-from": from, "data-to": to });
        });
      });
    }

    function light(id, on) {
      each(stage.querySelectorAll(".org-node.is-linked"), function (el) { el.classList.remove("is-linked"); });
      each(svg.childNodes, function (el) {
        var from = el.getAttribute("data-from"), to = el.getAttribute("data-to");
        var hit = on && (from === id || to === id);
        el.classList.toggle("is-lit", hit);
        if (hit) {
          var other = node(from === id ? to : from);
          if (other) other.classList.add("is-linked");
        }
      });
    }
    each(stage.querySelectorAll(".org-node"), function (el) {
      var id = el.getAttribute("data-team-id");
      el.addEventListener("mouseenter", function () { light(id, true); });
      el.addEventListener("focus", function () { light(id, true); });
      el.addEventListener("mouseleave", function () { light(id, false); });
      el.addEventListener("blur", function () { light(id, false); });
    });

    if (toggle && box) {
      var off = false;
      try { off = window.localStorage.getItem(KEY) === "off"; } catch (e) { /* storage blocked: lines stay on */ }
      box.checked = !off;
      stage.classList.toggle("links-off", off);
      toggle.hidden = false;
      box.addEventListener("change", function () {
        stage.classList.toggle("links-off", !box.checked);
        try { window.localStorage.setItem(KEY, box.checked ? "on" : "off"); } catch (e) { /* not remembered */ }
        draw();
      });
    }

    stage.addEventListener("toggle", draw, true);  // a folded branch opened or closed
    if (window.ResizeObserver) new window.ResizeObserver(draw).observe(stage);
    window.addEventListener("resize", draw);
    if (document.fonts && document.fonts.ready) document.fonts.ready.then(draw);
    draw();
  });

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

})();
