/* Customer email sign-in: email -> 6 digit code -> (new accounts) name. Talks to /login/otp/send, /verify and /name. */
(function () {
  "use strict";
  var root = document.querySelector("[data-otp]");
  if (!root || !window.fetch) return;
  var csrf = (document.querySelector("meta[name=csrf-token]") || {}).content || "";
  var live = document.getElementById("otp-live");
  var steps = {}; root.querySelectorAll("[data-step]").forEach(function (s) { steps[s.getAttribute("data-step")] = s; });
  var emailForm = root.querySelector("[data-email-form]"), codeForm = root.querySelector("[data-code-form]"), nameForm = root.querySelector("[data-name-form]");
  var boxes = Array.prototype.slice.call(root.querySelectorAll("[data-box]"));
  var timerEl = root.querySelector("[data-timer]"), resendBtn = root.querySelector("[data-resend]"), resendWait = root.querySelector("[data-resend-wait]");
  var EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/;
  var email = "", expiresAt = 0, resendAt = 0, tick = null, redirectTo = "/";

  function show(name) {
    Object.keys(steps).forEach(function (k) { steps[k].hidden = k !== name; });
    var first = steps[name].querySelector("input"); if (first) first.focus();
  }
  function say(text) { if (live) live.textContent = text; }
  function err(form, text) {
    var p = form.querySelector("[data-error]"); if (!p) return;
    p.textContent = text || ""; p.hidden = !text; if (text) say(text);
  }
  function busy(btn, on, label) {
    if (!btn) return;
    if (on) { btn.dataset.label = btn.textContent; btn.textContent = label; btn.disabled = true; }
    else { btn.textContent = btn.dataset.label || btn.textContent; btn.disabled = false; }
  }
  function post(url, body) {
    return fetch(url, { method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json", Accept: "application/json", "X-CSRFToken": csrf }, body: JSON.stringify(body) })
      .then(function (r) { return r.json().catch(function () { return {}; }).then(function (d) { d.status = r.status; return d; }); });
  }
  function fail(d) { return d.message || (d.status === 429 ? "Too many tries. Please wait a little and try again." : "Something went wrong. Please try again."); }
  function pad(n) { return (n < 10 ? "0" : "") + n; }

  /* countdown for the code lifetime and the resend wait */
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

  function send(isResend) {
    var form = isResend ? codeForm : emailForm, btn = isResend ? resendBtn : root.querySelector("[data-send-btn]");
    err(form, "");
    if (!isResend) {
      email = emailForm.elements.email.value.trim().toLowerCase();
      if (!EMAIL_RE.test(email) || email.length > 255) { err(form, "Enter a valid email address."); emailForm.elements.email.focus(); return; }
    }
    busy(btn, true, "Sending...");
    post(root.dataset.sendUrl, { email: email }).then(function (d) {
      busy(btn, false);
      if (!d.ok) { err(form, fail(d)); if (isResend && d.retry_after) { resendAt = Date.now() + d.retry_after * 1000; paint(); } return; }
      root.querySelector("[data-email-label]").textContent = email;
      boxes.forEach(function (b) { b.value = ""; });
      show("code"); boxes[0].focus(); startTimers(d.expires_in || 300, d.cooldown || 45); say(d.message);
    }).catch(function () { busy(btn, false); err(form, "No connection. Please check your internet and try again."); });
  }
  emailForm.addEventListener("submit", function (e) { e.preventDefault(); send(false); });
  resendBtn.addEventListener("click", function () { send(true); });
  root.querySelector("[data-change-email]").addEventListener("click", function () { clearInterval(tick); err(codeForm, ""); show("email"); });

  /* the six boxes: digits only, auto-advance, backspace goes back, paste fills all boxes */
  function code() { return boxes.map(function (b) { return b.value; }).join(""); }
  boxes.forEach(function (box, i) {
    box.addEventListener("input", function () {
      var d = box.value.replace(/\D/g, ""); box.value = d.slice(-1);
      if (d && i < boxes.length - 1) boxes[i + 1].focus();
      err(codeForm, "");
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

  codeForm.addEventListener("submit", function (e) {
    e.preventDefault(); var btn = root.querySelector("[data-verify-btn]"); err(codeForm, "");
    if (code().length !== 6) { err(codeForm, "Enter all 6 digits of the code."); (boxes.find(function (b) { return !b.value; }) || boxes[0]).focus(); return; }
    busy(btn, true, "Verifying...");
    post(root.dataset.verifyUrl, { email: email, code: code(), next: root.dataset.next || "" }).then(function (d) {
      if (!d.ok) {
        busy(btn, false); err(codeForm, fail(d));
        if (d.locked || d.expired) { boxes.forEach(function (b) { b.value = ""; }); }
        boxes[0].focus(); return;
      }
      clearInterval(tick); redirectTo = d.redirect || "/";
      if (d.new_user) { busy(btn, false); nameForm.elements.name.value = d.name || ""; show("name"); say("Your account is ready."); }
      else window.location.assign(redirectTo);
    }).catch(function () { busy(btn, false); err(codeForm, "No connection. Please check your internet and try again."); });
  });

  nameForm.addEventListener("submit", function (e) {
    e.preventDefault(); err(nameForm, "");
    var name = nameForm.elements.name.value.trim();
    if (name.length < 2) { err(nameForm, "Enter your name (at least 2 characters)."); return; }
    var btn = nameForm.querySelector("button[type=submit]"); busy(btn, true, "Saving...");
    post(root.dataset.nameUrl, { name: name }).then(function (d) {
      if (!d.ok) { busy(btn, false); err(nameForm, fail(d)); return; }
      window.location.assign(redirectTo);
    }).catch(function () { busy(btn, false); err(nameForm, "No connection. Please try again."); });
  });
  root.querySelector("[data-skip-name]").addEventListener("click", function () { window.location.assign(redirectTo); });
})();
