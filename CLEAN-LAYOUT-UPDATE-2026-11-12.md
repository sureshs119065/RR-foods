# RR FOODS — Clean customer storefront layout update

This patch updates the active Flask customer storefront source in the top-level `app/` package used by `wsgi.py` and the Docker image.

## Changed files

- `app/templates/shop/layout.html`
  - Removed the forced header line-break element.
  - Kept the logo image only, with descriptive alt text and an accessible home-link label.
  - Kept desktop order as logo, navigation, customer notifications, search, favourites, track orders, account and cart.
  - Added Recipes to the desktop navigation and retained Offers & Combo wording.
  - Kept Track orders and Favourites in the mobile drawer; mobile header uses icon-only controls to avoid 320px overflow.
  - Removed the extra customer mobile-fix stylesheet link so the storefront has one consolidated override file.
- `app/templates/shop/home.html`
  - Reordered the existing sections to banner, Offers & Combo, categories, bestsellers and new arrivals.
  - Added a responsive benefits strip below the shopping sections.
  - Preserved existing product cards, bundle forms, review data, trust content, story, CTA and contact section.
- `app/templates/base.html`
  - Updated CSS cache keys. The customer override stylesheet is loaded once; the design stylesheet is included once on the customer page.
- `app/static/css/rr-foods-overrides.css`
  - Replaced conflicting stacked rules with one consolidated responsive customer stylesheet.
  - Desktop header is a single flex row; tablet/mobile header is compact with centred logo and icon controls.
  - Added green fallback styling for missing banner imagery, responsive offers cards, category tiles, benefits, story, reviews and ordering steps.
  - Retained styles used by cart suggestion panels and contact forms.
- `app/static/css/shop.css`
  - Removed unused homepage promotional-tile and Shop-by-need styling. Kept `.need__i`, which is reused by the trust cards.
- `app/static/img/our-story-bg.webp`
  - Added an optimised WebP background derived from the existing RR Foods bestsellers background artwork.

## Preserved

No Flask routes, database models, authentication, CSRF handling, rate limits, cart, coupon, checkout, Buy Now, WhatsApp, wishlist, notifications, reviews, PWA or admin/owner code was changed in this visual-layout patch.

## Validation performed

- Jinja parsing of all templates: passed.
- Python bytecode compilation: passed.
- CSS parsing for `shop.css` and `rr-foods-overrides.css`: passed.
- JavaScript syntax checks for the existing customer scripts: passed.
- ZIP archive integrity: passed.

## Not claimed

A live Render browser run, seven-width visual inspection and Lighthouse score were not run in this environment. Please run the project's `scripts/layout_audit.py` against the deployed site and check widths 320, 360, 390, 412, 768, 1024 and 1280px.
