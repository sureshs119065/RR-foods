/* RR FOODS quality journey: nurse guide. Rewritten for stable scroll sync. */
(function () {
  "use strict";
  var root = document.querySelector("[data-nurse-guide]");
  if (!root) return;
  var stages = Array.prototype.slice.call(root.querySelectorAll("[data-nurse-stage]"));
  if (!stages.length) return;
  function q(sel) { return root.querySelector(sel); }
  var guide = q(".nurse-guide__guide"), timeline = q(".nurse-guide__timeline"), rail = q(".nurse-guide__rail");
  var title = q("[data-nurse-title]"), speech = q("[data-nurse-speech]"), live = q("[data-nurse-live]");
  var progress = q("[data-nurse-progress]"), finish = q("[data-nurse-finish]"), confetti = q("[data-nurse-confetti]");
  var prev = q("[data-nurse-prev]"), next = q("[data-nurse-next]"), counter = q("[data-nurse-counter]"), meter = q("[data-nurse-meter]");
  var header = document.getElementById("sh");
  var reduce = window.matchMedia("(prefers-reduced-motion: reduce)");
  var mobile = window.matchMedia("(max-width: 760px)");
  var last = stages.length - 1;
  var active = -1, completed = false, typingTimer = 0, lockUntil = 0, lockTimer = 0, queued = false;

  var data = stages.map(function (item) {
    var h = item.querySelector("h3"), p = item.querySelector(".nurse-stage__card > p:not(.nurse-stage__eyebrow)");
    return {
      title: h ? h.textContent.trim() : "",
      text: p ? p.textContent.replace(/\s+/g, " ").trim() : "",
      pose: item.dataset.stagePose || "sourcing"
    };
  });

  function headerBottom() { return header ? Math.max(0, header.getBoundingClientRect().bottom) : 0; }
  function topOffset() { return headerBottom() + (mobile.matches && guide ? guide.offsetHeight + 12 : 12); }
  function readingLine() { var t = topOffset(); return t + (window.innerHeight - t) * 0.3; }

  function syncVars() {
    root.style.setProperty("--ux-header-h", Math.round(headerBottom() || 70) + "px");
    root.style.setProperty("--ux-guide-h", (guide ? Math.round(guide.offsetHeight) : 180) + "px");
  }
  function dotCenter(i) {
    var d = stages[i].querySelector(".nurse-stage__dot");
    var r = d ? d.getBoundingClientRect() : stages[i].getBoundingClientRect();
    return r.top + r.height / 2;
  }
  function layoutRail() {
    if (!rail || !timeline) return;
    var tl = timeline.getBoundingClientRect(), a = dotCenter(0), b = dotCenter(last);
    rail.style.top = (a - tl.top) + "px";
    rail.style.bottom = "auto";
    rail.style.height = Math.max(0, b - a) + "px";
  }

  function countStat(i) {
    var el = stages[i].querySelector("[data-nurse-count]");
    if (!el || el.dataset.counted) return;
    el.dataset.counted = "1";
    var target = Number(el.dataset.nurseCount || 0), suffix = el.dataset.suffix || "";
    if (reduce.matches || !target) { el.textContent = String(target) + suffix; return; }
    var start = performance.now(), dur = 850;
    (function tick(now) {
      var t = Math.min(1, (now - start) / dur);
      el.textContent = Math.round(target * (1 - Math.pow(1 - t, 3))) + suffix;
      if (t < 1) requestAnimationFrame(tick);
    })(start);
  }

  function say(text) {
    window.clearInterval(typingTimer);
    if (live) live.textContent = text;
    if (!speech) return;
    if (reduce.matches) { speech.textContent = text; return; }
    speech.textContent = "";
    var i = 0;
    typingTimer = window.setInterval(function () {
      i += 1;
      speech.textContent = text.slice(0, i);
      if (i >= text.length) window.clearInterval(typingTimer);
    }, 14);
  }

  function burst() {
    if (!confetti || reduce.matches) return;
    confetti.innerHTML = "";
    var colors = ["#f5a623", "#1f5c3a", "#e56b45", "#8dbb78", "#e6c85c"];
    for (var i = 0; i < 28; i++) {
      var piece = document.createElement("i");
      piece.className = "nurse-confetti-piece";
      piece.style.setProperty("--confetti-color", colors[i % colors.length]);
      piece.style.setProperty("--angle", (i * 29) + "deg");
      piece.style.setProperty("--dx", (Math.cos(i * 0.7) * (45 + i % 5 * 13)) + "px");
      piece.style.setProperty("--dy", (Math.sin(i * 0.7) * (45 + i % 5 * 13) - 35) + "px");
      confetti.appendChild(piece);
    }
    window.setTimeout(function () { confetti.innerHTML = ""; }, 1100);
  }

  function render() {
    var atEnd = completed && active === last;
    root.dataset.pose = atEnd ? "complete" : data[active].pose;
    stages.forEach(function (stage, i) {
      stage.classList.toggle("is-active", i === active);
      stage.classList.toggle("is-complete", completed || i < active);
      var dot = stage.querySelector("[data-nurse-jump]");
      if (dot) { if (i === active) dot.setAttribute("aria-current", "step"); else dot.removeAttribute("aria-current"); }
    });
    if (counter) counter.textContent = completed ? "All " + stages.length + " stages completed" : "Stage " + (active + 1) + " of " + stages.length;
    if (meter) meter.style.width = (completed ? 100 : ((active + 1) / stages.length) * 100) + "%";
    if (prev) prev.disabled = active === 0;
    if (next) next.textContent = active < last ? "Next stage →" : (completed ? "Replay journey ↺" : "Finish journey ✓");
    if (finish) finish.hidden = !atEnd;
  }

  function setStage(i) {
    i = Math.max(0, Math.min(last, i));
    var changed = i !== active;
    active = i;
    root.classList.add("is-moving");
    window.clearTimeout(root._moveTimer);
    root._moveTimer = window.setTimeout(function () { root.classList.remove("is-moving"); }, 700);
    if (title) title.textContent = "Step " + (i + 1) + " · " + data[i].title;
    if (changed || !speech.textContent) say(completed && i === last ? "That's our promise: thoughtful care at every stage. Thank you for choosing RR FOODS!" : data[i].text);
    render();
    countStat(i);
  }

  function complete() {
    if (completed) return;
    completed = true;
    active = last;
    if (title) title.textContent = "Quality care, from start to finish";
    say("That's our promise: thoughtful care at every stage. Thank you for choosing RR FOODS!");
    render();
    burst();
  }

  function lock() {
    lockUntil = performance.now() + 1000;
    window.clearTimeout(lockTimer);
    lockTimer = window.setTimeout(update, 1050);
  }
  function goTo(i) {
    i = Math.max(0, Math.min(last, i));
    lock();
    setStage(i);
    syncVars();
    stages[i].scrollIntoView({ behavior: reduce.matches ? "auto" : "smooth", block: "start" });
  }
  function replay() {
    completed = false;
    stages.forEach(function (s) { s.classList.remove("is-complete"); });
    active = -1;
    goTo(0);
  }

  function update() {
    queued = false;
    if (performance.now() < lockUntil) return;
    var line = readingLine(), best = 0;
    stages.forEach(function (stage, i) { if (stage.getBoundingClientRect().top <= line) best = i; });
    var doc = document.documentElement;
    if (window.innerHeight + window.scrollY >= doc.scrollHeight - 2) best = last;
    if (best !== active) setStage(best);
    var a = dotCenter(0), b = dotCenter(last);
    var amount = b > a ? Math.max(0, Math.min(1, (line - a) / (b - a))) : 0;
    if (progress) progress.style.transform = "scaleY(" + amount + ")";
    if (!completed && best === last && stages[last].getBoundingClientRect().bottom < window.innerHeight * 0.85) complete();
  }
  function queueUpdate() { if (queued) return; queued = true; requestAnimationFrame(update); }
  function relayout() { syncVars(); layoutRail(); queueUpdate(); }

  stages.forEach(function (stage, i) {
    var dot = stage.querySelector("[data-nurse-jump]");
    if (dot) dot.addEventListener("click", function () { goTo(i); });
  });
  if (prev) prev.addEventListener("click", function () { if (active > 0) goTo(active - 1); });
  if (next) next.addEventListener("click", function () {
    if (active < last) goTo(active + 1);
    else if (!completed) { lock(); complete(); }
    else replay();
  });

  window.addEventListener("scroll", queueUpdate, { passive: true });
  window.addEventListener("resize", relayout, { passive: true });
  if (window.ResizeObserver && timeline) new ResizeObserver(relayout).observe(timeline);

  syncVars();
  layoutRail();
  setStage(0);
  update();
})();
