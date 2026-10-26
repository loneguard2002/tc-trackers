// Sortable, filterable tables (Tabulator). Any <table data-table> is rebuilt from its own rows, so the server-drawn
// table remains the page's content without JavaScript and in the PDF.
//   <table data-table data-table-page-size="50" data-table-export="entries.csv">
//   <th data-filter="text|select|none" data-sort="string|number|date|none" data-html data-width="120"
//       data-min-width="200" data-frozen>
// Plain cells are read as text and shown escaped; data-html cells (forms, links) keep their markup and are never
// sorted, filtered or exported. data-width fixes a column's width in pixels and the others share the rest, none
// narrower than its data-min-width; a narrow screen scrolls the table sideways. A data-frozen last column (row
// actions) stays in view while it scrolls.
(function () {
  "use strict";

  var MONTHS = { Jan: 0, Feb: 1, Mar: 2, Apr: 3, May: 4, Jun: 5, Jul: 6, Aug: 7, Sep: 8, Oct: 9, Nov: 10, Dec: 11 };

  // Dates as fmt_date prints them ("06 Oct 2026"); the dash and empty cells sort lowest.
  function dateValue(text) {
    var match = /^(\d{1,2}) ([A-Z][a-z]{2}) (\d{4})$/.exec(String(text || "").trim());
    if (!match || !(match[2] in MONTHS)) return -Infinity;
    return Date.UTC(Number(match[3]), MONTHS[match[2]], Number(match[1]));
  }

  function dateSorter(a, b) {
    return dateValue(a) - dateValue(b);
  }

  function numberSorter(a, b) {
    var x = parseFloat(String(a).replace(/[^0-9.\-]/g, ""));
    var y = parseFloat(String(b).replace(/[^0-9.\-]/g, ""));
    return (isNaN(x) ? -Infinity : x) - (isNaN(y) ? -Infinity : y);
  }

  // Tabulator renders list filter labels and column titles as HTML, so text taken from the page is escaped first.
  function escapeHtml(text) {
    return String(text).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }

  function columnFor(th, index) {
    var html = th.hasAttribute("data-html");
    var filter = th.getAttribute("data-filter") || "text";
    var sort = th.getAttribute("data-sort") || "string";
    // The title stays raw for the CSV header; on screen it is escaped, as Tabulator renders titles as HTML.
    // Tabulator swaps an empty title for "&nbsp;", so the formatter escapes the page's own text instead.
    var title = th.textContent.trim();
    var column = {
      title: title,
      field: "c" + index,
      vertAlign: "middle",
      titleFormatter: function () { return escapeHtml(title); }
    };
    var width = parseInt(th.getAttribute("data-width") || "", 10);
    var minWidth = parseInt(th.getAttribute("data-min-width") || "", 10);
    if (width > 0) column.width = width;
    if (minWidth > 0) column.minWidth = minWidth;
    if (th.hasAttribute("data-frozen")) column.frozen = true;
    if (html) {
      column.formatter = "html";
      column.headerSort = false;
      column.headerFilter = false;
      column.download = false;
      return column;
    }
    if (filter === "select") {
      column.headerFilter = "list";
      column.headerFilterParams = {
        valuesLookup: true,
        clearable: true,
        itemFormatter: function (label) { return escapeHtml(label); }
      };
    } else if (filter === "text") {
      column.headerFilter = "input";
    }
    if (sort === "none") {
      column.headerSort = false;
    } else if (sort === "number") {
      column.sorter = numberSorter;
    } else if (sort === "date") {
      column.sorter = dateSorter;
    }
    return column;
  }

  function enhance(table) {
    if (table.querySelector("tbody td[colspan]")) return;
    var headers = Array.prototype.slice.call(table.querySelectorAll("thead th"));
    var columns = headers.map(columnFor);
    var data = Array.prototype.map.call(table.querySelectorAll("tbody tr"), function (tr) {
      var row = {};
      Array.prototype.forEach.call(tr.children, function (cell, index) {
        if (index < columns.length) {
          row["c" + index] = columns[index].formatter === "html" ? cell.innerHTML : cell.textContent.trim();
        }
      });
      return row;
    });

    var host = document.createElement("div");
    host.className = "data-table";
    table.parentNode.replaceChild(host, table);

    var options = { data: data, columns: columns, layout: "fitColumns", placeholder: "No rows match." };
    var pageSize = parseInt(table.getAttribute("data-table-page-size") || "", 10);
    if (pageSize > 0) {
      options.pagination = true;
      options.paginationSize = pageSize;
    }
    var tabulator = new window.Tabulator(host, options);

    var exportName = table.getAttribute("data-table-export");
    if (exportName) {
      var button = document.createElement("button");
      button.className = "button data-table-export";
      button.type = "button";
      button.textContent = "Download CSV";
      button.addEventListener("click", function () { tabulator.download("csv", exportName); });
      host.parentNode.insertBefore(button, host);
    }
  }

  document.addEventListener("DOMContentLoaded", function () {
    if (!window.Tabulator) return;
    Array.prototype.forEach.call(document.querySelectorAll("table[data-table]"), enhance);
  });
})();
