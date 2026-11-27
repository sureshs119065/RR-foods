/* Forgot password: checks the email, shows "Sending...", then the red "not registered" message (with a Sign up link) or the green
   success message. Posts JSON to /forgot (the same URL the plain form uses, so the page still works without JavaScript). */
(function () {
  "use strict";
  var form = document.querySelector("[data-forgot]");
  if (!form || !window.fetch) return;
  var input = form.querySelector("input[name=email]");
  var btn = form.querySelector("[data-forgot-btn]");
  var errBox = form.querySelector("[data-forgot-error]");
  var errText = form.querySelector("[data-forgot-text]");
  var signup = form.querySelector("[data-forgot-signup]");
  var okBox = form.querySelector("[data-forgot-ok]");
  var field = input.closest(".field");
  var csrf = (document.querySelector("meta[name=csrf-token]") || {}).content || "";
  var EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/;
  var NOT_REGISTERED = "This email is not registered. Please check your email or sign up";

  function clear() {
    errBox.hidden = true; okBox.hidden = true; signup.hidden = true; errText.textContent = "";
    if (field) field.classList.remove("field--error");
    input.removeAttribute("aria-invalid");
  }
  function showError(text, withSignup) {
    okBox.hidden = true;
    errText.textContent = text; signup.hidden = !withSignup; errBox.hidden = false;
    if (field) field.classList.add("field--error");
    input.setAttribute("aria-invalid", "true");
  }
  function busy(on) {
    if (on) { btn.dataset.label = btn.textContent; btn.textContent = "Sending..."; btn.disabled = true; btn.setAttribute("aria-busy", "true"); }
    else { btn.textContent = btn.dataset.label || "Send reset link"; btn.disabled = false; btn.removeAttribute("aria-busy"); }
  }

  input.addEventListener("input", clear);   // typing again clears the message

  form.addEventListener("submit", function (e) {
    e.preventDefault();
    if (btn.disabled) return;
    clear();
    var email = input.value.trim().toLowerCase();
    if (!email) { showError("Please enter your email address.", false); input.focus(); return; }
    if (!EMAIL_RE.test(email)) { showError("Please enter a valid email address.", false); input.focus(); return; }

    busy(true);
    fetch(form.getAttribute("action") || window.location.pathname, {
      method: "POST", credentials: "same-origin",
      headers: { "Content-Type": "application/json", Accept: "application/json", "X-CSRFToken": csrf },
      body: JSON.stringify({ email: email })
    }).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (d) { d.status = r.status; return d; });
    }).then(function (d) {
      if (d.success) { okBox.hidden = false; return; }
      if (d.status === 404) showError(NOT_REGISTERED, true);
      else if (d.status === 429) showError("Too many attempts. Please wait a little and try again.", false);
      else showError(d.message || "Something went wrong. Please try again.", false);
    }).catch(function () {
      showError("We could not reach the server. Check your connection and try again.", false);
    }).then(function () { busy(false); });
  });
})();
