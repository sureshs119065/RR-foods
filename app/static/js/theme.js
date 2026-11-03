/* Runs before first paint (no defer) so the saved theme is applied without a flash. */
(function () {
  var d = document.documentElement;
  d.classList.add("js");
  try { var t = localStorage.getItem("nk-theme"); if (t === "dark" || t === "light") d.setAttribute("data-theme", t); } catch (e) { /* private mode: follow the system setting */ }
})();
