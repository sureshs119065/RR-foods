/* Bundle form: add or remove product rows. Rows with no product chosen are ignored on save. */
document.addEventListener("DOMContentLoaded", function () {
  var box = document.getElementById("bundle-lines");
  var tpl = document.getElementById("bundle-line-tpl");
  var add = document.getElementById("add-bundle-line");
  var count = document.getElementById("bundle-count");
  if (!box || !tpl || !add) return;
  var MAX = 30;
  function refresh() {
    var n = box.querySelectorAll(".bundle-line").length;
    if (count) count.textContent = n + " row" + (n === 1 ? "" : "s");
    add.disabled = n >= MAX;
  }
  add.addEventListener("click", function () {
    if (box.querySelectorAll(".bundle-line").length >= MAX) return;
    box.appendChild(tpl.content.cloneNode(true));
    var rows = box.querySelectorAll(".bundle-line select");
    if (rows.length) rows[rows.length - 1].focus();
    refresh();
  });
  box.addEventListener("click", function (e) {
    var b = e.target.closest("[data-remove-line]");
    if (!b) return;
    var row = b.closest(".bundle-line");
    if (box.querySelectorAll(".bundle-line").length <= 1) {
      var s = row.querySelector("select"); if (s) s.value = "";
      var q = row.querySelector("input"); if (q) q.value = 1;
    } else row.remove();
    refresh();
  });
  refresh();
});
