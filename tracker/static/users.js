// The Users list and the Reset password page. An eye button beside each password field shows or hides what was
// typed (it stays hidden without JavaScript). Reset password opens #reset-dialog as a modal for the person in that row: the dialog's form posts
// to the button's own link, and Set password waits until both fields hold the same password. Without JavaScript (or
// without <dialog>) the button stays a link to the person's Reset password page. On a person's Access page, Delete
// opens #delete-dialog the same way, and its Delete button waits until the typed email matches. Plain ES5 style, no
// modules.
(function () {
  "use strict";

  var toggles = document.querySelectorAll("[data-password-toggle]");

  function showPassword(toggle, shown) {
    document.getElementById(toggle.getAttribute("data-password-toggle")).type = shown ? "text" : "password";
    toggle.setAttribute("aria-pressed", shown ? "true" : "false");
  }

  function hidePasswords() {
    Array.prototype.forEach.call(toggles, function (toggle) { showPassword(toggle, false); });
  }

  Array.prototype.forEach.call(toggles, function (toggle) {
    toggle.hidden = false;
    toggle.addEventListener("click", function () {
      showPassword(toggle, toggle.getAttribute("aria-pressed") !== "true");
    });
  });

  var dialog = document.getElementById("reset-dialog");
  if (!dialog || typeof dialog.showModal !== "function") return;
  var form = dialog.querySelector("form");
  var password = dialog.querySelector("#reset-password");
  var confirm = dialog.querySelector("#reset-confirm");
  var person = dialog.querySelector("[data-reset-person]");

  function checkMatch() {
    confirm.setCustomValidity(confirm.value !== "" && confirm.value !== password.value
      ? "The two passwords do not match." : "");
  }

  password.addEventListener("input", checkMatch);
  confirm.addEventListener("input", checkMatch);

  Array.prototype.forEach.call(document.querySelectorAll("a[data-reset-password]"), function (link) {
    link.addEventListener("click", function (event) {
      event.preventDefault();
      form.reset();
      hidePasswords();
      checkMatch();
      form.setAttribute("action", link.getAttribute("href"));
      person.textContent = link.getAttribute("data-person");
      dialog.showModal();
      password.focus();
    });
  });

  Array.prototype.forEach.call(dialog.querySelectorAll("[data-reset-close]"), function (button) {
    button.addEventListener("click", function () { dialog.close(); });
  });
  dialog.addEventListener("close", function () {
    form.reset();
    hidePasswords();
  });
}());

// The Delete dialog of a person's Access page. Its Delete button starts disabled and is enabled while the typed
// text, trimmed and lower-cased, equals the person's email (the server checks again). Without <dialog> or JavaScript
// the Delete link goes to the Delete page instead.
(function () {
  "use strict";

  var dialog = document.getElementById("delete-dialog");
  if (!dialog || typeof dialog.showModal !== "function") return;
  var link = document.querySelector("a[data-delete-person]");
  var form = dialog.querySelector("form");
  var confirm = dialog.querySelector("[data-delete-confirm]");
  var submit = dialog.querySelector("[data-delete-submit]");
  if (!link || !confirm || !submit) return;

  function checkEmail() {
    submit.disabled = confirm.value.trim().toLowerCase() !== confirm.getAttribute("data-email");
  }

  confirm.addEventListener("input", checkEmail);

  link.addEventListener("click", function (event) {
    event.preventDefault();
    form.reset();
    checkEmail();
    dialog.showModal();
    confirm.focus();
  });

  Array.prototype.forEach.call(dialog.querySelectorAll("[data-delete-close]"), function (button) {
    button.addEventListener("click", function () { dialog.close(); });
  });
  dialog.addEventListener("close", function () {
    form.reset();
    checkEmail();
  });
}());
