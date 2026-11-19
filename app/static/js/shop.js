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
    toast.setAttribute("role", bad ? "alert" : "status"); toast.setAttribute("aria-live", bad ? "assertive" : "polite"); toast.textContent = text; toast.hidden = false; toast.classList.toggle("toast--error", !!bad);
    requestAnimationFrame(function () { toast.classList.add("toast--show"); });
    clearTimeout(tt); tt = setTimeout(function () { toast.classList.remove("toast--show"); }, bad ? 5000 : 2800);
  }
  function setCount(n) { $$("[data-cart-count]").forEach(function (b) { b.textContent = n; b.hidden = !n; }); }

  /* Product photos: try the original image, then its full-size upload, then a bundled product fallback. */
  $$("img[data-product-image]").forEach(function (img) {
    img.addEventListener("error", function () {
      var full = img.getAttribute("data-product-full") || "";
      var fallback = img.getAttribute("data-product-fallback") || "";
      if (full && !img.dataset.fullTried) {
        img.dataset.fullTried = "1";
        if (new URL(full, document.baseURI).href !== img.src) {
          img.removeAttribute("srcset"); img.removeAttribute("sizes");  /* a srcset would override src */
          img.src = full;
          return;
        }
      }
      if (fallback && !img.dataset.fallbackTried) {
        img.dataset.fallbackTried = "1";
        img.removeAttribute("srcset"); img.removeAttribute("sizes");
        img.src = fallback;
        return;
      }
      img.classList.add("is-image-unavailable");
      img.hidden = true;
    });
  });

  /* ---------- overlays: one open at a time, Esc and outside tap close, focus returns ---------- */
  var backdrop = $("#backdrop"), openEl = null, opener = null;
  function lock(on) { root.classList.toggle("nolock", on); }
  /* Step 3.5: closed off-canvas panels are inert (not tabbable, not read out); an open overlay traps Tab */
  var FOCUSABLE = 'a[href],button:not([disabled]),input:not([disabled]):not([type=hidden]),select:not([disabled]),textarea:not([disabled]),summary,[tabindex]:not([tabindex="-1"])';
  function focusables(box) { return $$(FOCUSABLE, box).filter(function (n) { return !n.closest("[hidden],[inert]") && (n.offsetWidth || n.offsetHeight || n.getClientRects().length); }); }
  function trapTab(e, box) {
    var f = focusables(box);
    if (!f.length) { e.preventDefault(); box.setAttribute("tabindex", "-1"); box.focus(); return; }
    var first = f[0], last = f[f.length - 1], a = document.activeElement;
    if (!box.contains(a)) { e.preventDefault(); first.focus(); }
    else if (e.shiftKey && a === first) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && a === last) { e.preventDefault(); first.focus(); }
  }
  function panelInert() {
    var d = $("#drawer"), fs = $("#filter-form");
    if (d && d !== openEl) d.inert = true;
    if (fs && fs !== openEl) fs.inert = !matchMedia("(min-width:1024px)").matches;
  }
  panelInert();
  function open(el, from, withBackdrop) {
    if (openEl) close();
    openEl = el; opener = from || document.activeElement;
    el.inert = false; el.hidden = false; el.setAttribute("aria-hidden", "false");
    if (el.id === "filter-form") { el.setAttribute("role", "dialog"); el.setAttribute("aria-modal", "true"); }
    if (withBackdrop && backdrop) { backdrop.hidden = false; requestAnimationFrame(function () { backdrop.classList.add("is-on"); }); }
    requestAnimationFrame(function () { el.classList.add("is-open"); var f = $("input,a,button", el); if (el.id === "search-overlay") { var i = $("#so-input"); if (i) i.focus(); } else if (f) f.focus(); });
    lock(true);
    $$("[aria-controls=" + el.id + "]").forEach(function (b) { b.setAttribute("aria-expanded", "true"); });
  }
  function close() {
    if (!openEl) return;
    var el = openEl; openEl = null;
    el.classList.remove("is-open"); el.setAttribute("aria-hidden", "true");
    if (el.id === "filter-form") { el.removeAttribute("role"); el.removeAttribute("aria-modal"); }
    if (backdrop) { backdrop.classList.remove("is-on"); setTimeout(function () { if (!openEl) backdrop.hidden = true; }, reduce ? 0 : 280); }
    setTimeout(function () { if (el !== openEl && el.classList.contains("so")) el.hidden = true; }, reduce ? 0 : 280);
    lock(false);
    $$("[aria-controls=" + el.id + "]").forEach(function (b) { b.setAttribute("aria-expanded", "false"); });
    panelInert();
    if (opener && opener.focus) opener.focus();
  }
  var drawer = $("#drawer"), searchO = $("#search-overlay");
  document.addEventListener("click", function (e) {
    var o = e.target.closest("[data-open]");
    if (o) { e.preventDefault(); var w = o.getAttribute("data-open"); if (w === "drawer" && drawer) open(drawer, o, true); if (w === "search" && searchO) { open(searchO, o, false); renderRecent(); } return; }
    if (e.target.closest("[data-close]") || e.target === backdrop) { close(); return; }
    var so = e.target.closest("[data-sheet-open]"); if (so) { var sh = $("#filter-form"); if (sh) open(sh, so, true); return; }
    if (e.target.closest("[data-sheet-close]") || e.target.id === "sheet-backdrop") close();
  });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") { close(); closeZoom(); hideSugg(); return; }
    if (e.key === "Tab") { if (zoom && !zoom.hidden) trapTab(e, zoom); else if (openEl) trapTab(e, openEl); }
  });
  window.addEventListener("resize", debounce(function () { if (openEl && openEl.id === "filter-form" && matchMedia("(min-width:1024px)").matches) { openEl.classList.remove("is-open"); openEl = null; if (backdrop) { backdrop.hidden = true; backdrop.classList.remove("is-on"); } lock(false); } panelInert(); }, 150));
  function debounce(fn, ms) { var t; return function () { var a = arguments, c = this; clearTimeout(t); t = setTimeout(function () { fn.apply(c, a); }, ms); }; }

  /* ---------- header shrinks smoothly on scroll ---------- */
  var sh = $("#sh"), tick = false;
  window.addEventListener("scroll", function () { if (tick || !sh) return; tick = true; requestAnimationFrame(function () { sh.classList.toggle("is-compact", window.scrollY > 40); tick = false; }); }, { passive: true });

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
    if (a.hasAttribute("data-open")) a.classList.add("is-open");
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
  $$("form[role=search]").forEach(function (f) { f.addEventListener("submit", function (e) { var i = $("input[name=q]", f); if (i && !i.value.trim()) { e.preventDefault(); i.focus(); return; } if (i) remember(i.value); }); });
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
        .then(function (d) {
          if (!d || my !== seq) return;
          /* keep the list (and keyboard focus inside it) as it is when the same query is already shown: replacing it would drop focus to <body> */
          if (list.dataset.q === q && list.contains(document.activeElement)) return;
          list.innerHTML = suggestHtml(d, q); list.dataset.q = q; list.hidden = false;
        })
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
      t.addEventListener("click", function () {
        if (!main) return;
        main.hidden = false;
        main.classList.remove("is-image-unavailable");
        main.dataset.fullTried = "";
        main.dataset.fallbackTried = "";
        main.removeAttribute("srcset"); main.removeAttribute("sizes");  /* the first image's srcset must not win over the new src */
        main.src = t.getAttribute("data-src");
        main.setAttribute("data-product-full", t.getAttribute("data-full-src") || t.getAttribute("data-src"));
        main.alt = t.getAttribute("data-alt");
        $$(".gal__t", gal).forEach(function (x) { x.removeAttribute("aria-current"); });
        t.setAttribute("aria-current", "true");
      });
    });
    // swipe between images on touch screens
    var sx = null; gal.addEventListener("touchstart", function (e) { sx = e.touches[0].clientX; }, { passive: true });
    gal.addEventListener("touchend", function (e) {
      if (sx === null) return; var dx = e.changedTouches[0].clientX - sx; sx = null; if (Math.abs(dx) < 50) return;
      var ts = $$(".gal__t", gal); if (ts.length < 2) return; var i = ts.findIndex(function (x) { return x.getAttribute("aria-current") === "true"; }); ts[(i + (dx < 0 ? 1 : -1) + ts.length) % ts.length].click();
    }, { passive: true });
  }
  var zoom = $("#zoom"), zs = zoom && $(".zoom__scroll", zoom), zimg = $("#zoom-img");
  var zoomOpener = null;
  function closeZoom() { if (zoom && !zoom.hidden) { zoom.hidden = true; lock(false); if (zoomOpener && zoomOpener.focus) { try { zoomOpener.focus(); } catch (e) { /* gone */ } } zoomOpener = null; } }
  document.addEventListener("click", function (e) {
    if (e.target.closest("[data-zoom]") && zoom) { zoomOpener = e.target.closest("[data-zoom]"); var m = $("#gal-main"); zimg.src = m.src; zimg.alt = m.alt; zs.classList.remove("is-in"); zoom.hidden = false; lock(true); var x = $("[data-zoom-close]", zoom); if (x) x.focus(); return; }
    if (e.target.closest("[data-zoom-close]")) { closeZoom(); return; }
    if (e.target === zimg) zs.classList.toggle("is-in");
  });

  var form = $("#buyform");
  if (form) {
    var now = $("#price-now"), mrp = $("#price-mrp"), off = $("#price-off"), note = $("#stock-note"), qty = $("#qty");
    function inr(v) { return "₹" + Number(v).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 }); }
    $$("input[name=variant_id]", form).forEach(function (r) {
      r.addEventListener("change", function () {
        var fbtVariant = $("[data-fbt-variant]"); if (fbtVariant) fbtVariant.value = r.value;
        var p = parseFloat(r.dataset.price), m = parseFloat(r.dataset.mrp), s = parseInt(r.dataset.stock, 10), low = parseInt(r.dataset.low, 10);
        now.textContent = inr(p); var barPrice = $("#bar-price"); if (barPrice) barPrice.textContent = inr(p); var pct = m > p ? Math.floor((m - p) * 100 / m) : 0;
        mrp.textContent = inr(m); mrp.hidden = off.hidden = !pct; off.textContent = pct + "% off";
        note.innerHTML = s <= 0 ? '<span class="stock stock--out">Out of stock</span>' : (s <= low || s <= 5) ? '<span class="stock stock--low">Only ' + s + " left</span>" : '<span class="stock stock--ok">In stock</span>';
        var dis = s <= 0; $$("[data-add],[data-buy]", form).forEach(function (b) { b.disabled = dis; });
        var fbtButton = $(".fbt button"); if (fbtButton) fbtButton.disabled = dis;
        qty.max = Math.max(1, Math.min(10, s)); if (+qty.value > +qty.max) qty.value = qty.max;
      });
    });
    $$("[data-step]", form).forEach(function (b) { b.addEventListener("click", function () { var v = (parseInt(qty.value, 10) || 1) + parseInt(b.dataset.step, 10); qty.value = Math.min(+qty.max || 10, Math.max(1, v)); }); });
    form.addEventListener("submit", function (e) {
      if (e.submitter && e.submitter.matches("[data-buy]")) {
        // Buy Now is a normal POST to /buy-now; lock immediately to stop rapid double taps.
        if (form.getAttribute("data-busy")) { e.preventDefault(); return; }
        form.setAttribute("data-busy", "1");
        e.submitter.setAttribute("aria-disabled", "true");
        return;
      }
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
    var pinInput = $("#pin"), pinTimer = null;
    try { var rememberedPin = localStorage.getItem("rr-foods-pincode"); if (rememberedPin && pinInput && !pinInput.value) pinInput.value = rememberedPin; } catch (e) {}
    if (pinInput) pinInput.addEventListener("input", function () {
      pinInput.value = pinInput.value.replace(/\D/g, "").slice(0, 6);
      if (pinInput.value.length === 6) { try { localStorage.setItem("rr-foods-pincode", pinInput.value); } catch (e) {} }
    });
    var pinMsg = $("#pin-msg");
    function etaDate(days) {
      var d = new Date(); d.setDate(d.getDate() + Math.max(1, days));
      return d.toLocaleDateString("en-IN", { weekday: "short", day: "numeric", month: "short" });
    }
    function checkPin(v, quiet) {
      if (!/^\d{6}$/.test(v)) { if (!quiet) { pinMsg.textContent = "Enter a 6 digit pincode."; pinMsg.className = "pin__msg is-bad"; pinInput.setAttribute("aria-invalid", "true"); } return; }
      pinInput.removeAttribute("aria-invalid");
      try { localStorage.setItem("rr-foods-pincode", v); } catch (e) {}
      pinMsg.textContent = ""; pinMsg.className = "pin__msg"; pinMsg.setAttribute("aria-busy", "true"); pinMsg.innerHTML = '<span class="skel skel--line skel--eta" aria-hidden="true"></span><span class="sr">Checking delivery…</span>';
      fetch("/api/pincode/" + v, { headers: { Accept: "application/json" } }).then(function (r) { return r.json(); })
        .then(function (d) {
          var ok = !!d.deliverable;
          pinMsg.removeAttribute("aria-busy");
          pinMsg.textContent = ok ? "Delivery by " + etaDate(d.eta_days || 3) + (d.fee ? " · delivery fee ₹" + Number(d.fee).toLocaleString("en-IN") : " · free delivery") + (d.city ? " (" + d.city + ")" : "") : (d.message || "Could not check right now.");
          pinMsg.className = "pin__msg " + (ok ? "is-ok" : "is-bad");
        })
        .catch(function () { pinMsg.removeAttribute("aria-busy"); pinMsg.textContent = "Could not check right now."; pinMsg.className = "pin__msg is-bad"; });
    }
    pin.addEventListener("submit", function (e) { e.preventDefault(); checkPin(pinInput.value.trim(), false); });
    if (pinInput && /^\d{6}$/.test(pinInput.value)) checkPin(pinInput.value, true);  // a remembered pincode shows its ETA straight away
  }

  /* ---------- saved pincode on address forms + optional city/state lookup ---------- */
  var addressPin = document.querySelector('input[name="pincode"]');
  if (addressPin) {
    try { var rememberedAddressPin = localStorage.getItem("rr-foods-pincode"); if (rememberedAddressPin && !addressPin.value) addressPin.value = rememberedAddressPin; } catch (e) {}
    var addressPinTimer;
    addressPin.addEventListener("input", function () {
      addressPin.value = addressPin.value.replace(/\D/g, "").slice(0, 6);
      if (addressPin.value.length !== 6) return;
      var pinValue = addressPin.value;
      try { localStorage.setItem("rr-foods-pincode", pinValue); } catch (e) {}
      clearTimeout(addressPinTimer);
      addressPinTimer = setTimeout(function () {
        fetch("/api/pincode/" + pinValue, { headers: { Accept: "application/json" } }).then(function (r) { return r.json(); }).then(function (d) {
          if (addressPin.value !== pinValue || !d.ok || !d.deliverable) return;
          var city = document.querySelector('input[name="city"]'), state = document.querySelector('input[name="state"]');
          if (city && d.city && !city.value) city.value = d.city;
          if (state && d.state && !state.value) state.value = d.state;
        }).catch(function () {});
      }, 180);
    });
    if (addressPin.value.length === 6) addressPin.dispatchEvent(new Event("input", { bubbles: true }));
  }

  /* ---------- remembered checkout pincode ---------- */
  var checkoutForm = $("[data-checkout]");
  if (checkoutForm) {
    var lastAddressButton = $("[data-use-last-address]", checkoutForm);
    if (lastAddressButton) lastAddressButton.addEventListener("click", function () {
      var radio = checkoutForm.querySelector('input[name="address_id"][value="' + lastAddressButton.dataset.useLastAddress + '"]');
      if (radio) { radio.checked = true; radio.dispatchEvent(new Event("change", { bubbles: true })); }
    });
    var checkoutPin = $("[data-checkout-pincode]", checkoutForm);
    try { var lastPin = localStorage.getItem("rr-foods-pincode"); } catch (e) {}
    checkoutForm.querySelectorAll('input[name="address_id"]').forEach(function (radio) {
      radio.addEventListener("change", function () {
        try { localStorage.setItem("rr-foods-pincode", radio.dataset.pincode || ""); } catch (e) {}
        if (checkoutPin) checkoutPin.textContent = radio.dataset.pincode || "—";
      });
    });
  }

  /* ---------- checkout: inline error summary (role=alert, focused on failure) ---------- */
  var coForm = $("[data-checkout]");
  if (coForm) {
    var summary = $("[data-error-summary]", coForm), list = $("#co-errors-list");
    if (summary && !summary.hidden) summary.focus();  // server-side failure: land on the summary
    coForm.addEventListener("submit", function (e) {
      var problems = [];
      var addr = $("input[name=address_id]:checked", coForm);
      if (!addr) problems.push(["address_id", "Choose a delivery address."]);
      else if (addr.dataset.ok !== "1") problems.push(["address_id", "We do not deliver to this pincode yet. Choose another address."]);
      $$("[data-field-error]", coForm).forEach(function (n) { n.hidden = true; n.textContent = ""; });
      $$("[aria-invalid]", coForm).forEach(function (n) { n.removeAttribute("aria-invalid"); });
      if (!problems.length) { if (summary) summary.hidden = true; return; }
      e.preventDefault(); coForm.removeAttribute("data-sent");
      list.innerHTML = "";
      problems.forEach(function (p) {
        var li = document.createElement("li"), a = document.createElement("a");
        a.href = "#field-" + p[0]; a.textContent = p[1]; li.appendChild(a); list.appendChild(li);
        var msg = $("#err-" + p[0], coForm); if (msg) { msg.textContent = p[1]; msg.hidden = false; }
        var fld = $("#field-" + p[0], coForm); if (fld) fld.setAttribute("aria-invalid", "true");
      });
      summary.hidden = false; summary.focus();
    });
  }

  /* ---------- checkout: delivery fee and total follow the chosen address ---------- */
  var co = $("[data-checkout]");
  if (co) {
    var money = function (v) { return "₹" + Number(v).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 }); };
    var update = function () {
      var r = $("input[name=address_id]:checked", co); if (!r) return;
      var ok = r.dataset.ok === "1", d = $("#sum-delivery");
      if (d) d.textContent = !ok ? "Not deliverable" : money(r.dataset.delivery);
      var t = money(r.dataset.total); $("#sum-total").textContent = t; $("#bar-total").textContent = t;
    };
    $$("input[name=address_id]", co).forEach(function (r) { r.addEventListener("change", update); }); update();
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
    if (!toast) return; toast.setAttribute("role", bad ? "alert" : "status"); toast.setAttribute("aria-live", bad ? "assertive" : "polite"); toast.textContent = text; toast.hidden = false; toast.classList.toggle("toast--error", !!bad);
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
        var shipment = document.querySelector("[data-order-shipment]");
        if (shipment) {
          var courier = shipment.querySelector("[data-track-courier]"), trackingId = shipment.querySelector("[data-track-id]"), trackingLink = shipment.querySelector("[data-track-link]");
          if (courier) courier.textContent = d.courier_name ? "Courier: " + d.courier_name : "Courier details will appear when the order is dispatched.";
          if (trackingId) trackingId.textContent = d.tracking_id ? "Tracking ID: " + d.tracking_id : "";
          if (trackingLink) { if (d.tracking_url) { trackingLink.href = d.tracking_url; trackingLink.hidden = false; } else { trackingLink.hidden = true; } }
        }
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
    if (!toast) return; toast.setAttribute("role", bad ? "alert" : "status"); toast.setAttribute("aria-live", bad ? "assertive" : "polite"); toast.textContent = text; toast.hidden = false; toast.classList.toggle("toast--error", !!bad);
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
    if (navigator.clipboard && navigator.clipboard.writeText) { navigator.clipboard.writeText(url).then(function () { say("Link copied."); }, function () { window.prompt("Copy this link", url); }); }
    else { window.prompt("Copy this link", url); }
  });
})();

/* "Notify me when available" on out-of-stock products. */
(function () {
  "use strict";
  var csrf = (document.querySelector("meta[name=csrf-token]") || {}).content || "";
  var toast = document.getElementById("toast"), tt;
  function say(text, bad) {
    if (!toast) return; toast.setAttribute("role", bad ? "alert" : "status"); toast.setAttribute("aria-live", bad ? "assertive" : "polite"); toast.textContent = text; toast.hidden = false; toast.classList.toggle("toast--error", !!bad);
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
