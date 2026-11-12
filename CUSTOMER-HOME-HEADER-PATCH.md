# RR FOODS customer home/header/cart patch

## Changed files (active source tree: `app/`)
- `app/templates/shop/layout.html` — logo-only header, nav label, customer action ordering, drawer links, footer cleanup and configured contact links.
- `app/templates/shop/home.html` — removed facts/promo/needs/deals-grid/reels blocks; added scrollable Offers & Combo products + bundles, two-card trust block, story background section, and featured customer reviews.
- `app/templates/shop/_macros.html` — bell icon glyph.
- `app/templates/shop/product.html` — removed duplicate `data-addcart` marker from the product form and routed Buy now with `formaction` to the isolated flow.
- `app/templates/shop/checkout.html` — Buy now indicator and product return link.
- `app/templates/shop/help.html` — configured email/WhatsApp contact cards and FAQ accordion.
- `app/static/css/rr-foods-overrides.css` — consolidated responsive header, offers carousel, trust, steps, story, reviews and contact styles.
- `app/static/js/shell.js` — removed its duplicate add-to-cart submit handler.
- `app/static/js/shop.js` — one customer add-to-cart submit handler for product, home/listing and wishlist forms; button busy lock.
- `app/shop/cart.py` — Buy now validation/session route and short repeated-submit guard.
- `app/shop/checkout.py` — isolated Buy now checkout view, checkout order handoff and session cleanup.
- `app/services/cart.py` — single-item session checkout view builder.
- `app/services/checkout.py` — order placement supports an isolated Buy now item without reading/deleting normal cart rows.
- `app/shop/catalog.py` — home route loads active bundle data.
- `app/__init__.py` — wishlist count is available to the shared customer header.

The archive also mirrors these changes under `app/app/`, because the supplied ZIP includes a duplicate nested source tree. The deployed Docker/WSGI application imports the top-level `app/` package.

## Validation
- Python bytecode compilation: passed.
- Jinja parsing of all shop templates: passed.
- `node --check` for `shell.js` and `shop.js`: passed.
- `pytest` could not start in this environment because `flask_migrate` is not installed (`ModuleNotFoundError`). No live browser/Lighthouse run was available.

## Remaining work / deployment notes
- The customer contact form is still limited to signed-in customer inbox threads. A true guest submission stored in the existing admin/owner inbox requires a schema migration because the current inbox thread and sender records require user foreign keys. This patch does not weaken those constraints or create a parallel inbox table.
- The story CSS references `/static/img/our-story-bg.webp`; the gradient remains as the fallback if the image is absent. Add an appropriately licensed/approved image at that path to enable the photographic background.
- The FAQ and contact cards are implemented on the Contact page. Phone/hours cards are omitted because no corresponding config keys are currently defined in this project.
- The requested physical viewport matrix (320, 360, 390, 412, 768, 1024, 1280px), screen-reader audit and Lighthouse 95+ target still require browser testing after deployment. The CSS is designed for those breakpoints, but a score is not claimed without a run.
- Existing offers page already includes active bundles; the home Offers & Combo carousel now includes discounted products first and active bundle cards after them.
