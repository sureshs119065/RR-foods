/* RR FOODS home: gentle auto-scrolling product rows.
   Frontend only. Rows scroll sideways on their own (New Arrivals, and Recently viewed on mobile), pause while touched / hovered / focused,
   can still be swiped or dragged, and stay still for visitors who prefer reduced motion. */
(function () {
  'use strict';
  var reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var loops = document.querySelectorAll('[data-loop]');
  if (!loops.length) return;

  loops.forEach(function (box) {
    var track = box.querySelector('.rr-loop__track');
    if (!track) return;
    var items = track.children;
    if (items.length < 2) return;

    if (reduce) return; /* keep as a plain swipeable row: no clones are made */
    if (track.scrollWidth <= box.clientWidth + 8) return; /* everything already fits: nothing to loop */

    /* Seamless loop: the server sends each card once; the clones exist only while the row is looping, and are hidden from
       assistive technology (aria-hidden), not focusable or clickable (inert), and carry no duplicate ids. */
    Array.prototype.slice.call(track.children).forEach(function (li) {
      var c = li.cloneNode(true);
      c.setAttribute('aria-hidden', 'true');
      c.setAttribute('inert', '');
      c.inert = true;
      if (c.hasAttribute('id')) c.removeAttribute('id');
      Array.prototype.forEach.call(c.querySelectorAll('[id]'), function (n) { n.removeAttribute('id'); });
      Array.prototype.forEach.call(c.querySelectorAll('[fetchpriority]'), function (n) { n.removeAttribute('fetchpriority'); n.setAttribute('loading', 'lazy'); });
      track.appendChild(c);
    });
    box.classList.add('is-looping');

    var pos = 0, paused = false, resumeTimer = null, visible = true, last = 0;
    var SPEED = 38; /* pixels per second */

    function half() { return track.scrollWidth / 2; }
    function pause() { paused = true; clearTimeout(resumeTimer); }
    function resume(delay) {
      clearTimeout(resumeTimer);
      resumeTimer = setTimeout(function () { pos = box.scrollLeft; paused = false; }, delay || 0);
    }

    /* keyboard: arrow keys scroll the row (it is a focusable region) and stop the motion */
    box.addEventListener('keydown', function (e) {
      if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') {
        pause(); box.scrollLeft += (e.key === 'ArrowRight' ? 1 : -1) * 200; pos = box.scrollLeft; e.preventDefault();
      }
    });

    box.addEventListener('mouseenter', pause);
    box.addEventListener('mouseleave', function () { resume(200); });
    box.addEventListener('focusin', pause);
    box.addEventListener('focusout', function () { resume(400); });
    box.addEventListener('touchstart', pause, { passive: true });
    box.addEventListener('touchend', function () { resume(2500); }, { passive: true });
    box.addEventListener('wheel', function () { pause(); resume(1800); }, { passive: true });

    if ('IntersectionObserver' in window) {
      new IntersectionObserver(function (e) { visible = e[0].isIntersecting; }).observe(box);
    }
    document.addEventListener('visibilitychange', function () { last = 0; });

    function tick(t) {
      if (last && !paused && visible && !document.hidden) {
        pos += SPEED * Math.min(t - last, 64) / 1000;
        var h = half();
        if (h > 0 && pos >= h) pos -= h;
        box.scrollLeft = pos;
      } else if (paused) {
        pos = box.scrollLeft;
      }
      last = t;
      requestAnimationFrame(tick);
    }
    /* keep the seamless wrap when a user scrolls manually */
    box.addEventListener('scroll', function () {
      var h = half();
      if (h <= 0) return;
      if (box.scrollLeft >= h) { box.scrollLeft -= h; pos = box.scrollLeft; }
      else if (box.scrollLeft <= 0 && paused) { box.scrollLeft += h; pos = box.scrollLeft; }
    }, { passive: true });

    requestAnimationFrame(tick);
  });
})();
