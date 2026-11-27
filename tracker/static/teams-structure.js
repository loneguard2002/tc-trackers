/* The Teams Whole structure layer (docs/superpowers/specs/2026-11-26-teams-simple-redesign-design.md 4.9). ES5, no
   inline handlers (CSP): positions and the scale are set through the CSSOM.

   The teams come from the JSON block #structure-data (tracker/teams/overview.py structure_items). They are laid out
   as a tidy tree on their main teams: each team with nothing shown below it takes the next row, and a team with
   teams below sits midway between its first and last. Teams in a damaged loop, which no walk from the top reaches,
   are left out; every walk keeps a visited set. */
(function () {
  "use strict";

  var layer = document.querySelector("[data-structure-layer]");
  var source = document.getElementById("structure-data");
  if (!layer || !source) return;

  var SVG = "http://www.w3.org/2000/svg";
  var BOX_W = 200, BOX_H = 56, PAD = 24, LABEL = 30;
  var GAPS = { lr: { depth: 80, row: 14 }, tb: { depth: 64, row: 18 } };
  var END_OFFSET = { lr: 8, tb: 30 };

  var items = JSON.parse(source.textContent);
  var byId = {};
  var below = {};  // team id to the teams whose main team it is, by name (the data comes by name)
  var tops = [];
  items.forEach(function (item) { byId[item.id] = item; });
  items.forEach(function (item) {
    if (item.main === null) tops.push(item);
    else if (byId[item.main]) (below[item.main] = below[item.main] || []).push(item);
  });

  var viewport = layer.querySelector("[data-structure-viewport]");
  var sizer = layer.querySelector("[data-structure-sizer]");
  var stage = layer.querySelector("[data-structure-stage]");
  var lines = layer.querySelector("[data-structure-lines]");
  var stats = layer.querySelector("[data-structure-stats]");
  var find = layer.querySelector("[data-structure-find]");
  var currentId = parseInt(layer.getAttribute("data-current-team"), 10);
  var opener = null;

  var state = { direction: "lr", scale: 1, width: 0, height: 0 };
  var boxes = {};  // team id to its box element, for the shown teams

  function each(list, fn) { Array.prototype.forEach.call(list, fn); }
  function plural(n, one, many) { return n + " " + (n === 1 ? one : many); }

  function svg(name, attrs) {
    var el = document.createElementNS(SVG, name);
    Object.keys(attrs).forEach(function (key) { el.setAttribute(key, attrs[key]); });
    return el;
  }

  // --- Layout ------------------------------------------------------------------------------------------------------

  // Walks the main tree from the top-level teams; returns the shown teams with their depth and row, and the totals.
  function layout() {
    var placed = {}, order = [], next = 0, deepest = -1, reached = 0, shared = 0;
    function walk(item, depth) {
      placed[item.id] = true;  // visited before its children: a loop ends here
      reached += 1;
      if (item.others.length) shared += 1;
      var rows = [];
      (below[item.id] || []).forEach(function (child) {
        if (!placed[child.id]) rows.push(walk(child, depth + 1));
      });
      var row = rows.length ? (rows[0] + rows[rows.length - 1]) / 2 : next++;
      order.push({ item: item, depth: depth, row: row });
      if (depth > deepest) deepest = depth;
      return row;
    }
    tops.forEach(function (item) { if (!placed[item.id]) walk(item, 0); });
    return { nodes: order, rows: next, levels: deepest + 1, reached: reached, shared: shared };
  }

  function position(node) {
    var gap = GAPS[state.direction];
    var along = node.depth * (BOX_H + gap.depth);
    if (state.direction === "lr") {
      return { x: PAD + node.depth * (BOX_W + gap.depth), y: PAD + LABEL + node.row * (BOX_H + gap.row) };
    }
    return { x: PAD + node.row * (BOX_W + gap.row), y: PAD + LABEL + along };
  }

  // A cubic curve from a higher team's box to a lower team's box; a dotted line whose higher team is not before the
  // lower team goes round underneath, bottom to bottom. ``offset`` moves a dotted end off the solid line.
  function curve(from, to, offset) {
    var x1, y1, x2, y2, bend;
    var lr = state.direction === "lr";
    var before = lr ? from.x < to.x : from.y < to.y;
    if (!before) {
      x1 = from.x + BOX_W / 2; y1 = from.y + BOX_H;
      x2 = to.x + BOX_W / 2 + offset; y2 = to.y + BOX_H;
      bend = Math.max(y1, y2) + 36;
      return "M" + x1 + " " + y1 + " C" + x1 + " " + bend + " " + x2 + " " + bend + " " + x2 + " " + y2;
    }
    if (lr) {
      x1 = from.x + BOX_W; y1 = from.y + BOX_H / 2;
      x2 = to.x; y2 = to.y + BOX_H / 2 + offset;
      var mx = (x1 + x2) / 2;
      return "M" + x1 + " " + y1 + " C" + mx + " " + y1 + " " + mx + " " + y2 + " " + x2 + " " + y2;
    }
    x1 = from.x + BOX_W / 2; y1 = from.y + BOX_H;
    x2 = to.x + BOX_W / 2 + offset; y2 = to.y;
    var my = (y1 + y2) / 2;
    return "M" + x1 + " " + y1 + " C" + x1 + " " + my + " " + x2 + " " + my + " " + x2 + " " + y2;
  }

  function lineEnd(path) {
    var length = path.getTotalLength();
    var point = path.getPointAtLength(length);
    return svg("circle", { "class": "structure-line-end", cx: point.x, cy: point.y, r: 3.5 });
  }

  // --- Drawing -----------------------------------------------------------------------------------------------------

  function makeBox(item, at) {
    var box = document.createElement("div");
    box.className = "structure-box" + (item.others.length ? " is-shared" : "") + (item.id === currentId ? " is-current" : "");
    box.setAttribute("data-team-id", item.id);
    box.style.left = at.x + "px";
    box.style.top = at.y + "px";
    var link = document.createElement("a");
    link.className = "structure-box-open";
    link.href = item.url;
    link.title = item.name;
    if (item.id === currentId) link.setAttribute("aria-current", "page");
    var name = document.createElement("span");
    name.className = "structure-box-name";
    name.textContent = item.name;
    var meta = document.createElement("span");
    meta.className = "structure-box-meta";
    meta.textContent = [item.place, plural(item.people, "person", "people")].filter(Boolean).join(" · ");
    link.appendChild(name);
    link.appendChild(meta);
    box.appendChild(link);
    box.addEventListener("mouseenter", function () { light(item.id); });
    box.addEventListener("mouseleave", unlight);
    box.addEventListener("focusin", function () { light(item.id); });
    box.addEventListener("focusout", unlight);
    return box;
  }

  function levelLabel(depth) {
    var gap = GAPS[state.direction];
    var label = document.createElement("div");
    label.className = "structure-level";
    label.textContent = depth === 0 ? "Top" : "Level " + (depth + 1);
    if (state.direction === "lr") {
      label.style.left = PAD + depth * (BOX_W + gap.depth) + "px";
      label.style.top = PAD + "px";
    } else {
      label.style.left = PAD + "px";
      label.style.top = PAD + LABEL + depth * (BOX_H + gap.depth) - 24 + "px";
    }
    return label;
  }

  function render() {
    each(stage.querySelectorAll(".structure-box, .structure-level"), function (el) { el.parentNode.removeChild(el); });
    while (lines.firstChild) lines.removeChild(lines.firstChild);
    boxes = {};
    var result = layout();
    var gap = GAPS[state.direction];
    var spanRows = result.rows ? result.rows * (state.direction === "lr" ? BOX_H : BOX_W) + (result.rows - 1) * gap.row : 0;
    var spanLevels = result.levels ? result.levels * (state.direction === "lr" ? BOX_W : BOX_H) + (result.levels - 1) * gap.depth : 0;
    state.width = 2 * PAD + (state.direction === "lr" ? spanLevels : spanRows);
    state.height = 2 * PAD + LABEL + (state.direction === "lr" ? spanRows : spanLevels);
    stage.style.width = state.width + "px";
    stage.style.height = state.height + "px";
    lines.setAttribute("width", state.width);
    lines.setAttribute("height", state.height);

    var at = {};
    for (var depth = 0; depth < result.levels; depth++) stage.appendChild(levelLabel(depth));
    result.nodes.forEach(function (node) { at[node.item.id] = position(node); });
    result.nodes.forEach(function (node) {
      var item = node.item;
      if (item.main !== null && at[item.main]) {
        lines.appendChild(svg("path", {
          "class": "structure-line is-solid", d: curve(at[item.main], at[item.id], 0),
          "data-from": item.main, "data-to": item.id
        }));
      }
      item.others.forEach(function (other) {
        if (!at[other]) return;  // its other higher team is not shown: no line to a hidden box
        var path = svg("path", {
          "class": "structure-line is-dotted", d: curve(at[other], at[item.id], END_OFFSET[state.direction]),
          "data-from": other, "data-to": item.id
        });
        lines.appendChild(path);
        lines.appendChild(lineEnd(path));
      });
    });
    result.nodes.forEach(function (node) {
      var box = makeBox(node.item, at[node.item.id]);
      boxes[node.item.id] = box;
      stage.appendChild(box);
    });
    stats.textContent = plural(result.reached, "team", "teams") + " · " +
      plural(result.levels, "level shown", "levels shown") + " · " + result.shared + " shared";
    fit();
  }

  // --- Scale -------------------------------------------------------------------------------------------------------

  function applyScale(scale) {
    state.scale = scale;
    stage.style.transform = "scale(" + scale + ")";
    sizer.style.width = state.width * scale + "px";
    sizer.style.height = state.height * scale + "px";
  }

  function fit() {
    var scale = Math.min((viewport.clientWidth - 8) / state.width, (viewport.clientHeight - 8) / state.height, 1.25);
    applyScale(Math.max(scale, 0.2));
  }

  // --- Lighting ----------------------------------------------------------------------------------------------------

  function light(id) {
    unlight();
    each(lines.querySelectorAll("path.structure-line"), function (path) {
      var from = parseInt(path.getAttribute("data-from"), 10), to = parseInt(path.getAttribute("data-to"), 10);
      if (from !== id && to !== id) return;
      path.classList.add("is-lit");
      var other = boxes[from === id ? to : from];
      if (other) other.classList.add("is-linked");
    });
  }

  function unlight() {
    each(lines.querySelectorAll(".is-lit"), function (el) { el.classList.remove("is-lit"); });
    each(stage.querySelectorAll(".is-linked"), function (el) { el.classList.remove("is-linked"); });
  }

  // --- Open and close ----------------------------------------------------------------------------------------------

  function open(from) {
    opener = from || document.querySelector("[data-open-structure]");
    layer.hidden = false;
    document.body.classList.add("structure-open");
    render();
    find.focus();
  }

  function close() {
    if (layer.hidden) return;
    layer.hidden = true;
    document.body.classList.remove("structure-open");
    if (window.location.hash === "#whole-structure" && window.history.replaceState) {
      window.history.replaceState(null, "", window.location.pathname + window.location.search);
    }
    if (opener) opener.focus();
  }

  each(document.querySelectorAll("[data-open-structure]"), function (button) {
    button.addEventListener("click", function (event) {
      event.preventDefault();
      open(button);
    });
  });
  layer.querySelector("[data-structure-close]").addEventListener("click", close);
  layer.addEventListener("click", function (event) { if (event.target === layer) close(); });

  each(layer.querySelectorAll("[data-direction]"), function (button) {
    button.addEventListener("click", function () {
      state.direction = button.getAttribute("data-direction");
      each(layer.querySelectorAll("[data-direction]"), function (other) {
        other.setAttribute("aria-pressed", other === button ? "true" : "false");
      });
      render();
    });
  });

  // Escape closes; Tab stays inside the layer while it is open (it is modal).
  document.addEventListener("keydown", function (event) {
    if (layer.hidden) return;
    if (event.key === "Escape") {
      event.preventDefault();
      close();
      return;
    }
    if (event.key !== "Tab") return;
    var focusable = Array.prototype.filter.call(
      layer.querySelectorAll("a[href], button, input"),
      function (el) { return !el.disabled && el.offsetParent !== null; }
    );
    if (!focusable.length) return;
    var first = focusable[0], last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  });

  if (window.location.hash === "#whole-structure") open(null);
}());
