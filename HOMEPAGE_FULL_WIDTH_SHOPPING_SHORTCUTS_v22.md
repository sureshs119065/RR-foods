# RR FOODS homepage correction — Version 22

Base: RR_Foods_Homepage_Full_Width_Shopping_Sections_v21.zip

## Fixes
- The homepage Offers & Combo shelf now queries and renders active admin-managed Combo records and active Bundle records, in addition to genuine discounted individual products.
- Combo cards show their real image (when configured), title, description, included catalogue products, actual price, original price and savings where available.
- Bundle cards show configured bundle image, actual included products, bundle price and calculated savings when the catalogue total supports it.
- Each combo/bundle has a working Add to Cart POST form wired to the existing `shop.add_bundle` endpoint with CSRF protection.
- The Offers shelf is hidden when there are no active product markdowns, combos or bundles; it no longer shows a misleading empty value-pack placeholder.
- Increased the Ready to order banner height, text sizing, padding and Shop Now button size.
- Removed the oversized pseudo-element link from the Our Story CTA. This prevents its invisible hit area from covering nearby homepage sections. The Story CTA itself remains clickable; product cards, combo cards, shortcuts and Shop Now retain their own intended destinations.
- Kept combo cards responsive for desktop, tablet and mobile.
- Updated storefront asset cache key to `rr-home-layout-22`.

## Validation
- Jinja parsing passed for homepage and shared layout.
- Python compilation passed for storefront query and shop catalog route.
- Confirmed the existing add-bundle endpoint is used by homepage forms.
- Confirmed mirrored app files and CSS brace balance.
- ZIP integrity checked.

The repository's pytest suite could not start in this environment because `flask_migrate` is not installed. No database schema or checkout logic was changed.
