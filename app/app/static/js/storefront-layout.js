/* RR FOODS shared layout helpers. No framework dependencies. */
(function () {
  "use strict";
  document.querySelectorAll("img[data-category-image]").forEach(function (img) {
    img.addEventListener("error", function () {
      img.hidden = true;
      var fallback = img.parentElement && img.parentElement.querySelector(".ct__ph");
      if (fallback) fallback.hidden = false;
    }, { once: true });
  });
})();
