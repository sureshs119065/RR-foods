/* Shared by the owner Inventory page and the admin Stock alerts page.
   Inline quantity editor: saves in the background, repaints the status chip, shows a toast.
   Plain JavaScript, no libraries. Every form still works as a normal form post without it. */
(function () {
  "use strict";
  var $ = function (s, r) { return (r || document).querySelector(s); };
  var $$ = function (s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); };
  var csrf = ($("meta[name=csrf-token]") || {}).content || "";

  /* ---- toast ---- */
  var toast = $("#toast"), timer = null;
  function say(text, isError) {
    if (!toast) return;
    toast.textContent = text;
    toast.hidden = false;
    toast.classList.toggle("toast--error", !!isError);
    toast.classList.add("toast--show");
    clearTimeout(timer);
    timer = setTimeout(function () { toast.classList.remove("toast--show"); }, isError ? 6000 : 3000);
  }

  /* ---- stock state badge, same wording as the server ---- */
  var LONG = { out: ["Out of stock", "badge--bad"], low: ["Low stock", "badge--warn"], ok: ["In stock", "badge--ok"] };
  var SHORT = { out: ["Out", "badge--bad"], low: ["Low", "badge--warn"], ok: ["Healthy", "badge--ok"] };
  function stateFor(qty, threshold) { return qty <= 0 ? "out" : qty <= threshold ? "low" : "ok"; }
  function paint(row, state) {
    var badge = $("[data-state-badge]", row);
    if (!badge) return;
    // a table can ask for the short wording (Out / Low / Healthy) with data-stock-labels="short"
    var host = row.closest("[data-stock-labels]");
    var set = host && host.getAttribute("data-stock-labels") === "short" ? SHORT : LONG;
    badge.className = "badge " + set[state][1];
    badge.textContent = set[state][0];
  }

  /* ---- inline editors (stock quantity and alert level) ---- */
  $$("form[data-inline]").forEach(function (form) {
    var input = $("input[type=number]", form), btn = $("button[type=submit]", form);
    var kind = form.getAttribute("data-inline"), row = form.closest("tr");
    function dirty() { return input.value !== input.defaultValue; }
    function sync() { btn.disabled = !dirty(); }
    sync();
    input.addEventListener("input", function () { form.classList.remove("qty--saved", "qty--failed"); sync(); });

    form.addEventListener("submit", function (e) {
      if (!window.fetch) return;            // old browser: normal form post
      e.preventDefault();
      if (!dirty() || form.classList.contains("qty--busy")) return;
      form.classList.add("qty--busy");
      fetch(form.action, {
        method: "POST", body: new FormData(form), credentials: "same-origin",
        headers: { "Accept": "application/json", "X-CSRFToken": csrf }
      }).then(function (r) {
        return r.json().then(function (d) { return { ok: r.ok, status: r.status, d: d }; });
      }).then(function (res) {
        form.classList.remove("qty--busy");
        var d = res.d || {};
        if (res.ok) {
          if (kind === "stock") {
            input.value = String(d.qty); input.defaultValue = input.value;
            var exp = $("input[name=expected]", form); if (exp) exp.value = String(d.qty);
            if (row) paint(row, d.state);
          } else {
            input.defaultValue = input.value;
            var t = Number(d.threshold);
            $$("tr[data-product='" + row.getAttribute("data-product") + "']").forEach(function (r) {
              r.setAttribute("data-threshold", String(t));
              var q = $("form[data-inline=stock] input[type=number]", r);
              if (q) paint(r, stateFor(Number(q.defaultValue), t));
            });
          }
          form.classList.add("qty--saved"); sync(); say(d.message || "Saved.");
        } else {
          form.classList.add("qty--failed");
          if (res.status === 409 && kind === "stock" && typeof d.current === "number") {
            // someone else changed it (for example a new order): show the real number so nothing is overwritten by mistake
            input.value = String(d.current); input.defaultValue = input.value;
            var ex = $("input[name=expected]", form); if (ex) ex.value = String(d.current);
            if (row) paint(row, stateFor(d.current, Number(row.getAttribute("data-threshold"))));
            sync();
          }
          say(d.message || "Could not save. Reload the page and try again.", true);
        }
      }).catch(function () {
        form.classList.remove("qty--busy"); form.classList.add("qty--failed");
        say("No connection. Your change was not saved.", true);
      });
    });
  });
})();
