# Features and design notes

Reference notes that sit beside the README: design system, listing and bestseller rules, the quality journey and festival combos, data and QA notes, and the marketplace comparison. History of changes is in [../CHANGELOG.md](../CHANGELOG.md).

## Design system

**Brand tokens:** primary green `#245C3A`, deep green `#183D2B`, white `#FFFFFF`, warm neutral `#F7F6F2`, light border `#E7E8E3`, brand red `#B3262D`, primary text `#252A26`, secondary text `#737B75`. White is the default page and surface colour; the shared CSS enforces light mode even if an old theme preference was stored in the browser. Buttons use one soft green gradient with white text (at least 4.62:1 contrast at both ends), pale-green secondary buttons, and red for destructive actions.

**Typography and layout:** system font stack for body, the self-hosted Bricolage Grotesque variable font for headings, 4/8-point spacing, fluid heading scale, 12 to 16 px corner radii, light borders, subtle elevation, visible keyboard focus, and 44 px minimum interactive targets (48 px token on mobile). Storefront pages share one container (max 1280 px with responsive gutters) and one header and footer (`partials/storefront_header.html`, `partials/storefront_footer.html`).

**Stylesheets (customer pages):** `base.css` (tokens), `shop.css`, `rr-storefront-layout.css` (single geometry layer), `rr-foods-design.css`, `rr-foods-overrides.css` (consolidated responsive overrides) and `rr-home-final.css` (loaded last on the home page). Do not append further competing override sheets: older stacked `!important` rules were the cause of the v25 layout problems.

**Brand asset:** `app/static/img/rr-foods-logo.png` is a byte-for-byte copy of the supplied logo; the 192 px and 512 px app icons are derived from the same artwork.

**Responsive targets:** no page-level horizontal scroll at 320, 360, 390, 412, 768, 1024 and 1280 px. Cache-busting query strings on the CSS links should be bumped whenever a stylesheet changes.

## Listing, search and bestsellers

- `/shop` shows every active, non-archived product; `/bestsellers` shows only active, non-archived products whose `is_bestseller` flag is true; `/category/<slug>` shows one category. All three use the shared `shop/listing.html`.
- The flag is set in Admin → Products → Add or Edit → Visibility → **Mark as Bestseller**. Sales counts are still recorded for the popularity sort but never promote a product to the Bestsellers page or the homepage bestseller row.
- **12 products per page.** Pagination links keep the active filters, search term, sort and category.
- Server-side filters: `min_price`, `max_price`, `rating`, `brand`, `discount`, `avail`, `sort`, `q`, `category`. A rating filter of 2, 3 or 4 uses the average rating and requires at least one review; "Any" includes unrated products. Sort options: popularity, price ascending and descending, newest, rating. The result total reflects the filtered query. An empty result shows category links and "Ask us on WhatsApp".
- Search uses PostgreSQL full text plus the `pg_trgm` extension for typo tolerance; short queries (under 2 characters) return popular picks instead. Suggestions are served by `/api/suggest`.
- Recommendations: "frequently bought together" ranks co-purchases over distinct orders, caches results per product in each worker for six hours, and fills from the same category when there is too little history. Inactive, deleted, out-of-stock and already-in-cart products are filtered out.

## Orders: operational notes

- The owner updates status through one shared order service that validates the transition, restores stock and releases the coupon on rejection, records history, notifies the customer and writes the audit entry in a single database commit.
- Order-placed page: tries same-tab WhatsApp navigation and keeps an explicit link and a copyable message as fallback. Checkout also has a submit guard (`data-once`) and the one-time server token.
- The `.env` in the project root is loaded before the configuration class is evaluated, regardless of the shell's current directory.
- Account overview shows order, active order, wishlist and unread-notification counts, recent orders, the default address and notifications.
- Customer inbox: customers see only their own threads; Admin and Owner share one staff inbox and either can reply. Customer messages notify both roles; staff replies notify the customer.

## About page: the quality journey

`/about` receives an editable `quality_stages` list from `app/shop/content.py` and renders six stages with inline SVG icons: Sourcing, Cleaning and Sorting, Traditional Processing, Quality Testing, Hygienic Packaging, Delivery. `rr-foods-journey.css` provides the vertical mobile and horizontal desktop timeline; `quality-journey.js` reveals the cards with an IntersectionObserver, counts the numeric metrics, draws scroll progress and moves the marker. Reduced-motion preferences are honoured and all text stays readable without JavaScript.

Only two numbers are shown, both supplied by the brand: `0 preservatives added` and `6 journey stages`. An unsupported "50+ quality checks" claim is deliberately not shown. Do not invent product claims.

## Festival combos (Diwali, Pongal, Children's Day)

A `Combo` stores a name, description, product list, original and discounted price, image, active state, festival tag and a link to an existing `Bundle`. The linked bundle drives the cart, so the combo price is allocated across the product lines. Admin manages combos at `/admin/combos` (only active, in-stock products without active variants are selectable) and the site-wide countdown end time is the `diwali_end_at` setting. `flask seed-diwali-combos` and `flask seed-childrens-day-combo` create samples from real catalogue products and never overwrite existing combos.

On the public site a combo linked to a bundle appears on `/offers` as that bundle's card inside the "Combo bundles" section. `diwali.css` and `diwali-fireworks.js` (canvas rockets about every 1.2 seconds, paused when off-screen or the tab is hidden, bounded particle pool, no audio, static for reduced motion) exist but no page loads them now.

**Test checklist (festival and storefront)**
- `/about` on desktop and mobile: six cards reveal in order, the line fills and the marker travels; with reduced motion and with JavaScript off, all six stages stay readable.
- `flask seed-diwali-combos`, then `/admin/combos`: edit contents, prices, image and active state; create and delete a test combo.
- `/offers`: only active combos and bundles render with real product names, struck-through originals and correct discounted prices.
- Signed in as a customer, add a combo to the cart: the bundle cart price equals the combo price.
- Regression: Shop All, Bestsellers, search, filters, cart and checkout behave as before.

## Data, QA and launch notes

- **Catalogue seed:** `app/seed_data/seed_products.csv` has all 32 supplied products with source SKUs, names, categories, MRP, discount amounts and pack sizes; a `Breakfast` subcategory holds seven relevant products. Ingredients, nutrition, allergens, preparation and FSSAI details are blank where not supplied. Stock is blank so imports default to zero and re-imports never overwrite existing stock. `docs/RR-FOODS-product-data-review.csv` lists what still needs approval.
- **Product page content:** the 20 products in the supplied catalogue document carry full content (ingredients, serving suggestions, recipe ideas, MRP, pack size, best-before, storage, allergens). Other products use their store-listing text in the same card layout; catalogue copy is never attached to products that are not in the catalogue. The provisional Multi Millet Pasta mapping note stays visible until confirmed.
- **Combo catalogue offer:** `app/services/product_catalogue.py` is the source of truth for the ₹999 seven-product combo.
- **Admin demo data:** `app/data/admin_dashboard_demo.json` (labelled illustrative figures shown only when the live range has no orders) and `app/data/admin_faqs.json` (help centre content) are replaceable.
- **Required before public launch:** real stock and approved pack images; all 32 products checked against packaging; business contact details, shipping coverage and charges, tax rules, legal policies and social links confirmed; SMTP, HTTPS, backups and a real-phone test pass (see the README launch checklist).
- **Compare is retired:** `/compare` redirects to `/shop`; the toggle route remains for old links.

## Marketplace comparison (9 Nov 2026)

```text
RR FOODS vs POPULAR E-COMMERCE SITES
Compared against well-known features of Amazon, Flipkart, BigBasket and Blinkit.
Note: this comparison is based on general knowledge of those sites, not a live audit of each one.

KEY
  Had   = already in the project before this update
  Added = added in this update
  Gap   = still missing (see "Recommended next")

PRODUCT DISCOVERY
  Search with suggestions and recent searches ........ Had
  Filters, sort, pagination, bestsellers ............. Had
  Category chips ..................................... Had
  Helpful empty search result (categories + ask on
  WhatsApp) .......................................... Added
  Quick "Add to cart" on product cards (Blinkit and
  BigBasket style; "Choose option" for variants) ..... Added

PRODUCT PAGE
  Back-in-stock alert box on sold-out products ........ Added (update 2)
  Image gallery with zoom, variants, price and % off . Had
  Pincode delivery check ............................. Had
  Add to cart and Buy now, sticky on mobile .......... Had
  Reviews with photos, verified purchase, helpful .... Had
  Questions and answers ............................... Had
  Frequently bought together, similar, recently viewed  Had
  Recipe video ........................................ Had (your own strength)
  Star-by-star rating bars (Amazon / Flipkart) ........ Added
  Share button (phone share sheet, else copy link) .... Added
  Trust strip (WhatsApp confirmation, tracking, returns) Added

CART AND CHECKOUT
  Save for later, coupons, price breakdown, savings ... Had
  Free-delivery progress bar (BigBasket / Blinkit) .... Added
  Address book, delivery zones, order and pay on
  WhatsApp ............................................ Had

AFTER THE ORDER
  Order tracking, invoice PDF, cancel, return, reorder . Had
  Notifications and email ............................. Had

ACCOUNT AND TRUST
  Wishlist, messages to the shop, forgot password ..... Had
  PWA (installable, offline page) ..................... Had
  Security: CSRF, rate limits, lockout, audit log ..... Had

RECOMMENDED NEXT (not done in this update)
  1. Online payment (UPI / cards) and optional Cash on Delivery. Postponed by choice (WhatsApp ordering stays).
  2. (done) Back-in-stock alerts.
  3. Delivery slot choice at checkout.
  4. Review filters and sorting (by stars, with photos).
  5. Subscribe-and-repeat for regular items (millet pasta, podi).
  6. Tamil language option.
  7. Responsive image sizes (srcset) and skeleton loading for faster feel on slow networks.
  8. Guest checkout (currently sign-in is required to add to cart).

COLOUR AND BUTTON SYSTEM (update 2, file app/static/css/rr-foods-white-ui.css)
  All page, section, card and panel backgrounds are white; separation uses thin green-grey borders and soft shadows.
  Buttons use one gradient: #2F7A4D to #245C3A to #1B4A2F, white text (contrast 5.2:1 or better), lift on hover,
  focus ring, press effect, 44 px tap height, disabled style. Secondary buttons are white with a green outline.
  Destructive buttons are solid brand red. Footer, announcement bar and admin side menu stay solid deep green #183D2B.

DESIGN RULES KEPT
  No inline styles or scripts (the project's tests enforce this), so the bars use the standard <progress> element.
  No database changes, no new migrations.
  Logo and "Fresh Market" green palette unchanged.
```
