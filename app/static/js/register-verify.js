/* Create account, step 2: digits only, submit when 6 digits are in, and a countdown on "Resend code". The page works without this file. */
(function () {
  "use strict";
  var root = document.querySelector("[data-signup-verify]");
  if (!root) return;

  var input = root.querySelector("input[name=code]");
  var form = input && input.form;
  if (input && form) {
    input.addEventListener("input", function () {
      var digits = input.value.replace(/\D/g, "").slice(0, 6);
      if (digits !== input.value) input.value = digits;
      if (digits.length === 6 && !form.dataset.sent) {      // pasted or autofilled code: no need to press the button
        form.dataset.sent = "1";
        if (form.requestSubmit) form.requestSubmit(); else form.submit();
      }
    });
  }

  var btn = root.querySelector("[data-resend]"), label = root.querySelector("[data-resend-wait]");
  var left = parseInt(root.getAttribute("data-wait"), 10) || 0;
  if (!btn || left <= 0) return;
  btn.disabled = true;
  var timer = setInterval(function () {
    left -= 1;
    if (left <= 0) { clearInterval(timer); btn.disabled = false; label.textContent = ""; return; }
    label.textContent = "(in " + left + "s)";
  }, 1000);
  label.textContent = "(in " + left + "s)";
})();
