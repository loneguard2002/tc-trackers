// New tracker: choosing a team ticks the region of the team's location (and unticks it again when the team
// changes), until a region box has been changed by
// hand; after that the ticks are left to the user. Without JavaScript nothing is pre-ticked.
(function () {
  "use strict";

  var team = document.getElementById("team_id");
  if (!team || !team.form) return;
  var boxes = team.form.querySelectorAll("input[type='checkbox'][name='region_ids']");
  var touched = false;

  Array.prototype.forEach.call(boxes, function (box) {
    box.addEventListener("change", function () { touched = true; });
  });

  var ticked = null;

  team.addEventListener("change", function () {
    if (touched) return;
    if (ticked) ticked.checked = false;
    ticked = null;
    var option = team.options[team.selectedIndex];
    var region = option ? option.getAttribute("data-region") : null;
    if (!region) return;
    Array.prototype.forEach.call(boxes, function (box) {
      if (box.value === region) {
        box.checked = true;
        ticked = box;
      }
    });
  });
})();
