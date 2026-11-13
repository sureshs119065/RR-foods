# RR FOODS v27 - home page alignment (frontend only)

Changed files (no backend, routes, models, database or JS touched):
- app/static/css/rr-home-final.css  (NEW, loaded last)
- app/templates/base.html           (one extra <link> to the new stylesheet)
- app/static/css/rr-storefront-layout.css (removed a stray literal "\n" typo)

Root cause: older sheets (rr-foods-overrides.css, rr-foods-design.css with !important)
out-ranked the v26 layout rules, so the header search wrapped to a second row, headings
turned dark on green banners, and the category grid left an orphan tile.

Fix: one shared container (1280px, responsive gutters) for header, hero copy, every
section and the footer; single-row header; 8 equal category tiles; 4-column product grid
(3 / 2 on smaller screens); aligned How to Order, Recently Viewed + Our Story, Reviews,
Shortcuts, Ready to order, support form and footer; white headings on green banners.
Tested at 390, 820, 1366 and 1920 px: no horizontal overflow.

## v28 additions (frontend only)
- Offers & Combo: designed combo banner (whole card is one link), animated rings, price + button.
- New Arrivals / offer products: auto-scrolling looping row (app/static/js/home-loop.js),
  pauses on hover/focus/touch, swipeable, still when "reduce motion" is on.
- Product cards in the rows are smaller (188px wide, 160px on phones).
- Recently Viewed: new full-width panel with compact horizontal item cards and a designed empty state.
Files: app/templates/shop/home.html, app/static/css/rr-home-final.css, app/static/js/home-loop.js
