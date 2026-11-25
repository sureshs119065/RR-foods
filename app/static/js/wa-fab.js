/* Hides the floating WhatsApp button while the footer is on screen, so it never covers footer links. */
(function () {
  'use strict';
  var fab = document.querySelector('.wa-fab'), footer = document.querySelector('.sf');
  if (!fab || !footer || !('IntersectionObserver' in window)) return;
  new IntersectionObserver(function (entries) {
    fab.classList.toggle('wa-fab--hide', entries[0].isIntersecting);
  }).observe(footer);
})();
