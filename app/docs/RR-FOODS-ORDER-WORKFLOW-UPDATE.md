# RR FOODS order workflow update

## Included
- Accessible storefront ghost/danger/WhatsApp button states for hover, focus, active and touch.
- Checkout submit guard using the existing `data-once` behavior plus a per-checkout session token.
- Order-placed page attempts same-tab WhatsApp navigation and retains an explicit fallback link and copyable order message.
- Project-root `.env` is loaded before `Config` class values are evaluated, independent of the shell's current directory.
- Admin order status endpoint with server-side transition validation, stock restoration, coupon release where applicable, payment refund state, history, notification and audit writes in one database commit.
- Account overview dashboard with order, active order, wishlist and unread-notification counts, recent orders, address and notifications.

## WhatsApp configuration
Set `ADMIN_WHATSAPP_NUMBER` in the `.env` located beside `wsgi.py`:
`ADMIN_WHATSAPP_NUMBER=91XXXXXXXXXX`
Use the actual shop WhatsApp number with country code and digits only. The uploaded `.env` had this setting blank, so no real shop number can be inferred or inserted.

## Database migration
This update reuses existing `OrderStatusHistory`, `Notification`, `AuditLog`, order status and payment status columns. No schema migration is required for the changes in this update.

## Run
`python -m flask run`

## Verification note
Python syntax, JavaScript syntax and Jinja template parsing were checked. The full pytest suite could not start in the build environment because `flask_migrate` is not installed there. Run `python -m pip install -r requirements.txt` in the project's activated environment, then `python -m pytest -q` locally.
