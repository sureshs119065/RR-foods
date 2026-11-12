/* Storefront behaviour. Plain JavaScript, no libraries. Every form and link still works without it. */
(function () {
  "use strict";
  var $ = function (s, r) { return (r || document).querySelector(s); };
  var $$ = function (s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); };
  var root = document.documentElement;
  var csrf = ($("meta[name=csrf-token]") || {}).content || "";
  var reduce = window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches;
  function store(get, key, val) { try { if (get) return localStorage.getItem(key); localStorage.setItem(key, val); } catch (e) { return null; } }

  /* ---------- toast ---------- */
  var toast = $("#toast"), tt;
  function say(text, bad) {
    if (!toast) return;
    toast.textContent = text; toast.hidden = false; toast.classList.toggle("toast--error", !!bad);
    requestAnimationFrame(function () { toast.classList.add("toast--show"); });
    clearTimeout(tt); tt = setTimeout(function () { toast.classList.remove("toast--show"); }, bad ? 5000 : 2800);
  }
  function setCount(n) { $$("[data-cart-count]").forEach(function (b) { b.textContent = n; b.hidden = !n; }); }

  /* ---------- overlays: one open at a time, Esc and outside tap close, focus returns ---------- */
  var backdrop = $("#backdrop"), openEl = null, opener = null;
  function lock(on) { root.classList.toggle("nolock", on); }
  function open(el, from, withBackdrop) {
    if (openEl) close();
    openEl = el; opener = from || document.activeElement;
    el.hidden = false; el.setAttribute("aria-hidden", "false");
    if (withBackdrop && backdrop) { backdrop.hidden = false; requestAnimationFrame(function () { backdrop.classList.add("is-on"); }); }
    requestAnimationFrame(function () { el.classList.add("is-open"); var f = $("input,a,button", el); if (el.id === "search-overlay") { var i = $("#so-input"); if (i) i.focus(); } else if (f) f.focus(); });
    lock(true);
    $$("[aria-controls=" + el.id + "]").forEach(function (b) { b.setAttribute("aria-expanded", "true"); });
  }
  function close() {
    if (!openEl) return;
    var el = openEl; openEl = null;
    el.classList.remove("is-open"); el.setAttribute("aria-hidden", "true");
    if (backdrop) { backdrop.classList.remove("is-on"); setTimeout(function () { if (!openEl) backdrop.hidden = true; }, reduce ? 0 : 280); }
    setTimeout(function () { if (el !== openEl && (el.classList.contains("so") || el.classList.contains("cat-sheet"))) el.hidden = true; }, reduce ? 0 : 280);
    lock(false);
    $$("[aria-controls=" + el.id + "]").forEach(function (b) { b.setAttribute("aria-expanded", "false"); });
    if (opener && opener.focus) opener.focus();
  }
  var drawer = $("#drawer"), searchO = $("#search-overlay"), categorySheet = $("#category-sheet");
  document.addEventListener("click", function (e) {
    var o = e.target.closest("[data-open]");
    if (o) { e.preventDefault(); var w = o.getAttribute("data-open"); if (w === "drawer" && drawer) open(drawer, o, true); if (w === "search" && searchO) { open(searchO, o, false); renderRecent(); } if (w === "categories" && categorySheet) open(categorySheet, o, true); return; }
    if (e.target.closest("[data-close]") || e.target === backdrop) { close(); return; }
    var so = e.target.closest("[data-sheet-open]"); if (so) { var sh = $("#filter-form"); if (sh) open(sh, so, true); return; }
    if (e.target.closest("[data-sheet-close]") || e.target.id === "sheet-backdrop") close();
  });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") { close(); closeZoom(); hideSugg(); }
    if (e.key === "Tab" && openEl) {
      var focusable = $$('a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])', openEl).filter(function (x) { return x.offsetParent !== null; });
      if (!focusable.length) return;
      var first = focusable[0], last = focusable[focusable.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    }
  });
  window.addEventListener("resize", debounce(function () { if (openEl && openEl.id === "filter-form" && matchMedia("(min-width:1024px)").matches) { openEl.classList.remove("is-open"); openEl = null; if (backdrop) { backdrop.hidden = true; backdrop.classList.remove("is-on"); } lock(false); } }, 150));
  function debounce(fn, ms) { var t; return function () { var a = arguments, c = this; clearTimeout(t); t = setTimeout(function () { fn.apply(c, a); }, ms); }; }

  /* ---------- header shrinks smoothly on scroll ---------- */
  var sh = $("#sh"), tick = false;
  var lastScrollY=window.scrollY, announcement=$("#announce");
  window.addEventListener("scroll", function () { if (tick) return; tick = true; requestAnimationFrame(function () { var y=window.scrollY; if(sh)sh.classList.toggle("is-compact", y>40); if(announcement && y>100)announcement.classList.toggle("is-hidden-on-scroll", y>lastScrollY+2); if(announcement && y<40)announcement.classList.remove("is-hidden-on-scroll"); lastScrollY=y; tick = false; }); }, { passive: true });

  /* ---------- theme ---------- */
  $$("[data-theme-toggle]").forEach(function (b) {
    b.addEventListener("click", function () {
      var dark = root.getAttribute("data-theme") === "dark" || (!root.getAttribute("data-theme") && matchMedia("(prefers-color-scheme: dark)").matches);
      var next = dark ? "light" : "dark"; root.setAttribute("data-theme", next); store(false, "nk-theme", next);
    });
  });

  /* ---------- confirm + one-click-only ---------- */
  document.addEventListener("click", function (e) { var c = e.target.closest("[data-confirm]"); if (c && !window.confirm(c.getAttribute("data-confirm"))) e.preventDefault(); });
  $$("form[data-once]").forEach(function (f) {
    f.addEventListener("submit", function (e) {
      if (e.defaultPrevented) return;
      if (f.getAttribute("data-sent")) { e.preventDefault(); return; }
      f.setAttribute("data-sent", "1"); setTimeout(function () { f.removeAttribute("data-sent"); }, 8000);
    });
  });

  /* ---------- accordions (animated by CSS: grid rows 0fr -> 1fr) ---------- */
  $$(".acc").forEach(function (a) {
    var h = $(".acc__h", a); if (!h) return;
    if (a.hasAttribute("data-open") && !(matchMedia("(max-width:767px)").matches && a.closest(".det"))) a.classList.add("is-open");
    h.setAttribute("aria-expanded", a.classList.contains("is-open") ? "true" : "false");
    h.addEventListener("click", function () { var o = a.classList.toggle("is-open"); h.setAttribute("aria-expanded", o ? "true" : "false"); });
  });
  var sum = $("[data-sum]"); // the cart summary starts collapsed on phones
  if (sum && matchMedia("(max-width:899px)").matches) { sum.classList.remove("is-open"); $(".acc__h", sum).setAttribute("aria-expanded", "false"); }

  /* ---------- search: overlay on phones, dropdown on desktop, recent searches ---------- */
  var RK = "nk-recent";
  function recent() { try { return JSON.parse(store(true, RK) || "[]").filter(function (x) { return typeof x === "string"; }).slice(0, 6); } catch (e) { return []; } }
  function remember(q) { q = (q || "").trim(); if (q.length < 2) return; var l = recent().filter(function (x) { return x.toLowerCase() !== q.toLowerCase(); }); l.unshift(q); store(false, RK, JSON.stringify(l.slice(0, 6))); }
  function esc(s) { var d = document.createElement("div"); d.textContent = s; return d.innerHTML; }
  function renderRecent() {
    var box = $("#so-recent"), list = $("#so-recent-list"); if (!box) return;
    var r = recent(); box.hidden = !r.length;
    list.innerHTML = r.map(function (q) { return '<li><a href="/shop?q=' + encodeURIComponent(q) + '">' + esc(q) + "</a></li>"; }).join("");
  }
  var clr = $("#so-clear"); if (clr) clr.addEventListener("click", function () { store(false, RK, "[]"); renderRecent(); });
  $$("form[role=search]").forEach(function (f) { f.addEventListener("submit", function () { var i = $("input[name=q]", f); if (i) remember(i.value); }); });
  function hl(name, q) {
    var i = q ? name.toLowerCase().indexOf(q.toLowerCase()) : -1;
    if (i < 0) return esc(name);
    return esc(name.slice(0, i)) + "<b>" + esc(name.slice(i, i + q.length)) + "</b>" + esc(name.slice(i + q.length));
  }
  var ICON = '<svg class="sg-i" viewBox="0 0 24 24" width="18" height="18" aria-hidden="true"><circle cx="11" cy="11" r="7" fill="none" stroke="currentColor" stroke-width="2"/><path d="M20 20l-4-4" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round"/></svg>';
  function termLink(t, q) { return '<li><a href="/shop?q=' + encodeURIComponent(t) + '" data-term="' + esc(t) + '">' + ICON + "<span>" + hl(t, q) + "</span></a></li>"; }
  function suggestHtml(d, q) {
    var out = [];
    if (d.popular) {
      out.push('<li class="sg-h" aria-hidden="true">Popular searches</li>');
      out = out.concat((d.terms || []).map(function (t) { return termLink(t, ""); }));
      if ((d.categories || []).length) out.push('<li class="sg-h" aria-hidden="true">Browse categories</li>');
      out = out.concat((d.categories || []).map(function (c) { return '<li><a href="' + esc(c.url) + '">' + ICON + "<span>" + esc(c.name) + "</span></a></li>"; }));
      return out.join("");
    }
    out = out.concat((d.bundles || []).map(function (b) { return '<li><a href="' + esc(b.url) + '"><span class="sg-tag">Combo offer</span><span>' + hl(b.name, q) + '</span><span class="sub">₹' + esc(b.price) + "</span></a></li>"; }));
    out = out.concat((d.categories || []).map(function (c) { return '<li><a href="' + esc(c.url) + '">' + ICON + "<span>" + hl(c.name, q) + ' <small class="muted">in categories</small></span></a></li>'; }));
    out = out.concat((d.terms || []).map(function (t) { return termLink(t, q); }));
    out = out.concat((d.products || []).map(function (p) { return '<li><a href="' + esc(p.url) + '">' + (p.image ? '<img src="' + esc(p.image) + '" alt="" width="40" height="40">' : "") + "<span>" + hl(p.name, q) + '</span><span class="sub">₹' + esc(p.price) + "</span></a></li>"; }));
    return out.join("") || '<li class="muted nomatch">No matches. Press search to look anyway.</li>';
  }
  var seq = 0;
  function wireSuggest(input, list) {
    function load() {
      var q = input.value.trim(); var my = ++seq;
      fetch("/api/suggest?q=" + encodeURIComponent(q), { headers: { Accept: "application/json" }, credentials: "same-origin" })
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (d) { if (!d || my !== seq) return; list.innerHTML = suggestHtml(d, q); list.hidden = false; })
        .catch(function () {});
    }
    input.addEventListener("input", debounce(load, 180));
    input.addEventListener("focus", load);
    input.addEventListener("keydown", function (e) {
      var links = $$("a", list);
      if (e.key === "ArrowDown" && links.length) { e.preventDefault(); links[0].focus(); }
      else if (e.key === "Escape") { list.hidden = true; }
    });
    list.addEventListener("keydown", function (e) {
      var links = $$("a", list), i = links.indexOf(document.activeElement);
      if (e.key === "ArrowDown") { e.preventDefault(); (links[i + 1] || links[0]).focus(); }
      else if (e.key === "ArrowUp") { e.preventDefault(); if (i <= 0) input.focus(); else links[i - 1].focus(); }
      else if (e.key === "Escape") { list.hidden = true; input.focus(); }
    });
    list.addEventListener("click", function (e) {
      var a = e.target.closest("a[data-term]"); if (a) remember(a.getAttribute("data-term"));
    });
  }
  var soIn = $("#so-input"), soRes = $("#so-results"); if (soIn && soRes) { wireSuggest(soIn, soRes); soIn.addEventListener("input", function () { var b = $("#so-recent"); if (b) b.hidden = soIn.value.trim().length >= 2 || !recent().length; }); }
  var dIn = $("[data-suggest]"), dList = null;
  function hideSugg() { if (dList) dList.hidden = true; }
  if (dIn) { dList = document.createElement("ul"); dList.className = "sugg"; dList.hidden = true; dIn.form.appendChild(dList); wireSuggest(dIn, dList); document.addEventListener("click", function (e) { if (!dIn.form.contains(e.target)) hideSugg(); }); }

  /* ---------- listing: sort and (on desktop) filters apply immediately ---------- */
  var ff = $("#filter-form");
  if (ff) {
    ff.addEventListener("change", debounce(function () { ff.submit(); }, 250));
    $$("[data-autosubmit]").forEach(function (s) {
      s.addEventListener("change", function () { if (ff) ff.requestSubmit(); });
    });
  }

  /* ---------- product page ---------- */
  var gal = $("[data-gallery]");
  if (gal) {
    var main = $("#gal-main");
    $$(".gal__t", gal).forEach(function (t) {
      t.addEventListener("click", function () { if (!main) return; main.src = t.getAttribute("data-src"); main.alt = t.getAttribute("data-alt"); $$(".gal__t", gal).forEach(function (x) { x.removeAttribute("aria-current"); }); t.setAttribute("aria-current", "true"); var index=$$(".gal__t",gal).indexOf(t); $$("[data-gallery-dot]",gal).forEach(function(d,i){ if(i===index)d.setAttribute("aria-current","true");else d.removeAttribute("aria-current"); }); });
    });
    $$("[data-gallery-dot]", gal).forEach(function(d){ d.addEventListener("click",function(){ var i=Number(d.getAttribute("data-gallery-dot")), t=$$(".gal__t",gal)[i]; if(t)t.click(); }); });
    // swipe between images on touch screens
    var sx = null; gal.addEventListener("touchstart", function (e) { sx = e.touches[0].clientX; }, { passive: true });
    gal.addEventListener("touchend", function (e) {
      if (sx === null) return; var dx = e.changedTouches[0].clientX - sx; sx = null; if (Math.abs(dx) < 50) return;
      var ts = $$(".gal__t", gal); if (ts.length < 2) return; var i = ts.findIndex(function (x) { return x.getAttribute("aria-current") === "true"; }); ts[(i + (dx < 0 ? 1 : -1) + ts.length) % ts.length].click();
    }, { passive: true });
  }
  var zoom = $("#zoom"), zs = zoom && $(".zoom__scroll", zoom), zimg = $("#zoom-img");
  function closeZoom() { if (zoom && !zoom.hidden) { zoom.hidden = true; lock(false); } }
  document.addEventListener("click", function (e) {
    if (e.target.closest("[data-zoom]") && zoom) { var m = $("#gal-main"); zimg.src = m.src; zimg.alt = m.alt; zs.classList.remove("is-in"); zoom.hidden = false; lock(true); var x = $("[data-zoom-close]", zoom); if (x) x.focus(); return; }
    if (e.target.closest("[data-zoom-close]")) { closeZoom(); return; }
    if (e.target === zimg) zs.classList.toggle("is-in");
  });

  var form = $("#buyform");
  if (form) {
    var now = $("#price-now"), mrp = $("#price-mrp"), off = $("#price-off"), note = $("#stock-note"), qty = $("#qty");
    function inr(v) { return "₹" + Number(v).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 }); }
    $$("input[name=variant_id]", form).forEach(function (r) {
      r.addEventListener("change", function () {
        var p = parseFloat(r.dataset.price), m = parseFloat(r.dataset.mrp), s = parseInt(r.dataset.stock, 10), low = parseInt(r.dataset.low, 10); var bb=$("[data-buybar-price]"); if(bb)bb.textContent=inr(p);
        now.textContent = inr(p); var pct = m > p ? Math.floor((m - p) * 100 / m) : 0;
        mrp.textContent = inr(m); mrp.hidden = off.hidden = !pct; off.textContent = pct + "% off";
        note.innerHTML = s <= 0 ? '<span class="stock stock--out">Out of stock</span>' : (s <= low || s <= 5) ? '<span class="stock stock--low">Only ' + s + " left</span>" : '<span class="stock stock--ok">In stock</span>';
        var dis = s <= 0; $$("[data-add],[data-buy]", form).forEach(function (b) { b.disabled = dis; });
        qty.max = Math.max(1, Math.min(10, s)); if (+qty.value > +qty.max) qty.value = qty.max;
      });
    });
    $$("[data-step]", form).forEach(function (b) { b.addEventListener("click", function () { var v = (parseInt(qty.value, 10) || 1) + parseInt(b.dataset.step, 10); qty.value = Math.min(+qty.max || 10, Math.max(1, v)); }); });
    form.addEventListener("submit", function (e) {
      if (e.submitter && e.submitter.name === "buy_now") return; // go straight to checkout with a normal post
      if (!window.fetch) return;
      e.preventDefault(); if (form.getAttribute("data-busy")) return;
      if (!form.reportValidity()) return;
      form.setAttribute("data-busy", "1");
      fetch(form.action, { method: "POST", body: new FormData(form), credentials: "same-origin", headers: { Accept: "application/json", "X-CSRFToken": csrf } })
        .then(function (r) { return r.json().then(function (d) { return { s: r.status, d: d }; }); })
        .then(function (res) { form.removeAttribute("data-busy"); if (res.s === 401 && res.d.login) { window.location.href = res.d.login; return; } if (typeof res.d.count === "number") setCount(res.d.count); say(res.d.message || "Done.", !res.d.ok); })
        .catch(function () { form.removeAttribute("data-busy"); say("No connection. Please try again.", true); });
    });
  }
  var pin = $("#pinform");
  if (pin) {
    var pinInput = $("#pin");
    try { var savedPin = localStorage.getItem("rr-foods-pincode"); if (savedPin && pinInput && !pinInput.value) pinInput.value = savedPin; } catch (e) {}
    pinInput.addEventListener("input", function () { pinInput.value = pinInput.value.replace(/\D/g, "").slice(0, 6); if (pinInput.value.length === 6) pin.requestSubmit ? pin.requestSubmit() : pin.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })); });
    pin.addEventListener("submit", function (e) {
    e.preventDefault(); var v = pinInput.value.trim(), msg = $("#pin-msg");
    if (!/^\d{6}$/.test(v)) { msg.textContent = "Enter a 6 digit pincode."; msg.className = "pin__msg is-bad"; return; }
    try { localStorage.setItem("rr-foods-pincode", v); } catch (e) {}
    msg.textContent = "Checking…"; msg.className = "pin__msg";
    fetch("/api/pincode/" + v, { headers: { Accept: "application/json" } }).then(function (r) { return r.json(); })
      .then(function (d) { msg.textContent = d.message; msg.className = "pin__msg " + (d.deliverable ? "is-ok" : "is-bad"); })
      .catch(function () { msg.textContent = "Could not check right now."; msg.className = "pin__msg is-bad"; });
    });
  }

  var addressPin = document.querySelector('input[name="pincode"]');
  if (addressPin) {
    try { var rememberedPin=localStorage.getItem("rr-foods-pincode"); if(rememberedPin && !addressPin.value) addressPin.value=rememberedPin; } catch(e) {}
    addressPin.addEventListener("input",function(){ addressPin.value=addressPin.value.replace(/\D/g,"").slice(0,6); if(addressPin.value.length===6){ try{localStorage.setItem("rr-foods-pincode",addressPin.value);}catch(e){} } });
  }

  /* ---------- checkout: delivery fee and total follow the chosen address ---------- */
  var co = $("[data-checkout]");
  if (co) {
    var money = function (v) { return "₹" + Number(v).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 }); };
    var update = function () {
      var r = $("input[name=address_id]:checked", co); if (!r) return;
      var ok = r.dataset.ok === "1", d = $("#sum-delivery");
      if (d) d.textContent = !ok ? "Not deliverable" : (parseFloat(r.dataset.delivery) === 0 ? "Free" : money(r.dataset.delivery));
      var t = money(r.dataset.total); $("#sum-total").textContent = t; $("#bar-total").textContent = t;
      var b = $("button[type=submit]", co); if (b && !co.hasAttribute("data-sent")) b.disabled = !ok;
    };
    $$('input[name=address_id]', co).forEach(function (r) { r.addEventListener("change", update); }); update();
    co.addEventListener("submit", function (e) {
      if (!co.reportValidity()) return;
      if (co.getAttribute("data-place-busy") === "1") { e.preventDefault(); return; }
      co.setAttribute("data-place-busy", "1"); var b = $("button[type=submit]", co);
      if (b) { b.disabled = true; b.setAttribute("aria-busy", "true"); b.innerHTML = '<span class="btn-spinner" aria-hidden="true"></span> Placing order…'; }
    });
  }

  /* ---------- password visibility toggle: preserves autocomplete and password-manager semantics ---------- */
  $$('input[type="password"]').forEach(function(input){
    var toggle=document.createElement("button"); toggle.type="button"; toggle.className="password-toggle"; toggle.textContent="Show"; toggle.setAttribute("aria-label","Show password"); toggle.setAttribute("aria-pressed","false");
    input.insertAdjacentElement("afterend",toggle);
    toggle.addEventListener("click",function(){ var show=input.type==="password"; input.type=show?"text":"password"; toggle.textContent=show?"Hide":"Show"; toggle.setAttribute("aria-label",show?"Hide password":"Show password"); toggle.setAttribute("aria-pressed",show?"true":"false"); input.focus(); });
  });

  /* ---------- viewport keyboard detection: keep fixed navigation out of the way ---------- */
  function syncKeyboard() {
    var vv = window.visualViewport, open = false;
    if (vv && window.innerHeight) open = (window.innerHeight - vv.height) > 150;
    if (!open && /INPUT|TEXTAREA|SELECT/.test((document.activeElement || {}).tagName || "")) open = true;
    root.classList.toggle("keyboard-open", !!open && window.innerWidth < 768);
  }
  if (window.visualViewport) { window.visualViewport.addEventListener("resize", syncKeyboard); window.visualViewport.addEventListener("scroll", syncKeyboard); }
  document.addEventListener("focusin", syncKeyboard); document.addEventListener("focusout", function () { setTimeout(syncKeyboard, 120); });

  /* ---------- announcement marquee pauses on touch ---------- */
  var marquee = $("#announce-marquee");
  if (marquee) { marquee.addEventListener("touchstart", function () { marquee.setAttribute("data-touch-paused", "true"); }, { passive:true }); marquee.addEventListener("touchend", function () { setTimeout(function () { marquee.removeAttribute("data-touch-paused"); }, 1800); }, { passive:true }); }

  /* ---------- defer page-specific enhancements until their section is visible ---------- */
  var lazyModules = { reels:"reels.js", diwali:"diwali-fireworks.js", quality:"quality-journey.js" };
  if ("IntersectionObserver" in window) {
    var moduleObserver = new IntersectionObserver(function (entries, obs) { entries.forEach(function (entry) { if (!entry.isIntersecting) return; var key = entry.target.getAttribute("data-lazy-script"), file = lazyModules[key]; if (file) { var script = document.createElement("script"); script.src = "/static/js/" + file; script.defer = true; document.body.appendChild(script); } obs.unobserve(entry.target); }); }, { rootMargin:"180px" });
    $$('[data-lazy-script]').forEach(function (el) { moduleObserver.observe(el); });
  } else { $$('[data-lazy-script]').forEach(function (el) { var key=el.getAttribute("data-lazy-script"); if (lazyModules[key]) { var script=document.createElement("script"); script.src="/static/js/"+lazyModules[key]; script.defer=true; document.body.appendChild(script); } }); }

  /* ---------- Add to Home Screen: once per visitor, only after browser offers install ---------- */
  var installEvent = null, installBanner = $("#install-banner"), installButton = $("#install-app"), dismissInstall = $("#dismiss-install");
  window.addEventListener("beforeinstallprompt", function (e) { e.preventDefault(); installEvent=e; try { if (localStorage.getItem("rr-install-dismissed") === "1" || localStorage.getItem("rr-install-shown") === "1") return; localStorage.setItem("rr-install-shown","1"); } catch (x) {} if (installBanner) installBanner.hidden=false; });
  if (installButton) installButton.addEventListener("click", function () { if (!installEvent) return; installEvent.prompt(); installEvent.userChoice.then(function () { installEvent=null; if (installBanner) installBanner.hidden=true; }); });
  if (dismissInstall) dismissInstall.addEventListener("click", function () { if (installBanner) installBanner.hidden=true; try { localStorage.setItem("rr-install-dismissed","1"); } catch (e) {} });

  /* ---------- English / Tamil main navigation labels ---------- */
  var language = "en", labels = { en:{home:"Home",categories:"Categories",search:"Search",cart:"Cart",account:"Account"}, ta:{home:"முகப்பு",categories:"வகைகள்",search:"தேடல்",cart:"கூடை",account:"கணக்கு"} };
  try { language=localStorage.getItem("rr-language") || "en"; } catch(e) {}
  function applyLanguage() { root.lang=language === "ta" ? "ta" : "en"; $$('[data-i18n]').forEach(function(el){ var k=el.getAttribute('data-i18n'); if(labels[language][k]) el.textContent=labels[language][k]; }); }
  $$('[data-language-toggle]').forEach(function(b){ b.addEventListener('click',function(){ language=language === "en" ? "ta" : "en"; try{localStorage.setItem("rr-language",language);}catch(e){} applyLanguage(); }); });
  applyLanguage();

  /* ---------- collapsible home extras on phones ---------- */
  var home = $("[data-home-sections]");
  if (home && matchMedia("(max-width:767px)").matches) {
    var extras = $$("[data-home-extra]", home), toggle = $("[data-home-more]", home);
    extras.forEach(function(el){ el.hidden=true; });
    if (toggle) toggle.addEventListener("click",function(){ var show=toggle.getAttribute("aria-expanded") !== "true"; extras.forEach(function(el){el.hidden=!show;}); toggle.setAttribute("aria-expanded",show?"true":"false"); toggle.textContent=show?"Show less":"Show more"; });
  }

  /* ---------- installable app: register the small service worker ---------- */
  if ("serviceWorker" in navigator && (location.protocol === "https:" || location.hostname === "localhost")) { try { navigator.serviceWorker.register("/sw.js", { scope: "/" }).catch(function () {}); } catch (e) {} }
})();

/* ---------- Step 7: one-tap buttons that answer with JSON (wishlist, compare, helpful) ---------- */
(function () {
  "use strict";
  var csrf = (document.querySelector("meta[name=csrf-token]") || {}).content || "";
  var toast = document.getElementById("toast"), tt;
  function say(text, bad) {
    if (!toast) return; toast.textContent = text; toast.hidden = false; toast.classList.toggle("toast--error", !!bad);
    requestAnimationFrame(function () { toast.classList.add("toast--show"); });
    clearTimeout(tt); tt = setTimeout(function () { toast.classList.remove("toast--show"); }, bad ? 5000 : 2500);
  }
  function send(form, done) {
    fetch(form.action, { method: "POST", body: new FormData(form), credentials: "same-origin", headers: { Accept: "application/json", "X-CSRFToken": csrf } })
      .then(function (r) { return r.json().then(function (d) { return { s: r.status, d: d }; }); })
      .then(function (res) {
        if (res.s === 401 && res.d.login) { window.location.href = res.d.login; return; }
        say(res.d.message || "Done.", !res.d.ok); if (res.d.ok) done(res.d);
      }).catch(function () { say("No connection. Please try again.", true); });
  }
  document.addEventListener("submit", function (e) {
    var f = e.target; if (!window.fetch) return;
    if (f.matches("[data-wish]")) {
      e.preventDefault();
      send(f, function (d) {
        var b = f.querySelector("button"); b.classList.toggle("is-on", d.on); b.setAttribute("aria-pressed", d.on ? "true" : "false");
        var l = f.querySelector("[data-wish-label]"); if (l) l.textContent = d.on ? "Saved" : "Wishlist";
        if (location.pathname === "/account/wishlist" && !d.on) location.reload();
      });
    } else if (f.matches("[data-helpful]")) {
      e.preventDefault();
      send(f, function (d) { f.querySelector("[data-count]").textContent = d.helpful; f.querySelector("button").classList.toggle("is-on", d.on); });
    } else if (f.matches("[data-compare]")) {
      e.preventDefault(); send(f, function () {});
    }
  });

  /* ---------- copy a text box (order message) ---------- */
  document.addEventListener("click", function (e) {
    var b = e.target.closest ? e.target.closest("[data-copy]") : null;
    if (!b) return;
    var src = document.querySelector(b.getAttribute("data-copy"));
    if (!src) return;
    var done = function () { say("Message copied. Paste it in WhatsApp."); };
    if (navigator.clipboard && navigator.clipboard.writeText) { navigator.clipboard.writeText(src.value).then(done, function () { src.select(); }); }
    else { src.select(); try { document.execCommand("copy"); done(); } catch (x) { /* the text stays selected for a manual copy */ } }
  });
})();

/* Live order updates: the bell count, the tracking page, and the review thank-you popup. */
(function () {
  "use strict";
  var $ = function (s, r) { return (r || document).querySelector(s); };
  var reduce = window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches;
  var POLL = 30000;

  function getJSON(url) {
    return fetch(url, { credentials: "same-origin", headers: { Accept: "application/json" }, cache: "no-store" })
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); });
  }
  function toast(text) {
    var t = $(".toast") || $("#toast");
    if (!t) return;
    t.textContent = text; t.hidden = false;
    requestAnimationFrame(function () { t.classList.add("toast--show"); });
    setTimeout(function () { t.classList.remove("toast--show"); }, 4500);
  }

  // ---- bell: refresh the unread count every 30 s, and when the tab becomes visible again
  var badges = Array.prototype.slice.call(document.querySelectorAll("[data-notif-count]"));
  if (badges.length) {
    var last = parseInt(badges[0].textContent, 10) || 0, busy = false;
    var tick = function () {
      if (busy || document.hidden) return;
      busy = true;
      getJSON("/notifications/unread.json").then(function (d) {
        badges.forEach(function (b) {
          b.textContent = d.count > 99 ? "99+" : d.count; b.hidden = !d.count;
          if (d.count > last) { b.classList.remove("dot-n--pop"); void b.offsetWidth; b.classList.add("dot-n--pop"); }
        });
        if (d.count > last && d.latest && d.latest[0]) toast(d.latest[0].title);
        last = d.count;
      }).catch(function () { /* offline or signed out: try again next time */ }).then(function () { busy = false; });
    };
    setInterval(tick, POLL);
    document.addEventListener("visibilitychange", function () { if (!document.hidden) tick(); });
  }

  // ---- tracking page: when the shop moves the order along, show it without a manual refresh
  var trk = $("[data-track]");
  if (trk) {
    var shown = trk.getAttribute("data-status"), url = trk.getAttribute("data-url"), live = $("[data-track-live]", trk), wait = false;
    var check = function () {
      if (wait || document.hidden) return;
      wait = true;
      getJSON(url).then(function (d) {
        if (d.status !== shown) {
          if (live) live.textContent = "Updated: " + d.label;
          trk.classList.add("trk--flash");
          setTimeout(function () { window.location.reload(); }, reduce ? 200 : 900);
        }
      }).catch(function () { if (live) live.textContent = "Could not check for updates. Retrying…"; }).then(function () { wait = false; });
    };
    setInterval(check, 20000);
    document.addEventListener("visibilitychange", function () { if (!document.hidden) check(); });
  }

  // ---- thank-you popup (only exists on the page right after a review was saved)
  var pop = $("[data-review-thanks]");
  if (pop) {
    var card = $(".rt__card", pop), fx = $(".rt__fx", pop), opener = document.activeElement, closed = false;
    if (fx && !reduce) {
      var hearts = ["❤️", "💚", "✨", "💖", "⭐"], colors = ["#f7b32b", "#e63e6d", "#2fbf71", "#4da3ff", "#b36bff"], html = "";
      for (var i = 0; i < 16; i++) {
        html += '<span class="rt__p" style="left:' + (Math.random() * 94 + 2).toFixed(1) + '%;font-size:' + (0.9 + Math.random() * 1.1).toFixed(2) + 'rem;--d:' + (3 + Math.random() * 2.5).toFixed(1) + 's;--delay:' + (Math.random() * 3).toFixed(1) + 's;--dx:' + ((Math.random() - 0.5) * 5).toFixed(1) + 'rem">' + hearts[i % hearts.length] + "</span>";
      }
      for (var j = 0; j < 22; j++) {
        html += '<span class="rt__c" style="left:' + (Math.random() * 98).toFixed(1) + '%;background:' + colors[j % colors.length] + ';--d:' + (2.6 + Math.random() * 2).toFixed(1) + 's;--delay:' + (Math.random() * 2.5).toFixed(1) + 's"></span>';
      }
      fx.innerHTML = html;
    }
    document.documentElement.classList.add("nolock");
    if (card) card.focus();
    var close = function () {
      if (closed) return; closed = true;
      pop.classList.add("is-closing");
      document.documentElement.classList.remove("nolock");
      setTimeout(function () { pop.remove(); if (opener && opener.focus) try { opener.focus(); } catch (e) { /* element gone */ } }, reduce ? 0 : 320);
    };
    pop.addEventListener("click", function (e) { if (e.target.closest("[data-rt-close]")) close(); });
    document.addEventListener("keydown", function (e) { if (e.key === "Escape" && !closed) close(); });
    pop.addEventListener("keydown", function (e) {  // keep Tab inside the dialog
      if (e.key !== "Tab") return;
      var f = pop.querySelectorAll("button"); if (!f.length) return;
      var first = f[0], lastEl = f[f.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); lastEl.focus(); }
      else if (!e.shiftKey && document.activeElement === lastEl) { e.preventDefault(); first.focus(); }
    });
  }
})();

/* Quick add from product cards, and the Share button on the product page. */
(function () {
  "use strict";
  var csrf = (document.querySelector("meta[name=csrf-token]") || {}).content || "";
  var toast = document.getElementById("toast"), tt;
  function say(text, bad) {
    if (!toast) return; toast.textContent = text; toast.hidden = false; toast.classList.toggle("toast--error", !!bad);
    requestAnimationFrame(function () { toast.classList.add("toast--show"); });
    clearTimeout(tt); tt = setTimeout(function () { toast.classList.remove("toast--show"); }, bad ? 5000 : 2500);
  }
  document.addEventListener("submit", function (e) {
    var f = e.target; if (!f.matches || !f.matches("[data-quickadd]") || !window.fetch) return;
    e.preventDefault(); if (f.hasAttribute("data-busy")) return;
    f.setAttribute("data-busy", "1");
    fetch(f.action, { method: "POST", body: new FormData(f), credentials: "same-origin", headers: { Accept: "application/json", "X-CSRFToken": csrf } })
      .then(function (r) { return r.json().then(function (d) { return { s: r.status, d: d }; }); })
      .then(function (res) {
        f.removeAttribute("data-busy");
        if (res.s === 401 && res.d.login) { window.location.href = res.d.login; return; }
        if (typeof res.d.count === "number") document.querySelectorAll("[data-cart-count]").forEach(function (b) { b.textContent = res.d.count; b.hidden = !res.d.count; });
        say(res.d.message || "Done.", !res.d.ok);
      })
      .catch(function () { f.removeAttribute("data-busy"); say("No connection. Please try again.", true); });
  });
  document.addEventListener("click", function (e) {
    var b = e.target.closest ? e.target.closest("[data-share]") : null; if (!b) return;
    var url = b.getAttribute("data-share-url") || location.href, title = b.getAttribute("data-share-title") || document.title;
    if (navigator.share) { navigator.share({ title: title, url: url }).catch(function () { /* the person closed the sheet */ }); return; }
    var wa = "https://wa.me/?text=" + encodeURIComponent(title + " " + url); window.open(wa, "_blank", "noopener,noreferrer");
  });
})();

/* "Notify me when available" on out-of-stock products. */
(function () {
  "use strict";
  var csrf = (document.querySelector("meta[name=csrf-token]") || {}).content || "";
  var toast = document.getElementById("toast"), tt;
  function say(text, bad) {
    if (!toast) return; toast.textContent = text; toast.hidden = false; toast.classList.toggle("toast--error", !!bad);
    requestAnimationFrame(function () { toast.classList.add("toast--show"); });
    clearTimeout(tt); tt = setTimeout(function () { toast.classList.remove("toast--show"); }, bad ? 5000 : 3500);
  }
  document.addEventListener("submit", function (e) {
    var f = e.target; if (!f.matches || !f.matches("[data-notify]") || !window.fetch) return;
    e.preventDefault(); if (f.hasAttribute("data-busy")) return;
    f.setAttribute("data-busy", "1");
    fetch(f.action, { method: "POST", body: new FormData(f), credentials: "same-origin", headers: { Accept: "application/json", "X-CSRFToken": csrf } })
      .then(function (r) { return r.json().then(function (d) { return { s: r.status, d: d }; }); })
      .then(function (res) {
        f.removeAttribute("data-busy");
        if (res.s === 401 && res.d.login) { window.location.href = res.d.login; return; }
        var b = f.querySelector("[data-notify-btn]");
        if (res.d.ok && b) { b.textContent = res.d.on ? "Alert on. Tap to cancel" : "Notify me when available"; b.setAttribute("aria-pressed", res.d.on ? "true" : "false"); }
        say(res.d.message || "Done.", !res.d.ok);
      })
      .catch(function () { f.removeAttribute("data-busy"); say("No connection. Please try again.", true); });
  });
})();
