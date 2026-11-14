# RR FOODS — Flask + PostgreSQL e-commerce platform

A Flask + PostgreSQL shop for RR FOODS: customer storefront, separate Owner and Admin workspaces, catalogue and inventory, cart and WhatsApp-first checkout, order processing, promotions, content (reels, recipes, bundles) and branded responsive pages.

**Brand colour:** `#245C3A` (deep green `#183D2B`) · **Backend:** Python 3.11+, Flask 3, SQLAlchemy 2, PostgreSQL 16+ · **Frontend:** Jinja templates, vanilla JavaScript, CSS · **Migrations:** Flask-Migrate / Alembic

Other documents: [CHANGELOG.md](CHANGELOG.md) (every update so far), [deploy/DEPLOY.md](deploy/DEPLOY.md) (Render, Linux server, Docker, backups, web push), [docs/FEATURES-AND-DESIGN.md](docs/FEATURES-AND-DESIGN.md) (design system, listing rules, Diwali and quality-journey notes, QA and data-review notes).

## Contents

1. [How ordering works](#how-ordering-works)
2. [Features](#features)
3. [Project structure](#project-structure)
4. [Local setup](#local-setup)
5. [Configuration](#configuration)
6. [Database and migrations](#database-and-migrations)
7. [Products and demo data](#products-and-demo-data)
8. [Roles, logins and routes](#roles-logins-and-routes)
9. [Admin panel](#admin-panel)
10. [Owner panel](#owner-panel)
11. [Cart, checkout and order lifecycle](#cart-checkout-and-order-lifecycle)
12. [Delivery](#delivery)
13. [Content, images and uploads](#content-images-and-uploads)
14. [CLI commands](#cli-commands)
15. [Testing](#testing)
16. [Security](#security)
17. [Launch checklist](#launch-checklist)
18. [What has and has not been verified](#what-has-and-has-not-been-verified)

---

## How ordering works

There is **no payment gateway**. Ordering is WhatsApp-first:

1. The customer places the order on the site. Prices, stock, coupon and delivery fee are always recalculated on the server.
2. The "Order placed" page opens WhatsApp with the order already written (`wa.me` link; also a copy-message button).
3. The owner takes payment directly on WhatsApp.
4. The owner confirms the order in the Owner panel, ticking **Payment received** if the money is already in, or uses **Mark as paid** later.
5. The owner moves the order along: Confirmed → Packed → Shipped → Out for delivery → Delivered.

Set `ADMIN_WHATSAPP_NUMBER` (country code and digits only, for example `919876543210`). `flask check-config` warns if it is empty. Orders placed earlier as cash on delivery or online still display and work. A cash-on-delivery order is marked paid when delivered; WhatsApp orders stay "pending" until the owner marks them paid.

## Features

**Customer storefront**
- Homepage with header banner carousel, Offers & Combo band, categories, bestsellers, new arrivals, recently viewed, trust sections and a contact form.
- Shop All (12 products per page), `/bestsellers`, category listings; search with suggestions and typo tolerance; filters for category, price, brand, rating, discount and availability; sorting.
- Product pages: gallery, variants, pincode delivery check, offers, reviews with rating bars, questions and answers, "you may also like", frequently bought together, YouTube recipe video, share button, Buy now.
- Cart (with saved-for-later and coupons), checkout with delivery date and slot, order history and live tracking, cancellation, returns, reorder, invoices (PDF).
- Wishlist, notifications, customer inbox, back-in-stock alerts, password recovery, optional browser push opt-in (see [Known gaps](#known-gaps)).
- Recipes (with cook mode), reels on the homepage, product bundles and festival combos, About page with the quality journey, Help page with a WhatsApp or email message form.

**Admin workspace**: products (variants, images, pricing, bestseller flag, bulk actions, CSV import/export), categories, **Offers** (product offers, coupons, bundles and festival combos together), header banners, reels, recipes, reviews moderation, users, shared customer inbox, stock alerts, read-only order list and detail, audit log, help centre.

**Owner workspace**: sales analytics (with CSV export), inventory (stock, reorder level, batches and expiry), stock history, one consolidated order queue with search and payment filter, order detail with status moves, courier and tracking, payment marking and WhatsApp status messages, delivery slot settings, customer questions, shared inbox.

## Project structure

```text
rr-foods/
├── app/
│   ├── __init__.py        # application factory, security headers, health endpoints
│   ├── config.py          # environment-based configuration
│   ├── cli.py             # custom flask commands
│   ├── api.py             # public JSON endpoints (header carousel, pincode, suggest)
│   ├── auth/              # login, registration, recovery, role decorators
│   ├── admin/             # admin routes
│   ├── owner/             # owner routes
│   ├── shop/              # public storefront routes
│   ├── services/          # cart, checkout, orders, inventory, delivery, notify, whatsapp, analytics, ...
│   ├── models/            # SQLAlchemy models
│   ├── templates/         # auth, account, shop, admin, owner, shared, partials, errors
│   ├── static/            # css, js, img, fonts
│   ├── seed_data/         # catalogue CSV files
│   ├── seed.py  security.py  uploads.py  media.py  prodcheck.py  extensions.py
├── migrations/            # Alembic history (single head)
├── tests/                 # pytest suite (needs PostgreSQL)
├── deploy/                # DEPLOY.md, nginx, systemd, cron
├── docs/                  # FEATURES-AND-DESIGN.md and the product data review CSV
├── scripts/               # backup scripts and the browser layout audit
├── tools/                 # live-site checks and k6 load test
├── add_pincodes.py        # add or change one delivery pincode
├── wsgi.py  gunicorn.conf.py  start.sh  Dockerfile  docker-compose.yml
└── requirements.txt  .env.example  .env.production.example
```

The Python package is the top-level `app/` folder. (Earlier zips contained a stale duplicate `app/app/` tree and copies of the root files inside `app/`; those were removed, so there is now exactly one copy of everything.)

## Local setup

Run everything from the project root (the folder containing `wsgi.py`).

**macOS / Linux**

```bash
python3 -m venv .venv && source .venv/bin/activate
python -m pip install --upgrade pip && pip install -r requirements.txt
cp .env.example .env              # then edit: SECRET_KEY, DATABASE_URL, ADMIN_WHATSAPP_NUMBER
docker compose up -d db           # or use your own PostgreSQL 16+
flask db upgrade
flask seed                        # development only: prints demo passwords once
python -m flask run
```

**Windows PowerShell**

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1      # if blocked: Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
python -m pip install --upgrade pip
pip install -r requirements.txt
Copy-Item .env.example .env       # then edit it
docker compose up -d db
flask db upgrade
flask seed
python -m flask run
```

Open `http://127.0.0.1:5000/`. Monitoring URLs: `/healthz` (process is up), `/readyz` (database answers, 503 if not) and `/health` (JSON database check plus version).

Never run `flask seed` on a live shop: it adds sample data and example logins.

## Configuration

Copy `.env.example` (development) or `.env.production.example` (production) to `.env`. Never commit `.env`.

| Variable | Purpose |
|---|---|
| `FLASK_APP`, `FLASK_ENV` | Entry point (`wsgi.py`); `development` or `production` |
| `SECRET_KEY` | Sessions and CSRF; use 48+ random characters |
| `DATABASE_URL` | PostgreSQL URL (`postgresql://` or `postgresql+psycopg://`) |
| `ADMIN_WHATSAPP_NUMBER` | Shop WhatsApp number; orders are sent here. `WHATSAPP_NUMBER` is accepted as a fallback |
| `DEFAULT_COUNTRY_CODE`, `SHOP_NAME`, `SHOP_TIMEZONE` | Defaults for WhatsApp links, messages and dates (`Asia/Kolkata`) |
| `SITE_URL` | Public URL, used in emails and sitemap |
| `SUPPORT_EMAIL` | Shown on the Help page and footer |
| `UPLOAD_DIR`, `MAX_UPLOAD_MB` | Where uploaded images and videos live, and the size cap |
| `MAIL_MODE` | `off`, `console` or `smtp`; with `smtp` also `MAIL_SERVER`, `MAIL_PORT`, `MAIL_USERNAME`, `MAIL_PASSWORD`, `MAIL_USE_TLS`, `MAIL_FROM` |
| `TRUST_PROXY` | `1` only behind a correctly configured reverse proxy |
| `RATELIMIT_STORAGE_URI` | Redis URL for shared rate-limit state with several workers |
| `SESSION_COOKIE_SECURE` | On by default in production |
| `LOGIN_IP_LOCKOUT_ENABLED`, `LOGIN_IP_MAX_FAILED` | Per-IP lockout (defaults: on, 12 failures); the per-account limit is 5 |
| `DEFAULT_DELIVERY_DAYS`, `DEFAULT_DELIVERY_FEE` | Delivery defaults for Tamil Nadu pincodes (3 days, free) |
| `LOG_DIR`, `LOG_LEVEL`, `LOG_MAX_BYTES`, `LOG_BACKUP_COUNT`, `APP_VERSION` | JSON logging and version reported by `/health` |
| `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY`, `VAPID_CLAIMS_EMAIL` | Optional web push (see deploy/DEPLOY.md) |

## Database and migrations

```bash
flask db upgrade                              # apply migrations
flask db migrate -m "describe the change"     # after changing models; review the file first
```

There is a single migration head (`5d2e9a7c1f40`). Alembic always proposes re-creating the `ix_products_fts` search index; delete that part of any new migration. Do not edit an applied migration or use `stamp head` to bypass the history; create a new migration instead. Migration 2 adds the `pg_trgm` extension used for typo-tolerant search.

`flask db check` currently reports small, harmless drift between the models and the migrations: the unused `orders.delivered_at` column (added by a migration, no code uses it), unique constraints on the `slug` columns of `bundles`, `combos` and `recipe_videos`, and the `ix_products_fts` index. Applying migrations from an empty database works. If you run `flask db migrate`, read the generated file and remove any operation that drops these before applying it.

## Products and demo data

- `flask seed` creates sample admin, owner and customer accounts, categories, products, coupons and banners (development only).
- `flask import-rr-foods --yes` imports the supplied RR FOODS catalogue (`app/seed_data/seed_products.csv`, 32 products, updated by SKU). Missing ingredients, nutrition, allergens and FSSAI details are left blank on purpose: do not invent regulated label facts. Imported stock is **0**; set real stock in Owner → Inventory before selling. Review `docs/RR-FOODS-product-data-review.csv` before publishing package information.
- `flask import-products-csv PATH` imports a general CSV; Admin → Products → Import gives row-level error reports.
- Product images bundled with the code live in `app/static/img/products/`; images uploaded in Admin go to `UPLOAD_DIR`.

## Roles, logins and routes

| Role | Login | Workspace |
|---|---|---|
| Customer | `/login` (sign-up at `/register`) | `/account` |
| Owner | `/owner/login` | `/owner/` |
| Admin | `/admin/login` | `/admin/` |

Role guards cover whole route groups: a wrong-role user cannot enter another workspace, and owners and admins cannot shop. `tests/test_step8_access.py` discovers every route automatically and fails if a new page is missing its protection.

Public pages: `/`, `/shop`, `/bestsellers`, `/category/<slug>`, `/product/<slug>`, `/offers`, `/bundles`, `/recipes`, `/about`, `/help`, `/forgot`, `/reset/<token>`. Signed-in customers: `/cart`, `/checkout`, `/order-placed/<number>`, `/account`, `/account/orders`, `/account/addresses`, `/account/wishlist`, `/notifications`. (`/compare` is retired and redirects to `/shop`.)

## Admin panel

Menu: Dashboard, Products, Orders (read-only), Stock alerts, Notifications, Help & FAQs, Categories, Reels, Recipes, Header banners, Reviews, Users, Audit log, Offers, Inbox, Change password.

- **Offers** is one section with product offers, festival combos, coupons and combo bundles. All offer management lives in Admin only.
- **Products:** create, edit, archive, restore, variants, images, price, discount, stock threshold, bestseller flag, YouTube recipe video ID, bulk actions and CSV.
- **Users:** search, block and unblock, password reset, create owner accounts. All admin actions are written to the audit log.
- Admins can view orders but not change them; fulfilment is the owner's job.

## Owner panel

Menu: Dashboard, Orders, Inventory, Delivery slots, Stock history, Questions, Inbox, Change password (plus Stock alerts with a live count).

- **Orders:** one queue, newest first, with search (order number, name, phone) and an unpaid filter. Each order has a status dropdown and a Reject button; the detail page adds courier and tracking, the payment actions and a WhatsApp status message (English or Tamil templates).
- **Inventory:** stock, reorder level, batch and expiry entries, bulk updates. Stock changes are transactional and logged with user, time, old value, new value and reason.
- **Dashboard:** sales analytics for this month, this year or a custom range; repeat-customer rate, coupon performance, pincode sales, slowest products, expiring batches, estimated days of stock left; CSV export.

## Cart, checkout and order lifecycle

```text
Placed → Confirmed → Packed → Shipped → Out for delivery → Delivered
```

Terminal and side states: Rejected (only before shipment), Cancelled (customer, restricted by status), Return requested, Returned, Refunded.

Rules enforced on the server:

- Price, stock, discounts, coupons and delivery fee are read from the database, never from browser totals. A bundle price saved in the cart is re-checked at checkout.
- Each checkout page carries a one-time token; a double click or a replayed form creates only one order.
- Checkout re-checks stock and locks the inventory rows. Two buyers racing for the last item cannot both succeed.
- Cancelling or rejecting an eligible order restores stock and coupon use once.
- Delivery date and slot (Morning or Evening) are validated against cutoff time, blocked dates, booking horizon and per-slot capacity; the settings row is locked so capacity checks cannot be oversold.
- Buy now uses an isolated session checkout that does not touch the normal cart.

## Delivery

Every pincode from 600001 to 643999 (Tamil Nadu, including Puducherry and Karaikal) is deliverable by rule: 3 days, free delivery by default. A row in `delivery_zones` overrides one pincode (custom fee or days, city and state, or switch it off):

```bash
python add_pincodes.py 641001 --eta 1 --fee 0
python add_pincodes.py 605001 --disable
python add_pincodes.py 636001 --city Salem --state "Tamil Nadu"
```

The product-page pincode check (`/api/pincode/<pin>`), checkout and order placement all use the same rule. The owner configures slots in Owner → Delivery slots.

## Content, images and uploads

- **Reels** (homepage only), **recipes** and **bundles** are managed in Admin. Videos: MP4, WebM or MOV up to 50 MB, checked by their real file header, not just the extension. Recipes accept an uploaded video or a YouTube URL.
- **Festival combos** (for example Diwali, Pongal) are admin-managed `Combo` records linked to a `Bundle`; a combo linked to a bundle appears on `/offers` as that bundle's card inside the "Combo bundles" section. Seed samples with `flask seed-diwali-combos` or `flask seed-childrens-day-combo`. The Diwali countdown and fireworks assets (`diwali.css`, `diwali-fireworks.js`) are kept but are not currently loaded by any page.
- **Images:** the uploader validates format, re-encodes with Pillow to WebP, strips metadata, uses random file names and resizes. Committed static images belong in `app/static/img/`. Uploads go to `UPLOAD_DIR` and are served by the app; back the folder up together with the database. On hosts with a temporary disk (such as Render) attach a persistent disk, or uploads are lost on restart.
- Optional images the CSS expects: `app/static/img/rr-foods-bestsellers-background.jpg`, `rr-foods-new-arrivals-background.jpg` and `RR-FOODS-About-Hero-Background.jpg` (file names are case-sensitive).

## CLI commands

Run from the project root with the virtual environment active.

| Command | Purpose |
|---|---|
| `flask db upgrade` | Apply migrations |
| `flask seed` | Development demo data and accounts |
| `flask import-rr-foods --yes` | Import the RR FOODS catalogue |
| `flask import-products-csv PATH` | Import a general product CSV |
| `flask create-user EMAIL "Name" --role admin\|owner\|user` | Create an account |
| `flask seed-diwali-combos` / `flask seed-childrens-day-combo` | Seed sample festival combos |
| `flask set-setting KEY VALUE` | Change a JSON-backed site setting (strings as JSON, for example `'"RR FOODS"'`) |
| `flask send-emails` | Deliver queued emails (cron, every minute) |
| `flask send-stock-alerts` | Back-in-stock notifications (cron, every 5 minutes) |
| `flask sync-stock-notifications` | Reconcile low-stock and out-of-stock alerts (cron, every 30 minutes) |
| `flask check-config` | Production safety check |

Examples: `flask set-setting tax_percent 5`, `flask set-setting business_name '"RR FOODS"'`. Invoice settings (business name, address, GSTIN) are also site settings.

## Testing

The suite needs PostgreSQL 16 and a **dedicated, empty test database**: tests clear it. Never point `TEST_DATABASE_URL` at a database with real data.

```bash
createdb rr_foods_test
export TEST_DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/rr_foods_test
export DATABASE_URL=$TEST_DATABASE_URL SECRET_KEY=test FLASK_ENV=testing
python -m pytest -q                      # whole suite, about 2 minutes
python -m pytest -q tests/test_step8_access.py tests/test_step8_e2e.py   # access rules + full shop journey
```

On the current code the whole suite passes (**486 tests**). Highlights: every route's access rules; the full customer, owner and admin journey through the real forms; two simultaneous checkouts for the last unit, over several rounds, with stock never below zero; order, review, return and refund rules; password reset; invoice PDF text; the production safety check; `/readyz`. GitHub Actions (`.github/workflows/pytest.yml`) runs the suite on PostgreSQL 16.

**Browser layout audit** (needs a running, seeded site):

```bash
pip install playwright && playwright install chromium
flask db upgrade && flask seed && flask run          # in another terminal
export AUDIT_USER=... AUDIT_OWNER=... AUDIT_ADMIN=...
AUDIT_ROLES=public,user AUDIT_WIDTHS=360,1366 python scripts/layout_audit.py
```

Hard failures (exit code 1): sideways page scroll, JavaScript errors, failed requests. Soft findings: elements sticking out, tap targets under 44 px, inputs under 16 px, images without alt, layout shift over 0.1. Run roles and widths in small groups.

**Still yours to do** (cannot be done from a server): a real Android phone and iPhone; Lighthouse mobile scores; dragging the browser from 1920 px down to 320 px; one real email through your SMTP server; widths 320, 360, 390, 412, 768, 1024 and 1280 on the deployed site. `tools/part3_site_checks.sh https://your-site` runs live-site checks and `k6 run -e BASE=https://staging tools/k6_shop_load.js` is a load test.

## Security

- Argon2 password hashing; CSRF on all forms; sign-out is a POST; role guards on `/admin` and `/owner`.
- Login lockout per account (5 failures) and per IP (12), stored as HMAC hashes (no raw emails or IPs); 15-minute cooldown. Rate limits on login, coupons (10/min), reviews (20/h), questions (10/h), search (90/min) and push routes.
- Content-Security-Policy `script-src 'self'; style-src 'self'`: **templates must not contain inline `<script>` or `style=` attributes** (data blocks such as `type="application/json"` and JSON-LD are fine). Tests enforce this. Also HSTS on HTTPS, Cross-Origin-Opener-Policy, `frame-ancestors`, `form-action`.
- Uploads are decoded and re-encoded; videos are checked by their first bytes. Pillow is kept on a supported release (`>=13,<14`).
- Staff actions are audited. In production the app refuses to start with a weak `SECRET_KEY`, the example database password, insecure cookies or debug on (`flask check-config` lists the problems as `[FIX]` or `[ADVICE]`).
- Never put database, SMTP or VAPID private keys in JavaScript or committed files.

## Launch checklist

- [ ] `flask check-config` reports "0 to fix"; advice items reviewed.
- [ ] Real admin and owner accounts created; no demo accounts or `@nurseskitchen.local` examples.
- [ ] `ADMIN_WHATSAPP_NUMBER` set and a test order walked through every owner step on a real phone.
- [ ] HTTPS works and HTTP redirects to it; `TRUST_PROXY=1` only behind a trusted proxy.
- [ ] Redis installed and `RATELIMIT_STORAGE_URI` set when using several workers.
- [ ] One real email sent through your SMTP server; cron lines installed (`send-emails`, `send-stock-alerts`, `sync-stock-notifications`).
- [ ] Invoice settings filled (business name, address, GSTIN) and checked by your accountant; tax percent set.
- [ ] Product names, prices, pack sizes, real stock, images, ingredients, allergens, nutrition and FSSAI details verified and approved.
- [ ] Delivery rules, fees and slots confirmed; privacy, terms, returns and cancellation policies approved.
- [ ] Database **and** uploads backed up on a schedule, and a restore tested once.
- [ ] Customer, owner and admin workflows, About, Offers and mobile layouts checked on Android and iPhone; Lighthouse run on Home, a product page, cart and checkout.

## What has and has not been verified

**Verified by automated tests on real PostgreSQL:** everything listed under [Testing](#testing).

**Verified by hand in earlier work:** gunicorn in production mode serves with Secure and HttpOnly cookies; `nginx.conf` passes `nginx -t`; the backup script produces a dump that restores with the same product count.

**Not verified:** real phones, Lighthouse scores, real SMTP delivery, the Docker build, the systemd unit, certbot/HTTPS, Redis rate limiting, behaviour under heavy traffic, and interactive widgets in a browser (menu drawer, bottom sheets, carousel swipe, gallery zoom).

### Known gaps

- **Browser push is not sent.** Subscriptions are stored and `app/services/push.py` can send, but nothing calls it, so order-status and back-in-stock events create in-app notifications only. Wiring it into `services/notify.py` should be done as a background or best-effort call so a slow push service cannot delay order changes.
- Guest (signed-out) contact messages are not supported; the contact form uses the signed-in customer inbox. The Help page offers a validated WhatsApp or email handoff instead.
- Not built from the original spec: sign-up email or OTP verification, loyalty or wallet points (only the ledger tables exist), a full Tamil translation (only storage, language switch and navigation labels), admin-editable homepage sections other than the carousel, a tax and delivery settings screen (use `flask set-setting`).
- Select-row checkboxes in Owner → Inventory and Admin → Products are 13 px wide, below the 44 px tap rule.

## License and ownership

No open-source license is declared. Treat the source code, brand assets, product images and business content as project-owned and private unless the owner says otherwise.
