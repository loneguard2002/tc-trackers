// Weekly inputs: a live preview of the report's status band, a headline length hint, "Use last week's text" and an
// unsaved-changes note. The form saves normally without JavaScript.
(function () {
  "use strict";

  var form = document.querySelector("[data-inputs-form]");
  if (!form) return;

  var TONES = { Red: "red", Amber: "amber", Green: "green" };
  var LONG_HEADLINE = 240;
  var band = form.querySelector("[data-band]");
  var dot = form.querySelector("[data-band-dot]");
  var word = form.querySelector("[data-band-word]");
  var bandHeadline = form.querySelector("[data-band-headline]");
  var bandDecisions = form.querySelector("[data-band-decisions]");
  var headline = form.querySelector("#headline");
  var decisions = form.querySelector("#decisions");
  var counter = form.querySelector("[data-counter]");
  var note = form.querySelector("[data-dirty-note]");
  var savedNote = note ? note.textContent : "";

  function status() {
    var checked = form.querySelector("input[name=status]:checked");
    return checked ? checked.value : "";
  }

  var saved = { status: status(), headline: headline.value.trim(), decisions: decisions.value.trim() };

  function setTone(el, prefix, tone) {
    ["red", "amber", "green", "none"].forEach(function (t) { el.classList.remove(prefix + t); });
    el.classList.add(prefix + tone);
  }

  function refresh() {
    var st = status();
    var tone = TONES[st] || "none";
    var hl = headline.value.trim();
    var dc = decisions.value.trim();
    setTone(band, "report-band-", tone);
    setTone(dot, "rag-dot-", tone);
    word.textContent = st || "Not set";
    bandHeadline.textContent = hl;
    bandHeadline.hidden = !hl;
    bandDecisions.textContent = dc || "None";

    counter.hidden = false;
    counter.textContent = hl.length + " characters" +
      (hl.length > LONG_HEADLINE ? " · consider shortening; it reads best in one or two sentences" : "");
    counter.classList.toggle("is-long", hl.length > LONG_HEADLINE);

    var dirty = st !== saved.status || hl !== saved.headline || dc !== saved.decisions;
    if (note) {
      note.textContent = dirty ? "Unsaved changes" : savedNote;
      note.classList.toggle("is-dirty", dirty);
    }
  }

  var copy = form.querySelector("[data-copy-last]");
  if (copy) {
    copy.hidden = false;
    copy.querySelector("[data-copy-button]").addEventListener("click", function () {
      var radio = form.querySelector('input[name=status][value="' + copy.dataset.status + '"]');
      if (radio) radio.checked = true;
      headline.value = copy.dataset.headline;
      decisions.value = copy.dataset.decisions;
      refresh();
      headline.focus();
    });
  }

  form.addEventListener("input", refresh);
  form.addEventListener("change", refresh);
  refresh();
})();
