# RR FOODS Admin + Owner Dashboard Update

This release updates both dashboard experiences.

## Admin dashboard
- Added a dedicated administration control-centre header.
- Added compact store-health cards for total products, low stock, out of stock, customers, categories, active coupons, archived products, and active banners.
- Added a two-column mobile card layout and compact two-column analytics charts/metrics.
- Added a mobile quick-navigation bar for Home, Products, Offers, Inbox, and Users.
- Preserved the existing shared sales analytics data source and admin workflows.

## Owner dashboard
- Retains the priority-first owner overview, order and stock attention cards, shared sales analytics, and operations panels.
- Retains mobile bottom navigation for Home, Orders, Inventory, Alerts, and Inbox.

## Validation
- Python source compilation and Jinja template parsing are run during packaging.
- Full Flask/database/browser integration tests still need to be run in the project's configured environment.
