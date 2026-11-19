/* Runs before first paint (no defer): marks the page as script-enabled.
   The shop is light-only (step 2.6: dark mode was not finished, so the toggle was removed). A visitor who saved "dark" with an
   earlier build has a stale key; drop it so nothing reads it later. */
(function () {
  document.documentElement.classList.add("js");
  try { localStorage.removeItem("nk-theme"); } catch (e) { /* private mode: nothing to clear */ }
})();
