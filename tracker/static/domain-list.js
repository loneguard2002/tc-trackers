// Email settings › Report recipients: the allowed domains as chips, each with a remove button, and a box to add one.
// The list itself stays in the form's text box (one domain per line), which is hidden and kept in step, so the form
// saves as it does without JavaScript. The server checks the list again. Plain ES5 style, no modules.
(function () {
  "use strict";

  var box = document.querySelector("[data-domain-list]");
  if (!box) return;

  var DOMAIN = /^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+$/;
  var list = document.createElement("ul");
  list.className = "domain-chips";
  list.setAttribute("aria-label", "Allowed domains");
  var row = document.createElement("div");
  row.className = "domain-add";
  var input = document.createElement("input");
  input.id = "domain-new";
  input.autocomplete = "off";
  input.spellcheck = false;
  input.placeholder = "example.com";
  input.setAttribute("aria-label", "Domain to allow");
  input.setAttribute("aria-describedby", "domain-error " + box.getAttribute("aria-describedby"));
  var add = document.createElement("button");
  add.type = "button";
  add.className = "button";
  add.textContent = "Add domain";
  var error = document.createElement("p");
  error.className = "field-error";
  error.id = "domain-error";
  error.setAttribute("role", "alert");
  error.hidden = true;
  row.appendChild(input);
  row.appendChild(add);
  box.hidden = true;
  box.removeAttribute("required");  // the chips show the list; the server refuses an empty one
  box.parentNode.insertBefore(list, box);
  box.parentNode.insertBefore(row, box);
  box.parentNode.insertBefore(error, box);

  function domains() {
    return box.value.toLowerCase().split(/[\s,;]+/).map(function (d) { return d.replace(/^@/, ""); })
      .filter(function (d, i, all) { return d && all.indexOf(d) === i; });
  }

  function say(text) {
    error.textContent = text;
    error.hidden = !text;
    if (text) input.setAttribute("aria-invalid", "true"); else input.removeAttribute("aria-invalid");
  }

  function draw() {
    var current = domains();
    list.textContent = "";
    current.forEach(function (domain) {
      var li = document.createElement("li");
      li.className = "domain-chip";
      li.appendChild(document.createTextNode("@" + domain));
      var remove = document.createElement("button");
      remove.type = "button";
      remove.className = "domain-remove";
      remove.textContent = "✕";
      remove.setAttribute("aria-label", "Remove " + domain);
      remove.disabled = current.length === 1;  // at least one domain stays
      if (remove.disabled) remove.title = "Keep at least one domain";
      remove.addEventListener("click", function () {
        box.value = domains().filter(function (d) { return d !== domain; }).join("\n");
        box.dispatchEvent(new Event("input", { bubbles: true }));
        draw();
        input.focus();
      });
      li.appendChild(remove);
      list.appendChild(li);
    });
  }

  function addDomain() {
    var domain = input.value.trim().toLowerCase().replace(/^@/, "");
    if (!domain) { say("Enter a domain to add, for example example.com."); input.focus(); return; }
    if (!DOMAIN.test(domain)) { say("Enter the domain as it appears after the @, for example example.com."); input.focus(); return; }
    if (domains().indexOf(domain) >= 0) { say(domain + " is already allowed."); input.focus(); return; }
    say("");
    box.value = domains().concat([domain]).join("\n");
    box.dispatchEvent(new Event("input", { bubbles: true }));
    input.value = "";
    draw();
    input.focus();
  }

  add.addEventListener("click", addDomain);
  // Enter in the box adds the domain instead of saving the whole page.
  input.addEventListener("keydown", function (event) {
    if (event.key === "Enter") { event.preventDefault(); addDomain(); }
  });
  input.addEventListener("input", function () { say(""); });
  draw();
})();
