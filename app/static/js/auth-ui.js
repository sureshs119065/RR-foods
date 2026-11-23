/* Sign in / create account pages: (1) one sign-in method visible at a time (tabs), (2) show/hide eye on every password box. */
(function () {
  "use strict";

  /* ---- 1. tabs: Email code | Password ---- */
  var tabsBar = document.querySelector("[data-tabs]");
  if (tabsBar) {
    var tabs = Array.prototype.slice.call(tabsBar.querySelectorAll("[data-tab]"));
    var panels = {};
    document.querySelectorAll("[data-panel]").forEach(function (p) { panels[p.getAttribute("data-panel")] = p; });

    var select = function (name, focusFirst) {
      tabs.forEach(function (t) {
        var on = t.getAttribute("data-tab") === name;
        t.setAttribute("aria-selected", on ? "true" : "false");
        t.tabIndex = on ? 0 : -1;
      });
      Object.keys(panels).forEach(function (k) { panels[k].hidden = k !== name; });
      if (focusFirst) {
        var visible = panels[name].querySelector("[data-step]:not([hidden]) input, input:not([type=hidden])");
        if (visible) visible.focus();
      }
    };

    /* carry a typed email over to the other tab so nobody types it twice */
    var emailIn = function (name) { return panels[name] && panels[name].querySelector("input[type=email]"); };
    tabs.forEach(function (t, i) {
      t.addEventListener("click", function () {
        var from = t.getAttribute("data-tab") === "code" ? "password" : "code", to = t.getAttribute("data-tab");
        var a = emailIn(from), b = emailIn(to);
        if (a && b && a.value && !b.value) b.value = a.value;
        select(to, true);
      });
      t.addEventListener("keydown", function (e) {
        var j = e.key === "ArrowRight" ? i + 1 : e.key === "ArrowLeft" ? i - 1 : -1;
        if (j < 0) return;
        e.preventDefault();
        var next = tabs[(j + tabs.length) % tabs.length];
        next.click(); next.focus();
      });
    });
  }

  /* ---- 2. eye button on password inputs ---- */
  var EYE = '<svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false"><path d="M1 12s4-7 11-7 11 7 11 7-4 7-11 7S1 12 1 12z"/><circle cx="12" cy="12" r="3"/></svg>';
  var EYE_OFF = '<svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false"><path d="M17.94 17.94A10.9 10.9 0 0 1 12 19c-7 0-11-7-11-7a19.8 19.8 0 0 1 5.06-5.94"/><path d="M9.9 4.24A10.9 10.9 0 0 1 12 5c7 0 11 7 11 7a19.8 19.8 0 0 1-3.17 4.19"/><path d="M14.12 14.12A3 3 0 1 1 9.88 9.88"/><line x1="1" y1="1" x2="23" y2="23"/></svg>';

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
    btn.innerHTML = EYE;
    wrap.appendChild(btn);

    btn.addEventListener("click", function () {
      var show = input.type === "password";
      input.type = show ? "text" : "password";
      btn.innerHTML = show ? EYE_OFF : EYE;
      btn.setAttribute("aria-label", show ? "Hide password" : "Show password");
      btn.setAttribute("aria-pressed", show ? "true" : "false");
      input.focus();
      try { var n = input.value.length; input.setSelectionRange(n, n); } catch (_) { /* some types do not support it */ }
    });
  });
})();
