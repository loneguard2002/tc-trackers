// The report's location pop-up (new view): an editor clicks a location's status chip to set its status, planned
// completion, ready figure and comment. Without JavaScript, or where a dialog cannot open as a modal, the chip is a
// link to the location's full edit page.
(function () {
  "use strict";

  function each(list, fn) {
    Array.prototype.forEach.call(list, fn);
  }

  document.addEventListener("DOMContentLoaded", function () {
    var dialog = document.getElementById("location-dialog");
    if (!dialog || typeof dialog.showModal !== "function") return;
    var form = dialog.querySelector("form");

    function open(link, data) {
      form.setAttribute("action", data.action);
      dialog.querySelector("[data-location-name]").textContent = data.name;
      dialog.querySelector("[data-location-more]").setAttribute("href", link.getAttribute("href"));
      each(form.querySelectorAll('input[name="rag"]'), function (radio) {
        radio.checked = radio.value === (data.rag || "");
      });
      form.elements.namedItem("planned_completion").value = data.planned_completion || "";
      form.elements.namedItem("ready_not_complete").value = String(data.ready_not_complete || 0);
      form.elements.namedItem("comment").value = data.comment || "";
      dialog.showModal();
      var checked = form.querySelector('input[name="rag"]:checked');
      if (checked) checked.focus();
    }

    each(document.querySelectorAll("a[data-location-edit]"), function (link) {
      link.addEventListener("click", function (event) {
        // A modifier key asks for the full edit page in a new tab or window.
        if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
        var data;
        try {
          data = JSON.parse(link.getAttribute("data-location-edit"));
        } catch (_) {
          return;
        }
        if (!data || !data.action) return;
        event.preventDefault();
        open(link, data);
      });
    });

    // Cancel and the close button; Escape closes a modal dialog by itself, and the browser returns the focus to the chip.
    each(dialog.querySelectorAll("[data-close]"), function (button) {
      button.addEventListener("click", function () { dialog.close(); });
    });
  });
})();
