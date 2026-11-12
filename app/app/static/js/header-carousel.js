/* Header offer carousel. Vanilla JS, no library.
   Slide mode uses native scroll-snap (so swipe has real momentum); fade mode stacks the slides.
   Auto-advance every `data-interval` ms, pauses on hover/touch/focus/hidden tab/reduced motion, wraps around forever. */
(function () {
  "use strict";
  var root = document.querySelector("[data-hc]");
  if (!root) return;
  var $ = function (s, r) { return (r || root).querySelector(s); };
  var $$ = function (s, r) { return Array.prototype.slice.call((r || root).querySelectorAll(s)); };

  var track = $(".hc__track"), view = $(".hc__viewport");
  var slides = $$(".hc__slide"), dots = $$("[data-hc-dot]");
  var fade = root.getAttribute("data-transition") === "fade";
  var interval = Math.max(2000, parseInt(root.getAttribute("data-interval"), 10) || 5000);
  var reduce = window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches;
  var wantAuto = root.getAttribute("data-autoplay") === "1" && !reduce;
  var index = 0, timer = null, hold = { hover: false, touch: false, focus: false, hidden: document.hidden, user: false };
  var bar = $(".hc__progress span"), anim = null, pauseBtn = $("[data-hc-pause]");

  function width() { return track.clientWidth || 1; }
  function paintDots() { dots.forEach(function (d, i) { d.setAttribute("aria-selected", i === index ? "true" : "false"); }); slides.forEach(function (s, i) { s.classList.toggle("is-active", i === index); s.setAttribute("aria-hidden", i === index || !fade ? "false" : "true"); }); }
  function go(i, instant) {
    if (!slides.length) return;
    index = (i + slides.length) % slides.length;
    if (!fade) track.scrollTo({ left: index * width(), behavior: instant || reduce ? "auto" : "smooth" });
    paintDots(); restart();
  }
  function next() { go(index + 1); } function prev() { go(index - 1); }

  /* progress bar + timer share one Web Animation, so pausing freezes both */
  function paused() { return hold.hover || hold.touch || hold.focus || hold.hidden || hold.user; }
  function restart() {
    clearTimeout(timer); if (anim) { anim.cancel(); anim = null; }
    if (!wantAuto || slides.length < 2) return;
    if (bar && bar.animate) { anim = bar.animate([{ transform: "scaleX(0)" }, { transform: "scaleX(1)" }], { duration: interval, fill: "forwards", easing: "linear" }); anim.onfinish = function () { if (!paused()) next(); else anim && anim.pause(); }; if (paused()) anim.pause(); }
    else if (!paused()) timer = setTimeout(next, interval);
  }
  function sync() { if (!wantAuto) return; if (anim) { paused() ? anim.pause() : anim.play(); } else if (!paused()) restart(); }

  /* the scroll position decides the current slide, so swipes and arrow keys stay in step */
  var st;
  if (!fade) track.addEventListener("scroll", function () { clearTimeout(st); st = setTimeout(function () { var i = Math.round(track.scrollLeft / width()); if (i !== index && i >= 0 && i < slides.length) { index = i; paintDots(); restart(); } }, 80); }, { passive: true });
  if (window.ResizeObserver && !fade) new ResizeObserver(function () { track.scrollTo({ left: index * width(), behavior: "auto" }); }).observe(track); // keep the slide aligned when the window resizes or the phone rotates

  /* controls */
  var pb = $("[data-hc-prev]"), nb = $("[data-hc-next]");
  if (pb) pb.addEventListener("click", prev); if (nb) nb.addEventListener("click", next);
  dots.forEach(function (d) { d.addEventListener("click", function () { go(parseInt(d.getAttribute("data-hc-dot"), 10)); }); });
  view.addEventListener("keydown", function (e) { if (e.key === "ArrowLeft") { e.preventDefault(); prev(); } else if (e.key === "ArrowRight") { e.preventDefault(); next(); } });
  if (pauseBtn) {
    if (!wantAuto) pauseBtn.hidden = true;
    pauseBtn.addEventListener("click", function () { hold.user = !hold.user; pauseBtn.setAttribute("aria-pressed", hold.user ? "true" : "false"); pauseBtn.setAttribute("aria-label", hold.user ? "Resume automatic sliding" : "Pause automatic sliding"); pauseBtn.firstElementChild.textContent = hold.user ? "▶" : "❚❚"; sync(); });
  }
  /* pause on hover / touch / keyboard focus, resume on leave */
  root.addEventListener("mouseenter", function () { hold.hover = true; sync(); }); root.addEventListener("mouseleave", function () { hold.hover = false; sync(); });
  root.addEventListener("touchstart", function () { hold.touch = true; sync(); }, { passive: true });
  ["touchend", "touchcancel"].forEach(function (t) { root.addEventListener(t, function () { setTimeout(function () { hold.touch = false; sync(); }, 1200); }, { passive: true }); });
  root.addEventListener("focusin", function () { hold.focus = true; sync(); }); root.addEventListener("focusout", function () { hold.focus = false; sync(); });
  document.addEventListener("visibilitychange", function () { hold.hidden = document.hidden; sync(); }); // Page Visibility API: no sliding in a background tab

  /* fade mode has no scrolling, so swipe is handled by hand */
  if (fade) {
    var x0 = null;
    view.addEventListener("touchstart", function (e) { x0 = e.touches[0].clientX; }, { passive: true });
    view.addEventListener("touchend", function (e) { if (x0 === null) return; var dx = e.changedTouches[0].clientX - x0; x0 = null; if (Math.abs(dx) > 40) (dx < 0 ? next : prev)(); }, { passive: true });
  }

  /* countdowns: use the server clock so a wrong phone clock cannot show a wrong time */
  var offset = (Date.parse(root.getAttribute("data-server-now")) || Date.now()) - Date.now();
  function pad(n) { return (n < 10 ? "0" : "") + n; }
  function removeSlide(el) {
    var i = slides.indexOf(el); if (i < 0) return;
    el.remove(); slides.splice(i, 1);
    var d = dots[i]; if (d) { d.remove(); dots.splice(i, 1); }
    dots.forEach(function (x, k) { x.setAttribute("data-hc-dot", k); });
    if (!slides.length) { root.remove(); return; }
    if (slides.length < 2) { wantAuto = false; $$(".hc__nav,.hc__bar,.hc__progress").forEach(function (n) { n.remove(); }); if (anim) anim.cancel(); }
    go(Math.min(index, slides.length - 1), true);
  }
  var cds = $$("[data-countdown]");
  function tickCountdown() {
    var now = Date.now() + offset;
    cds.slice().forEach(function (el) {
      var left = Math.floor((Date.parse(el.getAttribute("data-countdown")) - now) / 1000);
      if (isNaN(left)) { el.remove(); cds = cds.filter(function (c) { return c !== el; }); return; }
      if (left <= 0) { cds = cds.filter(function (c) { return c !== el; }); removeSlide(el.closest(".hc__slide")); return; } // expired while the page was open
      var d = Math.floor(left / 86400), h = Math.floor(left % 86400 / 3600), m = Math.floor(left % 3600 / 60), s = left % 60;
      el.textContent = "Ends in " + (d ? d + "d " : "") + pad(h) + ":" + pad(m) + ":" + pad(s);
    });
  }
  if (cds.length) { tickCountdown(); setInterval(function () { if (!document.hidden) tickCountdown(); }, 1000); document.addEventListener("visibilitychange", function () { if (!document.hidden) tickCountdown(); }); }

  paintDots(); restart();
})();
