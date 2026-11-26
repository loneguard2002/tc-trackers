// Email: an unknown placeholder is flagged as you type, and the preview redraws from the template on the page (with the
// chosen week's values) before it is saved. Without JavaScript the preview shows the saved template. The placeholder
// table's Insert buttons (placeholder-table.js) put placeholders into the body and fire an input event, which redraws
// the preview here.
(function () {
  "use strict";

  var form = document.querySelector("[data-template-form]");
  if (!form) return;

  var PLACEHOLDER = /\{\{\s*(\w+)\s*\}\}/g;
  var subject = form.elements.subject;
  var body = form.elements.body_html;
  var warning = form.querySelector("[data-unknown]");
  var known = warning.dataset.known.split(" ");
  var note = document.querySelector("[data-dirty-note]");
  var preview = document.querySelector("[data-preview]");
  var context = preview ? JSON.parse(preview.dataset.context) : {};
  // Message parts that are ready-made HTML: inserted as they are in the body, and as nothing in the subject.
  var blocks = preview && preview.dataset.blocks ? preview.dataset.blocks.split(" ") : [];
  var saved = { subject: subject.value, body: body.value };

  function escapeHtml(text) {
    return String(text).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;")
      .replace(/'/g, "&#x27;");
  }

  // As the server fills them: known names become their escaped value, unknown names stay as written.
  function fill(text, escape) {
    return text.replace(PLACEHOLDER, function (match, name) {
      if (!Object.prototype.hasOwnProperty.call(context, name)) return match;
      if (blocks.indexOf(name) >= 0) return escape ? String(context[name]) : "";
      return escape ? escapeHtml(context[name]) : String(context[name]);
    });
  }

  function refresh(initial) {
    var unknown = [];
    [subject.value, body.value].forEach(function (text) {
      text.replace(PLACEHOLDER, function (match, name) {
        if (known.indexOf(name) < 0 && unknown.indexOf(name) < 0) unknown.push(name);
        return match;
      });
    });
    warning.hidden = unknown.length === 0;
    warning.textContent = unknown.length ? "Unknown placeholders will be sent as written: " + unknown.join(", ") + "." : "";

    var dirty = subject.value !== saved.subject || body.value !== saved.body;
    if (note) {
      note.textContent = dirty ? "Unsaved changes; the preview shows them" : "";
      note.classList.toggle("is-dirty", dirty);
    }

    if (!preview) return;
    // The subject is plain text: control characters collapse to spaces, as they do when it is sent.
    var heading = fill(subject.value, false).replace(/[\x00-\x1f\x7f]+/g, " ").trim();
    preview.querySelector("[data-preview-subject]").textContent = "Subject: " + heading;
    // On load the server's frame already shows the saved template. Rebuilding it while it was still loading (the
    // usual case with the page's files cached, as after a week change) left it blank for good in Chrome and Edge,
    // so it is rebuilt then only when the browser has restored an edit to the template.
    if (initial && subject.value === subject.defaultValue && body.value === body.defaultValue) return;
    var frame = preview.querySelector("[data-preview-frame]");
    // The frame follows the page's security policy, which blocks inline styles; the server drops them too.
    var shown = fill(body.value, true).replace(/\sstyle=("[^"]*"|'[^']*')/g, "");
    frame.srcdoc = preview.dataset.shell.replace(preview.dataset.mark, shown);
  }

  form.addEventListener("input", function () { refresh(false); });
  refresh(true);
})();
