// Feedback: the "Feedback on this page" link opens the form as a pop-up. The form is the server's own page
// (/feedback/new), whose dialog is read from it; without JavaScript the link simply goes to that page. In the
// pop-up, Send posts in the background and the answer (the thank-you, or the form again with its errors) replaces
// the pop-up's contents. The switch changes the copy of the details, files are added by the button, by dropping them
// or by pasting a screenshot, and the browser line comes from the user agent and the window size.
(function () {
  "use strict";

  var MAX_FILES = 5;
  var MAX_BYTES = 5 * 1024 * 1024;
  var DIALOG_ID = "feedback-dialog";

  function each(list, callback) {
    Array.prototype.forEach.call(list, callback);
  }

  function canBeModal(dialog) {
    return Boolean(dialog) && typeof dialog.showModal === "function";
  }

  function canSetFiles() {
    try {
      return new DataTransfer().files !== undefined;
    } catch (error) {
      return false;
    }
  }

  // "Edge on Windows" from the user agent (the same reading the server makes when a page sends none).
  function browserName(agent) {
    var name = "";
    if (/Edg(A|e)?\//.test(agent)) name = "Edge";
    else if (/OPR\//.test(agent)) name = "Opera";
    else if (/Firefox\//.test(agent)) name = "Firefox";
    else if (/Chrome\/|CriOS\//.test(agent)) name = "Chrome";
    else if (/Safari\//.test(agent)) name = "Safari";
    if (!name) return "";
    var systems = [["Windows", "Windows"], ["Android", "Android"], ["iPhone", "iOS"], ["iPad", "iOS"],
      ["Mac OS X", "macOS"], ["Linux", "Linux"]];
    for (var i = 0; i < systems.length; i += 1) {
      if (agent.indexOf(systems[i][0]) !== -1) return name + " on " + systems[i][1];
    }
    return name;
  }

  function sizeText(bytes) {
    if (bytes >= 1024 * 1024) return (bytes / (1024 * 1024)).toFixed(1) + " MB";
    return Math.max(1, Math.round(bytes / 1024)) + " KB";
  }

  // The name a pasted picture gets: by its type, as the server checks a name against the content.
  var PICTURE_EXTENSIONS = { "image/png": "png", "image/jpeg": "jpg", "image/gif": "gif", "image/webp": "webp" };

  function request(method, url, data, done) {
    var xhr = new XMLHttpRequest();
    xhr.open(method, url);
    xhr.setRequestHeader("X-Requested-With", "XMLHttpRequest");
    xhr.onload = function () { done(xhr.status, xhr.responseText); };
    xhr.onerror = function () { done(0, ""); };
    xhr.send(data || null);
  }

  // The pop-up's dialog inside a page the server sent, or null.
  function dialogIn(html) {
    var doc = new DOMParser().parseFromString(html, "text/html");
    return doc.getElementById(DIALOG_ID);
  }

  function wire(dialog, popup) {
    var chosen = [];
    var form = dialog.querySelector("form");
    var input = dialog.querySelector("#feedback-files");
    var list = dialog.querySelector("[data-feedback-list]");
    var note = dialog.querySelector("[data-feedback-file-note]");
    var addButton = dialog.querySelector("[data-feedback-add]");
    var hint = dialog.querySelector("[data-feedback-drop-hint]");
    var setFiles = canSetFiles();

    function say(text) {
      if (!note) return;
      note.textContent = text;
      note.hidden = text === "";
    }

    function render() {
      if (!list) return;
      list.textContent = "";
      each(chosen, function (file, index) {
        var item = document.createElement("li");
        var name = document.createElement("span");
        name.className = "feedback-file-name";
        name.textContent = file.name;
        var size = document.createElement("span");
        size.className = "feedback-file-size";
        size.textContent = sizeText(file.size);
        var remove = document.createElement("button");
        remove.type = "button";
        remove.className = "button button-small";
        remove.setAttribute("data-feedback-remove", String(index));
        remove.appendChild(document.createTextNode("Remove"));
        var spoken = document.createElement("span");
        spoken.className = "sr-only";
        spoken.textContent = " " + file.name;
        remove.appendChild(spoken);
        item.appendChild(name);
        item.appendChild(size);
        item.appendChild(remove);
        list.appendChild(item);
      });
      list.hidden = chosen.length === 0;
    }

    // Put the chosen files into the file field, which is what the form posts.
    function sync() {
      if (!input) return;
      var transfer = new DataTransfer();
      each(chosen, function (file) { transfer.items.add(file); });
      input.files = transfer.files;
      render();
    }

    function add(files) {
      var messages = [];
      each(files, function (file) {
        if (chosen.length >= MAX_FILES) {
          if (messages.indexOf("Attach at most 5 files.") === -1) messages.push("Attach at most 5 files.");
        } else if (file.size > MAX_BYTES) {
          messages.push(file.name + " is over 5 MB.");
        } else {
          chosen.push(file);
        }
      });
      say(messages.join(" "));
      sync();
    }

    function pastedFile(file, number) {
      var extension = PICTURE_EXTENSIONS[file.type];
      if (!extension) return file;
      var name = "screenshot" + (number > 1 ? "-" + number : "") + "." + extension;
      return new File([file], name, { type: file.type });
    }

    // The tabs change the title, the send button's label and the details' label, help and placeholder (and whether
    // the details are needed).
    function showKind() {
      var picked = dialog.querySelector('input[name="kind"]:checked');
      var kind = picked ? picked.value : "idea";
      each(dialog.querySelectorAll("[data-feedback-title], [data-feedback-submit]"), function (element) {
        element.textContent = element.getAttribute("data-" + kind);
      });
      var box = dialog.querySelector("[data-feedback-details]");
      if (!box) return;
      var label = box.querySelector("[data-feedback-details-label]");
      var help = box.querySelector("[data-feedback-details-help]");
      var details = box.querySelector("textarea");
      label.textContent = box.getAttribute("data-" + kind + "-label");
      help.textContent = box.getAttribute("data-" + kind + "-help");
      details.placeholder = box.getAttribute("data-" + kind + "-placeholder");
      details.required = kind === "problem";
    }

    // The line under the box: the page's title, and the browser with the window's size.
    function showPage() {
      var sendIt = dialog.querySelector("#feedback-with-page");
      var line = dialog.querySelector("[data-feedback-page-line]");
      if (line && sendIt) line.hidden = !sendIt.checked;
    }

    function fillBrowser() {
      var field = dialog.querySelector("[data-feedback-browser]");
      var text = dialog.querySelector("[data-feedback-browser-text]");
      var name = browserName(navigator.userAgent);
      if (!field || !name) return;
      field.value = name + ", window " + window.innerWidth + " x " + window.innerHeight;
      if (text) text.textContent = name;
    }

    function swapIn(html) {
      var next = dialogIn(html);
      if (!next) return false;
      dialog.className = next.className;
      dialog.innerHTML = next.innerHTML;
      if (!dialog.querySelector("#feedback-files")) chosen = [];
      reset();
      return true;
    }

    function reset() {
      form = dialog.querySelector("form");
      input = dialog.querySelector("#feedback-files");
      list = dialog.querySelector("[data-feedback-list]");
      note = dialog.querySelector("[data-feedback-file-note]");
      addButton = dialog.querySelector("[data-feedback-add]");
      hint = dialog.querySelector("[data-feedback-drop-hint]");
      if (input && setFiles) {
        input.hidden = true;
        if (addButton) addButton.hidden = false;
        if (hint) hint.hidden = false;
        sync();
      }
      showKind();
      showPage();
      fillBrowser();
      var first = dialog.querySelector('[aria-invalid="true"], #feedback-summary');
      if (first && popup) first.focus();
    }

    function failed(text) {
      var box = dialog.querySelector(".list-dialog-body");
      var message = document.createElement("div");
      message.className = "form-alert";
      message.setAttribute("role", "alert");
      message.textContent = text;
      if (box) box.insertBefore(message, box.firstChild);
    }

    function load(url) {
      request("GET", url, null, function (status, html) {
        if (status !== 200 || !swapIn(html)) window.location.href = url;
      });
    }

    function submit() {
      var button = dialog.querySelector('button[type="submit"]');
      if (button) button.disabled = true;
      request("POST", form.getAttribute("action"), new FormData(form), function (status, html) {
        if (swapIn(html)) return;
        if (button) button.disabled = false;
        failed(status === 413
          ? "That is more than can be sent at once. Remove a file and try again."
          : "The feedback could not be sent. Try again.");
      });
    }

    dialog.addEventListener("change", function (event) {
      var target = event.target;
      if (target.name === "kind") showKind();
      if (target.id === "feedback-with-page") showPage();
      if (target.id === "feedback-files" && setFiles) {
        var picked = Array.prototype.slice.call(target.files);
        add(picked);
      }
    });

    dialog.addEventListener("click", function (event) {
      var target = event.target.closest ? event.target.closest("a, button") : null;
      if (!target) return;
      if (target.hasAttribute("data-feedback-add")) {
        input.click();
      } else if (target.hasAttribute("data-feedback-remove")) {
        chosen.splice(parseInt(target.getAttribute("data-feedback-remove"), 10), 1);
        say("");
        sync();
      } else if (target.hasAttribute("data-feedback-again") && popup) {
        event.preventDefault();
        load(target.getAttribute("href"));
      } else if (target.hasAttribute("data-dialog-close") && popup) {
        event.preventDefault();
        dialog.close();
      }
    });

    if (popup) {
      dialog.addEventListener("submit", function (event) {
        event.preventDefault();
        submit();
      });
    }

    dialog.addEventListener("paste", function (event) {
      var files = event.clipboardData && event.clipboardData.files;
      if (!files || !files.length || !setFiles || !input) return;
      event.preventDefault();
      var count = 0;
      add(Array.prototype.map.call(files, function (file) {
        count += 1;
        return pastedFile(file, chosen.length + count);
      }));
    });

    dialog.addEventListener("dragover", function (event) {
      if (!setFiles || !event.dataTransfer || !input) return;
      event.preventDefault();
      var zone = dialog.querySelector("[data-feedback-drop]");
      if (zone) zone.classList.add("is-over");
    });
    dialog.addEventListener("dragleave", function () {
      var zone = dialog.querySelector("[data-feedback-drop]");
      if (zone) zone.classList.remove("is-over");
    });
    dialog.addEventListener("drop", function (event) {
      var zone = dialog.querySelector("[data-feedback-drop]");
      if (zone) zone.classList.remove("is-over");
      if (!setFiles || !input || !event.dataTransfer || !event.dataTransfer.files.length) return;
      event.preventDefault();
      add(event.dataTransfer.files);
    });

    reset();
  }

  function open(link) {
    var url = link.getAttribute("href");
    request("GET", url, null, function (status, html) {
      var found = status === 200 ? dialogIn(html) : null;
      if (!found || !canBeModal(found)) {
        window.location.href = url;
        return;
      }
      var old = document.getElementById(DIALOG_ID);
      if (old && old.parentNode) old.parentNode.removeChild(old);
      var dialog = document.importNode(found, true);
      dialog.removeAttribute("open");
      dialog.removeAttribute("data-reopen");
      document.body.appendChild(dialog);
      dialog.addEventListener("close", function () {
        if (dialog.parentNode) dialog.parentNode.removeChild(dialog);
      });
      wire(dialog, true);
      dialog.showModal();
      var first = dialog.querySelector("#feedback-summary");
      if (first) first.focus();
    });
  }

  each(document.querySelectorAll("a[data-feedback-open]"), function (link) {
    link.addEventListener("click", function (event) {
      if (event.defaultPrevented || event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey) return;
      if (typeof XMLHttpRequest === "undefined" || typeof DOMParser === "undefined") return;
      event.preventDefault();
      open(link);
    });
  });

  // The page of its own (reached without the pop-up) still gets the switch, the files and the browser line.
  var onPage = document.querySelector(".feedback-page #" + DIALOG_ID + " form");
  if (onPage) wire(document.getElementById(DIALOG_ID), false);
})();

// Admin › Feedback: a request opens in the side panel (dialog#feedback-panel), as the permission sets panel does. The
// panel's body is the fragment from /admin/feedback/<id>/panel; without JavaScript, or when it cannot be loaded, the
// row's link goes to the request's own page. The status and reply forms post in the background and the panel shows
// the answer (the request again, or the form with its errors). A reply carries the status chosen in the head, and a
// status save keeps what is typed in the reply box; closing the panel after a change reloads the page, so
// the table shows the new status, replies and last activity. ?request=<id> follows the open panel. On a request's own
// page only the reply switch is wired.
(function () {
  "use strict";

  function each(list, callback) {
    Array.prototype.forEach.call(list, callback);
  }

  function element(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  // Update or Question: the box's label, its help and the button follow the switch.
  function wireReply(root) {
    var form = root ? root.querySelector("[data-reply-form]") : null;
    if (!form) return;
    function show() {
      var picked = form.querySelector('input[name="kind"]:checked');
      var kind = picked ? picked.value : "update";
      each(form.querySelectorAll("[data-update-text]"), function (node) {
        node.textContent = node.getAttribute("data-" + kind + "-text");
      });
    }
    form.addEventListener("change", function (event) {
      if (event.target.name === "kind") show();
    });
    show();
  }

  var panel = document.getElementById("feedback-panel");
  var table = document.getElementById("feedback-table");
  if (!panel || !table || typeof panel.showModal !== "function" || typeof fetch !== "function") {
    wireReply(document.querySelector(".feedback-request-page"));
    return;
  }

  var openRow = null;
  var changed = false;
  var body = null;
  var announce = null;

  function setAddress(id) {
    try {
      var params = new URLSearchParams(window.location.search);
      if (id) params.set("request", id);
      else params.delete("request");
      var query = params.toString();
      history.replaceState(history.state, "", location.pathname + (query ? "?" + query : "") + location.hash);
    } catch (error) { /* an address that cannot be rewritten leaves it as it is */ }
  }

  function ownPage(row) {
    return row.querySelector("[data-open-request]").getAttribute("href");
  }

  function failed(row, text) {
    if (openRow !== row) return;
    announce.textContent = text;
    body.textContent = "";
    var note = element("p", "empty-note", text + " ");
    var link = element("a", "", "Open the request's own page");
    link.href = ownPage(row);
    note.appendChild(link);
    body.appendChild(note);
  }

  // Puts the server's fragment in the panel; false when the answer is not the request (a sign-in page, an error).
  // ``restore`` runs on the new fragment before it is wired, to put back what the reader had typed.
  function show(row, html, restore) {
    if (openRow !== row) return true;
    if (html.indexOf("data-panel-feedback") === -1) return false;
    announce.textContent = "";
    body.innerHTML = html;
    if (restore) restore();
    wireReply(body);
    return true;
  }

  // What the reader has put in the reply box, kept across a status save (which sends the head's form only).
  function replyState() {
    var reply = body.querySelector("[data-reply-form]");
    if (!reply) return null;
    var kind = reply.querySelector('input[name="kind"]:checked');
    var email = reply.querySelector('input[name="email"]');
    var files = reply.querySelector('input[name="files"]');
    return {
      kind: kind ? kind.value : "update",
      text: reply.querySelector('textarea[name="body"]').value,
      email: email && !email.disabled ? email.checked : null,
      files: files ? files.files : null
    };
  }

  function putBack(state) {
    var reply = body.querySelector("[data-reply-form]");
    if (!state || !reply) return;
    each(reply.querySelectorAll('input[name="kind"]'), function (radio) { radio.checked = radio.value === state.kind; });
    reply.querySelector('textarea[name="body"]').value = state.text;
    var email = reply.querySelector('input[name="email"]');
    if (email && !email.disabled && state.email !== null) email.checked = state.email;
    var files = reply.querySelector('input[name="files"]');
    if (files && state.files && state.files.length) {
      try { files.files = state.files; } catch (error) { /* a browser that cannot set them leaves the field empty */ }
    }
  }

  function send(row, form) {
    var button = form.querySelector('button[type="submit"]');
    if (button) button.disabled = true;
    var data = new FormData(form);
    var kept = null;
    if (form.hasAttribute("data-reply-form")) {
      // An update applies the status chosen in the head; the server ignores it for a question.
      var head = body.querySelector("[data-head-status]");
      if (head) data.set("status", head.value);
    } else {
      kept = replyState();
    }
    fetch(form.getAttribute("action"), {
      method: "POST",
      body: data,
      credentials: "same-origin",
      headers: { "X-Requested-With": "fetch" }
    })
      .then(function (response) {
        if (response.redirected) throw new Error("redirected");
        return response.text().then(function (html) {
          return { ok: response.ok, status: response.status, html: html,
            changed: response.headers.get("X-Panel-Changed") !== "0" };
        });
      })
      .then(function (answer) {
        if (answer.status === 413) throw new Error("too large");
        if (!show(row, answer.html, function () { putBack(kept); })) throw new Error("not the panel");
        if (answer.ok && answer.changed) changed = true;
        var focus = body.querySelector('[aria-invalid="true"]') || body.querySelector("[data-panel-notice]");
        if (focus) {
          if (!focus.hasAttribute("aria-invalid")) focus.setAttribute("tabindex", "-1");
          focus.focus();
        }
      })
      .catch(function (error) {
        if (button) button.disabled = false;
        each(form.querySelectorAll(".form-alert"), function (old) { old.parentNode.removeChild(old); });
        var alert = element("div", "form-alert", error.message === "too large"
          ? "That is more than can be sent at once. Remove a file and try again."
          : "The change could not be saved. Try again.");
        alert.setAttribute("role", "alert");
        form.insertBefore(alert, form.firstChild);
      });
  }

  function open(row) {
    openRow = row;
    panel.textContent = "";
    var head = element("header", "drawer-head");
    var title = element("div", "perm-detail-title");
    var heading = element("h2", "", row.querySelector("[data-open-request]").textContent.trim());
    heading.id = "feedback-panel-title";
    title.appendChild(heading);
    head.appendChild(title);
    var cross = element("button", "tool-button", "✕");
    cross.type = "button";
    cross.title = "Close";
    cross.setAttribute("aria-label", "Close");
    cross.addEventListener("click", function () { panel.close(); });
    head.appendChild(cross);
    announce = element("p", "sr-only", "Loading the request…");
    announce.setAttribute("role", "status");
    body = element("div", "drawer-body");
    body.appendChild(element("p", "empty-note", "Loading the request…"));
    panel.appendChild(head);
    panel.appendChild(announce);
    panel.appendChild(body);
    if (!panel.open) panel.showModal();
    setAddress(row.getAttribute("data-request"));
    fetch(row.getAttribute("data-panel-url"), { credentials: "same-origin", headers: { "X-Requested-With": "fetch" } })
      .then(function (response) {
        // An expired session redirects to the sign-in page, which answers 200: that is a failure too.
        if (!response.ok || response.redirected) throw new Error("status " + response.status);
        // Opening a request in My feedback marks its new reply as seen, so the list and the count change.
        if (response.headers.get("X-Panel-Changed") === "1") changed = true;
        return response.text();
      })
      .then(function (html) {
        if (!show(row, html)) throw new Error("not the panel");
      })
      .catch(function () { failed(row, "The request could not be loaded."); });
  }

  panel.addEventListener("submit", function (event) {
    var form = event.target;
    if (!openRow || !form.hasAttribute("data-panel-form")) return;
    event.preventDefault();
    send(openRow, form);
  });

  // My feedback: Withdraw request asks in the panel (the link goes to a page that asks, without JavaScript).
  panel.addEventListener("click", function (event) {
    var target = event.target.closest ? event.target.closest("a") : null;
    if (!target) return;
    var area = target.closest("[data-panel-feedback]");
    var confirmation = area ? area.querySelector("[data-withdraw-confirm]") : null;
    var ask = area ? area.querySelector("[data-withdraw-ask]") : null;
    if (!confirmation || !ask) return;
    if (target === ask) {
      event.preventDefault();
      ask.hidden = true;
      confirmation.hidden = false;
      confirmation.querySelector("button").focus();
    } else if (target.hasAttribute("data-withdraw-cancel")) {
      event.preventDefault();
      confirmation.hidden = true;
      ask.hidden = false;
      ask.focus();
    }
  });

  panel.addEventListener("close", function () {
    var row = openRow;
    openRow = null;
    setAddress(null);
    if (changed) {
      window.location.reload();
      return;
    }
    var link = row && row.querySelector("[data-open-request]");
    if (link) link.focus();
  });

  // A click on the dimmed page closes it: the point lies outside the panel's box (keyboard clicks target a button).
  panel.addEventListener("click", function (event) {
    if (event.target !== panel) return;
    var box = panel.getBoundingClientRect();
    if (event.clientX < box.left || event.clientX > box.right || event.clientY < box.top || event.clientY > box.bottom) {
      panel.close();
    }
  });

  // The reference opens the panel, and so does a click anywhere else on the row.
  table.classList.add("opens-panel");
  table.addEventListener("click", function (event) {
    var row = event.target.closest ? event.target.closest("tbody tr[data-request]") : null;
    if (!row) return;
    var link = event.target.closest("a, button, input, select, textarea, label");
    if (link && !link.hasAttribute("data-open-request")) return;
    if (link && (event.metaKey || event.ctrlKey || event.shiftKey || event.button)) return;
    event.preventDefault();
    open(row);
  });

  // ?request=<id> opens that request's panel; anything that is not the id of a row here is ignored.
  var wanted = /[?&]request=(\d+)(&|$)/.exec(location.search);
  if (wanted) {
    var row = table.querySelector('tbody tr[data-request="' + String(Number(wanted[1])) + '"]');
    if (row) open(row);
  }
})();
