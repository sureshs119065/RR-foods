# Admin + Owner mobile and stock alert fix

- Missing icons: `app/templates/admin/_macros.html` had no SVG paths for alert-triangle, bell or message-circle. Added them to the shared macro.
- Stock alerts: `app/services/inventory.py` now provides `checkStockAndNotify(product)` and `sync_stock_notifications()`, with a single unread alert per product and status, and resolution on recovery. Existing edit, CSV, manual and order stock paths call the compatibility wrapper or `set_quantity`.
- Startup/periodic: first web request syncs and each worker checks at most every 30 minutes. **For reliable Render scheduling**, create a Render Cron Job every 30 minutes running `flask sync-stock-notifications`; multiple workers are safe from sequential duplicate scans but concurrent scans require a database-level unique constraint for strict race-free deduplication.
- Owner header and both mobile navs: CSS visibility and 24px SVG size.
- Shared analytics: Start / End / Apply / Reset; backend uses shop-local inclusive end date via exclusive next-day UTC bound.
- Validate after deployment: sign in as Admin and Owner; check icons at 320, 375, 480px; choose custom dates, Apply, Reset; run `flask sync-stock-notifications` and confirm alert count; restock and confirm resolution.
- Full browser/database tests not performed here.
