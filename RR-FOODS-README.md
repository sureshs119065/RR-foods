# RR FOODS — Full-Stack E-commerce Platform

A Flask + PostgreSQL e-commerce application for RR FOODS. It includes a customer storefront, separate customer/owner/admin access, catalogue and inventory management, cart and checkout, order processing, promotions, content modules, and responsive branded pages.

**Brand colour:** `#1f5c3a`  
**Backend:** Python, Flask, SQLAlchemy, PostgreSQL  
**Frontend:** Jinja templates, vanilla JavaScript, CSS  
**Database migrations:** Flask-Migrate / Alembic

---

## Contents

1. [Project overview](#project-overview)
2. [Main features](#main-features)
3. [Technology stack](#technology-stack)
4. [Project structure](#project-structure)
5. [Requirements](#requirements)
6. [Local setup — Windows PowerShell](#local-setup--windows-powershell)
7. [Local setup — macOS and Linux](#local-setup--macos-and-linux)
8. [Environment configuration](#environment-configuration)
9. [Database and migrations](#database-and-migrations)
10. [Initial data and product import](#initial-data-and-product-import)
11. [User roles and login URLs](#user-roles-and-login-urls)
12. [Customer storefront routes](#customer-storefront-routes)
13. [Admin panel](#admin-panel)
14. [Owner panel](#owner-panel)
15. [Cart, checkout and order lifecycle](#cart-checkout-and-order-lifecycle)
16. [RR FOODS homepage and About page](#rr-foods-homepage-and-about-page)
17. [Bestsellers, bundles and Diwali combos](#bestsellers-bundles-and-diwali-combos)
18. [Reels and recipes](#reels-and-recipes)
19. [Images and uploads](#images-and-uploads)
20. [CLI commands](#cli-commands)
21. [Testing](#testing)
22. [Production deployment](#production-deployment)
23. [Backup and restore](#backup-and-restore)
24. [Security notes](#security-notes)
25. [Pre-launch checklist](#pre-launch-checklist)
26. [Known configuration and verification notes](#known-configuration-and-verification-notes)

---

## Project overview

RR FOODS is organized as a Flask application with feature blueprints. Jinja templates render the storefront and staff panels. SQLAlchemy models store users, catalogue items, variants, carts, orders, inventory history, reviews, notifications, content, promotions and settings in PostgreSQL.

The application has three distinct account roles:

- **Customer:** browse products, manage a cart, place orders and use account features.
- **Owner:** manage inventory, fulfil orders and respond to customer questions.
- **Admin:** manage products, categories, promotions, users, content, combo offers and audit records.

The storefront is responsive and uses the RR FOODS green visual identity. Browser interactions use regular CSS and JavaScript; no frontend framework is required for the current pages.

## Main features

### Customer storefront

- Homepage with promotional areas and configurable header banner carousel.
- Shop All, bestseller and category product listings.
- Product search, suggestions, typo-tolerant search and recent searches.
- Filters for category, price, brand, rating, discount and stock.
- Product detail pages with gallery, variants, stock, offers, reviews and related products.
- Cart, saved-for-later items, coupon application and checkout.
- Customer addresses, order history, order tracking, cancellation and reorder.
- Wishlist, product comparison, reviews, helpful votes and product questions.
- Notifications, invoices, returns and password recovery.
- Recipes, recipe detail pages, product bundles and homepage reels.

### Admin workspace

- Product create/edit/archive/restore and permanent deletion workflow.
- Product variants, images, stock thresholds, pricing, discounts and bestseller flag.
- Category and subcategory management.
- Bulk product actions and CSV import/export.
- Offers and coupons.
- Header banner carousel management and scheduling.
- User management, owner account creation and password reset.
- Reviews moderation and audit log.
- Reels and recipe management.
- Product bundles and Diwali combo management.

### Owner workspace

- Sales and order dashboard.
- Inventory editing and bulk stock operations.
- Low-stock and out-of-stock alerts.
- Stock movement history.
- Order confirmation, packing, shipping, delivery and rejection.
- Customer questions and response workflow.
- Owner password management.

### Quality and brand experience

- RR FOODS green theme (`#1f5c3a`).
- About Us story page.
- Nurse Guide quality journey: six stages from ingredient sourcing through delivery, with SVG nurse character, stage props, speech bubble, progress, navigation and reduced-motion support.
- Homepage Bestsellers and New Arrivals image-backed promotional blocks.
- Diwali combo offer cards, countdown and canvas fireworks animation.
- Responsive layout and keyboard-accessible controls in the relevant components.

---

## Technology stack

| Layer | Technology |
|---|---|
| Server | Python 3.11+ and Flask 3 |
| ORM | Flask-SQLAlchemy / SQLAlchemy 2 |
| Database | PostgreSQL 16+ |
| Migrations | Flask-Migrate / Alembic |
| Templates | Jinja2 |
| Frontend | HTML, CSS and vanilla JavaScript |
| Authentication | Argon2 password hashing |
| Forms/security | Flask-WTF CSRF |
| Rate limiting | Flask-Limiter |
| Image processing | Pillow |
| PDF invoices | ReportLab |
| Tests | pytest |
| Production server | Gunicorn |
| Optional infrastructure | Redis, Nginx, Docker |

See `requirements.txt` for pinned compatibility ranges.

---

## Project structure

```text
rr-foods/
├── app/
│   ├── __init__.py              # Flask application factory and blueprint registration
│   ├── config.py                # Environment-based configuration
│   ├── extensions.py            # Flask extensions
│   ├── cli.py                   # Custom Flask CLI commands
│   ├── api.py                   # Public JSON API endpoints
│   ├── security.py              # Password/security helpers
│   ├── uploads.py               # Validated image upload handling
│   ├── media.py                 # Uploaded media serving
│   ├── prodcheck.py             # Production configuration checks
│   ├── seed.py                  # Demo seed and CSV import functions
│   ├── auth/                    # Login, registration, recovery and role decorators
│   ├── models/                  # SQLAlchemy models
│   ├── shop/                    # Public storefront routes
│   ├── admin/                   # Admin routes
│   ├── owner/                   # Owner routes
│   ├── services/                # Cart, checkout, inventory, orders, mail, etc.
│   ├── templates/
│   │   ├── auth/
│   │   ├── account/
│   │   ├── shop/
│   │   ├── admin/
│   │   ├── owner/
│   │   └── partials/
│   └── static/
│       ├── css/                 # Base, shop, admin, owner and feature styles
│       ├── js/                  # Storefront and feature interactions
│       ├── img/                 # Brand assets and static images
│       └── fonts/
├── migrations/                  # Alembic migration history
├── tests/                       # pytest tests
├── docs/                        # Feature notes, QA and data review documents
├── deploy/                      # Nginx, systemd and cron examples
├── scripts/                     # Backup and layout audit scripts
├── .env.example                 # Development environment template
├── .env.production.example      # Production environment template
├── Dockerfile
├── docker-compose.yml            # PostgreSQL service for local development
├── requirements.txt
├── TESTING.md
├── IMPLEMENTATION-REPORT.md
└── wsgi.py
```

---

## Requirements

- Python 3.11 or newer.
- PostgreSQL 16 or newer.
- Windows, macOS or Linux.
- Git (recommended).
- Optional: Docker Desktop, Redis and Nginx.

---

## Local setup — Windows PowerShell

Open PowerShell in the project root (the folder containing `wsgi.py` and `requirements.txt`).

### 1. Create and activate a virtual environment

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
```

If PowerShell blocks script execution for the current user:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

Then activate again. If the environment already exists at a different path, activate that exact path. For example:

```powershell
& "D:\path\to\project\.venv\Scripts\Activate.ps1"
```

Check that Python and pip belong to the intended environment:

```powershell
python --version
python -m pip --version
```

### 2. Install dependencies

```powershell
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### 3. Configure environment variables

```powershell
Copy-Item .env.example .env
```

Edit `.env` and set a strong `SECRET_KEY` and the correct PostgreSQL `DATABASE_URL`.

### 4. Start PostgreSQL

Use your local PostgreSQL installation, or start the included database container:

```powershell
docker compose up -d db
```

The default Docker database values are for local development only.

### 5. Create database tables

```powershell
flask db upgrade
```

### 6. Seed demo data (optional)

```powershell
flask seed
```

The command prints the generated demo account passwords once. Save them securely. Do not run demo seeding on a production database.

### 7. Start Flask

```powershell
python -m flask run
```

Open:

- Storefront: `http://127.0.0.1:5000/`
- Health: `http://127.0.0.1:5000/healthz`
- Readiness: `http://127.0.0.1:5000/readyz`

**Important:** Run commands from the project root. If `.\.venv\Scripts\Activate.ps1` is not found, the virtual environment is not located in the current directory. Use the correct full path or create a new `.venv` in the project root.

---

## Local setup — macOS and Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env`, ensure PostgreSQL is running, then:

```bash
flask db upgrade
flask seed
python -m flask run
```

---

## Environment configuration

The repository contains `.env.example` and `.env.production.example`. Copy the appropriate example and replace development values.

Common settings:

| Variable | Purpose |
|---|---|
| `FLASK_APP` | Flask entry point; normally `wsgi.py` |
| `FLASK_ENV` | `development` or `production` |
| `SECRET_KEY` | Secret used for sessions and CSRF; use a long random value |
| `DATABASE_URL` | PostgreSQL connection string using the psycopg driver |
| `UPLOAD_DIR` | Directory for uploaded product/banner/content media |
| `MAX_UPLOAD_MB` | Upload size limit |
| `SHOP_TIMEZONE` | Shop timezone; normally `Asia/Kolkata` |
| `ADMIN_WHATSAPP_NUMBER` | Shop WhatsApp number (country code, digits only). Orders are sent here; payment is taken on WhatsApp |
| `MAIL_MODE` | `off`, `console` or `smtp` |
| `MAIL_SERVER`, `MAIL_PORT` | SMTP server settings |
| `MAIL_USERNAME`, `MAIL_PASSWORD` | SMTP credentials |
| `MAIL_FROM` | Sender address |
| `SITE_URL` | Public site URL used in emails |
| `WHATSAPP_NUMBER` | Optional support number, country code plus digits |
| `SUPPORT_EMAIL` | Optional support email |
| `RATELIMIT_STORAGE_URI` | Redis URL for shared rate-limit state in multi-worker deployments |
| `TRUST_PROXY` | Enable only when correctly deployed behind a trusted reverse proxy |

Never commit `.env`, production credentials, database passwords or payment secrets. The `.env.example` file is a template, not a secure production configuration.

---

## Database and migrations

Apply migrations after installing dependencies and configuring the database:

```bash
flask db upgrade
```

Current migration history includes:

- `9abfa11104ad` — initial schema.
- `b7f1c9a4d203` — content modules.
- `dcef60c4798e` — login lockout columns.
- `ef30c2a6d811` — admin-managed Diwali combos.

To create a migration after changing SQLAlchemy models:

```bash
flask db migrate -m "describe the schema change"
flask db upgrade
```

Review generated migration files before applying them. Do not edit an already-applied migration in a deployed environment; create a new migration instead.

---

## Initial data and product import

### Demo seed

```bash
flask seed
```

This creates sample accounts and catalogue/demo data. It is intended for development and testing only.

### RR FOODS catalogue import

The supplied catalogue CSV is:

```text
app/seed_data/seed_products.csv
```

Import it using:

```bash
flask import-rr-foods --yes
```

The import preserves supplied catalogue values and creates missing categories as supported by the importer. Imported inventory defaults to zero where stock was not supplied. Set actual stock in Owner → Inventory before allowing orders.

Review `docs/RR-FOODS-product-data-review.csv` before publishing package information. Do not invent ingredients, nutrition, allergens, FSSAI details, preparation directions or other regulated product-label facts.

### Other product CSV import

```bash
flask import-products-csv path/to/products.csv
```

Use the Admin → Products import workflow for validation and row-level error reporting.

---

## User roles and login URLs

| Role | Login | Workspace |
|---|---|---|
| Customer | `/login` | `/account` |
| Owner | `/owner/login` | `/owner/` |
| Admin | `/admin/login` | `/admin/` |

Customer registration is available at `/register`.

Role guards protect the owner and admin route groups. A user with the wrong role cannot enter another role's workspace.

---

## Customer storefront routes

| Route | Purpose |
|---|---|
| `/` | Homepage |
| `/shop` | Shop All catalogue |
| `/bestsellers` | Products explicitly marked as bestsellers |
| `/category/<slug>` | Category listing |
| `/product/<slug>` | Product details |
| `/cart` | Shopping cart |
| `/checkout` | Checkout |
| `/offers` | Current offers and promotions, including active Diwali combos |
| `/bundles` | Active product bundles |
| `/recipes` | Published recipes |
| `/recipes/<slug>` | Recipe details |
| `/account` | Customer account |
| `/account/orders` | Order history |
| `/account/orders/<order-number>` | Order detail and tracking |
| `/account/addresses` | Saved addresses |
| `/account/wishlist` | Wishlist |
| `/compare` | Product comparison |
| `/notifications` | Customer notifications |
| `/about` | RR FOODS story and Nurse Guide quality journey |
| `/help` | Help page |
| `/forgot` | Password recovery |

Some routes require a signed-in customer. Staff accounts are intended to use their separate workspaces.

---

## Admin panel

Sign in at `/admin/login`.

The admin workspace includes:

- **Dashboard:** shop overview.
- **Products:** create/edit, images, variants, price, discount, stock threshold, visibility and bestseller status.
- **Bulk tools:** bulk visibility, archive/restore, price/discount and category actions.
- **CSV:** product import/export.
- **Categories:** category and subcategory management.
- **Offers:** product offer labels.
- **Coupons:** discount rules, limits and expiry.
- **Header banners:** desktop/mobile images, scheduling, ordering, carousel settings and countdown.
- **Users:** search, block/unblock, password reset and owner creation.
- **Audit:** administrative activity records.
- **Reviews:** moderation.
- **Reels:** upload and manage homepage reels.
- **Recipes:** create, edit, publish and remove recipes.
- **Bundles:** create product bundles.
- **Diwali Combos:** manage festival combo name, description, products, quantities, price, image, tag, active status and countdown end date.

All admin routes are role-protected. Use the audit log to review administrative changes.

---

## Owner panel

Sign in at `/owner/login`.

The owner workspace includes:

- Dashboard for orders, revenue and stock alerts.
- Inventory editing and bulk stock updates.
- Stock history with user, timestamp, old value, new value and reason.
- Order tabs for new, packing, shipping, delivered and rejected/cancelled orders.
- Order status actions and rejection reasons.
- Customer product questions.
- Password management.

Order progression is controlled by the backend. Stock changes are transactional and recorded in inventory history.

---

## Cart, checkout and order lifecycle

The intended order lifecycle is:

```text
Placed → Confirmed → Packed → Shipped → Delivered
```

Rejection is allowed only before shipment. Customer cancellation is also restricted by order status.

Important rules implemented in the application:

- Product price, stock, discounts, coupon rules and delivery fee are read from the database, not trusted from browser-submitted totals.
- Checkout rechecks stock and locks relevant inventory rows during order placement.
- Successful checkout records order items and stock history, applies coupon usage and clears the cart.
- Cancelling/rejecting an eligible order restores inventory and coupon usage once.
- COD orders are marked paid when delivered; this does not process online payments.
- Bundle cart additions use the existing bundle/cart pricing workflow.

Review the checkout and order service modules before integrating a real payment provider.

---

## RR FOODS homepage and About page

### Homepage

The homepage includes promotional areas, product sections and the configurable header banner carousel. The Bestsellers and New Arrivals promotional blocks can use local background images.

Expected static image paths (add the image files to this directory):

```text
app/static/img/rr-foods-bestsellers-background.jpg
app/static/img/rr-foods-new-arrivals-background.jpg
```

The About hero background can use:

```text
app/static/img/RR-FOODS-About-Hero-Background.jpg
```

CSS references should be relative to `app/static/css/`, for example:

```css
background-image: url("../img/rr-foods-bestsellers-background.jpg");
```

If the image is missing or the path/capitalization differs, the browser will not display it. Keep image filenames and CSS references identical.

### About page — Nurse Guide

The `/about` page contains the RR FOODS story and a six-stage quality guide:

1. **Sourcing:** handpicked millets, grains and nuts from trusted farmers.
2. **Cleaning and Sorting:** removal of stone, dust and impurities.
3. **Traditional Processing:** stone-ground or slow-roasted processing; no preservatives.
4. **Quality Testing:** moisture, purity and freshness checks.
5. **Hygienic Packaging:** sealed, food-grade and batch-coded packaging.
6. **Delivery:** fresh products delivered to the doorstep.

Stage content is supplied by a Python list in the About route and rendered by the Jinja template. The nurse character is inline SVG and its body/arms/props are animated with CSS. JavaScript handles stage activation, speech text, progress, navigation and count-up metrics. Reduced-motion preferences are respected.

---

## Bestsellers, bundles and Diwali combos

### Bestsellers

Admin users can mark products as bestsellers. The public `/bestsellers` page lists active products explicitly marked with the bestseller flag.

### Product bundles

Bundles are managed in the admin content area and displayed on `/bundles`. Bundle pricing is applied through the existing cart workflow.

### Diwali combos

The Diwali feature adds admin-managed `Combo` records connected to existing `Bundle` records. Active Diwali-tagged combos appear at the top of `/offers`.

Admin management:

- `/admin/combos`
- Create, edit, activate/deactivate and delete combos.
- Select catalogue products and quantities.
- Configure original and discounted prices.
- Configure image and festival tag.
- Set the site-wide Diwali countdown end date.

Seed three sample combos from active catalogue products:

```bash
flask seed-diwali-combos
```

The seed command requires at least two active, in-stock products without active variants. It does not duplicate samples if combos already exist. Review the selected products, descriptions and prices in the admin panel before publishing.

The offers page uses existing cart handling through the linked bundle. A customer must sign in to add items to the cart.

The fireworks effect is implemented with canvas and vanilla JavaScript. It pauses when the section is off-screen or the browser tab is hidden, limits particle count and respects reduced-motion preferences.

---

## Reels and recipes

- Reels are managed in the admin workspace and shown on the homepage.
- Reels support MP4, WebM and MOV within the configured upload limit.
- Recipes support text, ingredients, category, thumbnail and video or YouTube URL.
- Recipe detail pages can link ingredient products to the cart.
- Uploaded videos are served from the configured uploads directory.

Review the admin forms and upload configuration before increasing upload limits.

---

## Images and uploads

Static, committed images belong in:

```text
app/static/img/
```

Uploaded product, banner, reel and recipe media are stored in the configured upload directory (default: `uploads/`) and served through the application's media route.

The image uploader validates image formats, re-encodes supported images with Pillow, strips metadata, assigns random filenames and resizes images for their intended use. Keep the uploads directory backed up together with the database.

Do not store secrets or private customer documents in the public static directory.

---

## CLI commands

Run commands from the project root with the virtual environment activated.

| Command | Purpose |
|---|---|
| `flask db upgrade` | Apply database migrations |
| `flask db migrate -m "message"` | Generate a migration after model changes |
| `flask seed` | Create development/demo data and accounts |
| `flask import-rr-foods --yes` | Import supplied RR FOODS catalogue |
| `flask import-products-csv PATH` | Import a general product CSV |
| `flask create-user EMAIL "Name" --role admin` | Create an admin account |
| `flask create-user EMAIL "Name" --role owner` | Create an owner account |
| `flask create-user EMAIL "Name" --role user` | Create a customer account |
| `flask seed-diwali-combos` | Seed sample Diwali combos |
| `flask set-setting KEY VALUE` | Change a JSON-backed site setting |
| `flask send-emails` | Deliver queued emails |
| `flask check-config` | Check production configuration |

Example site settings:

```bash
flask set-setting free_delivery_min_cart 500
flask set-setting tax_percent 5
flask set-setting business_name '"RR FOODS"'
```

The `set-setting` command parses JSON values where possible. Strings should be passed as JSON strings, including quotes.

---

## Testing

Install dependencies first:

```bash
pip install -r requirements.txt
```

Read `TESTING.md` before running the full suite. The tests use a dedicated test database and may clear its contents. **Never point `TEST_DATABASE_URL` at the production database or a database containing important data.**

Typical command:

```bash
pytest -q
```

For PostgreSQL-backed tests, create a separate test database and configure the test connection as described in `TESTING.md`.

Additional manual checks:

- Sign in as each role and verify access boundaries.
- Browse `/shop`, `/bestsellers`, categories and product details.
- Add products and bundles to the cart and complete a test checkout.
- Verify inventory and order status history.
- Test `/about`, all six Nurse Guide stages, stage navigation and reduced-motion mode.
- Test `/offers`, Diwali countdown and fireworks.
- Test the homepage promotional background images.
- Test responsive layouts at mobile, tablet and desktop widths.
- Test admin CRUD and owner inventory/order actions.

---

## Production deployment

Do not expose the Flask development server to the public internet.

Before production:

1. Use a production `.env` with a strong random `SECRET_KEY`.
2. Use a dedicated PostgreSQL database and strong credentials.
3. Set `FLASK_ENV=production`.
4. Set `ADMIN_WHATSAPP_NUMBER`. Payment is taken on WhatsApp and marked Paid in the owner panel (there is no gateway).
5. Set secure cookies and serve only over HTTPS.
6. Configure Redis for rate limiting when using multiple workers.
7. Configure SMTP if transactional email is required.
8. Configure Nginx or another reverse proxy and Gunicorn.
9. Set `TRUST_PROXY=1` only behind a correctly configured trusted proxy.
10. Run migrations and `flask check-config`.
11. Create real staff accounts; do not use demo credentials.
12. Back up database and uploads.
13. Complete the launch checklist and real-device tests.

### Configuration check

```bash
flask check-config
```

Resolve every `[FIX]` item before launch and review all `[ADVICE]` items.

### Gunicorn

The project includes `gunicorn.conf.py` and deployment examples under `deploy/`. Install Gunicorn in the production environment if it is not already present:

```bash
pip install gunicorn
gunicorn -c gunicorn.conf.py wsgi:app
```

Confirm the WSGI target in `wsgi.py` and the deployment service file before starting the service.

### Docker

The repository includes a Dockerfile and a PostgreSQL `docker-compose.yml` service for local development. Review the Dockerfile, environment, persistent uploads volume and database URL before using it in production.

---

## Backup and restore

Back up both:

- PostgreSQL database.
- Upload directory configured by `UPLOAD_DIR`.

A database-only backup does not preserve uploaded product images, banners, reels or recipe media.

The project includes `scripts/backup.sh` as a deployment example. Review its paths, credentials, retention and destination before scheduling it. Store copies off the application server and test a restore before launch.

---

## Security notes

- Passwords are hashed using Argon2.
- Forms use CSRF protection.
- Role-based access protects admin and owner workspaces.
- Sign-out uses POST.
- Login lockout and rate limiting are included.
- Staff actions are recorded in audit history.
- Uploads are validated and re-encoded.
- Checkout recalculates prices and checks stock on the server.
- Production must use HTTPS, secure cookies and a strong secret key.
- The payment `stub` mode is a test mechanism only. It does not move money and must not be enabled for real customer payments.
- Never put database, SMTP or payment secrets in frontend JavaScript or committed files.

---

## Pre-launch checklist

- [ ] Confirm `.env` contains production-only secrets and strong database credentials.
- [ ] `flask check-config` reports no blocking issues.
- [ ] Database migrations have been applied.
- [ ] Real admin and owner accounts have been created.
- [ ] Demo accounts/passwords are disabled or removed.
- [ ] Product names, prices, variants and pack sizes are verified.
- [ ] Actual inventory quantities have been entered.
- [ ] Ingredients, allergens, nutrition, FSSAI and package details are approved.
- [ ] Product and homepage images are approved and load correctly.
- [ ] Delivery zones, fees, tax and free-delivery threshold are confirmed.
- [ ] Privacy, terms, returns and cancellation policies are approved.
- [ ] SMTP delivery is tested if email is enabled.
- [ ] Online payment gateway is integrated and verified before enabling it.
- [ ] HTTPS, secure cookies and rate limiting are configured.
- [ ] Database and uploads backups are scheduled and restore-tested.
- [ ] Customer, owner and admin workflows are tested.
- [ ] About Nurse Guide, offers, Diwali combos and mobile layouts are checked.
- [ ] Android and iPhone browser testing is completed.

---

## Known configuration and verification notes

- The repository contains implementation notes in `IMPLEMENTATION-REPORT.md`, `TESTING.md` and `docs/`. Read them alongside this README.
- Some business details and product label data are intentionally left for RR FOODS to confirm. Do not publish unverified claims.
- The current online payment stub is not a production payment gateway.
- Email delivery requires SMTP configuration and scheduled execution of `flask send-emails`.
- Browser testing, Lighthouse, real-device testing and production infrastructure checks must be completed in the target deployment environment.
- A development setup may use demo credentials and a local database; never reuse those defaults in production.

---

## Documentation

- `TESTING.md` — automated and manual test guidance.
- `IMPLEMENTATION-REPORT.md` — implementation overview.
- `docs/RR-FOODS-DESIGN-SYSTEM.md` — visual design notes.
- `docs/RR-FOODS-DIWALI-QUALITY-JOURNEY.md` — quality journey implementation notes.
- `docs/RR-FOODS-DIWALI-IMPLEMENTATION-TESTS.md` — Diwali feature test checklist.
- `docs/RR-FOODS-BESTSELLER-RULES.md` — bestseller behaviour.
- `docs/RR-FOODS-LISTING-FILTERS-IMPLEMENTATION.md` — listing/filter notes.
- `docs/RR-FOODS-QA-REPORT.md` — QA notes.
- `docs/RR-FOODS-product-data-review.csv` — internal product data review; not storefront content.

---

## License and ownership

This repository does not declare an open-source license. Treat the source code, brand assets, product images and business content as project-owned/private unless the project owner specifies otherwise.
