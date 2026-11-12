# RR Foods — Phase 1 checkout and order experience

This patch implements the requested Phase 1 features in the existing Flask/Jinja/SQLAlchemy application. It does not add paid services or third-party runtime dependencies.

## Included

1. **Frequently bought together / cart suggestions**
   - Co-purchase ranking from `OrderItem` history, counting distinct orders.
   - Process-local six-hour cache of related product IDs (per worker; no Redis).
   - Same-category bestseller/sales fallback when history is sparse.
   - Filters inactive, deleted, out-of-stock and already-in-cart products.
   - Product-page Add all uses the existing `/cart/add-many` endpoint and carries a selected variant when required.
   - Cart suggestions quick-add simple products and link to option selection for variant products.

2. **Courier tracking and order timeline**
   - Nullable `courier_name`, `tracking_id`, and `tracking_url` columns on `orders`.
   - Owner and admin order detail forms; HTTPS-only tracking links.
   - Owner/admin changes create audit-log entries.
   - Customer order page displays courier/tracking details and polls the existing status JSON endpoint.
   - Timeline includes Placed, Confirmed, Packed, Shipped, Out for delivery, Delivered, plus terminal Cancelled/Rejected/Returned/Refunded states.

3. **Delivery slot selection**
   - Nullable `delivery_date` and `delivery_slot` columns on `orders` (existing rows remain valid).
   - Owner settings stored in `SiteSetting`: cutoff time, per-slot capacity, blocked dates, and booking horizon.
   - Morning/Evening slots; checkout only lists dates/slots with capacity.
   - Server revalidates date, cutoff, blocked dates, booking horizon and capacity before order creation.
   - PostgreSQL row lock on the shared settings row serializes capacity checks across checkout transactions.
   - Selected slot appears on customer order details/lists, owner/admin order lists, packing slip, invoice PDF and WhatsApp order text.
   - Product and cart pages show the owner-configured next-day cutoff note.

4. **Saved pincode and address memory**
   - Last checked six-digit pincode is stored in browser localStorage.
   - Product and address forms prefill the pincode; checkout shows the last checked pincode.
   - Address form calls the existing `/api/pincode/<pin>` endpoint and fills city/state when the zone record has those values.
   - Default address remains preselected; “Use my last address” selects the most recently updated address.

5. **Delivery fee rule**
   - Removed the old `free_delivery_min_cart` threshold override and cart progress bar, plus the seeded free-delivery banner.
   - Delivery fees now always come from the configured `DeliveryZone.delivery_fee` (including a legitimate ₹0 zone fee); no shipping offer or threshold is introduced.

## Database migration

A new Flask-Migrate revision is included:

`migrations/versions/7a91c3e5d802_order_delivery_tracking_slots.py`

It adds nullable order tracking/slot columns, nullable city/state fields to `delivery_zones`, a delivery-slot capacity index, and a default `SiteSetting` row. It also removes the obsolete free-delivery threshold setting and seeded free-delivery banner. Existing orders and delivery-zone rows are preserved because new columns are nullable.

Run from the project root after setting the same environment variables used by the current app:

```powershell
flask db upgrade
```

## Pincode city/state data

The existing Tamil Nadu fallback can determine serviceability and the state (`Tamil Nadu`), but it cannot infer a city from a six-digit pincode without postal-directory data. For explicit delivery-zone rows, city and state are returned by the API and auto-filled. Populate them without a paid API using the existing helper:

```powershell
python add_pincodes.py 636001 --city Salem --state "Tamil Nadu"
```

This updates only the location metadata unless `--eta` or `--fee` is also supplied. It does not change delivery fees by itself.

## Tests and validation

New pytest coverage is in `tests/test_phase1_order_experience.py`; existing free-shipping tests were updated to assert that legacy threshold settings are ignored and the DeliveryZone fee remains authoritative.

Static checks performed in the build environment:

- Python compilation: passed.
- JavaScript syntax (`node --check app/static/js/shop.js`): passed.
- Changed Jinja templates: parsed successfully.
- CSS parsing (`tinycss2`): passed.

The pytest suite could not be executed in the build environment because Flask-Migrate is not installed there (`ModuleNotFoundError: flask_migrate`). Install the project's existing `requirements.txt` in the app environment, then run:

```powershell
pytest -q tests/test_phase1_order_experience.py
pytest -q
```

No package was added to `requirements.txt`.

## Payment, security and cost

- WhatsApp remains the existing free `wa.me` handoff; UPI/COD remain manual owner-settled methods.
- No SMS/OTP, payment gateway, Redis, Sentry, Twilio, WhatsApp Business API or paid SaaS was added.
- New write routes use Flask-Limiter; POST forms continue to use the app-wide CSRF protection.
- Owner/admin blueprints retain their existing role guards; owner/admin edits are audited.
- Existing bundle, coupon, review, Q&A, stock alert, notification, inbox, invoice, reorder, return, recipe, compare, wishlist and Diwali implementations were not replaced.
