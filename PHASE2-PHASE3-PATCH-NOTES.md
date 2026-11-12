# Phase 2 / Phase 3 patch notes

This patch is an incremental starting implementation against the existing Flask application. It does not change payment processing, delivery-zone pricing, or introduce paid services.

## Included in this patch
- Owner WhatsApp status-message action for Confirmed, Packed, Shipped and Delivered, with English/Tamil defaults, editable owner templates, courier/tracking placeholders, an order-history entry and an audit entry. Opening WhatsApp is recorded; the app cannot verify that the user pressed Send inside WhatsApp.
- Share helper using Web Share API, clipboard fallback and wa.me fallback; product share control was already present and bundle/recipe share controls are added.
- Referral code field and customer referral-code card/share surface.
- Points ledger, search-term and recipe-favourite schema foundations.
- Tamil fields on product/category/recipe models, preferred-language field and HTML lang output.
- Gift message and hide-prices fields at checkout; owner order view and packing slip display gift message. Hide-prices invoices render as a price-free packing slip.
- Recipe cook-mode dialog with one-at-a-time ingredient navigation and optional Wake Lock API.
- Migration and initial pytest coverage for the new schema/share assets.

## Still requiring completion before production use
- Referral attribution at signup/checkout, coupon issuance after first delivered order, reward caps and phone/address abuse checks.
- Full loyalty earn/redeem/expiry configuration, checkout redemption and cancellation/return reversals.
- Complete Tamil translation dictionary and admin Tamil input forms; current patch adds storage and language metadata only.
- Typo/transliteration-aware search, category/trending/recent suggestions and no-results experience.
- Structured recipe step/timer model, serving-size ingredient arithmetic and account favourite UI.
- Review photo moderation queue and rating breakdown/with-photos filtering (existing review upload handling is retained).
- Automated 25–30 day restock reminders and home/account banners.
- Full Open Graph metadata on every shareable product, bundle and recipe URL.

## Deployment
Run `flask db upgrade` before deploying the updated application. The uploaded environment did not contain the Python dependencies needed to execute pytest here, so tests were syntax-checked but not run against PostgreSQL.
