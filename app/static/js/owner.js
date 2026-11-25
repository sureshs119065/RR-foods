/* Owner panel behaviour. Plain JavaScript, no libraries. Every form still works as a normal form without it. */
(function () {
  "use strict";
  var $ = function (s, r) { return (r || document).querySelector(s); };
  var $$ = function (s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); };

  /* ---- one click only: stops a double tap from sending an order action twice ---- */
  $$("form[data-once]").forEach(function (form) {
    form.addEventListener("submit", function (e) {
      if (e.defaultPrevented) return;
      if (form.getAttribute("data-sent")) { e.preventDefault(); return; }
      form.setAttribute("data-sent", "1");
      setTimeout(function () { form.removeAttribute("data-sent"); }, 8000);
    });
  });
  // a cancelled confirm() dialog calls preventDefault on the click, which blocks the submit, so the form stays usable.

  /* ---- quick reasons fill the reject box ---- */
  document.addEventListener("click", function (e) {
    var b = e.target.closest("[data-fill]");
    if (!b) return;
    var box = $(b.getAttribute("data-fill"));
    if (box) { box.value = b.getAttribute("data-text"); box.focus(); }
  });

  /* ---- reject-order dialog (owner orders list) ---- */
  (function () {
    var dialog = document.getElementById("reject-order-dialog");
    var form = document.getElementById("reject-order-form");
    if (!dialog || !form) return;
    $$("[data-reject-order]").forEach(function (button) {
      button.addEventListener("click", function () {
        form.action = button.dataset.action;
        document.getElementById("reject-from-status").value = button.dataset.fromStatus;
        document.getElementById("reject-order-number").textContent = "Reject " + button.dataset.orderNumber + "? The customer will be notified and reserved stock will be restored.";
        document.getElementById("reject-reason").value = "";
        dialog.showModal();
      });
    });
    dialog.querySelector("[data-close-reject]").addEventListener("click", function () { dialog.close(); });
    dialog.addEventListener("click", function (event) { if (event.target === dialog) dialog.close(); });
  })();
})();
