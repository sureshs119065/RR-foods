# RR FOODS Design System — Step 2

## Scope completed
This step establishes the shared RR FOODS visual foundation across the existing Flask application. It is a presentation-only change: application routes, database models, migrations, business logic, checkout, and integrations were not changed.

## Approved brand tokens
- Primary green: `#245C3A`
- Deep green: `#183D2B`
- White: `#FFFFFF`
- Warm neutral: `#F7F6F2`
- Light border: `#E7E8E3`
- Brand red: `#B3262D`
- Primary text: `#252A26`
- Secondary text: `#737B75`

White is the default page and surface colour. The shared CSS enforces light mode, including the storefront, even if an old NK theme preference was stored in the browser.

## Typography and layout
- Body: system font stack.
- Display/headings: existing self-hosted Bricolage Grotesque variable font.
- Spacing tokens follow 4/8-point increments.
- Responsive heading sizes and 44px minimum interactive targets.
- Consistent 12–16px corner radii, light borders and subtle elevation.
- Visible keyboard focus and consistent input focus treatment.

## Brand asset
`app/static/img/rr-foods-logo.png` is an exact byte-for-byte copy of the supplied `logo.png`. It has not been recoloured, cropped, resized or otherwise edited.

## Files changed
- `app/static/css/base.css` — shared RR FOODS design tokens and global typography.
- `app/static/css/rr-foods-design.css` — common visual refinement layer for storefront, admin and owner.
- `app/templates/base.html` — loads the design system and updates browser theme colour.
- `app/templates/shop/layout.html` — loads the design system after storefront CSS.
- `app/templates/admin/layout.html` — loads the design system after admin CSS.
- `app/templates/owner/layout.html` — loads the design system after owner CSS.
- `app/static/img/rr-foods-logo.png` — original supplied brand asset.
- `docs/RR-FOODS-DESIGN-SYSTEM.md` — this implementation note.

## Not included in Step 2
Header replacement, homepage section restructuring, product import, product metadata, admin brand navigation, new payment gateway integration, and content migration are intentionally deferred to later steps.
