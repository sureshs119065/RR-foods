# RR FOODS platform (Flask + PostgreSQL)

Steps 2 to 7 of the upgrade: project setup, database, sign-in and roles, the admin panel, the owner panel, the storefront, and the extras
(wishlist, compare, reviews, questions, notifications and email, invoices, returns, forgot password). Step 8 is final testing and deployment notes.

## Run it (first time)
1. Install Python 3.11 or newer and PostgreSQL 16 (or run `docker compose up -d` for a ready database).
2. Create the environment and install:
       python -m venv .venv
       .venv\Scripts\activate          (Windows)   or   source .venv/bin/activate   (Mac/Linux)
       pip install -r requirements.txt
3. Copy `.env.example` to `.env` and set `SECRET_KEY` and `DATABASE_URL`.
   With docker compose the default `DATABASE_URL` already works.
4. Create the tables and sample data:
       flask db upgrade
       flask seed
   `flask seed` prints the passwords for the admin, owner and demo customer once. Save them.
   (Or set SEED_ADMIN_PASSWORD, SEED_OWNER_PASSWORD, SEED_USER_PASSWORD in `.env` first.)
5. Start the app:
       flask run
   Open http://127.0.0.1:5000  and  http://127.0.0.1:5000/healthz

## Sign-in and roles (Step 3)
Three separate logins. Each accepts only its own role, and a correct password on the wrong page shows the same
"Incorrect email or password." message, so nobody can learn which accounts exist or what role they have.
    Customers   /login   then /account        (sign up at /register)
    Owner       /owner/login   then /owner/
    Admin       /admin/login   then /admin/
Owner pages return 403 for admins and customers, admin pages return 403 for owners and customers, and signed-out
visitors are sent to the matching login. Every route inside /owner and /admin is protected automatically.
Safety measures: argon2 password hashes, CSRF token on every form, sign-out only by POST, new session on every sign-in,
5 wrong passwords lock the account for 15 minutes, 10 sign-in attempts per minute per IP, owner/admin sessions end after
60 minutes idle (STAFF_IDLE_MINUTES), changing a password signs out other devices, blocked accounts are signed out at once,
"next" links can only point to pages on this site, security headers, private pages are never cached,
and every staff sign-in, failure, lockout and password change is written to the audit log.
Not in this step: forgot-password and email verification (Step 7), block/unblock and reset-password screens (Step 4).
For the live server: set SECRET_KEY, FLASK_ENV=production (marks cookies Secure, needs HTTPS), TRUST_PROXY=1 if you
run behind nginx or a load balancer, and RATELIMIT_STORAGE_URI=redis://... so limits work across several workers.

## Admin panel (Step 4)  /admin/
Sign in at /admin/login. The menu is a slide-in drawer on phones and a collapsible icon-only sidebar on desktop.
Tables turn into stacked cards on small screens, and long forms are collapsible sections.
  Products      add and edit with live price preview, SKU, brand, category and subcategory, MRP, percent or flat discount,
                stock, low-stock alert level, variants (size/colour/weight with own price and stock), up to 10 images
                (drag files in, set the main image, reorder, remove), ingredients, nutrition, specifications, tags,
                offer labels, related products, visible/hidden.
                Archive with Undo, permanent delete (needs a tick and an archived product), duplicate (hidden copy with its own image files).
  Bulk tools    select rows, then hide/show, archive/restore, set discount, change price by %, move category, delete.
                CSV export (respects your filters) and CSV import (see below).
  Categories    two levels, reorder, image, archive/restore, permanent delete only when empty.
  Offers        labels such as "Deal of the Day", shown on products.
  Coupons       percent or flat, minimum cart, optional cap, expiry, total and per-customer limits.
  Header banners  see below.
  Users         search, block/unblock (signs the person out at once), reset password (temporary password shown once),
                create owner accounts.
  Audit log     who did what and when, with before/after values.
Every change is written to the audit log. Money, stock and discount rules are enforced twice: by the form and by the database.

CSV import columns. Required: sku, name, category, mrp (the old site's id and price columns also work).
Optional: subcategory, brand, pack_size, discount_type (none/percent/flat), discount_value, stock_qty, low_stock_threshold,
short_description, description, ingredients, how_to_use, fssai, video_id, tags, is_active, is_bestseller, image_urls (separate with |).
The file is checked first and NOTHING is imported if any row has a problem; the error list gives row numbers.
Exports protect against spreadsheet formula injection (cells starting with = + - @ get a leading apostrophe).

Header banner carousel
  Admin: /admin/header-banners. Add, edit, duplicate, delete, turn on/off, drag to reorder, schedule start and end (typed in shop
  time, stored in UTC), optional countdown, desktop and mobile images (resized automatically), quick-start templates
  (festival, today's special, flash sale, coupon), and carousel settings (seconds per banner 2-30, autoplay, slide or fade, max 1-10).
  Public data for the home page (built in Step 6):  GET /api/header-banners
  returns {"settings": {interval_ms, autoplay, transition, arrows}, "banners": [{id, title, subtitle, badge, desktop_image,
  mobile_image, bg_color, text_color, button_text, href, ends_at}]} with only live banners, in order. It is cached for 60 seconds
  and also refreshed at the exact moment a banner starts or expires, and whenever the admin changes anything.
  With no live banners the list is empty (the home page hides the area). With one banner, autoplay and arrows are off.
  Banner links accept only: a real category, product or coupon, a page on this site starting with /, or a full https:// address.

Uploads are re-encoded with Pillow: anything that is not a real JPG/PNG/WebP is refused, metadata is removed, files are renamed
with random names, resized (products 1600 px, banners 1920 px / 900 px) and saved as WebP. Max 5 MB per image.
Files go in the uploads/ folder and are served from /uploads/. Back that folder up with your database.

## Owner panel (Step 5)  /owner/
Sign in at /owner/login. Same menu behaviour as the admin panel (drawer on phones, collapsible on desktop).
  Dashboard     orders today, orders waiting for confirmation (with how long they have waited), orders to pack or ship,
                low/out-of-stock alerts, revenue for today, the last 7 days and the last 30 days.
                Revenue counts orders that are confirmed, packed, shipped or delivered. New, rejected and cancelled orders are not counted.
                "Today" follows SHOP_TIMEZONE (default Asia/Kolkata).
  Inventory     every live product (and its variants) with the stock number as an editable box: type a number, press Save (or Enter).
                Select rows for bulk update: set to, add, take away, or set the alert level. Bulk is all-or-nothing:
                if any item would go below zero, nothing changes. Alert level (low-stock threshold) is edited per product.
                Filters: search, category, low/out/healthy; sort: lowest stock first (default).
  Stock history who, when, old number, new number and reason for every change, per product or for the whole shop.
  Orders        tabs: New, To pack, To ship, On the way, Delivered, Rejected/cancelled, All; search by order number, name or phone.
                One-tap buttons: Confirm order, Mark packed, Mark shipped, Mark delivered. Reject needs a reason (5 to 300 characters)
                that the customer sees. Every change is stored in order history, audit log and sent to the customer as an in-app notification.
Rules the code enforces
  - Moves go forward only: placed > confirmed > packed > shipped > delivered. Reject is allowed from placed, confirmed or packed (before it ships).
  - Rejecting puts the items back on the shelf (with stock history rows) and gives back a coupon use. It can only happen once per order.
  - Delivering a cash-on-delivery order marks it paid. Online orders are not touched (the refund for a rejected paid order is done in your
    payment dashboard until the refund feature in Step 7; the order page says so).
  - Stock rows are locked while they change, and each edit carries the number the owner saw. If a customer's order changed the stock in the meantime,
    the edit is refused and the real number is shown, so an old page can never overwrite an order's deduction.
  - Two people opening the same order: the second click is refused with "this order is now ...".
  - The owner sees the customer's name, phone and delivery address (needed to deliver), never their email.
Contract with checkout (built in Step 6): checkout takes the stock off the shelf and writes a coupon_usages row when the order is placed.
Order history links in notifications point to /account/orders/<order number>, which Step 6 provides.
No new database migration and no new packages in this step.

## Storefront (Step 6)
Pages: / (home with header offer carousel), /shop (search + filters), /category/<slug>, /product/<slug>, /cart, /checkout, /account/orders,
/account/orders/<order number>, /account/addresses, /offers. Existing /login, /register, /account are unchanged apart from the new header and menu.
  Search         type in the box: suggestions appear as you type (products and categories), typos are tolerated ("milet" finds "Millet"),
                 recent searches are remembered on the device. Phones get a full-screen search.
  Filters        category, price range, brand, rating, discount %, in-stock only. Sort: relevance, popularity, newest, price, rating, discount.
                 On phones filters open as a bottom sheet; on desktop they sit beside the results and apply immediately.
  Product page   gallery (swipe, tap to zoom), option selector with its own price and stock, "Only N left", MRP struck through with % off,
                 pincode delivery check, offers and coupons, specifications, reviews (read-only until Step 7), questions, related products,
                 frequently bought together (from real past orders), recently viewed. Sticky Add to cart / Buy now bar on phones.
  Cart           saved in your account (works on any device), save for later, quantity limited by stock and by 10 per item, coupon box, price breakdown.
  Checkout       saved addresses, cash on delivery or online (test mode), summary with delivery fee for the chosen address, stock re-checked when you press Place order.
  Orders         history, tracking timeline (Placed > Confirmed > Packed > Shipped > Delivered), cancel until shipped, reorder.
Rules the code enforces
  - Prices, stock, coupon and delivery fee are always read from the database. Nothing price-related is trusted from the browser.
  - Placing an order is one transaction: it locks the stock rows, re-checks every line, takes the stock (with a stock-history row naming the order),
    records the coupon use, writes the order with a copy of names/prices/address, and empties the cart. Two buyers racing for the last item: exactly one wins.
  - Cancelling (customer) or rejecting (owner) gives the stock and the coupon use back, once.
  - Adding to the cart needs a customer account (signed-out visitors are sent to sign in and come back). Owners and admins cannot shop.
  - Option products (sizes/weights): the customer must choose an option; the option's own price and stock are used.
Site settings you can change with one command (no screen for these yet):
    flask set-setting free_delivery_min_cart 500      delivery is free when the cart (after coupon) reaches this amount (0 = never free)
    flask set-setting tax_percent 5                   prices include this tax; the bill shows how much of the total it is (0 = hide the line)
    flask set-setting header_carousel_interval_ms 5000   (the carousel settings from Step 4 work the same way)
Delivery fee and ETA per pincode come from the delivery_zones table (seeded for a few pincodes). A pincode that is missing or not serviceable cannot be ordered to.
Online payments: ONLINE_PAYMENT_MODE in .env.
    off    the option is hidden (default when FLASK_ENV=production)
    stub   shows a "Pay online" option and a test page whose button only marks the order paid. No money moves. Default in development.
    To plug in Razorpay: create the gateway order in app/shop/checkout.py (pay view), and mark the payment paid from Razorpay's signed webhook,
    never from the browser. Until then keep production on "off".
Mobile and speed: designed at 360px first; bottom navigation, drawer menu, bottom-sheet filters, sticky buy bars, 44px tap targets, 16px inputs,
safe-area padding for notched phones, lazy images with fixed sizes (no layout shift), dark mode (menu > Dark mode), installable (manifest + a tiny
service worker that only shows an offline page), reduced-motion respected. See "Mobile checks" below for what still has to be tested on real phones.
Header carousel: templates/partials/header_carousel.html, static/js/header-carousel.js. Banner colours are served as CSS from /banner-colors.css
(the site's security policy forbids inline styles). Countdowns use the server's clock. A banner whose countdown ends while the page is open slides out by itself.
No new database migration and no new packages in this step.
Mobile checks to do before launch (I cannot run these from here): real Android + iPhone, Lighthouse mobile run, drag the window from 1920 to 320 px.

## Extras (Step 7)
  Wishlist       heart on every product card and product page; /account/wishlist; works for customers only (guests are sent to sign in).
  Compare        up to 4 products side by side (/compare), kept in the browser session, no account needed.
  Reviews        a customer can review a product only after an order containing it was delivered ("Verified purchase"). One review per
                 customer per product, editable and deletable by its author. Up to 3 photos (JPG/PNG/WebP, re-encoded, 5 MB each).
                 "Helpful" votes (not on your own review). The product's rating is recalculated from visible reviews every time.
                 Admin > Reviews can hide a review that breaks your rules; hidden reviews stop counting in the rating.
  Questions      customers ask on the product page (10-500 characters, at most 3 unanswered per product). Owner > Questions answers or removes
                 them. Only answered questions are public. The customer is notified when answered.
  Notifications  bell in the header with unread count, inbox at /notifications (customers and owners), "mark all read".
                 Owners are told about customer cancellations, return requests and new questions.
  Email          order updates, return updates and password resets are also queued as emails. They are sent by:  flask send-emails
                 Run it every minute from cron.  MAIL_MODE in .env:  off (send nothing)  console (print, for testing)  smtp (real: set MAIL_SERVER,
                 MAIL_PORT, MAIL_USERNAME, MAIL_PASSWORD, MAIL_FROM, SITE_URL). Default is console in development and OFF in production.
                 An email is stamped "sent" only after the mail server accepted it; failures are retried on the next run.
  Invoices       PDF for any order from "confirmed" onwards: customer (order page) and owner (order page). Seller details come from site settings:
                     flask set-setting business_name '"RR FOODS"'
                     flask set-setting business_address '"12 Lake Road, Coimbatore 641001"'
                     flask set-setting gstin '"33ABCDE1234F1Z5"'
                 Amounts print as "Rs." (standard PDF fonts have no rupee sign). Ask your accountant what a GST invoice must contain for you.
  Returns        a customer can request a return of a delivered order within return_window_days (default 7, change with
                 `flask set-setting return_window_days 10`). The owner accepts (optionally putting the items back in stock) or declines with a reason,
                 then marks it refunded after sending the money back. Marking refunded records it; it does not move money. Tab "Returns" in Owner > Orders.
  Forgot password  /forgot sends a one-hour link by email (customers only; staff are reset by an admin). The link works once and stops working if
                 the password changes any other way. The page gives the same answer for unknown emails. Needs MAIL_MODE=smtp in production.
New dependency: reportlab (invoices). No new database migration.
Not built: email/OTP verification at sign-up, loyalty points. Coupons are managed in Admin > Coupons (Step 4) and applied in the cart (Step 6).

## Move your existing products in
Your current website keeps products in a CSV (`docs/sample-products.csv` in the old project).
Copy your latest CSV over `app/seed_data/products.csv`, or run:
    flask import-products-csv path\to\your-products.csv
Existing products (matched by the id column, which becomes the SKU) are updated, new ones are added.
Stock is set to 25 for new in-stock products and 0 for sold-out ones. Change stock in the owner panel (/owner/inventory).
Rows tagged `featured` become bestsellers.

## Tests
Full instructions: TESTING.md. Short version:
    createdb nk_test
    set TEST_DATABASE_URL=postgresql+psycopg://USER:PASSWORD@localhost:5432/nk_test
    python -m pytest -q
WARNING: the test run wipes the test database. Never point TEST_DATABASE_URL at your real data.
Browser layout audit (needs a running seeded site): scripts/layout_audit.py, see TESTING.md.

## Changing the database later
After editing a model:  flask db migrate -m "what changed"   then   flask db upgrade
(Alembic always proposes re-creating the `ix_products_fts` index. Delete that part of the new file.)

## Tables (27)  (migration 2 adds failed_login_count and locked_until to users)
users, addresses, delivery_zones, categories, products, product_images, product_variants, offers, product_offers,
product_related, coupons, coupon_usages, cart_items, wishlist, orders, order_items, order_status_history, payments,
reviews, review_votes, product_questions, inventory_logs, notifications, banners, header_banners, site_settings, audit_logs.

## Files
app/__init__.py       app factory, /healthz and a placeholder home page
app/config.py         settings read from .env
app/models/           user.py, catalog.py, orders.py, engagement.py, content.py, base.py
app/seed.py           seed data and CSV importer
app/cli.py            flask seed, import-products-csv, create-user, set-setting, send-emails, check-config
app/prodcheck.py      production safety check (used at startup and by flask check-config)
app/security.py       argon2 password hashing
app/auth/             sign-in service, routes, decorators, password rules
app/admin/            admin panel (products, categories, offers, coupons, banners, users, audit, bulk, CSV)
app/services/         header banner schedule and cache
app/api.py            public JSON for the home page header carousel
app/uploads.py        safe image upload and resize; app/media.py serves /uploads/
app/owner/            owner panel: dashboard, inventory, orders, password (role-guarded)
app/admin/            admin panel (role-guarded)
app/services/inventory.py, orders.py, notify.py   stock locking and history, order status moves, in-app notifications
app/templates/        base, auth, account, owner, admin, error pages
app/static/css/base.css   shared design tokens (mobile-first)
migrations/           Alembic migration (adds the pg_trgm extension for typo-tolerant search)
tests/                pytest suite

## Deployment (Step 8, Part 2)

### Before anything: the safety check
    flask check-config
It lists settings that are unsafe for real customers ([FIX] = the site refuses to start in production until fixed,
[ADVICE] = works, but fix it soon). With FLASK_ENV=production the site will not start if: SECRET_KEY is weak, the database
still has the example password, ONLINE_PAYMENT_MODE=stub (it would let anyone mark an order paid), cookies are not Secure,
or DEBUG is on. Monitoring URLs: /healthz (process is up) and /readyz (database answers; 503 if not).

### Option A: one Linux server (Ubuntu/Debian)
1. Install: python3-venv, postgresql, nginx, redis-server, certbot.
2. Database: create a user and a database with a strong password (not the example one).
3. Code: copy the project to /srv/nk, then
       python3 -m venv venv && venv/bin/pip install -r requirements.txt gunicorn
4. Settings: copy .env.production.example to /srv/nk/.env and fill it in. Then:
       cd /srv/nk && set -a && . ./.env && set +a
       venv/bin/flask check-config          # must say "0 to fix"
       venv/bin/flask db upgrade
5. Accounts: do NOT run `flask seed` on a live shop (it adds sample data and example @nurseskitchen.local logins).
       venv/bin/flask create-user you@yourshop.com "Your Name" --role admin
       venv/bin/flask create-user owner@yourshop.com "Owner Name" --role owner
   Add real products from Admin > Products (or CSV import). Set business details for invoices:
       flask set-setting business_name '"RR FOODS"'   (see "Extras (Step 7)" for the other invoice settings)
6. Run it: deploy/nk.service (systemd). deploy/nginx.conf for the web server, then `certbot --nginx -d your.domain`.
7. Cron: deploy/crontab.txt (sends queued emails every minute, nightly backup).

### Option B: Docker (web app only)
    docker build -t nk-shop .
    docker run -d --name nk --env-file .env -p 8000:8000 -v nk_uploads:/data/uploads nk-shop
The image does not contain a database: set DATABASE_URL to a managed PostgreSQL or your own server. Run migrations once with
    docker run --rm --env-file .env nk-shop flask db upgrade
Put nginx or a cloud load balancer in front for HTTPS and set TRUST_PROXY=1. Note: the Docker files were written but not built
or run while preparing this step (no Docker was available).

### Backups (do this before launch, not after)
scripts/backup.sh saves the database and the uploaded images every night and keeps 14 days. Copy them off the server as well.
Restore test (do it once, so you know it works):
    createdb nk_restore && pg_restore -d nk_restore /var/backups/nk/db-YYYYMMDD-HHMMSS.dump
Uploads: unpack uploads-*.tar.gz into the folder UPLOAD_DIR points to.

### Updating a live site
    git pull (or copy new files) && venv/bin/pip install -r requirements.txt
    venv/bin/flask db upgrade && sudo systemctl restart nk
Take a backup first. Check /readyz afterwards.

### Online payments
Production defaults to cash on delivery only. To accept online payments, wire Razorpay in app/services/payments.py (verify the
payment signature on the server, never trust the browser), then set ONLINE_PAYMENT_MODE=razorpay and test with Razorpay test keys.

## Launch checklist
[ ] flask check-config says "0 to fix", and advice items are reviewed
[ ] Real admin and owner accounts created; the @nurseskitchen.local examples blocked or never created
[ ] HTTPS works (padlock), http redirects to https
[ ] Redis installed and RATELIMIT_STORAGE_URI set
[ ] One real email sent (forgot password) through your SMTP server; cron line for flask send-emails installed
[ ] Invoice settings filled (business name, address, GSTIN); accountant has looked at the invoice
[ ] Backup ran once and a restore was tested
[ ] Tax percent and free delivery minimum set (flask set-setting tax_percent 5, flask set-setting free_delivery_min_cart 500)
[ ] Delivery zones (pincodes and fees) entered
[ ] Test order placed and walked through all owner steps on a real phone
[ ] Lighthouse mobile run on Home, a product page, cart and checkout
[ ] Android phone and iPhone checked (see TESTING.md section 3)

## What has and has not been verified
Verified by automatic tests on real PostgreSQL (see TESTING.md): every route's access rules, the full customer + owner + admin
journey, stock when two buyers check out at the same instant, order, review, return and refund rules, password reset, invoice PDF
text, production safety check, /readyz.
Verified by hand in this environment: gunicorn in production mode serves the site with Secure/HttpOnly cookies; nginx.conf passes
`nginx -t`; backup.sh makes a dump that restores with the same product count; Chromium layout audit found and fixed sideways
scroll on /shop (360 px) and the signed-out top bar (320 px).
NOT verified: real phones, Lighthouse scores, real SMTP delivery, a real payment gateway, the Dockerfile build, the systemd unit,
certbot/HTTPS, Redis rate limiting, behaviour under heavy traffic, interactive widgets in a browser (menu drawer, bottom
sheets, carousel swipe, gallery zoom), owner/admin pages at widths other than 360 px.
Known small gap: the select-row checkboxes in Owner > Inventory and Admin > Products are 13 px wide (below the 44 px tap rule).
Not built (from the original spec): sign-up email/OTP verification, loyalty/wallet points, admin-editable homepage sections other
than the header carousel, a tax/delivery settings screen (use flask set-setting).


## Content modules (Reels, Recipes and Bundles)

Apply the latest database migration after pulling this update:
    flask db upgrade

Admin menu:
- `/admin/reels`: upload MP4/WebM/MOV reels (50 MB max), set thumbnail, linked product, active state and display order. The home-page display settings control visibility, selected reels and maximum count.
- `/admin/recipes`: full recipe create/edit/publish/delete. Recipes support uploaded video or a YouTube URL, thumbnail, category, ingredients (one per line) and linked products.
- `/admin/bundles`: create/edit/activate/delete product bundles, choose products and quantities, set a bundle price and optional validity dates.

Storefront:
- `/recipes` and `/recipes/<slug>` show published recipes. Recipe detail supports the video player, ingredients and adding linked ingredient products to the cart.
- `/bundles` shows active bundles and savings. Bundle additions create bundle-specific cart lines with allocated discounted unit prices, so the existing checkout/order workflow receives the discounted values. Product detail pages link to matching bundles.
- Reels appear on the home page only. They lazy-load, play muted when visible, and open in a fullscreen-style dialog when tapped.

Uploads:
- Reels and recipe videos accept MP4, WebM or MOV up to 50 MB. Images are re-encoded to WebP by the existing safe image uploader. Configure `MAX_UPLOAD_MB=60` if your deployment overrides the upload cap.
- Configure `WHATSAPP_NUMBER` (country code plus number, digits only) and `SUPPORT_EMAIL` in `.env` to show the optional WhatsApp and support links.

Design/accessibility:
- Storefront surfaces are white, the footer is black, the mobile header keeps navigation above a second-row search/actions area, and content cards are responsive. Controls retain 44px minimum tap targets and visible keyboard focus styles.
- Reels and recipe videos use native browser video playback. Admin uploads show transfer progress and server-side validation errors.

## Verification notes
The source package was syntax-checked with Python's compiler and Jinja's parser. The runtime dependencies (Flask and SQLAlchemy) were not installed in the build environment, so database migration execution, full route tests, checkout integration tests and Lighthouse scoring must be completed in the target environment. Run `pytest` after `pip install -r requirements.txt`; then test `/admin/reels`, `/admin/recipes`, `/admin/bundles`, `/recipes` and `/bundles` with seeded accounts.


## RR FOODS rollout notes

This repository has been rebranded for RR FOODS using the supplied brand asset and the approved Fresh Market – Modern Premium palette. The customer storefront, account pages, owner workspace and admin workspace use the RR FOODS identity.

### Product catalogue import

The supplied spreadsheet has been converted to `app/seed_data/rr_foods_products.csv` for the existing Admin → Products → Import workflow. It contains all 32 source product records, the supplied SKU, category, name, variant, pack weight and price fields. Missing ingredients, nutrition, allergen, preparation, FSSAI and other package data have deliberately been left blank. Source marketing claims have not been published.

1. Configure the application and database using the normal setup instructions below.
2. Create or sign in with an administrator account.
3. Run `flask import-rr-foods` from the project root (add `--yes` to skip the confirmation prompt), or use **Admin → Products → Import** and upload the CSV with **Create missing categories** enabled.
4. Review the import result.
5. Set verified inventory quantities and upload approved product images before opening sales.

All products are imported with zero stock because the source spreadsheet contains no stock counts. They remain unavailable for purchase until the owner enters actual inventory. Do not set stock based on assumptions.

`docs/RR-FOODS-product-data-review.csv` is an internal review sheet retaining the supplied marketing notes and highlighting the package fields that still need verification. Do not upload this review sheet to the storefront.

### About RR FOODS

The `/about` page uses the supplied About Us document. The story is reproduced as provided, with only layout and punctuation formatting.

### Payment and production readiness

The existing project includes a test payment stub, not a live payment gateway. It does not move money and must not be used for customer payments. Production configuration must keep the stub disabled. A real gateway (for example, Razorpay) still requires merchant credentials, server-side order creation, signature verification, webhook handling and end-to-end sandbox testing before enabling online payment. Do not enter gateway secrets into frontend code.

### Launch items requiring business confirmation

- Confirm and publish the official business phone, email, address, WhatsApp number and social links.
- Supply approved product pack images and verify product names, variants, weights and prices.
- Confirm actual inventory quantities.
- Provide approved ingredients, allergens, nutrition panels, preparation and storage directions, shelf life, barcode and FSSAI licence details for each SKU.
- Approve or remove marketing statements in the source spreadsheet before publication.
- Confirm delivery charges, tax rules, shipping coverage, return/cancellation terms and privacy/terms copy.
- Connect and test a live payment gateway before accepting online payments.

### Brand files

The original RR FOODS logo is stored at `app/static/img/rr-foods-logo.png`. It is copied byte-for-byte from the supplied PNG and must not be altered.

### RR FOODS combo offers and bestsellers
- Mark catalogue items as **Bestseller** in Admin → Products. The storefront navigation opens `/bestsellers`, which only lists active products explicitly marked as bestsellers.
- Configure combo promotions in Admin → Combo Offers. Add a name, image, products/quantities, discounted bundle price, active status and optional start/end dates. Active bundles appear on the Offers page and the dedicated Bundles page.
- Combo offers use the existing `bundles` table and migration (`b7f1c9a4d203_content_modules`); run `flask db upgrade` when setting up a fresh database.


## RR FOODS product seed import

The canonical product seed file is `app/seed_data/seed_products.csv` (32 source products).
The source categories and supplied prices/pack sizes are preserved. Seven relevant products
receive a `Breakfast` subcategory under their source category. Missing ingredients, nutrition,
allergens, FSSAI and preparation details are intentionally left blank until approved label
information is supplied. Imported stock defaults to zero.

From the project root, after configuring `.env` and applying migrations:

```powershell
flask import-rr-foods --yes
```

The import command updates matching SKUs and creates missing categories/subcategories.


## RR FOODS brand identity update
The supplied RR FOODS sunflower-and-bees logo is stored at
`app/static/img/rr-foods-brand-logo.png`. The shared base header, storefront
header/footer, authentication pages, admin sidebar and owner sidebar use this
asset. Shared favicon and Apple touch icon references use the same brand image.
The About page Nurse Guide includes an animated identity badge, a stage progress
meter, refined nurse movement, active-stage emphasis, and explicit completion
through the Finish Journey control. Reduced-motion preferences remain supported.
