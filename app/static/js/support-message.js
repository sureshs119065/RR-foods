/* Home page "Message RR FOODS" form: sends with fetch() so the page never reloads or moves, then shows the same thank-you
   popup style (.rt) that the review thank-you uses. Fields are cleared on success; the Send button is locked while sending. */
(function () {
  "use strict";
  var form = document.querySelector("[data-support-form]");
  if (!form || !window.fetch) return;   // without fetch the normal form post still works
  var csrf = (document.querySelector("meta[name=csrf-token]") || {}).content || "";
  var btn = form.querySelector("[data-support-btn]"), sending = false;
  var LIMITS = { subject: [3, 150], body: [5, 2000] };
  var reduce = window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches;

  function field(name) { return form.elements[name]; }
  function showErr(name, text) {
    var el = form.querySelector('[data-err="' + name + '"]'), input = field(name);
    if (el) { el.textContent = text || ""; el.hidden = !text; }
    if (input) { if (text) input.setAttribute("aria-invalid", "true"); else input.removeAttribute("aria-invalid"); }
  }
  function clearErrs() { showErr("subject", ""); showErr("body", ""); }
  function clean(v) { return (v || "").replace(/\s+$/gm, "").trim(); }
  function validate() {
    var bad = null, subject = field("subject").value.replace(/\s+/g, " ").trim(), body = clean(field("body").value);
    clearErrs();
    if (!subject) { showErr("subject", "Enter a subject."); bad = bad || "subject"; }
    else if (subject.length < LIMITS.subject[0]) { showErr("subject", "The subject needs at least 3 characters."); bad = bad || "subject"; }
    else if (subject.length > LIMITS.subject[1]) { showErr("subject", "The subject can be up to 150 characters."); bad = bad || "subject"; }
    if (!body) { showErr("body", "Write your message."); bad = bad || "body"; }
    else if (body.length < LIMITS.body[0]) { showErr("body", "Your message needs at least 5 characters."); bad = bad || "body"; }
    else if (body.length > LIMITS.body[1]) { showErr("body", "Your message can be up to 2,000 characters."); bad = bad || "body"; }
    if (bad) { field(bad).focus({ preventScroll: true }); return null; }
    return { subject: subject, body: body };
  }

  /* ---- popup: same markup and classes as partials/review_thanks.html, so it looks and behaves the same */
  function popup(ok, title, text) {
    var opener = document.activeElement, closed = false;
    var pop = document.createElement("div");
    pop.className = "rt" + (ok ? "" : " rt--error"); pop.setAttribute("role", ok ? "dialog" : "alertdialog");
    pop.setAttribute("aria-modal", "true"); pop.setAttribute("aria-labelledby", "sf-title"); pop.setAttribute("aria-describedby", "sf-text");
    pop.innerHTML =
      '<div class="rt__backdrop" data-rt-close></div>' +
      '<div class="rt__card" tabindex="-1" aria-live="assertive">' +
      '<button class="rt__x" type="button" data-rt-close aria-label="Close">&times;</button>' +
      '<div class="rt__heart" aria-hidden="true"></div><h2 class="rt__title" id="sf-title"></h2>' +
      '<p class="rt__lead" id="sf-text"></p>' +
      (ok ? '<p class="rt__text">Our Admin team and Shop Owner can both see it. You can read their reply in My messages.</p>' : '') +
      '<button class="btn rt__btn" type="button" data-rt-close>' + (ok ? "Close" : "Try again") + "</button></div>";
    pop.querySelector(".rt__heart").textContent = ok ? "\u2705" : "\u26A0\uFE0F";
    pop.querySelector("#sf-title").textContent = title;
    pop.querySelector("#sf-text").textContent = text;
    document.body.appendChild(pop);
    var scrollY = window.scrollY;
    document.documentElement.classList.add("nolock");
    var card = pop.querySelector(".rt__card"); card.focus({ preventScroll: true });
    function close() {
      if (closed) return; closed = true;
      document.removeEventListener("keydown", onKey, true);
      pop.classList.add("is-closing"); document.documentElement.classList.remove("nolock");
      setTimeout(function () {
        pop.remove();
        window.scrollTo(0, scrollY);                     // exactly where the form was
        if (opener && opener.focus) try { opener.focus({ preventScroll: true }); } catch (e) { /* gone */ }
      }, reduce ? 0 : 320);
    }
    function onKey(e) {
      if (e.key === "Escape") { e.preventDefault(); close(); }
      else if (e.key === "Tab") {                       // keep Tab inside the dialog
        var f = pop.querySelectorAll("button"), first = f[0], last = f[f.length - 1];
        if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
        else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
        else if (!pop.contains(document.activeElement)) { e.preventDefault(); first.focus(); }
      }
    }
    pop.addEventListener("click", function (e) { if (e.target.closest("[data-rt-close]")) close(); });
    document.addEventListener("keydown", onKey, true);
  }

  function setBusy(on) {
    sending = on; btn.disabled = on; btn.setAttribute("aria-busy", on ? "true" : "false");
    if (on) { btn.dataset.label = btn.textContent; btn.textContent = "Sending..."; } else btn.textContent = btn.dataset.label || "Send message";
  }

  form.addEventListener("input", function (e) { if (e.target.name) showErr(e.target.name, ""); });
  form.addEventListener("submit", function (e) {
    e.preventDefault();
    if (sending) return;
    var data = validate(); if (!data) return;
    setBusy(true);
    fetch(form.getAttribute("data-quick-url"), {
      method: "POST", credentials: "same-origin",
      headers: { "Content-Type": "application/json", Accept: "application/json", "X-CSRFToken": csrf },
      body: JSON.stringify(data)
    }).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (d) { return { s: r.status, d: d }; });
    }).then(function (res) {
      setBusy(false);
      if (res.d.ok) { form.reset(); clearErrs(); popup(true, "Message sent", res.d.message || "Your message was sent successfully."); return; }
      if (res.s === 401 && res.d.login) { window.location.assign(res.d.login); return; }
      if (res.s === 422 && res.d.errors) {
        Object.keys(res.d.errors).forEach(function (k) { showErr(k, res.d.errors[k]); });
        var first = res.d.errors.subject ? "subject" : "body"; field(first).focus({ preventScroll: true }); return;
      }
      var msg = res.s === 429 ? "You have sent several messages already. Please try again a little later." :
        res.s === 400 ? "For your safety this form expired. Please reload the page and try again." :
        (res.d.message || "We could not send your message right now. Please try again in a moment.");
      popup(false, "Message not sent", msg);
    }).catch(function () {
      setBusy(false); popup(false, "Message not sent", "No connection. Please check your internet and try again.");
    });
  });
})();
