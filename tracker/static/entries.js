// Entries: the quick-add form names the week a date counts towards, and delete asks for confirmation in the row
// itself. Without JavaScript the form still records and delete falls back to the data-confirm dialog.
(function () {
  "use strict";

  var MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

  function parse(value) {
    var match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value || "");
    return match ? new Date(Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3]))) : null;
  }

  function label(d) {
    return String(d.getUTCDate()).padStart(2, "0") + " " + MONTHS[d.getUTCMonth()] + " " + d.getUTCFullYear();
  }

  var form = document.querySelector("[data-quick-add]");
  if (form) {
    var input = form.querySelector("input[name=entry_date]");
    var hint = form.querySelector("[data-week-hint]");
    var weekday = Number(form.dataset.weekday);
    var first = parse(form.dataset.first);
    var last = parse(form.dataset.last);

    var showWeek = function () {
      var d = parse(input.value);
      hint.classList.remove("tone-danger");
      if (!d) {
        hint.textContent = "";
        return;
      }
      // Python numbers weekdays from Monday (0); getUTCDay counts from Sunday (0).
      var ahead = (weekday - (d.getUTCDay() + 6) % 7 + 7) % 7;
      var ending = new Date(d.getTime() + ahead * 864e5);
      if (ending < first || ending > last) {
        hint.textContent = "Outside this tracker's weeks";
        hint.classList.add("tone-danger");
      } else {
        hint.textContent = "Counts towards week ending " + label(ending);
      }
    };
    input.addEventListener("input", showWeek);
    showWeek();
  }

  function reset(box) {
    box.hidden = true;
    box.parentNode.querySelector("[data-ask]").hidden = false;
  }

  document.querySelectorAll("form[data-inline-confirm]").forEach(function (del) {
    var ask = del.querySelector("[data-ask]");
    var box = del.querySelector("[data-confirm-box]");
    ask.addEventListener("click", function (event) {
      event.preventDefault();
      document.querySelectorAll("[data-confirm-box]:not([hidden])").forEach(reset);
      ask.hidden = true;
      box.hidden = false;
      box.querySelector("[data-confirm-no]").focus();
    });
    // form.submit() skips the submit event, so the data-confirm dialog does not ask a second time.
    box.querySelector("[data-confirm-yes]").addEventListener("click", function () { del.submit(); });
    box.querySelector("[data-confirm-no]").addEventListener("click", function () {
      reset(box);
      ask.focus();
    });
    box.addEventListener("keydown", function (event) {
      if (event.key === "Escape") {
        reset(box);
        ask.focus();
      }
    });
  });
})();
