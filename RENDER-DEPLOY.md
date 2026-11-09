# Deploying on Render

1. In this folder run: git init -b main; git add -A; git commit -m "NK platform"; then add your NEW empty GitHub repo as origin and git push -u origin main (.env is gitignored).
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
