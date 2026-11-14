# Deployment

Pick one: [Render](#option-1-render), [one Linux server](#option-2-one-linux-server-ubuntu--debian) or [Docker](#option-3-docker-web-app-only). Then do [backups](#backups-and-restore) **before** launch, not after.

Never expose the Flask development server to the internet.

## Before anything: the safety check

```bash
flask check-config
```

`[FIX]` items must be resolved: with `FLASK_ENV=production` the site refuses to start if `SECRET_KEY` is weak, the database still has the example password, cookies are not Secure, or debug is on. `[ADVICE]` items work but should be fixed soon (for example an empty `ADMIN_WHATSAPP_NUMBER`). Monitoring URLs: `/healthz` (process up), `/readyz` (database answers, 503 if not), `/health` (JSON database check and version).

Payments: there is no gateway. Customers pay the owner on WhatsApp and the owner marks the order Paid. Set `ADMIN_WHATSAPP_NUMBER`.

## Option 1: Render

1. Push the project to GitHub (`.env` is gitignored).
2. Render → New → PostgreSQL. Copy the **Internal Database URL** (the app accepts `postgresql://` as is).
3. Render → New → Web Service → your repo, Python runtime:
   - Build command: `pip install -r requirements.txt`
   - Start command: `flask db upgrade && gunicorn -c gunicorn.conf.py wsgi:app` (gunicorn binds to Render's `PORT` automatically)
   - Health check path: `/readyz`
4. Environment variables: `PYTHON_VERSION=3.12.3`, `FLASK_APP=wsgi.py`, `FLASK_ENV=production`, `SECRET_KEY` (`python -c "import secrets; print(secrets.token_urlsafe(48))"`), `DATABASE_URL`, `TRUST_PROXY=1`, `SITE_URL=https://<your-service>.onrender.com`, `ADMIN_WHATSAPP_NUMBER=91XXXXXXXXXX`, `SHOP_TIMEZONE=Asia/Kolkata`, `UPLOAD_DIR=/var/data/uploads`.
5. Attach a **Disk** (paid instance) mounted at `/var/data`, or admin-uploaded images are lost on every deploy. Images bundled with the code (`app/static/img/products/`) survive on any plan.
6. Create an admin from the Shell: `flask create-user you@example.com "Your Name" --role admin --password 'StrongPassword'`. Do not run `flask seed` on a live shop.
7. Load the catalogue once: `flask import-rr-foods --yes`. Imported stock is 0; set real stock in Owner → Inventory before selling. Products without a bundled image get theirs via Admin → Products → Edit → Images.
8. Cron jobs (same environment variables): `flask send-emails` every minute (needs `MAIL_MODE=smtp`), `flask send-stock-alerts` every 5 minutes, `flask sync-stock-notifications` every 30 minutes (run it once after deploying to backfill existing alerts).

Render's temporary filesystem is not a backup. Use a persistent host or Render cron for `scripts/backup_postgres.sh`.

## Option 2: one Linux server (Ubuntu / Debian)

1. Install `python3-venv postgresql nginx redis-server certbot`.
2. Create a database user and database with a strong password (not the example one).
3. Copy the project to `/srv/nk`, then: `python3 -m venv venv && venv/bin/pip install -r requirements.txt gunicorn`.
4. Copy `.env.production.example` to `/srv/nk/.env` and fill it in. Then:
   ```bash
   cd /srv/nk && set -a && . ./.env && set +a
   venv/bin/flask check-config        # must say "0 to fix"
   venv/bin/flask db upgrade
   ```
5. Accounts (**not** `flask seed`):
   ```bash
   venv/bin/flask create-user you@yourshop.com "Your Name" --role admin
   venv/bin/flask create-user owner@yourshop.com "Owner Name" --role owner
   ```
   Add real products in Admin → Products (or CSV import). Set invoice details: `flask set-setting business_name '"RR FOODS"'` (also address and GSTIN).
6. Run it with `deploy/nk.service` (systemd) and `deploy/nginx.conf`, then `certbot --nginx -d your.domain` and switch to `deploy/nginx-https.conf` (redirect, HTTP/2, HSTS, no version header).
7. Install the cron lines from `deploy/crontab.txt` (backup) plus `flask send-emails` every minute, `flask send-stock-alerts` every 5 minutes and `flask sync-stock-notifications` every 30 minutes.
8. In `.env`: `FLASK_ENV=production`, `TRUST_PROXY=1`, `RATELIMIT_STORAGE_URI=redis://...`, `SITE_URL=https://...`.

Updating a live site (take a backup first): `git pull && venv/bin/pip install -r requirements.txt && venv/bin/flask db upgrade && sudo systemctl restart nk`, then check `/readyz`.

## Option 3: Docker (web app only)

```bash
docker build -t nk-shop .
docker run -d --name nk --env-file .env -p 8000:8000 -v nk_uploads:/data/uploads nk-shop
docker run --rm --env-file .env nk-shop flask db upgrade     # once
```

The image contains no database: point `DATABASE_URL` at a managed PostgreSQL or your own server. Put nginx or a cloud load balancer in front for HTTPS and set `TRUST_PROXY=1`. The container's `start.sh` prints diagnostics, runs migrations, seeds the Children's Day combo (safe to repeat) and starts gunicorn. The Docker files have not been built or run in a verified environment.

`docker-compose.yml` starts only a local development PostgreSQL (`docker compose up -d db`).

## Backups and restore

Back up **both** the PostgreSQL database and the `UPLOAD_DIR` folder; a database-only backup loses uploaded product images, banners, reels and recipe media.

- `scripts/backup_postgres.sh` writes a custom-format dump daily (cron: `deploy/crontab.txt`, 02:15 UTC) and keeps seven days. Set `DATABASE_URL` and optionally `BACKUP_DIR` (default `/var/backups/rr-foods`). Needs `pg_dump` and `pg_restore` on the cron host.
- `scripts/backup.sh` backs up the database and the uploaded images nightly and keeps 14 days.
- Keep the backup directory outside the public static and uploads folders with restrictive permissions, and copy encrypted backups to separate persistent storage: local retention does not protect against losing the host.

Restore (test it once so you know it works):

1. Stop application writes and take a safety dump of the current database.
2. Set `DATABASE_URL` to the target database.
3. `pg_restore --clean --if-exists --no-owner --no-acl --dbname="$DATABASE_URL" /path/to/rr-foods-TIMESTAMP.dump` (or into a scratch database: `createdb nk_restore && pg_restore -d nk_restore <dump>`).
4. Unpack `uploads-*.tar.gz` into the folder `UPLOAD_DIR` points to.
5. Run `flask db upgrade` if the restored database predates the deployed migrations.
6. Start the app and verify `/health`.

## Optional: browser push

Web push is opt-in and asked for only on the signed-in customer's account page. It uses the browser Push API with VAPID; no SMS, WhatsApp API, Redis or paid provider is involved. Delivery is best-effort and depends on the browser vendor.

1. `pywebpush` is in `requirements.txt`.
2. Generate one VAPID key pair on a trusted machine with `vapid --gen` (from the `py-vapid` dependency). Keep the private key secret.
3. Set `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY` and `VAPID_CLAIMS_EMAIL` in the environment. Never put the private key in JavaScript or a public file.
4. Serve over HTTPS; the account page then shows "Enable notifications". Customers can turn it off from the same card.

Push stays disabled when the keys are absent, and the public-key endpoint exposes only the public key. Expired browser endpoints (HTTP 404 or 410) are disabled automatically.

**Current limitation:** subscriptions are saved and `app/services/push.py` can send, but nothing in the order or stock code calls it yet, so order-status and back-in-stock events produce in-app notifications only. Wire it into `app/services/notify.py` as a best-effort background call before relying on it.
