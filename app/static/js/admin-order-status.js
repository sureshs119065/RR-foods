document.addEventListener("submit", function (event) {
  const form = event.target.closest(".status-action-form");
  if (!form) return;
  const status = form.dataset.status;
  const reason = form.querySelector('[name="reason"]');
  if (["rejected", "cancelled", "returned", "refunded"].includes(status)) {
    const message = `Are you sure you want to mark this order ${status}?`;
    if (!window.confirm(message)) { event.preventDefault(); return; }
  }
  if (["rejected", "returned"].includes(status) && (!reason.value.trim() || reason.value.trim().length < 5)) {
    event.preventDefault();
    window.alert("Please enter a reason of at least 5 characters.");
    reason.focus();
    return;
  }
  form.querySelector("button").disabled = true;
});
