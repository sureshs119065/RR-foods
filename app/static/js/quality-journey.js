(function () {
  "use strict";
  var root = document.querySelector("[data-nurse-guide]");
  if (!root) return;
  var stages = Array.prototype.slice.call(root.querySelectorAll("[data-nurse-stage]"));
  var title = root.querySelector("[data-nurse-title]");
  var speech = root.querySelector("[data-nurse-speech]");
  var nurse = root.querySelector("[data-nurse-character]");
  var progress = root.querySelector("[data-nurse-progress]");
  var finish = root.querySelector("[data-nurse-finish]");
  var confetti = root.querySelector("[data-nurse-confetti]");
  var prev = root.querySelector("[data-nurse-prev]");
  var next = root.querySelector("[data-nurse-next]");
  var counter = root.querySelector("[data-nurse-counter]");
  var reduce = window.matchMedia("(prefers-reduced-motion: reduce)");
  var active = -1, typingTimer = 0, observed = false;
  var data = stages.map(function (item) {
    var h = item.querySelector("h3"), p = item.querySelector(".nurse-stage__card > p:not(.nurse-stage__eyebrow)");
    return { title: h ? h.textContent.trim() : "", text: p ? p.textContent.trim() : "", pose: item.dataset.stagePose || "sourcing" };
  });
  function countStat(index) {
    var el = stages[index].querySelector("[data-nurse-count]");
    if (!el || el.dataset.counted) return;
    el.dataset.counted = "1";
    var target = Number(el.dataset.nurseCount || 0), suffix = el.dataset.suffix || "";
    if (reduce.matches || target === 0) { el.textContent = String(target) + suffix; return; }
    var start = performance.now(), duration = 850;
    function tick(now) { var t = Math.min(1, (now - start) / duration); el.textContent = Math.round(target * (1 - Math.pow(1 - t, 3))) + suffix; if (t < 1) requestAnimationFrame(tick); }
    requestAnimationFrame(tick);
  }
  function typeText(text) {
    window.clearInterval(typingTimer);
    if (!speech) return;
    if (reduce.matches) { speech.textContent = text; return; }
    speech.textContent = "";
    var i = 0;
    typingTimer = window.setInterval(function () { speech.textContent += text.charAt(i++); if (i >= text.length) window.clearInterval(typingTimer); }, 19);
  }
  function confettiBurst() {
    if (!confetti || reduce.matches) return;
    confetti.innerHTML = "";
    var colors = ["#f5a623", "#1f5c3a", "#e56b45", "#8dbb78", "#e6c85c"];
    for (var i = 0; i < 28; i++) {
      var piece = document.createElement("i");
      piece.className = "nurse-confetti-piece";
      piece.style.setProperty("--confetti-color", colors[i % colors.length]);
      piece.style.setProperty("--angle", (i * 29) + "deg");
      piece.style.setProperty("--dx", (Math.cos(i * .7) * (45 + i % 5 * 13)) + "px");
      piece.style.setProperty("--dy", (Math.sin(i * .7) * (45 + i % 5 * 13) - 35) + "px");
      confetti.appendChild(piece);
    }
    window.setTimeout(function () { if (confetti) confetti.innerHTML = ""; }, 1100);
  }
  function setStage(index, scrollTo) {
    index = Math.max(0, Math.min(stages.length - 1, index));
    active = index;
    root.classList.add("is-moving");
    window.clearTimeout(root._nurseMoveTimer);
    root._nurseMoveTimer = window.setTimeout(function () { root.classList.remove("is-moving"); }, 600);
    root.dataset.pose = index === stages.length - 1 && root.dataset.completed === "true" ? "complete" : data[index].pose;
    if (title) title.textContent = "Step " + (index + 1) + " · " + data[index].title;
    typeText(data[index].text);
    stages.forEach(function (stage, i) {
      stage.classList.toggle("is-active", i === index);
      stage.classList.toggle("is-complete", i < index || (root.dataset.completed === "true" && i === index));
      var dot = stage.querySelector("[data-nurse-jump]");
      if (dot) { if (i === index) dot.setAttribute("aria-current", "step"); else dot.removeAttribute("aria-current"); }
    });
    if (progress) progress.style.transform = "scaleY(" + (index / Math.max(1, stages.length - 1)) + ")";
    if (counter) counter.textContent = "Stage " + (index + 1) + " of " + stages.length;
    if (prev) prev.disabled = index === 0;
    if (next) { next.disabled = root.dataset.completed === "true"; next.textContent = index === stages.length - 1 ? "Finish journey ✓" : "Next stage →"; }
    countStat(index);
    if (finish) finish.hidden = !(root.dataset.completed === "true" && index === stages.length - 1);
    if (scrollTo && stages[index]) stages[index].scrollIntoView({ behavior: reduce.matches ? "auto" : "smooth", block: "center" });
  }
  function completeJourney() {
    root.dataset.completed = "true";
    root.dataset.pose = "complete";
    stages.forEach(function (stage) { stage.classList.add("is-complete"); });
    if (finish) finish.hidden = false;
    if (title) title.textContent = "Quality care, from start to finish";
    typeText("That's our promise: thoughtful care at every stage. Thank you for choosing RR FOODS!");
    if (counter) counter.textContent = "All 6 stages completed";
    if (next) { next.disabled = true; next.textContent = "Journey complete ✓"; }
    confettiBurst();
  }
  stages.forEach(function (stage, index) {
    var dot = stage.querySelector("[data-nurse-jump]");
    if (dot) dot.addEventListener("click", function () { setStage(index, true); });
  });
  if (prev) prev.addEventListener("click", function () { if (active > 0) setStage(active - 1, true); });
  if (next) next.addEventListener("click", function () { if (active < stages.length - 1) setStage(active + 1, true); else completeJourney(); });
  function activateFromScroll() {
    var target = window.innerHeight * .48, best = active, distance = Infinity;
    stages.forEach(function (stage, index) { var rect = stage.getBoundingClientRect(); if (rect.top < window.innerHeight * .78 && rect.bottom > window.innerHeight * .2) { var d = Math.abs((rect.top + rect.height / 2) - target); if (d < distance) { distance = d; best = index; } } });
    if (best >= 0 && best !== active) setStage(best, false);
    var first = stages[0].getBoundingClientRect(), last = stages[stages.length - 1].getBoundingClientRect();
    var total = Math.max(1, (last.top + last.height / 2) - (first.top + first.height / 2));
    var amount = Math.max(0, Math.min(1, (window.innerHeight * .48 - (first.top + first.height / 2)) / total));
    if (progress) progress.style.transform = "scaleY(" + amount + ")";
    if (last.bottom < window.innerHeight * .65 && root.dataset.completed !== "true") completeJourney();
  }
  if (reduce.matches) {
    stages.forEach(function (stage, i) { stage.classList.add("is-complete"); stage.classList.toggle("is-active", i === 0); });
    root.dataset.pose = "sourcing";
    if (title) title.textContent = "Step 1 · " + data[0].title;
    if (speech) speech.textContent = data.map(function (d, i) { return (i + 1) + ". " + d.title + ": " + d.text; }).join(" ");
    if (progress) progress.style.transform = "scaleY(1)";
    stages.forEach(function (_, i) { countStat(i); });
    if (finish) finish.hidden = false;
    if (next) next.disabled = false;
    if (counter) counter.textContent = "All 6 stages · reduced motion";
    if (prev) prev.disabled = true;
    next && next.addEventListener("click", function () { var i = Math.min(stages.length - 1, active + 1); active = i; stages.forEach(function (stage, j) { stage.classList.toggle("is-active", j === i); }); if (title) title.textContent = "Step " + (i + 1) + " · " + data[i].title; });
    return;
  }
  setStage(0, false);
  if ("IntersectionObserver" in window) {
    var observer = new IntersectionObserver(function (entries) { entries.forEach(function (entry) { if (entry.isIntersecting) { var i = stages.indexOf(entry.target); if (i >= 0 && (active < 0 || Math.abs(i - active) <= 1)) setStage(i, false); } }); }, { rootMargin: "-25% 0px -25% 0px", threshold: 0.15 });
    stages.forEach(function (stage) { observer.observe(stage); });
    observed = true;
  }
  var scrollQueued = false;
  window.addEventListener("scroll", function () { if (scrollQueued) return; scrollQueued = true; requestAnimationFrame(function () { scrollQueued = false; activateFromScroll(); }); }, { passive: true });
  window.addEventListener("resize", activateFromScroll, { passive: true });
  activateFromScroll();
})();
