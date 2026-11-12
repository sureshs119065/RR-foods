# RR FOODS Admin mobile UX update

## What changed

- **Dashboard:** Added pending and total order KPIs, recent orders, and a clearly labelled illustrative sales preview that appears only when the selected live period has no orders. Live sales analytics remain backed by the existing analytics service.
- **Stock alerts:** Added a dedicated Admin stock-alert screen with low/out-of-stock states, product image/SKU/category/price, +/- quantity controls, direct quantity entry, stale-value protection and a save confirmation. The existing Owner inventory workflow remains available.
- **Automatic notifications:** Stock quantity reductions that cross into low-stock or out-of-stock state create an in-app notification for each active Admin user. Notifications have unread styling, unread counts, mark-one-read and mark-all-read actions, and a direct stock-alert link. The existing `notifications` table is reused; no schema migration is introduced.
- **Orders:** Added Admin order list/search/status filtering and a complete read-only order detail view with customer contact, delivery address, line items, totals, payment information and status timeline. Fulfilment actions remain in the Owner workflow.
- **Inventory:** Existing Admin product rows now collapse into readable mobile product cards. Search/filter/sort and edit actions are retained; stock updates are reachable from the dedicated Stock alerts page.
- **FAQs:** Added a searchable accordion help centre with editable sample content in `app/data/admin_faqs.json`.
- **Reusable UI:** Added shared operations styles and small progressive-enhancement JavaScript in `app/static/css/admin-dashboard.css` and `app/static/js/admin-operations.js`.

## Replaceable demo data

`app/data/admin_dashboard_demo.json` contains clearly labelled example figures and a sample seven-day sales trend. It is shown only when the selected live analytics range has zero orders. Replace the JSON values or remove the preview section when production data is available.

## Responsive implementation

Responsive rules cover 760px, 480px and 360px breakpoints; the target layouts include narrow 320px devices, common 360–430px phones, and tablet widths. Layouts use single-column cards on phones, two-column cards on tablets, wrapping controls, and minimum 44px stock stepper/button targets.

## Validation

Python compilation and Jinja template parsing are run as part of the update. Full production database, payment-provider, and end-to-end browser tests must still be run in the deployment environment.
