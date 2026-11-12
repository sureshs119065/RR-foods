/* Admin panel behaviour. Plain JavaScript, no libraries. Everything still works as normal forms without it. */
(function () {
  "use strict";
  var doc = document.documentElement;
  doc.classList.add("js");
  var $ = function (s, r) { return (r || document).querySelector(s); };
  var $$ = function (s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); };
  var csrf = ($("meta[name=csrf-token]") || {}).content || "";

  /* ---- sidebar: drawer on phones, collapsible icon-only mode on desktop ---- */
  var shell = $(".adm");
  var toggle = $("#nav-toggle"), backdrop = $("#nav-backdrop"), collapse = $("#nav-collapse");
  function setDrawer(open) {
    if (!shell) return;
    shell.classList.toggle("adm--open", open);
    if (toggle) toggle.setAttribute("aria-expanded", String(open));
    document.body.classList.toggle("no-scroll", open);
  }
  if (toggle) toggle.addEventListener("click", function () { setDrawer(!shell.classList.contains("adm--open")); });
  if (backdrop) backdrop.addEventListener("click", function () { setDrawer(false); });
  document.addEventListener("keydown", function (e) { if (e.key === "Escape") setDrawer(false); });
  if (collapse) {
    var saved = false;
    try { saved = localStorage.getItem("adm-collapsed") === "1"; } catch (e) {}
    shell.classList.toggle("adm--mini", saved);
    collapse.setAttribute("aria-pressed", String(saved));
    collapse.addEventListener("click", function () {
      var mini = !shell.classList.contains("adm--mini");
      shell.classList.toggle("adm--mini", mini);
      collapse.setAttribute("aria-pressed", String(mini));
      try { localStorage.setItem("adm-collapsed", mini ? "1" : "0"); } catch (e) {}
    });
  }

  /* ---- accordions (animated with grid-template-rows 0fr -> 1fr) ---- */
  var desktop = window.matchMedia("(min-width: 768px)");
  $$(".acc").forEach(function (acc) {
    var btn = $(".acc__head", acc);
    function set(open) { acc.classList.toggle("acc--open", open); btn.setAttribute("aria-expanded", String(open)); }
    set(desktop.matches || acc.hasAttribute("data-open"));
    btn.addEventListener("click", function () { set(!acc.classList.contains("acc--open")); });
    // a section containing an error must be open
    if ($(".error", acc)) set(true);
  });

  /* ---- confirm dialogs for dangerous buttons ---- */
  document.addEventListener("click", function (e) {
    var el = e.target.closest("[data-confirm]");
    if (el && !window.confirm(el.getAttribute("data-confirm"))) e.preventDefault();
  });

  /* ---- bulk selection ---- */
  var all = $("#select-all"), bar = $("#bulk-form");
  function boxes() { return $$("input[name=ids]"); }
  function refreshBulk() {
    var n = boxes().filter(function (b) { return b.checked; }).length;
    if (bar) { bar.classList.toggle("bulk--show", n > 0); var c = $("#bulk-count", bar); if (c) c.textContent = n + " selected"; }
    if (all) all.checked = n > 0 && n === boxes().length;
  }
  if (all) all.addEventListener("change", function () { boxes().forEach(function (b) { b.checked = all.checked; }); refreshBulk(); });
  document.addEventListener("change", function (e) { if (e.target.name === "ids") refreshBulk(); });

  /* ---- live price preview on the product form ---- */
  var mrp = $("[name=mrp]"), dtype = $("[name=discount_type]"), dval = $("[name=discount_value]"), prev = $("#price-preview");
  function money(n) { return "\u20B9" + n.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 }); }
  function updatePreview() {
    if (!mrp || !prev) return;
    var m = parseFloat(mrp.value), v = parseFloat(dval && dval.value) || 0, t = dtype ? dtype.value : "none", f = m;
    if (isNaN(m)) { prev.textContent = "Enter the MRP to see the final price."; return; }
    if (t === "percent") f = m * (100 - Math.min(Math.max(v, 0), 100)) / 100;
    else if (t === "flat") f = m - Math.max(v, 0);
    f = Math.max(f, 0);
    var pct = m > 0 ? Math.round((m - f) / m * 100) : 0;
    prev.innerHTML = "<strong>" + money(f) + "</strong>" + (f < m ? " <s>" + money(m) + "</s> <span class=\"badge badge--ok\">" + pct + "% off</span>" : "");
    if (dval) dval.disabled = t === "none";
  }
  [mrp, dtype, dval].forEach(function (el) { if (el) { el.addEventListener("input", updatePreview); el.addEventListener("change", updatePreview); } });
  updatePreview();

  /* ---- repeating rows (variants) ---- */
  $$("[data-add-row]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var host = $(btn.getAttribute("data-add-row")), tpl = $("template", host);
      host.insertBefore(tpl.content.cloneNode(true), tpl);
    });
  });

  /* ---- drag-and-drop image zone (fills the normal file input) ---- */
  $$(".dropzone").forEach(function (zone) {
    var input = $("input[type=file]", zone), list = $(".dropzone__list", zone);
    function show() {
      if (!list) return;
      list.innerHTML = "";
      Array.prototype.forEach.call(input.files, function (f) {
        var li = document.createElement("li"); li.textContent = f.name + " (" + Math.round(f.size / 1024) + " KB)"; list.appendChild(li);
      });
    }
    input.addEventListener("change", show);
    ["dragenter", "dragover"].forEach(function (ev) { zone.addEventListener(ev, function (e) { e.preventDefault(); zone.classList.add("dropzone--over"); }); });
    ["dragleave", "drop"].forEach(function (ev) { zone.addEventListener(ev, function (e) { e.preventDefault(); zone.classList.remove("dropzone--over"); }); });
    zone.addEventListener("drop", function (e) {
      if (e.dataTransfer && e.dataTransfer.files.length) { input.files = e.dataTransfer.files; show(); }
    });
  });

  /* ---- drag-and-drop reorder for sortable lists (banners). Buttons remain as the keyboard/touch fallback. ---- */
  $$("[data-sortable]").forEach(function (list) {
    var url = list.getAttribute("data-sortable"), dragged = null;
    function save() {
      var ids = $$("[data-id]", list).map(function (el) { return Number(el.getAttribute("data-id")); });
      fetch(url, { method: "POST", headers: { "Content-Type": "application/json", "X-CSRFToken": csrf }, body: JSON.stringify({ ids: ids }), credentials: "same-origin" })
        .then(function (r) { if (!r.ok) throw new Error(); var s = $("#sort-status"); if (s) s.textContent = "Order saved."; })
        .catch(function () { var s = $("#sort-status"); if (s) s.textContent = "Could not save the order. Reload and try again."; });
    }
    $$("[data-id]", list).forEach(function (row) {
      row.setAttribute("draggable", "true");
      row.addEventListener("dragstart", function () { dragged = row; row.classList.add("dragging"); });
      row.addEventListener("dragend", function () { row.classList.remove("dragging"); dragged = null; save(); });
      row.addEventListener("dragover", function (e) {
        e.preventDefault();
        if (!dragged || dragged === row) return;
        var r = row.getBoundingClientRect(), after = (e.clientY - r.top) > r.height / 2;
        row.parentNode.insertBefore(dragged, after ? row.nextSibling : row);
      });
    });
  });

  /* ---- live preview on the header banner form ---- */
  var bp = $("#banner-preview");
  if (bp) {
    var map = { title: "[data-pv=title]", subtitle: "[data-pv=subtitle]", badge_text: "[data-pv=badge]", button_text: "[data-pv=button]" };
    function pv() {
      Object.keys(map).forEach(function (n) { var i = $("[name=" + n + "]"), t = $(map[n], bp); if (i && t) { t.textContent = i.value; t.hidden = !i.value; } });
      var bg = $("[name=bg_color]"), tx = $("[name=text_color]");
      if (bg) bp.style.background = bg.value; if (tx) bp.style.color = tx.value;
    }
    $$("#banner-form input").forEach(function (i) { i.addEventListener("input", pv); });
    pv();
  }
})();

/* ---- header banner form: show only the link field that matches the chosen type ---- */
(function () {
  var sel = document.getElementById("link-type");
  if (!sel) return;
  function sync() {
    Array.prototype.forEach.call(document.querySelectorAll("[data-show-for]"), function (el) {
      el.hidden = el.getAttribute("data-show-for") !== sel.value;
    });
  }
  sel.addEventListener("change", sync);
  sync();
})();
