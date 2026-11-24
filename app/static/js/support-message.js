/* Shared AJAX forms: the contact form (home page + Contact page) and the product "Ask a question" box.
   Any <form data-support-form> is sent with fetch() so the page never reloads or jumps, then the same thank-you popup
   (.rt, same look as the review thank-you) appears. Fields are cleared on success; the button is locked while sending.
   Per-form settings (all optional):  data-quick-url  data-success-title  data-success-text  data-success-note
   Without fetch() the normal form post still works. */
(function () {
  "use strict";
  var forms = document.querySelectorAll("[data-support-form]");
  if (!forms.length || !window.fetch) return;
  var csrf = (document.querySelector("meta[name=csrf-token]") || {}).content || "";
  var reduce = window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches;

  function clean(v) { return (v || "").replace(/[ \t]+$/gm, "").trim(); }

  function popup(ok, title, text, note) {
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
      (ok && note ? '<p class="rt__text" data-note></p>' : '') +
      '<button class="btn rt__btn" type="button" data-rt-close>' + (ok ? "Close" : "Try again") + "</button></div>";
    pop.querySelector(".rt__heart").textContent = ok ? "\u2705" : "\u26A0\uFE0F";
    pop.querySelector("#sf-title").textContent = title;
    pop.querySelector("#sf-text").textContent = text;
    if (ok && note) pop.querySelector("[data-note]").textContent = note;
    document.body.appendChild(pop);
    var scrollY = window.scrollY;
    document.documentElement.classList.add("nolock");
    pop.querySelector(".rt__card").focus({ preventScroll: true });
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

  Array.prototype.forEach.call(forms, function (form) {
    var btn = form.querySelector("[type=submit]"), sending = false;
    var fields = Array.prototype.filter.call(form.elements, function (el) {
      return el.name && el.name !== "csrf_token" && (el.tagName === "INPUT" || el.tagName === "TEXTAREA") && el.type !== "hidden";
    });

    function errEl(name) { return form.querySelector('[data-err="' + name + '"]'); }
    function showErr(name, text) {
      var el = errEl(name), input = form.elements[name];
      if (el) { el.textContent = text || ""; el.hidden = !text; }
      if (input) { if (text) input.setAttribute("aria-invalid", "true"); else input.removeAttribute("aria-invalid"); }
    }
    function clearErrs() { fields.forEach(function (f) { showErr(f.name, ""); }); }
    function label(el) { return el.getAttribute("data-label") || el.name; }

    function validate() {
      var data = {}, bad = null;
      clearErrs();
      fields.forEach(function (el) {
        var multi = el.tagName === "TEXTAREA";
        var val = multi ? clean(el.value) : el.value.replace(/\s+/g, " ").trim(), min = +el.getAttribute("minlength") || 0, max = +el.getAttribute("maxlength") || 0, msg = "";
        if (!val) { if (el.required) msg = "Enter your " + label(el) + "."; }
        else if (min && val.length < min) msg = "Your " + label(el) + " needs at least " + min + " characters.";
        else if (max && val.length > max) msg = "Your " + label(el) + " can be up to " + max.toLocaleString() + " characters.";
        else if (el.type === "email" && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(val)) msg = "Enter a valid email address.";
        if (msg) { showErr(el.name, msg); bad = bad || el; }
        data[el.name] = val;
      });
      if (bad) { bad.focus({ preventScroll: true }); return null; }
      return data;
    }

    function setBusy(on) {
      sending = on; btn.disabled = on; btn.setAttribute("aria-busy", on ? "true" : "false");
      if (on) { btn.dataset.label = btn.textContent; btn.textContent = "Sending..."; } else btn.textContent = btn.dataset.label || btn.textContent;
    }

    form.addEventListener("input", function (e) { if (e.target.name) showErr(e.target.name, ""); });
    form.addEventListener("submit", function (e) {
      e.preventDefault();
      if (sending) return;
      var data = validate(); if (!data) return;
      var title = form.getAttribute("data-success-title") || "Message sent";
      setBusy(true);
      fetch(form.getAttribute("data-quick-url") || form.action, {
        method: "POST", credentials: "same-origin",
        headers: { "Content-Type": "application/json", Accept: "application/json", "X-Requested-With": "XMLHttpRequest", "X-CSRFToken": csrf },
        body: JSON.stringify(data)
      }).then(function (r) {
        return r.json().catch(function () { return {}; }).then(function (d) { return { s: r.status, d: d }; });
      }).then(function (res) {
        setBusy(false);
        if (res.d.ok) {
          form.reset(); clearErrs();
          popup(true, title, form.getAttribute("data-success-text") || res.d.message || "Your message was sent successfully.", form.getAttribute("data-success-note") || res.d.note || "");
          return;
        }
        if (res.s === 401 && res.d.login) { window.location.assign(res.d.login); return; }
        if (res.s === 422 && res.d.errors) {
          var first = null;
          Object.keys(res.d.errors).forEach(function (k) { showErr(k, res.d.errors[k]); first = first || form.elements[k]; });
          if (first) first.focus({ preventScroll: true });
          return;
        }
        var msg = res.s === 429 ? "You have sent several messages already. Please try again a little later." :
          res.s === 400 ? "For your safety this form expired. Please reload the page and try again." :
          (res.d.message || "We could not send your message right now. Please try again in a moment.");
        popup(false, "Message not sent", msg);
      }).catch(function () {
        setBusy(false); popup(false, "Message not sent", "No connection. Please check your internet and try again.");
      });
    });
  });
})();
