// Behaviours for the Regions and Locations tables (lists/_table.html). The search box, status buttons, region filter
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
  // leave for its token; the footer counts the rows shown, all rows, and all active rows (whatever is shown, as the
  // total is). A line inside the table's frame says so when no row is shown.
  //
  // A table with a [data-pager-for="<id>"] block is also paged: 25 rows to start (or 50, 100), taken in the order the
  // rows are in after sorting. A change of search, filter or sort returns to page 1. "Shown" is then the rows on
  // the page, and the pager says which of the matching rows they are.
  function setUpTable(table) {
    var id = table.id;
    var body = table.tBodies[0];
    if (!body) return;
    var items = Array.prototype.map.call(body.rows, function (row, index) {
      return { row: row, index: index };
    });
    var search = document.querySelector('[data-search-for="' + id + '"]');
    var input = search ? search.querySelector("[data-search-input]") : null;
    var statusGroup = document.querySelector('[data-status-for="' + id + '"]');
    var buttons = statusGroup ? statusGroup.querySelectorAll("button[data-status]") : [];
    var regionFilter = document.querySelector('select[data-region-filter="' + id + '"]');
    var panel = table.closest(".list-panel");
    var foot = panel ? panel.querySelector(".list-foot") : null;
    // The line sits inside the table's own frame, so that two tables in one panel (the team page's picker) never share one.
    var frame = table.closest(".list-table") || panel;
    var noMatch = frame ? frame.querySelector("[data-no-match]") : null;
    var pager = document.querySelector('[data-pager-for="' + id + '"]');
    var sizeSelect = pager ? pager.querySelector("[data-pager-size]") : null;
    var status = "all";
    var pageNumber = 1;
    var pageSize = 25;

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
      Array.prototype.forEach.call(body.rows, function (row) {
        var rowTokens = tokens(row);
        var found = inSearchAndRegion(row);
        if (found && !row.hasAttribute("data-uncounted")) {  // listed but not counted: a person who is not active
          counts.all += 1;
          rowTokens.forEach(function (token) { counts[token] = (counts[token] || 0) + 1; });
        }
        if (found && (status === "all" || rowTokens.indexOf(status) !== -1)) matching.push(row);
        if (rowTokens.indexOf("active") !== -1) active += 1;
      });
      var pages = Math.max(1, Math.ceil(matching.length / pageSize));
      if (pageNumber > pages) pageNumber = pages;
      var first = pager ? (pageNumber - 1) * pageSize : 0;
      var last = pager ? first + pageSize : matching.length;
      var shown = 0;
      Array.prototype.forEach.call(body.rows, function (row) {
        var index = matching.indexOf(row);
        var show = index !== -1 && index >= first && index < last;
        row.hidden = !show;
        if (show) shown += 1;
      });
      if (noMatch) noMatch.hidden = matching.length !== 0;
      each(buttons, function (button) {
        var count = button.querySelector("[data-count]");
        if (count) count.textContent = String(counts[button.getAttribute("data-status")] || 0);
      });
      if (pager) {
        var range = pager.querySelector("[data-pager-range]");
        var total = pager.querySelector("[data-pager-total]");
        if (range) range.textContent = shown === 0 ? "0" : (first + 1) + "\u2013" + (first + shown);
        if (total) total.textContent = String(matching.length);
        var noun = pager.querySelector("[data-pager-noun]");
        if (noun) {
          var one = noun.getAttribute("data-noun-one");
          noun.textContent = matching.length === 1 && one ? one : noun.getAttribute("data-noun-many");
        }
        var previous = pager.querySelector("[data-pager-prev]");
        var next = pager.querySelector("[data-pager-next]");
        if (previous) previous.disabled = pageNumber <= 1;
        if (next) next.disabled = pageNumber >= pages;
        var numbers = pager.querySelector("[data-pager-pages]");
        if (numbers) showPages(pages, numbers);
      }
      if (!foot) return;
      var parts = { "[data-shown]": shown, "[data-total]": items.length, "[data-active]": active };
      Object.keys(parts).forEach(function (selector) {
        var target = foot.querySelector(selector);
        if (target) target.textContent = String(parts[selector]);
      });
    }

    // A change of search, filter or sort starts again at the first page.
    function restart() {
      pageNumber = 1;
      refresh();
    }

    if (pager) {
      pager.hidden = false;
      var previous = pager.querySelector("[data-pager-prev]");
      var next = pager.querySelector("[data-pager-next]");
      if (sizeSelect) {
        pageSize = Number(sizeSelect.value) || 25;
        sizeSelect.addEventListener("change", function () {
          pageSize = Number(sizeSelect.value) || 25;
          restart();
        });
      }
      if (previous) previous.addEventListener("click", function () { pageNumber -= 1; focusCurrent = true; refresh(); });
      if (next) next.addEventListener("click", function () { pageNumber += 1; focusCurrent = true; refresh(); });
    }

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
    if (foot) foot.setAttribute("aria-live", "polite");

    // A header's sort button orders the rows by its data-sort-<key>: numbers as numbers, text in the reader's
    // language ignoring case; a second click reverses the order. Rows that compare equal keep the server's order.
    // The rows arrive in the order of the column marked data-sort-default, so that column starts "ascending" and its
    // first click reverses it.
    var headers = Array.prototype.filter.call(table.querySelectorAll("thead th"), function (header) {
      return Boolean(header.querySelector("button.sort-button[data-sort]"));
    });
    headers.forEach(function (header) {
      var button = header.querySelector("button.sort-button[data-sort]");
      var label = header.querySelector("[data-sort-label]");
      header.setAttribute("aria-sort", header.hasAttribute("data-sort-default") ? "ascending" : "none");
      button.hidden = false;
      if (label) label.hidden = true;
      button.addEventListener("click", function () {
        var key = "data-sort-" + button.getAttribute("data-sort");
        var direction = header.getAttribute("aria-sort") === "ascending" ? "descending" : "ascending";
        var sign = direction === "ascending" ? 1 : -1;
        var numeric = items.every(function (item) {
          return /^-?\d+(\.\d+)?$/.test(item.row.getAttribute(key) || "");
        });
        var sorted = items.slice().sort(function (a, b) {
          var first = a.row.getAttribute(key) || "";
          var second = b.row.getAttribute(key) || "";
          var order = numeric ? Number(first) - Number(second)
            : first.localeCompare(second, undefined, { sensitivity: "base", numeric: true });
          return order * sign || a.index - b.index;
        });
        headers.forEach(function (other) { other.setAttribute("aria-sort", "none"); });
        header.setAttribute("aria-sort", direction);
        sorted.forEach(function (item) { body.appendChild(item.row); });
        restart();
      });
    });

    refresh();  // applies a region chosen in the address (?region=<id>) and any search the browser kept
  }

  each(document.querySelectorAll(".list-table table[id]"), setUpTable);

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
  each(document.querySelectorAll("a[data-dialog-open]"), function (link) {
    link.addEventListener("click", function (event) {
      if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
      if (link.getAttribute("data-dialog-open") === "add") {
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
