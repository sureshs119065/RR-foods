/* Loading states for listing, product and cart: a skeleton replaces the content while the next page loads.
   Progressive enhancement: without JavaScript nothing changes. Content is restored if the page comes back from the
   back/forward cache. Skeletons are aria-hidden; the container gets aria-busy and a visually hidden "Loading" status. */
(function () {
  "use strict";
  var busy = [];

  function show(container, templateId) {
    if (!container || container.classList.contains("is-loading")) return;
    var tpl = document.getElementById(templateId);
    if (!tpl || !tpl.content) return;
    var holder = document.createElement("div");
    holder.className = "skel-holder";
    var status = document.createElement("p");
    status.className = "sr"; status.setAttribute("role", "status"); status.textContent = "Loading…";
    holder.appendChild(status);
    holder.appendChild(tpl.content.cloneNode(true));
    container.classList.add("is-loading");
    container.setAttribute("aria-busy", "true");
    container.appendChild(holder);
    busy.push(container);
  }

  function restore() {
    busy.splice(0).forEach(function (c) {
      c.classList.remove("is-loading");
      c.removeAttribute("aria-busy");
      var h = c.querySelector(":scope > .skel-holder");
      if (h) h.remove();
    });
  }

  function area(name) { return document.querySelector('[data-skel-container="' + name + '"]'); }

  // Run after every other submit handler: if one of them handled the form itself (fetch, preventDefault) there is no page load to wait for.
  function whenNavigating(e, fn) { setTimeout(function () { if (!e.defaultPrevented) fn(); }, 0); }

  document.addEventListener("submit", function (e) {
    var f = e.target;
    if (!f || !f.matches) return;
    if (f.id === "filter-form") whenNavigating(e, function () { show(area("listing"), "skel-listing"); });
    else if (f.matches('form[action^="/cart/"]') && !f.hasAttribute("data-no-skel")) whenNavigating(e, function () { show(area("cart"), "skel-cart"); });
  });

  // The filter form also submits itself on change (form.submit() raises no submit event), so show the loader just before that happens.
  var ff = document.getElementById("filter-form");
  if (ff) ff.addEventListener("change", function () { setTimeout(function () { show(area("listing"), "skel-listing"); }, 280); });

  document.addEventListener("click", function (e) {
    if (e.defaultPrevented || e.button || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    var a = e.target.closest ? e.target.closest("a[href]") : null;
    if (!a || a.target === "_blank" || a.hasAttribute("download")) return;
    var href = a.getAttribute("href") || "";
    if (a.closest(".pager, .active-filters")) whenNavigating(e, function () { show(area("listing"), "skel-listing"); });
    else if (a.closest(".pgrid") && /^\/product\//.test(href)) whenNavigating(e, function () { show(area("listing"), "skel-product"); });
  });

  window.addEventListener("pageshow", function (e) { if (e.persisted) restore(); });
})();
