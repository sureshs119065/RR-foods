document.addEventListener("DOMContentLoaded", () => {
  const link = document.getElementById("wa-open");
  if (!link) return;
  // Same-tab navigation is not blocked as a delayed popup can be.
  window.setTimeout(() => {
    if (document.visibilityState === "visible") window.location.assign(link.href);
  }, 650);
});
