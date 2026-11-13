// The Users list and the Reset password page. An eye button beside each password field shows or hides what was
// typed (it stays hidden without JavaScript). Reset password opens #reset-dialog as a modal for the person in that row: the dialog's form posts
// to the button's own link, and Set password waits until both fields hold the same password. Without JavaScript (or
// without <dialog>) the button stays a link to the person's Reset password page. Plain ES5 style, no modules.
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
