// Placeholders (mail/_placeholders.html): the Insert buttons in each placeholder table, which show "✓ Inserted" while
// the placeholder is in their field; on Email settings also the subject's character count, its live example and the
// unknown-placeholder warning. Without JavaScript the table stays readable and the buttons stay hidden. Plain ES5
// style, no modules; fields changed here fire an input event, so email.js redraws its preview. On the Email tab the
// formatted editor (email-editor.js) takes the inserts while it is shown.
(function () {
  "use strict";

  function tokenPattern(name) {
    return new RegExp("\\{\\{\\s*" + name + "\\s*\\}\\}", "g");
  }

  function used(text) {
    var names = {};
    text.replace(/\{\{\s*(\w+)\s*\}\}/g, function (match, name) { names[name] = true; return match; });
    return names;
  }

  function changed(field) {
    field.dispatchEvent(new Event("input", { bubbles: true }));
  }

  document.querySelectorAll("[data-placeholder-table]").forEach(function (table) {
    var field = document.getElementById(table.dataset.target);
    if (!field) return;
    var toggle = table.dataset.mode === "toggle";
    var buttons = table.querySelectorAll("[data-insert]");

    function sync() {
      var names = used(field.value);
      buttons.forEach(function (button) {
        var name = button.dataset.insert;
        var token = "{{" + name + "}}";
        var isIn = Object.prototype.hasOwnProperty.call(names, name);
        button.classList.toggle("is-inserted", isIn);
        button.closest("tr").classList.toggle("is-inserted", isIn);
        button.setAttribute("aria-label", !isIn ? "Insert " + token
          : toggle ? token + " is in the field. Remove it" : token + " is in the field. Insert it again");
      });
    }

    buttons.forEach(function (button) {
      button.hidden = false;
      button.addEventListener("click", function () {
        // The Email tab's formatted editor (email-editor.js) puts the placeholder in as a tag, and says so.
        if (typeof field.insertPlaceholder === "function" && field.insertPlaceholder(button.dataset.insert)) return;
        var token = "{{" + button.dataset.insert + "}}";
        if (toggle && button.classList.contains("is-inserted")) {
          field.value = field.value.replace(tokenPattern(button.dataset.insert), "").replace(/\s{2,}/g, " ").trim();
          field.focus();
        } else {
          var start = field.selectionStart === null ? field.value.length : field.selectionStart;
          var end = field.selectionEnd === null ? start : field.selectionEnd;
          field.value = field.value.slice(0, start) + token + field.value.slice(end);
          field.focus();
          field.selectionStart = field.selectionEnd = start + token.length;
        }
        changed(field);
      });
    });
    field.addEventListener("input", sync);
    sync();
  });

  // Email settings: the subject's count, example and warning.
  var subject = document.querySelector("[data-subject-field]");
  if (!subject) return;
  var max = Number(subject.dataset.maxLength);
  var near = max - 30;
  var count = document.querySelector("[data-char-count]");
  var countNote = document.querySelector("[data-char-note]");
  var example = document.querySelector("[data-subject-example]");
  var exampleText = example.querySelector("[data-example-text]");
  var exampleLength = example.querySelector("[data-example-length]");
  var context = JSON.parse(example.dataset.context);
  var blocks = example.dataset.blocks ? example.dataset.blocks.split(" ") : [];
  var warning = document.querySelector("[data-unknown]");
  var known = warning.dataset.known.split(" ");

  // As the server saves it: runs of spaces become one, and the ends are trimmed. Counted in characters, not UTF-16.
  function saved(text) { return text.split(/\s+/).filter(Boolean).join(" "); }
  function length(text) { return Array.from(text).length; }
  function plural(n, word) { return n + " " + word + (n === 1 ? "" : "s"); }

  function refresh() {
    var text = saved(subject.value);
    var n = length(text);
    var over = n > max;
    count.textContent = n + " / " + max;
    count.parentElement.classList.toggle("is-near", n >= near && !over);
    countNote.textContent = n === 0 ? "Enter a subject: every report email needs one."
      : over ? plural(n - max, "character") + " too many: shorten the subject to save."
      : n >= near ? plural(max - n, "character") + " left." : "";
    count.parentElement.classList.toggle("is-over", over || n === 0);
    subject.setAttribute("aria-invalid", over || n === 0 ? "true" : "false");

    var unknown = [];
    var filled = text.replace(/\{\{\s*(\w+)\s*\}\}/g, function (match, name) {
      if (known.indexOf(name) < 0) { if (unknown.indexOf(name) < 0) unknown.push(name); return match; }
      if (blocks.indexOf(name) >= 0) return "";
      return Object.prototype.hasOwnProperty.call(context, name) ? String(context[name]) : match;
    });
    filled = saved(filled);
    exampleText.textContent = filled || "The subject is empty.";
    exampleText.classList.toggle("muted", !filled);
    var filledLength = length(filled);
    exampleLength.textContent = !filled ? ""
      : "· " + plural(filledLength, "character") + " once filled in"
        + (filledLength > max ? ": the email's subject stops at " + max : "");
    exampleLength.classList.toggle("is-over", filledLength > max);
    warning.hidden = unknown.length === 0;
    warning.textContent = unknown.length ? "Unknown placeholders will be sent as written: " + unknown.join(", ") + "." : "";
  }

  subject.addEventListener("input", refresh);
  subject.form.addEventListener("submit", function (event) {
    var n = length(saved(subject.value));
    if (n === 0 || n > max) {
      event.preventDefault();
      refresh();
      subject.focus();
    }
  });
  refresh();
})();
