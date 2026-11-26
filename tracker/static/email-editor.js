// Email tab: the template body as a formatted editor (bold, italic, underline, a heading, lists, links), with each
// placeholder shown as a tag, and a View code switch back to the HTML. The form's own text box (#body_html) stays the
// field that is saved: the editor writes its HTML there on every change and fires an input event, so email.js redraws
// the preview and placeholder-table.js marks what is inserted. Without JavaScript the text box is used as it is.
//
// What the editor keeps follows the server's cleaning (compose.clean_body): these tags only, and only a link's
// address, when it is https:, mailto: or {{report_link}}. The server cleans again when the template is saved and sent.
// Plain ES5 style, no modules. No inline styles: the page's security policy blocks them.
(function () {
  "use strict";

  var field = document.querySelector("textarea[data-rich-editor]");
  if (!field || !window.DOMParser || !document.execCommand) return;

  var TAGS = { P: 1, BR: 1, STRONG: 1, B: 1, EM: 1, I: 1, U: 1, H2: 1, H3: 1, H4: 1, UL: 1, OL: 1, LI: 1,
    TABLE: 1, THEAD: 1, TBODY: 1, TR: 1, TH: 1, TD: 1, A: 1, SPAN: 1, DIV: 1 };
  var DROP = { SCRIPT: 1, STYLE: 1, IFRAME: 1, OBJECT: 1, SVG: 1, MATH: 1, TEMPLATE: 1, NOSCRIPT: 1, TEXTAREA: 1,
    SELECT: 1, TITLE: 1 };
  var TOKEN = /\{\{\s*(\w+)\s*\}\}/;
  var preview = document.querySelector("[data-preview]");
  var BLOCKS = preview && preview.dataset.blocks ? preview.dataset.blocks.split(" ") : [];
  var warningBox = document.querySelector("[data-unknown]");
  var KNOWN = warningBox ? warningBox.dataset.known.split(" ") : [];

  function safeLink(href) {
    var h = (href || "").trim();
    return /^(https:\/\/|mailto:)\S/i.test(h) || /^\{\{\s*report_link\s*\}\}$/.test(h);
  }

  // The HTML with only what the server keeps, and what was taken out, in plain words.
  function clean(html) {
    var doc = new DOMParser().parseFromString("<body>" + html + "</body>", "text/html");
    var removed = [];
    function note(text) { if (removed.indexOf(text) < 0) removed.push(text); }
    (function walk(node) {
      Array.prototype.slice.call(node.childNodes).forEach(function (child) {
        if (child.nodeType === 8) { note("comments"); child.remove(); return; }
        if (child.nodeType !== 1) return;
        var tag = child.tagName.toUpperCase();
        if (DROP[tag]) { note("<" + tag.toLowerCase() + ">"); child.remove(); return; }
        if (!TAGS[tag]) {
          note("<" + tag.toLowerCase() + ">");
          walk(child);
          while (child.firstChild) child.parentNode.insertBefore(child.firstChild, child);
          child.remove();
          return;
        }
        Array.prototype.slice.call(child.attributes).forEach(function (attr) {
          var name = attr.name.toLowerCase();
          if (tag === "A" && name === "href") {
            if (safeLink(attr.value)) return;
            note("a link that is not https or mailto");
          } else if (name.indexOf("on") === 0) {
            note("the " + name + " attribute");
          } else {
            note(name + " attributes");
          }
          child.removeAttribute(attr.name);
        });
        walk(child);
      });
    })(doc.body);
    return { html: doc.body.innerHTML, removed: removed };
  }

  // --- The editor, built around the text box -----------------------------------------------------------------------
  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }
  function tool(label, content, command, argument) {
    var button = el("button", "editor-tool");
    button.type = "button";
    button.setAttribute("aria-label", label);
    button.title = label;
    button.appendChild(content);
    if (command) {
      button.dataset.command = command;
      if (argument) button.dataset.argument = argument;
    }
    return button;
  }

  var wrap = el("div", "email-editor");
  var top = el("div", "editor-top");
  var modes = el("div", "editor-modes");
  modes.setAttribute("role", "group");
  modes.setAttribute("aria-label", "Edit the body as");
  var richMode = el("button", "", "Formatted");
  var codeMode = el("button", "", "View code");
  [richMode, codeMode].forEach(function (b) { b.type = "button"; modes.appendChild(b); });
  var modeNote = el("span", "editor-note");
  top.appendChild(modes);
  top.appendChild(modeNote);

  var toolbar = el("div", "editor-toolbar");
  toolbar.setAttribute("role", "toolbar");
  toolbar.setAttribute("aria-label", "Formatting");
  toolbar.appendChild(tool("Bold", el("b", "", "B"), "bold"));
  toolbar.appendChild(tool("Italic", el("i", "", "I"), "italic"));
  toolbar.appendChild(tool("Underline", el("u", "", "U"), "underline"));
  toolbar.appendChild(el("span", "editor-sep"));
  toolbar.appendChild(tool("Heading", document.createTextNode("H"), "formatBlock", "h3"));
  toolbar.appendChild(tool("Paragraph", document.createTextNode("¶"), "formatBlock", "p"));
  toolbar.appendChild(tool("Bulleted list", document.createTextNode("• —"), "insertUnorderedList"));
  toolbar.appendChild(tool("Numbered list", document.createTextNode("1."), "insertOrderedList"));
  toolbar.appendChild(el("span", "editor-sep"));
  var linkTool = tool("Add link", document.createTextNode("Link"));
  toolbar.appendChild(linkTool);
  toolbar.appendChild(tool("Remove link", document.createTextNode("Unlink"), "unlink"));
  toolbar.appendChild(tool("Clear formatting", document.createTextNode("Clear"), "removeFormat"));

  var rich = el("div", "editor-rich");
  rich.contentEditable = "true";
  rich.setAttribute("role", "textbox");
  rich.setAttribute("aria-multiline", "true");
  rich.setAttribute("aria-label", "Body");
  rich.setAttribute("aria-describedby", field.getAttribute("aria-describedby") || "");

  var linkRow = el("div", "editor-link");
  linkRow.hidden = true;
  var linkInput = el("input");
  linkInput.id = "editor-link-url";
  linkInput.placeholder = "https://… or {{report_link}}";
  linkInput.setAttribute("aria-label", "Link address");
  linkInput.autocomplete = "off";
  linkInput.spellcheck = false;
  var linkAdd = el("button", "button", "Add link");
  var linkCancel = el("button", "button", "Cancel");
  linkAdd.type = linkCancel.type = "button";
  var linkError = el("p", "field-error", "Links must start with https:// or mailto:, or be {{report_link}}.");
  linkError.hidden = true;
  linkError.setAttribute("role", "alert");
  [linkInput, linkAdd, linkCancel, linkError].forEach(function (n) { linkRow.appendChild(n); });

  var removedBox = el("div", "warn-box editor-removed");
  removedBox.setAttribute("role", "status");
  removedBox.hidden = true;
  var emptyError = el("p", "field-error", "Write a message: the body cannot be empty.");
  emptyError.hidden = true;
  emptyError.setAttribute("role", "alert");

  field.parentNode.insertBefore(wrap, field);
  [top, toolbar, rich].forEach(function (n) { wrap.appendChild(n); });
  wrap.appendChild(field);  // the text box is the code view
  [linkRow, removedBox, emptyError].forEach(function (n) { wrap.appendChild(n); });
  field.removeAttribute("required");  // checked on submit below, as a hidden box cannot show the browser's message

  document.execCommand("defaultParagraphSeparator", false, "p");
  document.execCommand("styleWithCSS", false, false);

  // --- Placeholders as tags ----------------------------------------------------------------------------------------
  function chip(name) {
    var tag = el("span", "editor-ph" + (BLOCKS.indexOf(name) >= 0 ? " is-block" : "") + (KNOWN.indexOf(name) < 0 ? " is-unknown" : ""));
    tag.contentEditable = "false";
    tag.dataset.ph = name;
    tag.textContent = "{{" + name + "}}";
    return tag;
  }
  // Every {{name}} written in the text becomes a tag. Returns the last tag made inside ``caretText``, if any.
  function chipify(root, caretText) {
    var walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    var texts = [];
    var last = null;
    while (walker.nextNode()) texts.push(walker.currentNode);
    texts.forEach(function (text) {
      if (!TOKEN.test(text.nodeValue) || (text.parentNode.closest && text.parentNode.closest(".editor-ph"))) return;
      var parts = text.nodeValue.split(/(\{\{\s*\w+\s*\}\})/);
      var frag = document.createDocumentFragment();
      var made = null;
      parts.forEach(function (part) {
        var match = /^\{\{\s*(\w+)\s*\}\}$/.exec(part);
        if (match) { made = chip(match[1]); frag.appendChild(made); } else if (part) frag.appendChild(document.createTextNode(part));
      });
      if (text === caretText) last = made;
      text.parentNode.replaceChild(frag, text);
    });
    return last;
  }
  // A body that ends in a placeholder block leaves nowhere to type after it, so an empty paragraph always ends the
  // editor; it is not saved.
  function endWithParagraph() {
    var last = rich.lastChild;
    while (last && last.nodeType === 3 && !last.nodeValue.trim()) last = last.previousSibling;
    if (last && last.nodeType === 1 && last.tagName === "P" && !last.textContent.trim() && !last.querySelector(".editor-ph")) return;
    var p = document.createElement("p");
    p.appendChild(document.createElement("br"));
    rich.appendChild(p);
  }
  function toRich(html) {
    rich.innerHTML = clean(html).html;
    chipify(rich, null);
    endWithParagraph();
  }
  function fromRich() {
    var copy = rich.cloneNode(true);
    Array.prototype.forEach.call(copy.querySelectorAll(".editor-ph"), function (tag) {
      tag.parentNode.replaceChild(document.createTextNode("{{" + tag.dataset.ph + "}}"), tag);
    });
    return copy.innerHTML
      .replace(/<p>(?:\s|<br>)*<\/p>/g, "")  // empty paragraphs, the one ending the editor among them
      .replace(/&nbsp;/g, " ")
      .replace(/\s*(<\/(?:p|h\d|ul|ol|li|table|tr|div)>)\s*/g, "$1\n")
      .replace(/\n{2,}/g, "\n")
      .trim();
  }

  // --- Keeping the text box, the preview and the warnings in step --------------------------------------------------
  var inCode = false;
  function showRemoved(html) {
    var removed = clean(html).removed;
    removedBox.hidden = removed.length === 0;
    removedBox.textContent = removed.length ? "Removed when you save, because an email cannot carry them safely: " + removed.join(", ") + "." : "";
  }
  function sync() {
    field.value = fromRich();
    emptyError.hidden = true;
    field.dispatchEvent(new Event("input", { bubbles: true }));
  }
  rich.addEventListener("input", function (event) {
    event.stopPropagation();  // the text box's own input event below tells the rest of the page
    var sel = window.getSelection();
    var at = sel.rangeCount ? sel.anchorNode : null;
    if (at && at.nodeType === 3 && TOKEN.test(at.nodeValue)) {  // a placeholder typed by hand becomes a tag
      var made = chipify(at.parentNode, at);
      if (made) placeCaretAfter(made);
    }
    endWithParagraph();
    sync();
  });
  field.addEventListener("input", function () { if (inCode) showRemoved(field.value); });

  function setMode(code) {
    if (code === inCode) return;
    inCode = code;
    if (code) {
      field.value = fromRich();
    } else {
      toRich(field.value);
      sync();
    }
    rich.hidden = toolbar.hidden = code;
    field.hidden = !code;
    linkRow.hidden = true;
    richMode.setAttribute("aria-pressed", String(!code));
    codeMode.setAttribute("aria-pressed", String(code));
    modeNote.textContent = code ? "The HTML that is saved. Placeholders are written {{like_this}}."
      : "Write as in an email. Placeholders show as tags.";
    showRemoved(field.value);
    (code ? field : rich).focus();
  }
  richMode.addEventListener("click", function () { setMode(false); });
  codeMode.addEventListener("click", function () { setMode(true); });

  // --- Where the caret was, so the toolbar and the Insert buttons act there ----------------------------------------
  var range = null;
  document.addEventListener("selectionchange", function () {
    var sel = window.getSelection();
    if (sel.rangeCount && rich.contains(sel.anchorNode)) range = sel.getRangeAt(0).cloneRange();
  });
  // A tag is one piece: a caret or selection inside one is moved to just after it.
  function outsideTags(r) {
    var node = r.startContainer.nodeType === 1 ? r.startContainer : r.startContainer.parentNode;
    var tag = node && node.closest ? node.closest(".editor-ph") : null;
    if (tag && rich.contains(tag)) {
      r.setStartAfter(tag);
      r.collapse(true);
    }
    return r;
  }
  function restore() {
    rich.focus();
    var sel = window.getSelection();
    sel.removeAllRanges();
    if (range && rich.contains(range.startContainer)) {
      sel.addRange(outsideTags(range));
    } else {
      var end = document.createRange();
      end.selectNodeContents(rich);
      end.collapse(false);
      sel.addRange(end);
    }
  }
  function placeCaretAfter(node) {
    var space = document.createTextNode(" ");
    node.parentNode.insertBefore(space, node.nextSibling);
    var r = document.createRange();
    r.setStartAfter(space);
    r.collapse(true);
    var sel = window.getSelection();
    sel.removeAllRanges();
    sel.addRange(r);
  }

  Array.prototype.forEach.call(toolbar.querySelectorAll("button"), function (button) {
    button.addEventListener("mousedown", function (event) { event.preventDefault(); });  // keep the selection
  });
  Array.prototype.forEach.call(toolbar.querySelectorAll("[data-command]"), function (button) {
    button.addEventListener("click", function () {
      restore();
      document.execCommand(button.dataset.command, false, button.dataset.argument || null);
      sync();
    });
  });

  linkTool.addEventListener("click", function () {
    linkRow.hidden = false;
    linkError.hidden = true;
    linkInput.removeAttribute("aria-invalid");
    linkInput.value = "";
    linkInput.focus();
  });
  function addLink() {
    var href = linkInput.value.trim();
    if (!safeLink(href)) {
      linkError.hidden = false;
      linkInput.setAttribute("aria-invalid", "true");
      linkInput.focus();
      return;
    }
    restore();
    if (window.getSelection().isCollapsed) {
      // Nothing selected: the link goes in with readable text, the address itself or "the live report".
      var link = document.createElement("a");
      link.setAttribute("href", href);
      link.textContent = /^\{\{/.test(href) ? "the live report" : href.replace(/^mailto:/i, "");
      document.execCommand("insertHTML", false, link.outerHTML + " ");
    } else {
      document.execCommand("createLink", false, href);
    }
    linkRow.hidden = true;
    sync();
  }
  linkAdd.addEventListener("click", addLink);
  linkCancel.addEventListener("click", function () { linkRow.hidden = true; restore(); });
  linkInput.addEventListener("keydown", function (event) {
    if (event.key === "Enter") { event.preventDefault(); addLink(); }
    if (event.key === "Escape") { event.preventDefault(); linkRow.hidden = true; restore(); }
  });

  // Pasted content is cleaned first, so formatting from another document cannot bring in anything unsafe.
  rich.addEventListener("paste", function (event) {
    var data = event.clipboardData;
    if (!data) return;
    event.preventDefault();
    var html = data.getData("text/html");
    if (html) {
      document.execCommand("insertHTML", false, clean(html).html);
    } else {
      document.execCommand("insertText", false, data.getData("text/plain"));
    }
    chipify(rich, null);
    sync();
  });

  // The Insert buttons of the placeholder table put a tag at the caret (placeholder-table.js calls this). In the code
  // view it returns false, and the table writes {{name}} into the text box itself.
  field.insertPlaceholder = function (name) {
    if (inCode) return false;
    restore();
    var sel = window.getSelection();
    var r = outsideTags(sel.getRangeAt(0));
    r.deleteContents();
    var tag = chip(name);
    r.insertNode(tag);
    placeCaretAfter(tag);
    sync();
    return true;
  };

  field.form.addEventListener("submit", function (event) {
    if (!inCode) field.value = fromRich();
    if (!field.value.replace(/<[^>]*>/g, "").trim()) {
      event.preventDefault();
      emptyError.hidden = false;
      (inCode ? field : rich).focus();
    }
  });

  toRich(field.value);
  field.hidden = true;
  richMode.setAttribute("aria-pressed", "true");
  codeMode.setAttribute("aria-pressed", "false");
  modeNote.textContent = "Write as in an email. Placeholders show as tags.";
})();
