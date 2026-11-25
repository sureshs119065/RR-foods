/* FAQ accordion: one answer open at a time, each question is a button with aria-expanded. No inline script, no libraries. */
(function () {
  "use strict";
  var roots = document.querySelectorAll("[data-faq]");
  Array.prototype.forEach.call(roots, function (root) {
    var items = Array.prototype.slice.call(root.querySelectorAll(".faq__item"));
    var buttons = items.map(function (item) { return item.querySelector(".faq__btn"); });

    function set(item, open) {
      item.classList.toggle("is-open", open);
      item.querySelector(".faq__btn").setAttribute("aria-expanded", open ? "true" : "false");
    }

    root.classList.add("faq--js");              // from here on the CSS collapses closed answers
    items.forEach(function (item) { set(item, false); });

    root.addEventListener("click", function (e) {
      var btn = e.target.closest(".faq__btn");
      if (!btn || !root.contains(btn)) return;
      var item = btn.closest(".faq__item");
      var willOpen = btn.getAttribute("aria-expanded") !== "true";
      items.forEach(function (other) { set(other, other === item && willOpen); });
    });

    root.addEventListener("keydown", function (e) {      // optional arrow-key movement between questions
      var i = buttons.indexOf(document.activeElement);
      if (i < 0) return;
      var next = e.key === "ArrowDown" ? i + 1 : e.key === "ArrowUp" ? i - 1 : e.key === "Home" ? 0 : e.key === "End" ? buttons.length - 1 : -1;
      if (next < 0) return;
      e.preventDefault();
      buttons[(next + buttons.length) % buttons.length].focus();
    });

    var hash = decodeURIComponent((location.hash || "").slice(1));   // /faq#faq-page-3 opens that question
    var target = hash && items.filter(function (item) { return item.id === hash; })[0];
    if (target) { set(target, true); target.scrollIntoView({ block: "center" }); }
  });
})();
