// Risk form: a live preview of the risk as the report's Top risks table shows it. The form saves normally without
// JavaScript; the preview then shows the values as they were when the page loaded.
(function () {
  "use strict";

  var form = document.querySelector("[data-risk-form]");
  if (!form) return;

  var MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  var TONES = { Red: "red", Amber: "amber", Green: "green" };
  var item = form.querySelector("[data-preview]");
  var dot = item.querySelector(".rag-dot");
  var openList = form.querySelector("[data-preview-open]");
  var closedNote = form.querySelector("[data-preview-closed]");
  var fallbackRef = form.dataset.nextRef || form.querySelector("[data-preview-ref]").textContent;

  function value(name) {
    var field = form.elements[name];
    if (!field) return "";
    if (field instanceof RadioNodeList) return field.value;
    return field.value.trim();
  }

  function formatDate(text) {
    var match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(text);
    return match ? match[3] + " " + MONTHS[Number(match[2]) - 1] + " " + match[1] : "";
  }

  function setTone(el, prefix, tone) {
    ["red", "amber", "green", "none"].forEach(function (t) { el.classList.remove(prefix + t); });
    el.classList.add(prefix + tone);
  }

  function refresh() {
    var rag = value("rag");
    var status = value("status") || "Open";
    var closed = status === "Closed";
    openList.hidden = closed;
    closedNote.hidden = !closed;

    var tone = TONES[rag] || "none";
    setTone(item, "top-risk-", tone);
    setTone(dot, "rag-dot-", tone);
    item.querySelector("[data-preview-rag]").textContent = rag || "Not set";
    item.querySelector("[data-preview-ref]").textContent = value("ref") || fallbackRef;
    item.querySelector("[data-preview-desc]").textContent = value("description") || "–";

    var group = form.elements.group_id;
    var parts = [value("owner_role") || "–"];
    if (group.value) parts.push(group.options[group.selectedIndex].text);
    parts.push(status);
    var target = formatDate(value("target_date"));
    parts.push(target ? "target " + target : "no target date");
    item.querySelector("[data-preview-meta]").textContent = parts.join(" · ");
  }

  form.addEventListener("input", refresh);
  form.addEventListener("change", refresh);
  refresh();
})();
