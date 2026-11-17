// Entries: the quick-add form names the week a date counts towards, or says the date is after today.
// Without JavaScript the form still records, and the server refuses the same dates.
// (Delete asks in the row itself through tracker.js's data-inline-confirm.)
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
    var today = parse(input.max);

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
      if (today && d > today) {
        hint.textContent = "The date cannot be after today";
        hint.classList.add("tone-danger");
      } else if (ending < first || ending > last) {
        hint.textContent = "Outside this tracker's weeks";
        hint.classList.add("tone-danger");
      } else {
        hint.textContent = "Counts towards week ending " + label(ending);
      }
    };
    input.addEventListener("input", showWeek);
    showWeek();
  }
})();
