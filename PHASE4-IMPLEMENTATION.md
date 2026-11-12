# RR Foods — Phase 4 implementation

## Scope
This patch implements Phase 4 items 15 (Sales insights dashboard) and 17 (Inventory intelligence). Item 16 was not specified in the request and has not been invented.

## Database changes
- `products.reorder_level INTEGER NOT NULL DEFAULT 5` (safe for existing products).
- New `inventory_batches` table: `id`, `product_id`, `batch_number`, `expiry_date`, `quantity`, `created_at`; unique product/batch pair, non-negative quantity, and product/expiry indexes.
- Migration: `migrations/versions/1c4f8a9d2b70_phase4_sales_inventory.py`.

## Routes
- `GET /owner/analytics.csv` — owner-only CSV export for the selected analytics range.
- `POST /owner/inventory/product/<product_id>/batch` — owner-only batch and expiry entry; protected by the existing global CSRF protection and owner blueprint role guard.
- Existing `/owner/` dashboard and `/owner/analytics-data` now include retention and inventory insight data.

## Files changed
- `app/models/catalog.py`
- `app/models/engagement.py`
- `app/models/__init__.py`
- `app/services/analytics.py`
- `app/owner/dashboard.py`
- `app/owner/inventory.py`
- `app/templates/shared/sales_analytics.html`
- `app/templates/owner/dashboard.html`
- `app/templates/owner/inventory.html`
- `app/static/css/sales-analytics.css`
- `app/static/css/owner.css`
- `tests/test_phase4_sales_inventory.py`
- `migrations/versions/1c4f8a9d2b70_phase4_sales_inventory.py`

## Sales insights
- Existing monthly/daily-or-weekly trend and top products retained.
- Adds repeat-customer rate, coupon usage/discount/sales, pincode sales, slowest products and CSV export.
- KPI cards use two columns on mobile and four on wider screens.

## Inventory intelligence
- Batch number, expiry date, batch quantity and reorder level can be recorded from the owner inventory table.
- Owner dashboard lists out-of-stock products, batches expiring in the next 30 days, and estimated days of stock left using the previous 30 days of accepted-order item sales.
- Near-expiry rows include a bundle/markdown suggestion for owner review; this patch does not automatically change prices or publish discounts. Batch quantity is traceability metadata and does not silently alter aggregate sellable stock.

## Validation and deployment
- Python syntax compilation passed (`python -m compileall -q app tests`).
- Full pytest/database migration execution was not possible in this environment because Flask dependencies and a PostgreSQL test database are unavailable. Run the full suite in the project environment before deployment.
- Back up the production database, install the existing requirements, run `flask db upgrade`, then run `pytest`. No new environment variables or paid services are required.

## Manual test checklist
- [ ] Owner dashboard loads and analytics cards render at 320px, 390px, 768px and desktop widths.
- [ ] Dashboard cards are two columns on mobile; no horizontal overflow.
- [ ] Month/year/custom date ranges update sales metrics and CSV export.
- [ ] CSV opens correctly in Excel and includes sales, products, coupons and pincodes.
- [ ] Repeat-customer rate is zero with no customers and accurate with repeat orders.
- [ ] Owner can add a batch with a valid date and quantity; duplicate batch number for the same product is rejected by the database.
- [ ] Invalid/missing batch number, expiry date or quantity is rejected with a safe message.
- [ ] Existing stock editing and low-stock notifications still work.
- [ ] Expiring batches appear only within the next 30 days; expired batches are not shown in the upcoming-expiry list.
- [ ] Days-of-stock estimates use 30-day sales and omit products with no sales history.
- [ ] Test with slow network and keyboard open; all form controls remain usable and at least 44px high, with 16px inputs.
- [ ] Confirm owner-only access and CSRF rejection for POST without a valid token.
