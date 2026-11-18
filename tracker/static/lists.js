// Behaviours for the Regions and Locations tables (lists/_table.html), and the sort buttons of any other table marked
// data-sortable (the Users list). The search box, status buttons, region filter
// and sort buttons render with the `hidden` attribute, because they do nothing without JavaScript; this script reveals
// them. Add and Edit open their dialog as a modal instead of following the link to their own page, and a dialog the
// server rendered open (data-reopen) is reopened as a modal. Plain ES5 style, no modules.
(function () {
  "use strict";

  function each(list, fn) {
    Array.prototype.forEach.call(list, fn);
  }

  // --- Tables -------------------------------------------------------------------------------------------------------

  // Each table's rows carry data-search (lower-case text), data-status (one token such as "active" or "retired", or
  // several separated by spaces, as in "direct inherited"), data-region (Locations) and data-sort-<key>. A row shows
  // when it contains the typed text (a plain substring, never a pattern), is in the chosen region, and holds the
  // chosen status token ("all" matches every row). Each status button counts the rows the search and region filter
  // leave for its token. A line inside the table's frame says so when no row is shown.
  //
  // A table with a [data-pager-for="<id>"] block is also paged: 25 rows to start (or 50, 100), taken in the order the
  // rows are in after sorting. A change of search, filter or sort returns to page 1. The footer's [data-pager-count]
  // reads "Showing 1\u201325 of 30 locations \u00b7 28 active" when the matches fill more than one page and "Showing 3 of 30
  // locations \u00b7 28 active" otherwise (the active part only on a table that says so, and counting every row with the
  // "active" status, whatever the search and filters); its [data-pager-controls] show only while more than 25 rows
  // match.
  //
  // The view is kept in the address, so that a reload, a shared link and the Back button's neighbours show the same
  // rows: q (the search box), filter (the status button), region (the region select), sort ("name" ascending,
  // "-name" descending), page and size, each written with history.replaceState and only when it is not the default.
  // A table marked data-state-prefix="people-" reads and writes people-q, people-filter and so on, so that two tables
  // on one page never meet. A table writes only the keys of the controls it has (the Users table's own search is a
  // server form, whose keys are left alone); every other key and the hash stay as they are. A value that does not
  // fit (an unknown filter or sort, a size other than 25, 50 or 100, a page that is not a positive whole number or
  // lies beyond the last) is ignored and is gone from the address after the next change.
  //
  // window.trackerLists.setUp(table) sets up one table, for a table put on the page after load (the side panel's
  // holders); a table already set up is left alone, so a second call does nothing.
  //
  // A row marked data-uncounted is listed but left out of every count: the status buttons, and the footer's "of N"
  // and its matching figure, so that "All N" and "Showing N of N" agree.
  //
  // A table whose rows the server orders and moves (the Locations tab's Up and Down) marks those buttons
  // data-hide-when-reordered: lists.js hides them while a sort, a search or a status button other than the first is in
  // use, and shows the element marked data-show-when-reordered="<table id>" (the note saying why) in their place. The
  // table can also carry data-clear-sort, which makes Clear filters clear the sort as well and show while one is in use.
  function setUpTable(table) {
    var id = table.id;
    var body = table.tBodies[0];
    if (!body || table.hasAttribute("data-table-ready")) return;
    table.setAttribute("data-table-ready", "");
    var items = Array.prototype.map.call(body.rows, function (row, index) {
      return { row: row, index: index };
    });
    var search = document.querySelector('[data-search-for="' + id + '"]');
    var input = search ? search.querySelector("[data-search-input]") : null;
    var statusGroup = document.querySelector('[data-status-for="' + id + '"]');
    var buttons = statusGroup ? statusGroup.querySelectorAll("button[data-status]") : [];
    var regionFilter = document.querySelector('select[data-region-filter="' + id + '"]');
    var panel = table.closest(".list-panel");
    // The line sits inside the table's own frame, so that two tables in one panel (the team page's picker) never share one.
    var frame = table.closest(".list-table") || panel;
    var noMatch = frame ? frame.querySelector("[data-no-match]") : null;
    var pager = document.querySelector('[data-pager-for="' + id + '"]');
    var sizeSelect = pager ? pager.querySelector("[data-pager-size]") : null;
    var countText = pager ? pager.querySelector("[data-pager-count]") : null;
    var controls = pager ? pager.querySelector("[data-pager-controls]") : null;
    // The first status button is the default view ("All", or "All open"); a table without buttons matches every row.
    var defaultStatus = buttons.length ? buttons[0].getAttribute("data-status") : "all";
    var status = defaultStatus;
    var pageNumber = 1;
    var pageSize = 25;
    var prefix = table.getAttribute("data-state-prefix") || "";
    var clearsSort = table.hasAttribute("data-clear-sort");
    var settingUp = true;  // until the first refresh, so that a page from the address is checked, not clamped

    each(buttons, function (button) {
      if (button.getAttribute("aria-pressed") === "true") status = button.getAttribute("data-status");
    });

    function tokens(row) {
      return (row.getAttribute("data-status") || "").split(/\s+/).filter(Boolean);
    }

    function inSearchAndRegion(row) {
      var text = input ? input.value.trim().toLowerCase() : "";
      if (text !== "" && (row.getAttribute("data-search") || "").indexOf(text) === -1) return false;
      return !(regionFilter && regionFilter.value !== "" && row.getAttribute("data-region") !== regionFilter.value);
    }

    // A rebuilt page button loses the focus the reader had in the pager, so the current page's button takes it.
    var focusCurrent = false;

    function pageButton(label, number, current) {
      var button = document.createElement("button");
      button.type = "button";
      button.className = "pager-button";
      button.textContent = label;
      button.setAttribute("aria-label", "Page " + label);
      if (current) button.setAttribute("aria-current", "page");
      button.addEventListener("click", function () {
        pageNumber = number;
        focusCurrent = true;
        refresh();
        writeState();
      });
      return button;
    }

    // The numbers of the pages, the first and last always and those beside the current one; a gap shows as "...".
    function showPages(pages, target) {
      while (target.firstChild) target.removeChild(target.firstChild);
      var last = 0;
      for (var number = 1; number <= pages; number += 1) {
        if (number !== 1 && number !== pages && Math.abs(number - pageNumber) > 1) continue;
        if (last && number - last > 1) {
          var gap = document.createElement("span");
          gap.className = "pager-gap";
          gap.textContent = "\u2026";
          target.appendChild(gap);
        }
        target.appendChild(pageButton(String(number), number, number === pageNumber));
        last = number;
      }
      if (focusCurrent) {
        var current = target.querySelector('[aria-current="page"]');
        if (current) current.focus();
        focusCurrent = false;
      }
    }

    function refresh() {
      var counts = { all: 0 };
      var matching = [];
      var active = 0;
      var countedMatching = 0;
      var countedTotal = 0;
      Array.prototype.forEach.call(body.rows, function (row) {
        var rowTokens = tokens(row);
        var found = inSearchAndRegion(row);
        var counted = !row.hasAttribute("data-uncounted");  // listed but not counted: a person who is not active
        if (counted) countedTotal += 1;
        if (found && counted) {
          counts.all += 1;
          rowTokens.forEach(function (token) { counts[token] = (counts[token] || 0) + 1; });
        }
        row.matchIndex = -1;  // its place among the matching rows, for the page it falls on
        if (found && (status === "all" || rowTokens.indexOf(status) !== -1)) {
          row.matchIndex = matching.length;
          matching.push(row);
          if (counted) countedMatching += 1;
        }
        if (rowTokens.indexOf("active") !== -1) active += 1;
      });
      var pages = Math.max(1, Math.ceil(matching.length / pageSize));
      if (pageNumber > pages) pageNumber = settingUp ? 1 : pages;
      var first = pager ? (pageNumber - 1) * pageSize : 0;
      var last = pager ? first + pageSize : matching.length;
      var shown = 0;
      Array.prototype.forEach.call(body.rows, function (row) {
        var index = row.matchIndex;
        var show = index !== -1 && index >= first && index < last;
        row.hidden = !show;
        if (show) shown += 1;
      });
      if (noMatch) noMatch.hidden = matching.length !== 0;
      var inUse = filtersInUse();
      each(clearButtons, function (button) { button.hidden = !inUse; });
      each(buttons, function (button) {
        var count = button.querySelector("[data-count]");
        if (count) count.textContent = String(counts[button.getAttribute("data-status")] || 0);
      });
      showMoveButtons(inUse || sortValue() !== "");
      if (countText) {
        var many = matching.length > pageSize;
        var noun = countText.getAttribute(countedTotal === 1 ? "data-noun-one" : "data-noun-many");
        var copy = "Showing " + (many ? (first + 1) + "\u2013" + (first + shown) + " of " + matching.length
          : countedMatching + " of " + countedTotal) + " " + (many ? countText.getAttribute("data-noun-many") : noun);
        if (countText.hasAttribute("data-has-active")) copy += " \u00b7 " + active + " active";
        countText.textContent = copy;
        if (controls) controls.hidden = matching.length <= 25;
      }
      if (pager) {
        var previous = pager.querySelector("[data-pager-prev]");
        var next = pager.querySelector("[data-pager-next]");
        if (previous) previous.disabled = pageNumber <= 1;
        if (next) next.disabled = pageNumber >= pages;
        var numbers = pager.querySelector("[data-pager-pages]");
        if (numbers) showPages(pages, numbers);
      }
      keepWideTableReachable();
    }

    // The Clear filters buttons (beside the chips and in the no-match line) show while a search, a status button other
    // than the first (All) or a region is in use.
    var clearButtons = document.querySelectorAll('[data-clear-for="' + id + '"]');

    function filtersInUse() {
      return Boolean((input && input.value.trim() !== "") || (regionFilter && regionFilter.value !== "")
        || status !== defaultStatus || (clearsSort && sortValue() !== ""));
    }

    // The buttons that move a row in the server's own order make sense only in that order.
    function showMoveButtons(reordered) {
      each(table.querySelectorAll("[data-hide-when-reordered]"), function (element) { element.hidden = reordered; });
      each(document.querySelectorAll('[data-show-when-reordered="' + id + '"]'), function (element) {
        element.hidden = !reordered;
      });
    }

    // A change of search, filter, region, sort or size starts again at the first page.
    function restart() {
      pageNumber = 1;
      refresh();
      writeState();
    }

    if (pager) {
      var previous = pager.querySelector("[data-pager-prev]");
      var next = pager.querySelector("[data-pager-next]");
      if (sizeSelect) {
        pageSize = Number(sizeSelect.value) || 25;
        sizeSelect.addEventListener("change", function () {
          pageSize = Number(sizeSelect.value) || 25;
          restart();
        });
      }
      if (previous) previous.addEventListener("click", function () { pageNumber -= 1; focusCurrent = true; refresh(); writeState(); });
      if (next) next.addEventListener("click", function () { pageNumber += 1; focusCurrent = true; refresh(); writeState(); });
    }

    // Clear filters empties the search, picks the first status button (All) and the first region (All regions), and
    // starts again at page 1. The sort and the rows per page stay. The button then hides, so the focus moves to the
    // search box (when the table has one) rather than staying on it.
    each(clearButtons, function (button) {
      button.addEventListener("click", function () {
        if (input) input.value = "";
        if (regionFilter) regionFilter.value = "";
        if (clearsSort) resetSort();
        if (buttons.length) {
          status = buttons[0].getAttribute("data-status");
          each(buttons, function (other) { other.setAttribute("aria-pressed", other === buttons[0] ? "true" : "false"); });
        }
        restart();
        if (input) input.focus();
      });
    });

    if (search && input) {
      search.hidden = false;
      input.addEventListener("input", restart);
    }
    if (regionFilter) {
      regionFilter.hidden = false;
      regionFilter.addEventListener("change", restart);
    }
    if (statusGroup) {
      statusGroup.hidden = false;
      each(buttons, function (button) {
        button.addEventListener("click", function () {
          status = button.getAttribute("data-status");
          each(buttons, function (other) { other.setAttribute("aria-pressed", other === button ? "true" : "false"); });
          restart();
        });
      });
    }

    // A header's sort button orders the rows by its data-sort-<key>, read as the heading's data-sort-type says: "text"
    // (the default) in the reader's language ignoring case, with numbers inside the text in natural order (LD5 before
    // LD10); "number"; or "date" as ISO YYYY-MM-DD, which compares as text. A second click reverses the order. Rows
    // with no value come last in both directions, and rows that compare equal keep the server's order. The rows
    // arrive in the order of the column marked data-sort-default, so that column starts "ascending" and its first
    // click reverses it.
    function compareValues(type, first, second) {
      if (type === "number") return Number(first) - Number(second);
      if (type === "date") return first < second ? -1 : first > second ? 1 : 0;
      return first.localeCompare(second, undefined, { sensitivity: "base", numeric: true });
    }

    // On a phone a table marked card-rows shows each row as a card, and CSS prints a cell's data-label before its
    // value. Cells the server did not label take their column heading's visible text (the sort label when the heading
    // has one); a column whose heading shows no text (Actions, Remove, Choose) stays unlabelled.
    // A cell with nothing to see (only screen-reader text, such as "Not an administrator") gets no label: a card must not
    // print "Admin" with nothing after it.
    function isBlank(cell) {
      if (cell.querySelector("img, svg, input, select, textarea, button, a")) return false;
      var copy = cell.cloneNode(true);
      each(copy.querySelectorAll(".sr-only"), function (hidden) { hidden.parentNode.removeChild(hidden); });
      return copy.textContent.trim() === "";
    }

    (function labelCells() {
      var head = table.tHead && table.tHead.rows[0];
      if (!head) return;
      var labels = Array.prototype.map.call(head.cells, function (cell) {
        var sortLabel = cell.querySelector("[data-sort-label]");
        if (sortLabel) return sortLabel.textContent.trim();
        var copy = cell.cloneNode(true);
        each(copy.querySelectorAll(".sr-only"), function (hidden) { hidden.parentNode.removeChild(hidden); });
        return copy.textContent.replace(/\s+/g, " ").trim();
      });
      each(body.rows, function (row) {
        each(row.cells, function (cell, position) {
          if (labels[position] && !cell.hasAttribute("data-label") && !isBlank(cell)) cell.setAttribute("data-label", labels[position]);
        });
      });
    })();

    // The table's wrapper clips rather than scrolls above 720px, so that the headings can stick. A table too wide for
    // its wrapper (a narrow window) would then lose its last columns, so the wrapper is marked is-wide and CSS lets it
    // scroll sideways again; its headings then scroll with the page.
    var wrapper = table.closest(".section-table");

    function keepWideTableReachable() {
      if (!wrapper) return;
      wrapper.classList.remove("is-wide");
      if (wrapper.scrollWidth > wrapper.clientWidth + 1) wrapper.classList.add("is-wide");
    }
    window.addEventListener("resize", keepWideTableReachable);
    window.addEventListener("load", keepWideTableReachable);  // the flags and fonts have arrived
    // A tab's table is measured as it is first shown; a hidden table has no width.
    if (wrapper && window.ResizeObserver) new window.ResizeObserver(keepWideTableReachable).observe(wrapper);

    var headers = Array.prototype.filter.call(table.querySelectorAll("thead th"), function (header) {
      return Boolean(header.querySelector("button.sort-button[data-sort]"));
    });
    headers.forEach(function (header) {
      var button = header.querySelector("button.sort-button[data-sort]");
      var label = header.querySelector("[data-sort-label]");
      header.setAttribute("aria-sort", header.hasAttribute("data-sort-default") ? "ascending" : "none");
      button.hidden = false;
      if (label) label.hidden = true;
      header.sortBy = function (direction) {
        var key = "data-sort-" + button.getAttribute("data-sort");
        var type = header.getAttribute("data-sort-type") || "text";
        var sign = direction === "ascending" ? 1 : -1;
        // A value that is empty, or not a number in a number column, counts as empty.
        function value(item) {
          var text = (item.row.getAttribute(key) || "").trim();
          return type === "number" && isNaN(Number(text)) ? "" : text;
        }
        var sorted = items.slice().sort(function (a, b) {
          var first = value(a);
          var second = value(b);
          if (first === "" || second === "") {
            if (first !== second) return first === "" ? 1 : -1;
            return a.index - b.index;
          }
          return compareValues(type, first, second) * sign || a.index - b.index;
        });
        headers.forEach(function (other) { other.setAttribute("aria-sort", "none"); });
        header.setAttribute("aria-sort", direction);
        sorted.forEach(function (item) { body.appendChild(item.row); });
      };
      button.addEventListener("click", function () {
        header.sortBy(header.getAttribute("aria-sort") === "ascending" ? "descending" : "ascending");
        restart();
      });
    });

    // Back to the server's order: the rows as they arrived, and the column marked data-sort-default (if any) ascending.
    function resetSort() {
      headers.forEach(function (header) {
        header.setAttribute("aria-sort", header.hasAttribute("data-sort-default") ? "ascending" : "none");
      });
      items.forEach(function (item) { body.appendChild(item.row); });
    }

    // --- The view in the address ---
    function key(name) {
      return prefix + name;
    }

    function headerFor(name) {
      return headers.filter(function (header) {
        return header.querySelector("button.sort-button[data-sort]").getAttribute("data-sort") === name;
      })[0];
    }

    // The sorted heading as an address value, or "" while the rows are in the server's order (or in the order of the
    // column marked data-sort-default, which is where they start).
    function sortValue() {
      var found = headers.filter(function (header) { return header.getAttribute("aria-sort") !== "none"; })[0];
      if (!found) return "";
      var descending = found.getAttribute("aria-sort") === "descending";
      if (!descending && found.hasAttribute("data-sort-default")) return "";
      return (descending ? "-" : "") + found.querySelector("button.sort-button[data-sort]").getAttribute("data-sort");
    }

    function readState() {
      var params = new URLSearchParams(window.location.search);
      var text = params.get(key("q"));
      if (input && text) input.value = text;
      var wanted = params.get(key("filter"));
      if (wanted) {
        var chosen = Array.prototype.filter.call(buttons, function (button) {
          return button.getAttribute("data-status") === wanted;
        })[0];
        if (chosen) {
          status = wanted;
          each(buttons, function (other) { other.setAttribute("aria-pressed", other === chosen ? "true" : "false"); });
        }
      }
      var order = params.get(key("sort")) || "";
      var descending = order.charAt(0) === "-";
      var header = headerFor(descending ? order.slice(1) : order);
      // Ascending on the column the rows already arrive in is the starting order, so there is nothing to apply.
      if (header && (descending || !header.hasAttribute("data-sort-default"))) {
        header.sortBy(descending ? "descending" : "ascending");
      }
      var size = params.get(key("size"));
      if (sizeSelect && (size === "25" || size === "50" || size === "100")) {
        pageSize = Number(size);
        sizeSelect.value = size;
      }
      var number = params.get(key("page"));
      if (pager && /^[1-9][0-9]{0,8}$/.test(number || "")) pageNumber = Number(number);
    }

    // Rebuilds this table's keys in the address from the state, leaving every other key and the hash as they are.
    function writeState() {
      var params = new URLSearchParams(window.location.search);
      function put(name, value, isDefault) {
        if (isDefault) params.delete(key(name));
        else params.set(key(name), value);
      }
      if (input) put("q", input.value.trim(), input.value.trim() === "");
      if (statusGroup) put("filter", status, status === defaultStatus);
      if (regionFilter) put("region", regionFilter.value, regionFilter.value === "");
      if (headers.length) put("sort", sortValue(), sortValue() === "");
      if (sizeSelect) put("size", String(pageSize), pageSize === 25);
      if (pager) put("page", String(pageNumber), pageNumber === 1);
      var query = params.toString();
      keepViewInForms(query ? "?" + query : "", params);
      try {
        window.history.replaceState(window.history.state, "",
          window.location.pathname + (query ? "?" + query : "") + window.location.hash);
      } catch (error) { /* an address that cannot be rewritten leaves the view as it is */ }
    }

    // A row action or the Edit dialog posts the view (the address's query) with it, so that the server sends the reader
    // back to the same search, filters, sort and page. The server keeps only the keys the list understands. The Users
    // filter form and its Clear filters link (data-keeps-sort) carry the sort and the rows per page, which the form's
    // own fields do not hold. Dialogs marked data-keeps-view belong to the table that has no state prefix.
    function keepViewInForms(query, params) {
      var forms = Array.prototype.slice.call(body.querySelectorAll("form"));
      if (!prefix) {
        each(document.querySelectorAll("dialog[data-keeps-view] form"), function (form) { forms.push(form); });
      }
      forms.forEach(function (form) {
        var field = form.querySelector('input[type="hidden"][name="view"]');
        if (!field) {
          field = document.createElement("input");
          field.type = "hidden";
          field.name = "view";
          form.appendChild(field);
        }
        field.value = query;
      });
      if (prefix) return;
      each(document.querySelectorAll("form[data-keeps-sort]"), function (form) {
        ["sort", "size"].forEach(function (name) {
          var field = form.querySelector('input[type="hidden"][name="' + name + '"]');
          if (!params.get(name)) {
            if (field) field.parentNode.removeChild(field);
            return;
          }
          if (!field) {
            field = document.createElement("input");
            field.type = "hidden";
            field.name = name;
            form.appendChild(field);
          }
          field.value = params.get(name);
        });
      });
      each(document.querySelectorAll("a[data-keeps-sort]"), function (link) {
        var kept = new URLSearchParams();
        ["sort", "size"].forEach(function (name) { if (params.get(name)) kept.set(name, params.get(name)); });
        var text = kept.toString();
        link.setAttribute("href", window.location.pathname + (text ? "?" + text : ""));
      });
    }

    // A row named by the address's hash (#location-12, where a row action sent the reader) is brought onto the page
    // shown, when the search and filters leave it in the table. Otherwise the view stays as it is. Returns the row
    // when the page changed, to scroll to.
    function revealHashRow() {
      var target = null;
      try {
        target = document.getElementById(decodeURIComponent(window.location.hash.replace(/^#/, "")));
      } catch (error) { /* a hash that is not a valid address component names no row */ }
      if (!target || target.parentNode !== body || !pager) return null;
      var position = 0;
      var found = Array.prototype.some.call(body.rows, function (row) {
        if (!inSearchAndRegion(row) || !(status === "all" || tokens(row).indexOf(status) !== -1)) return false;
        if (row === target) return true;
        position += 1;
        return false;
      });
      if (!found) return null;
      var wanted = Math.floor(position / pageSize) + 1;
      if (wanted === pageNumber) return null;
      pageNumber = wanted;
      return target;
    }

    readState();
    var moved = revealHashRow();
    refresh();  // applies a region chosen in the address (?region=<id>) and any search the browser kept
    settingUp = false;
    if (moved) {
      writeState();
      moved.scrollIntoView();
    } else {
      keepViewInForms(window.location.search, new URLSearchParams(window.location.search));
    }
  }

  each(document.querySelectorAll(".list-table table[id], table[data-sortable][id]"), setUpTable);
  window.trackerLists = { setUp: setUpTable };

  // --- Dialogs ------------------------------------------------------------------------------------------------------

  function canBeModal(dialog) {
    return Boolean(dialog) && typeof dialog.showModal === "function";
  }

  // The first field with an error, or else the first field.
  function firstField(dialog) {
    return dialog.querySelector('.list-dialog-body [aria-invalid="true"]')
      || dialog.querySelector(".list-dialog-body input:not([type=hidden]), .list-dialog-body select");
  }

  function showModal(dialog) {
    if (dialog.open) dialog.close();
    dialog.showModal();
    var field = firstField(dialog);
    if (field) field.focus();
  }

  // Remove the errors an earlier submission left: the list at the top, each field's message, the red borders, and
  // the references to the messages from aria-describedby. A field's help, hidden while its error said the same, is
  // shown again and described by once more.
  function clearErrors(dialog) {
    var gone = [];
    each(dialog.querySelectorAll(".list-dialog-body > .form-alert, .field-error"), function (element) {
      if (element.id) gone.push(element.id);
      element.parentNode.removeChild(element);
    });
    each(dialog.querySelectorAll(".field.has-error"), function (field) { field.classList.remove("has-error"); });
    each(dialog.querySelectorAll("[aria-invalid]"), function (control) {
      control.removeAttribute("aria-invalid");
      var kept = (control.getAttribute("aria-describedby") || "").split(" ").filter(function (ref) {
        return ref !== "" && gone.indexOf(ref) === -1;
      });
      var field = control.closest(".field");
      var help = field && control.id ? field.querySelector('.field-help[id="' + control.id + '-help"]') : null;
      if (help) {
        help.hidden = false;
        if (kept.indexOf(help.id) === -1) kept.unshift(help.id);
      }
      if (kept.length) {
        control.setAttribute("aria-describedby", kept.join(" "));
      } else {
        control.removeAttribute("aria-describedby");
      }
    });
  }

  // The flag beside a country list shows the chosen country's flag, and nothing for the prompt.
  function showFlag(select) {
    var flag = select.parentNode.querySelector("img[data-flag-preview]");
    if (!flag) return;
    if (select.value) {
      flag.src = (flag.getAttribute("data-flag-base") || "") + select.value.toLowerCase() + ".svg";
      flag.hidden = false;
    } else {
      flag.removeAttribute("src");
      flag.hidden = true;
    }
  }

  each(document.querySelectorAll("select[data-country-select]"), function (select) {
    select.addEventListener("change", function () { showFlag(select); });
  });

  function showFlags(dialog) {
    each(dialog.querySelectorAll("select[data-country-select]"), showFlag);
  }

  function openAdd(dialog) {
    clearErrors(dialog);
    var fields = dialog.querySelectorAll(".list-dialog-body input:not([type=hidden]), .list-dialog-body select");
    each(fields, function (field) { field.value = ""; });
    showFlags(dialog);
    showModal(dialog);
  }

  // Fill the Edit dialog from the row's data-edit: the fields, the title, where the form saves (form.action itself is
  // the hidden input named "action", so the attribute is set), and the note of how many teams move with a location.
  // A retired region is offered only to its own locations.
  function openEdit(dialog, data) {
    var form = dialog.querySelector("form");
    form.setAttribute("action", data.action);
    clearErrors(dialog);
    var region = form.elements.namedItem("region_id");
    if (region) {
      each(region.querySelectorAll("option[data-retired]"), function (option) {
        var own = option.value === String(data.region_id);
        option.hidden = !own;
        option.disabled = !own;
      });
    }
    ["region_id", "code", "name", "city", "country_code"].forEach(function (name) {
      var field = form.elements.namedItem(name);
      if (!field || !Object.prototype.hasOwnProperty.call(data, name)) return;
      field.value = data[name] === null ? "" : String(data[name]);
    });
    showFlags(dialog);
    var title = dialog.querySelector("[data-title-prefix]");
    if (title) {
      title.textContent = title.getAttribute("data-title-prefix") + " " + (data.code || data.city || data.name || "");
    }
    var note = dialog.querySelector("[data-team-note]");
    if (note) {
      var teams = Number(data.teams) || 0;
      // Empty while hidden: aria-describedby still reads a hidden element's text.
      note.textContent = teams === 1 ? note.getAttribute("data-note-one")
        : teams > 1 ? note.getAttribute("data-note-many").split("{n}").join(String(teams)) : "";
      note.hidden = teams === 0;
    }
    showModal(dialog);
  }

  function rowData(link) {
    var row = link.closest("tr[data-edit]");
    if (!row) return null;
    try {
      return JSON.parse(row.getAttribute("data-edit"));
    } catch (_) {
      return null;
    }
  }

  var addDialog = document.getElementById("add-dialog");
  var editDialog = document.getElementById("edit-dialog");

  // Add and Edit follow their link to the no-JavaScript page when the dialog cannot open as a modal, when a modifier
  // key asks for a new tab or window, or (Edit) when the row does not say where to save.
  // Any other data-dialog-open names a dialog the server wrote in full, such as a question, opened as it is.
  each(document.querySelectorAll("a[data-dialog-open]"), function (link) {
    link.addEventListener("click", function (event) {
      if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
      var kind = link.getAttribute("data-dialog-open");
      if (kind !== "add" && kind !== "edit") {
        var question = document.getElementById(kind + "-dialog");
        if (!canBeModal(question)) return;
        event.preventDefault();
        showModal(question);
        return;
      }
      if (kind === "add") {
        if (!canBeModal(addDialog)) return;
        event.preventDefault();
        openAdd(addDialog);
        return;
      }
      var data = rowData(link);
      if (!canBeModal(editDialog) || !data || !data.action) return;
      event.preventDefault();
      openEdit(editDialog, data);
    });
  });

  // The close button and Cancel are links back to the table without JavaScript; here they close the dialog in place.
  // Escape closes a modal dialog by itself.
  each(document.querySelectorAll("dialog [data-dialog-close]"), function (control) {
    control.addEventListener("click", function (event) {
      var dialog = control.closest("dialog");
      if (!canBeModal(dialog)) return;
      event.preventDefault();
      dialog.close();
    });
  });

  // A dialog the server rendered open sits at the address its form was sent to (or its own /new or /edit page).
  // Closing it, by Escape, Cancel or the close button, puts back the table's address, so that a reload shows the
  // table rather than the dialog.
  each(document.querySelectorAll("dialog[data-reopen]"), function (dialog) {
    if (!canBeModal(dialog)) return;
    var back = dialog.querySelector("[data-dialog-close][href]");
    dialog.addEventListener("close", function () {
      // showModal() below first closes the dialog the server rendered open; that close event arrives once the
      // dialog is open again as a modal, and is not the reader's.
      if (dialog.open) return;
      if (back && window.history && typeof window.history.replaceState === "function") {
        window.history.replaceState(null, "", back.getAttribute("href"));
      }
    });
    showModal(dialog);
  });
})();
