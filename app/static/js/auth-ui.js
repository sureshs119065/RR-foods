/* Auth pages: (1) switch between the password view and the email-code view, (2) show/hide eye on every password box,
   (3) "Remember Me" keeps the email address on this device. The pages work without this file (the password form still posts). */
(function () {
  "use strict";

  var panels = {};
  document.querySelectorAll("[data-panel]").forEach(function (p) { panels[p.getAttribute("data-panel")] = p; });
  var emailIn = function (name) { return panels[name] && panels[name].querySelector("input[type=email]"); };

  /* show one panel, carry a typed email over so nobody types it twice, optionally move focus into it */
  var selectPanel = function (name, focusFirst) {
    if (!panels[name]) return;
    var from = Object.keys(panels).filter(function (k) { return !panels[k].hidden; })[0];
    var a = from && emailIn(from), b = emailIn(name);
    if (a && b && a.value && !b.value) b.value = a.value;
    Object.keys(panels).forEach(function (k) { panels[k].hidden = k !== name; });
    var tabsBar = document.querySelector("[data-tabs]");
    if (tabsBar) {
      tabsBar.querySelectorAll("[data-tab]").forEach(function (t) {
        var on = t.getAttribute("data-tab") === name;
        t.setAttribute("aria-selected", on ? "true" : "false");
        t.tabIndex = on ? 0 : -1;
      });
    }
    if (focusFirst) {
      var visible = panels[name].querySelector("[data-step]:not([hidden]) input, input:not([type=hidden])");
      if (visible) visible.focus();
    }
  };

  /* ---- 1a. buttons that swap views: <button data-switch="code|password"> ---- */
  document.querySelectorAll("[data-switch]").forEach(function (btn) {
    btn.addEventListener("click", function () { selectPanel(btn.getAttribute("data-switch"), true); });
  });

  /* ---- 1b. tab bar (kept for any page that still uses role=tablist): Email code | Password ---- */
  var tabsBar = document.querySelector("[data-tabs]");
  if (tabsBar) {
    var tabs = Array.prototype.slice.call(tabsBar.querySelectorAll("[data-tab]"));
    tabs.forEach(function (t, i) {
      t.addEventListener("click", function () { selectPanel(t.getAttribute("data-tab"), true); });
      t.addEventListener("keydown", function (e) {
        var j = e.key === "ArrowRight" ? i + 1 : e.key === "ArrowLeft" ? i - 1 : -1;
        if (j < 0) return;
        e.preventDefault();
        var next = tabs[(j + tabs.length) % tabs.length];
        next.click(); next.focus();
      });
    });
  }

  /* ---- 2. eye button on password inputs. Hidden = crossed eye, shown = open eye. aria-pressed is true while the password is visible ---- */
  var SVG = '<svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">';
  var EYE = SVG + '<path d="M1 12s4-7 11-7 11 7 11 7-4 7-11 7S1 12 1 12z"/><circle cx="12" cy="12" r="3"/></svg>';
  var EYE_OFF = SVG + '<path d="M17.94 17.94A10.9 10.9 0 0 1 12 19c-7 0-11-7-11-7a19.8 19.8 0 0 1 5.06-5.94"/><path d="M9.9 4.24A10.9 10.9 0 0 1 12 5c7 0 11 7 11 7a19.8 19.8 0 0 1-3.17 4.19"/><path d="M14.12 14.12A3 3 0 1 1 9.88 9.88"/><line x1="1" y1="1" x2="23" y2="23"/></svg>';

  document.querySelectorAll("input[type=password]").forEach(function (input) {
    if (input.closest(".pw")) return;
    var wrap = document.createElement("span");
    wrap.className = "pw";
    input.parentNode.insertBefore(wrap, input);
    wrap.appendChild(input);

    var btn = document.createElement("button");
    btn.type = "button";
    btn.className = "pw__eye";
    btn.setAttribute("aria-label", "Show password");
    btn.setAttribute("aria-pressed", "false");
    btn.innerHTML = EYE_OFF;
    wrap.appendChild(btn);

    btn.addEventListener("click", function () {
      var show = input.type === "password";
      input.type = show ? "text" : "password";
      btn.innerHTML = show ? EYE : EYE_OFF;
      btn.setAttribute("aria-label", show ? "Hide password" : "Show password");
      btn.setAttribute("aria-pressed", show ? "true" : "false");
      input.focus();
      try { var n = input.value.length; input.setSelectionRange(n, n); } catch (_) { /* some types do not support it */ }
    });
  });

  /* ---- 3. Remember Me: store only the email address, only in this browser, only while the box is ticked ---- */
  var KEY = "rr_auth_email";
  var remember = document.querySelector("[data-remember]");
  if (remember && remember.form) {
    var form = remember.form, email = form.querySelector("input[type=email]");
    var store = function (fn) { try { return fn(window.localStorage); } catch (_) { return null; } };  // storage can be blocked
    var saved = store(function (s) { return s.getItem(KEY); });
    if (saved && email) {
      remember.checked = true;
      if (!email.value) {
        email.value = saved;
        var pw = form.querySelector("input[name=password]");   // email is filled, so the next thing to type is the password
        if (pw && document.activeElement === email) pw.focus();
      }
    }
    form.addEventListener("submit", function () {
      if (remember.checked && email && email.value) store(function (s) { s.setItem(KEY, email.value.trim()); });
      else store(function (s) { s.removeItem(KEY); });
    });
  }

  /* ---- 4. on-screen keyboard: keep the focused field visible inside the scrolling card (the page itself never scrolls) ---- */
  var FIELD = "input:not([type=hidden]):not([type=checkbox]):not([type=radio]):not([type=submit]), select, textarea";
  var calm = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var keepVisible = function (el) {
    var wrap = el.closest && el.closest(".auth-wrap");
    if (wrap) {                                   // already fully on screen: leave the scroll position alone
      var r = el.getBoundingClientRect(), w = wrap.getBoundingClientRect();
      var vh = window.visualViewport ? window.visualViewport.height : window.innerHeight;
      if (r.top >= Math.max(w.top, 0) + 8 && r.bottom <= Math.min(w.bottom, vh) - 8) return;
    }
    try { el.scrollIntoView({ block: "center", inline: "nearest", behavior: calm ? "auto" : "smooth" }); }
    catch (_) { el.scrollIntoView(true); }
  };
  var activeField = function () {
    var a = document.activeElement;
    return a && a.matches && a.matches(FIELD) ? a : null;
  };
  document.addEventListener("focusin", function (e) {
    var el = e.target;
    if (!el.matches || !el.matches(FIELD)) return;
    window.setTimeout(function () { if (document.activeElement === el) keepVisible(el); }, 300);   // let the keyboard finish opening
  });
  if (window.visualViewport) {
    window.visualViewport.addEventListener("resize", function () { var a = activeField(); if (a) keepVisible(a); });
  }
})();
