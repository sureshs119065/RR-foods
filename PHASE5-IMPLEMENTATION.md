# RR FOODS — Phase 5 implementation

## Scope

Phase 5 adds a public database health endpoint, JSON structured logs with request IDs
and rotating file output, PostgreSQL backup tooling, stronger response headers and
persistent per-account/per-IP login lockout, GitHub Actions CI, and opt-in Web Push.

No paid SaaS, Redis, SMS/OTP, payment gateway, WhatsApp Business API, or paid push
service is added. Web Push is disabled until VAPID environment variables are set.

## Database migration

`migrations/versions/5d2e9a7c1f40_phase5_security_push.py`

This is the merge-and-upgrade migration for all existing migration heads, then creates:
- `login_lockouts`: HMAC-hashed account/IP identifiers, failure counters and cooldowns.
- `push_subscriptions`: user-owned browser endpoint and encryption keys, enabled flag.

Raw account emails and IP addresses are not stored in the lockout table. Existing
`users.failed_login_count` and `users.locked_until` remain supported for compatibility.

## Routes

- `GET /health`: unauthenticated JSON database check and application version.
- `GET /push/vapid-public-key`: public VAPID key only.
- `POST /account/push/subscribe`: authenticated, CSRF-protected, rate-limited opt-in.
- `POST /account/push/unsubscribe`: authenticated, CSRF-protected, rate-limited opt-out.

## Files changed / added

Changed:
- `app/__init__.py`, `app/config.py`, `app/auth/service.py`
- `app/models/engagement.py`, `app/models/__init__.py`
- `app/services/notify.py`, `app/shop/account.py`, `app/shop/pwa.py`
- `app/shop/cart.py`, `app/shop/engage.py`
- `app/static/js/sw.js`, `app/templates/account/index.html`
- `requirements.txt`, `.env.production.example`, `.gitignore`

Added:
- `app/services/push.py`, `app/static/js/push-optin.js`
- `migrations/versions/5d2e9a7c1f40_phase5_security_push.py`
- `scripts/backup_postgres.sh`, `deploy/crontab.txt`
- `deploy/BACKUP-RESTORE.md`, `deploy/WEB-PUSH.md`
- `.github/workflows/pytest.yml`
- `tests/test_phase5_health_security.py`, `tests/test_phase5_push.py`

## Security notes

- Existing Flask-WTF global CSRF remains enabled; push write routes use the CSRF header.
- Login keeps the existing per-account counter and adds persistent HMAC-keyed account/IP
  counters. Default IP threshold is 12 failures; account threshold remains 5; cooldown
  remains the configured 15 minutes.
- New push routes are user-only and limited to 10 requests/hour.
- Existing coupon, review, question and search endpoints are rate-limited (coupon:
  10/minute; reviews: 20/hour; questions: 10/hour; search: 90/minute).
- Cookies retain HttpOnly and SameSite=Lax; Secure is configurable and enabled for
  production by default. HSTS is emitted on HTTPS requests.
- Existing upload validation continues to decode/re-encode images with Pillow.
- CSP includes default-src, base-uri, object-src, frame-ancestors and form-action rules.
- Push sends are best-effort and cannot interrupt order/stock notification transactions.

## Deploy

1. Back up the database.
2. Install updated requirements: `pip install -r requirements.txt`.
3. Run `flask db upgrade`.
4. Run `pytest -q` with PostgreSQL configured.
5. Deploy and verify `GET /health` returns `status=ok`.
6. Configure `scripts/backup_postgres.sh` using `deploy/crontab.txt` on a persistent
   host or equivalent Render cron setup. Render's ephemeral filesystem is not a backup.
7. Optional push: set VAPID keys as documented in `deploy/WEB-PUSH.md`.

Environment variables:
- `APP_VERSION` (default `1.0.0`)
- `LOG_DIR`, `LOG_LEVEL`, `LOG_MAX_BYTES`, `LOG_BACKUP_COUNT`
- `SESSION_COOKIE_SECURE` (defaults to enabled when `FLASK_ENV=production`)
- `LOGIN_IP_LOCKOUT_ENABLED` (default `1`), `LOGIN_IP_MAX_FAILED` (default `12`)
- Optional `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY`, `VAPID_CLAIMS_EMAIL`

## Validation status

Python syntax compilation and shell syntax validation are performed for this patch.
The project test suite and PostgreSQL migration cannot be executed in this packaging
environment because Flask/SQLAlchemy dependencies and a PostgreSQL server are not
available. CI is configured to run the migration and pytest against PostgreSQL 16.
