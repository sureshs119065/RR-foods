/* Questions & Feedback: quick-answer buttons fill the answer box (works in the Admin and the Owner panel). */
(function () {
  "use strict";
  document.addEventListener("click", function (e) {
    var b = e.target.closest("[data-fill]");
    if (!b) return;
    var box = document.querySelector(b.getAttribute("data-fill"));
    if (box) { box.value = b.getAttribute("data-text"); box.focus(); }
  });
})();
