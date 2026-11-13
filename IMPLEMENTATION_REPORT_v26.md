# RR FOODS storefront layout repair — v26

## What changed
- Replaced the generic base topbar and duplicated shop-specific header markup with one shared `partials/storefront_header.html`.
- The same shared header is used by `base.html` and `shop/layout.html`, so public error, login/register, account, inbox and offers pages share the storefront header.
- Moved desktop search into the header's single row. Mobile uses the existing drawer and search overlay interactions.
- Added a visible inline SVG cart icon and badge with a green circular action surface.
- Added one shared footer partial and included it in both base and shop layouts.
- Added `rr-storefront-layout.css` as the final stylesheet with the requested variables and one `.container` system (1440px max, responsive gutters).
- Replaced the old 196KB append-only mobile-fix stylesheet with an unloaded compatibility stub and removed the duplicate `rr-foods-design.css` include from the shop layout.
- Aligned the hero copy, shelves, category section, new-arrival grid, How to Order, bottom homepage sections, Offers page and footer to the same container.
- Product shelves use responsive equal-height grids to avoid clipped cards and half-visible cards. Category image failures now show a branded leaf SVG fallback.
- Removed the duplicate cloned product-card markup from the home shelves.
- Removed the unused `storefront.home_rows()` query from `/offers`; the Offers template does not consume `rows`. The route still queries active coupons and promotions and passes the catalogue combo object.

## Not changed
- No URL route definitions, database models, migrations, cart/wishlist/order business logic, or existing JavaScript source files were changed.
- Existing `shop.js` and `shell.js` are loaded once from the shared base shell. One small new helper, `storefront-layout.js`, only reveals the category fallback if an image fails.

## Validation
- 92 Jinja templates parsed without syntax errors.
- Modified Python route files compiled.
- All CSS stylesheets parsed without CSS syntax errors.
- All original JavaScript files and the new helper passed `node --check`.
- Shared route names referenced by the header/footer were found in the shop/auth source.
- ZIP integrity verified after packaging.
- Flask runtime test-client verification was not possible because Flask is not installed in the execution environment. The actual `/offers` HTTP status must be confirmed in the user's Flask environment; see `FRONTEND_LAYOUT_AUDIT_v26.md`.
