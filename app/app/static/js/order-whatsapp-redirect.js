/* After an order is placed, open WhatsApp with the order message ready.
   - Redirects once per order (so coming back from WhatsApp does not bounce you out again).
   - If the browser blocks it, the big "Open WhatsApp and send order" button still works. */
(function () {
  function go() {
    var link = document.getElementById("wa-open");
    if (!link || !link.href) return;
    var key = "wa-sent:" + location.pathname;
    var note = document.getElementById("wa-opening");
    try {
      if (sessionStorage.getItem(key)) {
        if (note) note.textContent = "Tap the button above to open WhatsApp again.";
        return;
      }
      sessionStorage.setItem(key, "1");
    } catch (e) { /* private mode: just redirect */ }
    setTimeout(function () { window.location.href = link.href; }, 300);
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", go);
  else go();
})();
