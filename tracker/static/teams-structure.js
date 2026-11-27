/* The Teams Whole structure layer (docs/superpowers/specs/2026-11-26-teams-simple-redesign-design.md 4.9). ES5, no
   inline handlers (CSP): positions and the scale are set through the CSSOM.

   The teams come from the layer's data-structure JSON (tracker/teams/overview.py structure_items). They are laid out
   as a tidy tree on their main teams: each team with nothing shown below it takes the next row, and a team with
   teams below sits midway between its first and last. Teams in a damaged loop, which no walk from the top reaches,
   are left out; every walk keeps a visited set. */
(function () {
  "use strict";

  var layer = document.querySelector("[data-structure-layer]");
  if (!layer) return;

  var SVG = "http://www.w3.org/2000/svg";
  var BOX_W = 200, BOX_H = 56, PAD = 24, LABEL = 30;
  var GAPS = { lr: { depth: 80, row: 14 }, tb: { depth: 64, row: 18 } };
  var END_OFFSET = { lr: 8, tb: 30 };

  var items = JSON.parse(layer.getAttribute("data-structure") || "[]");
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
  var foldAll = layer.querySelector("[data-fold-all]");
  var fitButton = layer.querySelector('[data-zoom="fit"]');
  var percentButton = layer.querySelector('[data-zoom="reset"]');
  var currentId = parseInt(layer.getAttribute("data-current-team"), 10);
  var opener = null;

  // folded: team id to true while its branch is folded; query: the Find a team text, lower case.
  var state = { direction: "lr", fit: true, scale: 1, width: 0, height: 0, folded: {}, query: "" };
  var boxes = {};  // team id to its box element, for the shown teams

  function each(list, fn) { Array.prototype.forEach.call(list, fn); }
  function plural(n, one, many) { return n + " " + (n === 1 ? one : many); }

  function svg(name, attrs) {
    var el = document.createElementNS(SVG, name);
    Object.keys(attrs).forEach(function (key) { el.setAttribute(key, attrs[key]); });
    return el;
  }

  // --- The whole main tree, folded or not ---------------------------------------------------------------------------

  // Every team reached from the top, with its depth and how many teams sit below it on the main tree. The stats'
  // team and shared counts and the "+N" of a folded box come from here, so folding does not change them.
  var tree = (function () {
    var depth = {}, count = {}, reached = 0, shared = 0;
    function walk(item, level) {
      depth[item.id] = level;
      reached += 1;
      if (item.others.length) shared += 1;
      var total = 0;
      (below[item.id] || []).forEach(function (child) {
        if (depth[child.id] === undefined) total += 1 + walk(child, level + 1);
      });
      count[item.id] = total;
      return total;
    }
    tops.forEach(function (item) { if (depth[item.id] === undefined) walk(item, 0); });
    return { depth: depth, count: count, reached: reached, shared: shared };
  }());

  function anyFolded() { return Object.keys(state.folded).length > 0; }

  // --- Layout ------------------------------------------------------------------------------------------------------

  // Walks the main tree from the top-level teams; returns the shown teams with their depth and row, and the totals.
  function layout() {
    var placed = {}, order = [], next = 0, deepest = -1;
    function walk(item, depth) {
      placed[item.id] = true;  // visited before its children: a loop ends here
      var rows = [];
      if (!state.folded[item.id]) {
        (below[item.id] || []).forEach(function (child) {
          if (!placed[child.id]) rows.push(walk(child, depth + 1));
        });
      }
      var row = rows.length ? (rows[0] + rows[rows.length - 1]) / 2 : next++;
      order.push({ item: item, depth: depth, row: row });
      if (depth > deepest) deepest = depth;
      return row;
    }
    tops.forEach(function (item) { if (!placed[item.id]) walk(item, 0); });
    return { nodes: order, rows: next, levels: deepest + 1 };
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
  // lower team goes round underneath, bottom to bottom. In left to right, two boxes in one column are stacked, so
  // that line goes round their right side instead of through the boxes between them. ``offset`` moves a dotted end
  // off the solid line. A bend reaches at most 0.75 × BEND past the boxes, inside the stage's padding.
  var BEND = 30;
  function curve(from, to, offset) {
    var x1, y1, x2, y2, bend;
    var lr = state.direction === "lr";
    var before = lr ? from.x < to.x : from.y < to.y;
    if (!before && lr && from.x === to.x) {
      x1 = from.x + BOX_W; y1 = from.y + BOX_H / 2;
      x2 = to.x + BOX_W; y2 = to.y + BOX_H / 2 + offset;
      bend = x1 + BEND;
      return "M" + x1 + " " + y1 + " C" + bend + " " + y1 + " " + bend + " " + y2 + " " + x2 + " " + y2;
    }
    if (!before) {
      x1 = from.x + BOX_W / 2; y1 = from.y + BOX_H;
      x2 = to.x + BOX_W / 2 + offset; y2 = to.y + BOX_H;
      bend = Math.max(y1, y2) + BEND;
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
    if (tree.count[item.id]) box.appendChild(foldButton(item));
    box.addEventListener("mouseenter", function () { light(item.id); });
    box.addEventListener("mouseleave", unlight);
    box.addEventListener("focusin", function () { light(item.id); });
    box.addEventListener("focusout", unlight);
    return box;
  }

  // "−" folds the team's branch; a folded team shows "+N", N being every team below it on the main tree.
  function foldButton(item) {
    var button = document.createElement("button");
    var folded = !!state.folded[item.id];
    button.type = "button";
    button.className = "structure-box-fold";
    button.textContent = folded ? "+" + tree.count[item.id] : "\u2212";
    button.setAttribute("aria-label", (folded ? "Unfold " : "Fold ") + item.name);
    button.setAttribute("aria-expanded", folded ? "false" : "true");
    button.addEventListener("click", function () {
      if (folded) delete state.folded[item.id];
      else state.folded[item.id] = true;
      render();
      var again = stage.querySelector('.structure-box[data-team-id="' + item.id + '"] .structure-box-fold');
      if (again) again.focus();
    });
    return button;
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
    stats.textContent = plural(tree.reached, "team", "teams") + " · " +
      plural(result.levels, "level shown", "levels shown") + " · " + tree.shared + " shared";
    foldAll.textContent = anyFolded() ? "Unfold all" : "Fold all";
    mark();
    if (state.fit) fit();
    else applyScale(state.scale);
  }

  // --- Scale -------------------------------------------------------------------------------------------------------

  function applyScale(scale) {
    state.scale = scale;
    stage.style.transform = "scale(" + scale + ")";
    sizer.style.width = state.width * scale + "px";
    sizer.style.height = state.height * scale + "px";
    percentButton.textContent = Math.round(scale * 100) + "%";
    fitButton.setAttribute("aria-pressed", state.fit ? "true" : "false");
  }

  function zoom(how) {
    if (how === "fit") {
      state.fit = true;
      fit();
      return;
    }
    state.fit = false;
    if (how === "reset") applyScale(1);
    else applyScale(Math.min(2, Math.max(0.2, how === "in" ? state.scale * 1.2 : state.scale / 1.2)));
  }

  // --- Search ------------------------------------------------------------------------------------------------------

  // Marks the shown teams whose name holds the typed text; the stage then fades the rest.
  function mark() {
    stage.classList.toggle("is-searching", state.query !== "");
    Object.keys(boxes).forEach(function (id) {
      var item = byId[id];
      boxes[id].classList.toggle("is-match", state.query !== "" && item.name.toLowerCase().indexOf(state.query) !== -1);
    });
  }

  // Unfolds the main-tree path to every team whose name holds the text, then draws again.
  function search(text) {
    state.query = text.trim().toLowerCase();
    if (state.query !== "") {
      items.forEach(function (item) {
        if (tree.depth[item.id] === undefined || item.name.toLowerCase().indexOf(state.query) === -1) return;
        var seen = {}, up = item.main;
        while (up !== null && up !== undefined && !seen[up] && byId[up]) {
          seen[up] = true;
          delete state.folded[up];
          up = byId[up].main;
        }
      });
    }
    render();
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
    state.fit = true;
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

  each(layer.querySelectorAll("[data-zoom]"), function (button) {
    button.addEventListener("click", function () { zoom(button.getAttribute("data-zoom")); });
  });

  // Fold all folds every team below the top level that has teams below it, so the top two levels stay; Unfold all
  // opens everything.
  foldAll.addEventListener("click", function () {
    if (anyFolded()) {
      state.folded = {};
    } else {
      items.forEach(function (item) {
        if (tree.depth[item.id] >= 1 && tree.count[item.id]) state.folded[item.id] = true;
      });
    }
    render();
  });

  find.addEventListener("input", function () { search(find.value); });

  window.addEventListener("resize", function () { if (!layer.hidden && state.fit) fit(); });

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
