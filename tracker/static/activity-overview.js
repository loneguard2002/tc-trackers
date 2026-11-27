// Activity › Overview: choosing a day on the heatmap shows it in the strip below, with a link to that day in the log.
// Without JavaScript each square is an ordinary link to the log. Plain ES5 style, no modules.
(function () {
  "use strict";

  var map = document.querySelector("[data-heatmap]");
  var text = document.querySelector("[data-heat-detail]");
  var link = document.querySelector("[data-heat-link]");
  if (!map || !text || !link) return;
  var empty = text.textContent;
  var picked = null;

  function show(day) {
    if (picked) picked.classList.remove("is-picked");
    picked = day;
    if (!day) {
      text.textContent = empty;
      link.hidden = true;
      return;
    }
    day.classList.add("is-picked");
    text.textContent = day.getAttribute("data-detail");
    link.setAttribute("href", day.getAttribute("href"));
    link.hidden = /: no changes/.test(day.getAttribute("data-detail"));
  }

  map.addEventListener("click", function (event) {
    var day = event.target.closest ? event.target.closest(".heat-day") : null;
    if (!day) return;
    event.preventDefault();
    show(day === picked ? null : day);
  });
})();
