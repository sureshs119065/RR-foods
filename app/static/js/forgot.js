/* Forgot password, two steps on one page: 1) email -> emailed 6 digit code, 2) type the code -> the change-password page.
   Posts JSON to /forgot and /forgot/verify (the same URLs the plain forms use, so the page still works without JavaScript). */
(function () {
  "use strict";
  var root = document.querySelector("[data-forgot]");
  if (!root || !window.fetch) return;
  var csrf = (document.querySelector("meta[name=csrf-token]") || {}).content || "";
  var live = document.getElementById("forgot-live");
  var sub = root.querySelector("[data-forgot-sub]");
  var steps = {}; root.querySelectorAll("[data-step]").forEach(function (s) { steps[s.getAttribute("data-step")] = s; });
  var emailForm = root.querySelector("[data-email-form]"), codeForm = root.querySelector("[data-code-form]");
  var emailInput = emailForm.elements.email, sendBtn = root.querySelector("[data-send-btn]"), verifyBtn = root.querySelector("[data-verify-btn]");
  var errBox = emailForm.querySelector("[data-forgot-error]"), errText = emailForm.querySelector("[data-forgot-text]"), signup = emailForm.querySelector("[data-forgot-signup]");
  var codeErr = codeForm.querySelector("[data-error]"), boxWrap = codeForm.querySelector("[data-boxes]"), plain = codeForm.querySelector("[data-plain-code]");
  var boxes = Array.prototype.slice.call(codeForm.querySelectorAll("[data-box]"));
  var timerEl = codeForm.querySelector("[data-timer]"), resendBtn = root.querySelector("[data-resend]"), resendWait = root.querySelector("[data-resend-wait]");
  var field = emailInput.closest(".field");
  var EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/;
  var NOT_REGISTERED = "This email is not registered. Please check your email or sign up";
  var email = (codeForm.querySelector("[data-code-email]").value || "").trim().toLowerCase();
  var expiresAt = 0, resendAt = 0, tick = null;

  /* JavaScript is on: use the six boxes instead of the single plain input */
  boxWrap.hidden = false; plain.hidden = true; plain.querySelector("input").required = false;

  function say(t) { if (live) live.textContent = t; }
  function show(name) {
    Object.keys(steps).forEach(function (k) { steps[k].hidden = k !== name; });
    sub.textContent = name === "code" ? "Enter the code we emailed you, then choose a new password." : "Enter your email and we will send you a 6 digit code.";
    var first = steps[name].querySelector(name === "code" ? "[data-box]" : "input"); if (first) first.focus();
  }
  function emailError(text, withSignup) {
    errText.textContent = text || ""; signup.hidden = !withSignup; errBox.hidden = !text;
    if (field) field.classList.toggle("field--error", !!text);
    if (text) { emailInput.setAttribute("aria-invalid", "true"); say(text); } else emailInput.removeAttribute("aria-invalid");
  }
  function codeError(text) { codeErr.textContent = text || ""; codeErr.hidden = !text; if (text) say(text); }
  function busy(btn, on, label) {
    if (on) { btn.dataset.label = btn.textContent; btn.textContent = label; btn.disabled = true; btn.setAttribute("aria-busy", "true"); }
    else { btn.textContent = btn.dataset.label || btn.textContent; btn.disabled = false; btn.removeAttribute("aria-busy"); }
  }
  function post(url, body) {
    return fetch(url, { method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json", Accept: "application/json", "X-CSRFToken": csrf }, body: JSON.stringify(body) })
      .then(function (r) { return r.json().catch(function () { return {}; }).then(function (d) { d.status = r.status; return d; }); });
  }
  function pad(n) { return (n < 10 ? "0" : "") + n; }

  function startTimers(expiresIn, cooldown) {
    var now = Date.now(); expiresAt = now + expiresIn * 1000; resendAt = now + cooldown * 1000;
    clearInterval(tick); paint(); tick = setInterval(paint, 1000);
  }
  function paint() {
    var now = Date.now(), left = Math.max(0, Math.round((expiresAt - now) / 1000)), wait = Math.max(0, Math.ceil((resendAt - now) / 1000));
    timerEl.textContent = left > 0 ? "Code expires in " + pad(Math.floor(left / 60)) + ":" + pad(left % 60) : "This code has expired. Please resend a new one.";
    resendBtn.disabled = wait > 0; resendWait.textContent = wait > 0 ? "(in " + wait + "s)" : "";
    if (left === 0 && wait === 0) clearInterval(tick);
  }

  /* ---- step 1: send the code ---- */
  function send(isResend) {
    var btn = isResend ? resendBtn : sendBtn;
    emailError(""); codeError("");
    if (!isResend) {
      email = emailInput.value.trim().toLowerCase();
      if (!email) { emailError("Please enter your email address.", false); emailInput.focus(); return; }
      if (!EMAIL_RE.test(email) || email.length > 255) { emailError("Please enter a valid email address.", false); emailInput.focus(); return; }
    }
    busy(btn, true, "Sending...");
    post(root.dataset.sendUrl, { email: email }).then(function (d) {
      busy(btn, false);
      if (d.success) {
        codeForm.querySelector("[data-code-email]").value = email;
        root.querySelector("[data-email-label]").textContent = email;
        boxes.forEach(function (b) { b.value = ""; });
        show("code"); startTimers(d.expires_in || 300, d.cooldown || 45); say(d.message);
        return;
      }
      var msg = d.status === 404 ? NOT_REGISTERED : d.status === 429 && !d.message ? "Too many attempts. Please wait a little and try again." : (d.message || "Something went wrong. Please try again.");
      if (isResend) { codeError(msg); if (d.retry_after) { resendAt = Date.now() + d.retry_after * 1000; paint(); } }
      else emailError(msg, d.status === 404);
    }).catch(function () {
      busy(btn, false);
      var m = "We could not reach the server. Check your connection and try again.";
      if (isResend) codeError(m); else emailError(m, false);
    });
  }
  emailInput.addEventListener("input", function () { emailError(""); });
  emailForm.addEventListener("submit", function (e) { e.preventDefault(); if (!sendBtn.disabled) send(false); });
  resendBtn.addEventListener("click", function () { send(true); });
  root.querySelector("[data-change-email]").addEventListener("click", function () { clearInterval(tick); codeError(""); show("email"); });

  /* ---- the six boxes: digits only, auto-advance, backspace goes back, paste fills all boxes ---- */
  function code() { return boxes.map(function (b) { return b.value; }).join(""); }
  boxes.forEach(function (box, i) {
    box.addEventListener("input", function () {
      var d = box.value.replace(/\D/g, ""); box.value = d.slice(-1);
      if (d && i < boxes.length - 1) boxes[i + 1].focus();
      codeError("");
    });
    box.addEventListener("keydown", function (e) {
      if (e.key === "Backspace" && !box.value && i > 0) { boxes[i - 1].focus(); boxes[i - 1].value = ""; e.preventDefault(); }
      else if (e.key === "ArrowLeft" && i > 0) { boxes[i - 1].focus(); e.preventDefault(); }
      else if (e.key === "ArrowRight" && i < boxes.length - 1) { boxes[i + 1].focus(); e.preventDefault(); }
    });
    box.addEventListener("focus", function () { box.select(); });
    box.addEventListener("paste", function (e) {
      var text = ((e.clipboardData || window.clipboardData).getData("text") || "").replace(/\D/g, "").slice(0, 6);
      if (!text) return; e.preventDefault();
      boxes.forEach(function (b, k) { b.value = text[k] || ""; });
      boxes[Math.min(text.length, boxes.length - 1)].focus();
    });
  });

  /* ---- step 2: verify the code, then go to the change-password page ---- */
  codeForm.addEventListener("submit", function (e) {
    e.preventDefault(); codeError("");
    if (code().length !== 6) { codeError("Enter all 6 digits of the code."); (boxes.find(function (b) { return !b.value; }) || boxes[0]).focus(); return; }
    busy(verifyBtn, true, "Verifying...");
    post(root.dataset.verifyUrl, { email: email, code: code() }).then(function (d) {
      if (!d.success) {
        busy(verifyBtn, false);
        codeError(d.message || (d.status === 429 ? "Too many tries. Please wait a little and try again." : "Something went wrong. Please try again."));
        if (d.locked || d.expired) boxes.forEach(function (b) { b.value = ""; });
        boxes[0].focus(); return;
      }
      clearInterval(tick); say("Email verified. Opening the change password page.");
      window.location.assign(d.redirect);
    }).catch(function () { busy(verifyBtn, false); codeError("No connection. Please check your internet and try again."); });
  });

  /* the page was rendered on the code step (form posted without JavaScript first) */
  if (root.dataset.stepNow === "code") { startTimers(parseInt(root.dataset.expires, 10) || 300, parseInt(root.dataset.cooldown, 10) || 45); boxes[0].focus(); }
})();
