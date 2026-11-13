# RR FOODS product page corrections — v20

Starting point: Version 19, preserving the complete 20-product catalogue integration.

## Changes
- Expanded the product page to use nearly the full desktop viewport width (48 px total side gutter, 1440 px maximum).
- Rebalanced the product gallery and purchase panel for wide desktop screens; retained a single-column stacked mobile layout.
- Increased the main product image presentation area and removed forced image zoom scaling.
- Fixed local image resolution: missing `/static/...` files and invalid uploaded paths now fall through to an existing bundled product image instead of rendering a blank image.
- Added a specific bundled image fallback for Millet Soup Mix.
- Moved Order on WhatsApp, Track your order and Easy returns out of the purchase panel into a separate three-card service strip immediately below the main product hero.
- Kept the pincode delivery checker, purchase controls and offers in the purchase panel.
- Preserved Version 19's full product catalogue content and product information sections.
- Bumped storefront CSS cache key to `rr-product-layout-20`.

## Validation
- Jinja product template parsed successfully.
- Python image resolver compiled successfully.
- Required bundled product image files checked.
- Mirrored app template/CSS/helper files checked.
- Service strip placement checked below the hero and outside the purchase panel.
- CSS brace balance and ZIP integrity checked.

The full pytest suite was not executed because the environment used for this packaging task does not have `flask_migrate` installed. Please run the app locally and confirm the database-backed product image for each SKU.
