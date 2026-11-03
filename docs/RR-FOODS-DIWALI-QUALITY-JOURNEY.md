# RR FOODS Quality Journey and Diwali Combos

## About page
`/about` now receives an editable `quality_stages` list from `app/shop/content.py`. The About template renders the six steps and inline SVG icons. `rr-foods-journey.css` provides the responsive vertical/mobile and horizontal/desktop timeline. `quality-journey.js` reveals cards with IntersectionObserver, counts the small verified numeric metrics, draws scroll progress and moves the marker. It honours `prefers-reduced-motion` and leaves content visible without JavaScript.

The only numeric claims displayed are `0 preservatives added` (the supplied brand requirement) and `6 journey stages`. A previously unsupported `50+ quality checks` claim is deliberately not shown.

## Diwali combos
A new `Combo` table stores name, description, item/product list, discounted price, original price, image URL, active state, festival tag and its linked existing `Bundle`. The linked Bundle is used by the existing bundle/cart implementation, so cart pricing is allocated across the product lines at the combo price rather than merely adding full-price products.

Admin routes are under `/admin/combos`: list, create, edit and delete. The form controls product selection, active state, image, prices, festival tag and the site-wide Diwali countdown end time stored in `site_settings` (key: `diwali_end_at`). Only active, in-stock products without active variants are selectable, matching the existing bundle-cart constraints.

Run `flask seed-diwali-combos` after products are imported, active and stocked. It creates three sample combos from actual catalogue products and does not overwrite existing combos.

## Fireworks
`diwali-fireworks.js` uses a bounded canvas particle pool, gravity, fading trails and rocket bursts. Automatic launches run about every 1.2 seconds only while the section is visible and the tab is active. The section wrapper captures pointer clicks; canvas has `pointer-events:none`, leaving cards and forms usable. The Celebrate button fires a multi-burst show. There is no audio by default. Reduced-motion users get a static celebratory state without automatic animation.

## Setup
1. Back up the database and `.env`.
2. Install project requirements in the project's virtual environment.
3. Run `flask db upgrade` to create the `combos` table.
4. Ensure catalogue products are active and have stock; then run `flask seed-diwali-combos` for sample records.
5. Open `/admin/combos` to edit sample contents, prices, active state and countdown date.
6. Verify `/about` and `/offers` on desktop and mobile.
