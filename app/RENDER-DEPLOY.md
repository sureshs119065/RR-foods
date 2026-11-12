# Deploying on Render

1. Push this folder to GitHub (`.env` is gitignored).
2. Render > New > PostgreSQL. Copy the *Internal Database URL* (the app accepts `postgresql://` as-is).
3. Render > New > Web Service > your repo, Python runtime:
   - Build command: `pip install -r requirements.txt`
   - Start command: `flask db upgrade && gunicorn -c gunicorn.conf.py wsgi:app`
   - Health check path: `/readyz`
4. Environment variables:
   - `PYTHON_VERSION=3.12.3`, `FLASK_APP=wsgi.py`, `FLASK_ENV=production`
   - `SECRET_KEY` (48+ random chars: `python -c "import secrets; print(secrets.token_urlsafe(48))"`)
   - `DATABASE_URL` (from step 2), `TRUST_PROXY=1`
   - `SITE_URL=https://<your-service>.onrender.com`, `ADMIN_WHATSAPP_NUMBER=91XXXXXXXXXX`, `SHOP_TIMEZONE=Asia/Kolkata`
   - `UPLOAD_DIR=/var/data/uploads`
   (gunicorn binds to Render's `PORT` automatically.)
5. Attach a Disk (paid instance) mounted at `/var/data` so admin-uploaded images survive deploys.
6. Create an admin (Shell, or once in the start command on free tier):
   `flask create-user you@example.com "Your Name" --role admin --password 'StrongPassword'`
   Do not run `flask seed` on a live shop.
7. Optional Cron Jobs (same env vars): `flask send-emails` every minute, `flask send-stock-alerts` every 5 minutes (needs `MAIL_MODE=smtp` + MAIL_* settings).

## Product images and catalogue
- 19 product images are bundled in `app/static/img/products/` and linked in `app/seed_data/seed_products.csv`. They ship with the code, so they survive restarts on any plan.
- Load the 32 products once (Render Shell, or temporarily in the start command): `flask import-rr-foods --yes`. Imported stock is 0: set real stock in Admin before selling.
- Images you upload in Admin go to `UPLOAD_DIR` (`/var/data/uploads` with a paid Disk mounted at `/var/data`). Without a Disk they are lost on restart.
- Products without a bundled image (13) get theirs via Admin > Products > edit > Images.

## Mobile layout fix
`app/static/css/rr-foods-mobile-fix.css` (linked in `app/templates/shop/layout.html`) keeps the phone header on one row and aligns breadcrumbs.
