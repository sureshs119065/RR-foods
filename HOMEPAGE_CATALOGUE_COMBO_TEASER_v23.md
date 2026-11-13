# RR FOODS homepage catalogue combo teaser — Version 23

Base: `RR_Foods_Homepage_Combo_ReadyOrder_Fix_v22.zip`

## Homepage
- Removed the database-driven loop that could display multiple sample/admin Combo and Bundle records in the homepage Offers & Combo shelf.
- The homepage now displays one catalogue-defined combo teaser: `RR FOODS – TRADITIONAL GRAINS & EVERYDAY ESSENTIALS COMBO`, priced at `₹999`.
- The homepage teaser contains only the combo name, price and a View combo link. It does not show the combo description, included-product list, pack sizes, or add-to-cart form.
- The teaser links directly to `/offers#catalogue-combo`.
- Genuine discounted individual products remain in the separate product-offers carousel.

## Offers & Combo page
- Added the full catalogue combo detail using `CATALOGUE_COMBO_OFFER` as the source of truth.
- Shows the catalogue title, strapline, description, price, all seven included products with pack sizes, and closing description.
- Removed the sample Diwali combo and dynamic bundle card loops from this page so the catalogue combo is the single featured combo.
- Existing product promotions and coupon-code sections remain.

## Source content
The seven products and pack sizes are taken verbatim from `app/services/product_catalogue.py`:
1. Multi Millet Instant Noodles — 180 g
2. Multi Millet Pasta — 180 g
3. Multi Millet Vermicelli (Semiya) — 200 g
4. Multi Millet Chapati Maavu (Multi Millet Grain Atta) — 500 g
5. Soup Mix (selected variant) — 130 g
6. Traditional Tirunelveli Idli Podi — 250 g
7. Karuppu Kavuni Rice, Black Urad Dal & Biotin Kanji Mix — 275 g

No sample combo records are created or deleted by this source-code update. Existing database records may remain in the admin database, but they are no longer rendered as combo cards on the homepage or Offers & Combo page.

## Validation
- Jinja parsing passed for homepage, offers page and shared layout.
- Python compilation passed for storefront and catalog route.
- Mirrored `app/app` files match their corresponding `app` files.
- CSS and template cache key updated to `rr-home-layout-23`.
- ZIP integrity checked.
