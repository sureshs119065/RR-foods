/* Storefront shell: categories mega menu, announcement bar, collapsible footer columns. Plain JavaScript. */
(function () {
  "use strict";
  var $ = function (s, r) { return (r || document).querySelector(s); };
  var $$ = function (s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); };

  /* ---------- categories mega menu (desktop) ---------- */
  var btn = $("#mega-btn"), mega = $("#mega");
  function setMega(on) {
    if (!btn || !mega) return;
    mega.hidden = !on; btn.setAttribute("aria-expanded", on ? "true" : "false");
  }
  if (btn && mega) {
    var header = $("#sh");
    btn.addEventListener("click", function (e) {
      e.stopPropagation();
      setMega(matchMedia("(min-width:1024px)").matches ? true : mega.hidden);
    });
    // Desktop pointer and keyboard users can open the menu without clicking.
    btn.addEventListener("mouseenter", function () { if (matchMedia("(min-width:1024px)").matches) setMega(true); });
    btn.addEventListener("focus", function () { if (matchMedia("(min-width:1024px)").matches) setMega(true); });
    if (header) header.addEventListener("mouseleave", function () {
      if (matchMedia("(min-width:1024px)").matches) setMega(false);
    });
    document.addEventListener("click", function (e) {
      if (!mega.hidden && !mega.contains(e.target) && e.target !== btn && !btn.contains(e.target)) setMega(false);
    });
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && !mega.hidden) { setMega(false); btn.focus(); }
    });
    window.addEventListener("resize", function () { if (!matchMedia("(min-width:1024px)").matches) setMega(false); });
  }

  /* ---------- announcement bar: pause and dismiss (dismissal lasts for this visit) ---------- */
  var ann = $("#announce"), pause = $("#announce-pause"), close = $("#announce-close"), marq = $("#announce-marquee");
  try { if (ann && sessionStorage.getItem("nk-ann-closed") === "1") ann.hidden = true; } catch (e) { /* storage blocked: keep the bar */ }
  if (pause && marq) pause.addEventListener("click", function () {
    var on = marq.getAttribute("data-paused") !== "true";
    marq.setAttribute("data-paused", on ? "true" : "false"); pause.setAttribute("aria-pressed", on ? "true" : "false");
    pause.setAttribute("aria-label", on ? "Resume scrolling announcements" : "Pause scrolling announcements");
  });
  if (close && ann) close.addEventListener("click", function () {
    ann.hidden = true;
    try { sessionStorage.setItem("nk-ann-closed", "1"); } catch (e) { /* ignore */ }
  });

  /* ---------- footer columns: collapsible on phones, always open from tablet width ---------- */
  var cols = $$("[data-col]");
  if (cols.length && window.matchMedia) {
    var mq = matchMedia("(min-width: 768px)");
    var sync = function () { cols.forEach(function (d) { d.open = mq.matches; }); };
    sync();
    if (mq.addEventListener) mq.addEventListener("change", sync);
  }
})();

/* ---------- home page scroll rows: arrow buttons ---------- */
(function () {
  "use strict";
  function track(id) { return document.getElementById(id); }
  document.addEventListener("click", function (e) {
    var b = e.target.closest("[data-row-prev],[data-row-next]"); if (!b) return;
    var t = track(b.getAttribute("data-row-prev") || b.getAttribute("data-row-next")); if (!t) return;
    var dir = b.hasAttribute("data-row-prev") ? -1 : 1;
    t.scrollBy({ left: dir * Math.max(t.clientWidth * 0.8, 200), behavior: "smooth" });
  });
  function sync(t) {
    ["prev", "next"].forEach(function (k) {
      var btn = document.querySelector("[data-row-" + k + "=" + t.id + "]"); if (!btn) return;
      btn.disabled = k === "prev" ? t.scrollLeft <= 4 : t.scrollLeft + t.clientWidth >= t.scrollWidth - 4;
    });
  }
  Array.prototype.forEach.call(document.querySelectorAll(".snaprow[id]"), function (t) {
    t.addEventListener("scroll", function () { sync(t); }, { passive: true }); window.addEventListener("resize", function () { sync(t); }); sync(t);
  });
})();


