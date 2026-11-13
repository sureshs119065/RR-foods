/* Admin + owner dashboard polish: entrance motion, count-up numbers, greeting, refresh, KPI filter.
   Purely visual. It never changes data, forms or links, and the page works without it. */
(function () {
  "use strict";
  var reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var $ = function (s, r) { return (r || document).querySelector(s); };
  var $$ = function (s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); };

  function ready(fn) { if (document.readyState !== "loading") fn(); else document.addEventListener("DOMContentLoaded", fn); }

  ready(function () {
    var topbar = $(".adm__top");
    if (topbar) {
      var onScroll = function () { topbar.classList.toggle("is-scrolled", window.scrollY > 6); };
      window.addEventListener("scroll", onScroll, { passive: true }); onScroll();
    }

    var isDash = $(".admin-hero, .owner-hero");
    if (!isDash) return;

    /* greeting + date */
    var greet = $("[data-dp-greet]");
    if (greet) {
      var who = (($(".adm__top .hint") || {}).textContent || "").trim().split(/\s+/)[0];
      var h = new Date().getHours();
      var part = h < 12 ? "Good morning" : h < 17 ? "Good afternoon" : "Good evening";
      var date = new Date().toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "long" });
      greet.textContent = part + (who ? ", " + who : "") + " · " + date;
    }

    /* refresh + "updated x ago" */
    var loadedAt = Date.now();
    var btn = $("[data-dp-refresh]"), label = $("[data-dp-updated]");
    function tick() {
      if (!label) return;
      var m = Math.floor((Date.now() - loadedAt) / 60000);
      label.textContent = m < 1 ? "Updated just now" : "Updated " + m + " min ago";
    }
    setInterval(tick, 30000);
    if (btn) btn.addEventListener("click", function () {
      btn.classList.add("is-spinning");
      if (label) label.textContent = "Refreshing…";
      setTimeout(function () { window.location.reload(); }, reduce ? 0 : 450);
    });

    /* KPI count-up (whole numbers only; sales analytics figures are left to their own script) */
    function countUp(el) {
      var raw = el.textContent.trim();
      if (!/^\d[\d,]*$/.test(raw)) return;
      var end = parseInt(raw.replace(/,/g, ""), 10);
      if (!end || end > 1e7) return;
      var t0 = null, dur = 750;
      el.setAttribute("aria-label", raw);
      function step(ts) {
        if (t0 === null) t0 = ts;
        var p = Math.min(1, (ts - t0) / dur), e = 1 - Math.pow(1 - p, 3);
        el.textContent = Math.round(end * e).toLocaleString("en-IN");
        if (p < 1) requestAnimationFrame(step); else el.textContent = raw;
      }
      requestAnimationFrame(step);
    }

    /* staggered reveal */
    var targets = $$(".admin-hero,.owner-hero,.dp-attn,.admin-kpi,.owner-kpi,.sales-analytics,.ops-demo-panel,.ops-dashboard-lower,.admin-action-grid a,.owner-ops-card");
    var counted = new WeakSet();
    function show(el, i) {
      el.style.setProperty("--dp-d", Math.min(i, 10) * 55 + "ms");
      el.classList.add("dp-in");
      var n = el.matches(".admin-kpi,.owner-kpi") ? el.querySelector(":scope > strong") : null;
      if (n && !counted.has(n) && !reduce) { counted.add(n); setTimeout(function () { countUp(n); }, Math.min(i, 10) * 55); }
    }
    if (reduce || !("IntersectionObserver" in window)) {
      targets.forEach(function (el) { el.classList.add("dp-in"); });
    } else {
      document.documentElement.classList.add("dp-ready");
      targets.forEach(function (el) { el.classList.add("dp-pre"); });
      var seen = 0;
      var io = new IntersectionObserver(function (entries) {
        entries.forEach(function (en) {
          if (!en.isIntersecting) return;
          io.unobserve(en.target); show(en.target, seen++);
        });
        setTimeout(function () { seen = 0; }, 400);
      }, { threshold: 0.08, rootMargin: "0px 0px -30px 0px" });
      targets.forEach(function (el) { io.observe(el); });
      /* safety net: never leave anything hidden */
      setTimeout(function () { targets.forEach(function (el) { el.classList.add("dp-in"); }); }, 2500);
    }

    /* KPI spotlight follows the pointer */
    $$(".admin-kpi,.owner-kpi").forEach(function (k) {
      k.addEventListener("pointermove", function (e) {
        var r = k.getBoundingClientRect();
        k.style.setProperty("--mx", (e.clientX - r.left) + "px");
        k.style.setProperty("--my", (e.clientY - r.top) + "px");
      });
    });

    /* All / Needs attention filter for long KPI grids */
    var grid = $(".admin-kpi-grid");
    if (grid && $$(".admin-kpi", grid).length > 6) {
      var head = grid.parentNode.querySelector(".admin-section-head");
      if (head) {
        var seg = document.createElement("div");
        seg.className = "dp-seg"; seg.setAttribute("role", "group"); seg.setAttribute("aria-label", "Filter indicators");
        seg.innerHTML = '<button type="button" aria-pressed="true" data-f="all">All</button><button type="button" aria-pressed="false" data-f="attn">Needs attention</button>';
        var note = head.querySelector(".admin-section-note");
        if (note) note.replaceWith(seg); else head.appendChild(seg);
        var msg = document.createElement("p");
        msg.className = "dp-seg-note"; msg.hidden = true; msg.textContent = "✓ Nothing needs attention — every indicator looks healthy.";
        grid.parentNode.insertBefore(msg, grid);
        seg.addEventListener("click", function (e) {
          var b = e.target.closest("button"); if (!b) return;
          $$("button", seg).forEach(function (x) { x.setAttribute("aria-pressed", x === b ? "true" : "false"); });
          var only = b.getAttribute("data-f") === "attn", shown = 0;
          $$(".admin-kpi", grid).forEach(function (k) {
            var flag = k.classList.contains("admin-kpi--warning") || k.classList.contains("admin-kpi--critical");
            var hide = only && !flag;
            k.classList.toggle("dp-hide", hide);
            if (!hide) { shown++; k.classList.add("dp-in"); }
          });
          msg.hidden = !(only && shown === 0);
        });
      }
    }
  });
})();
