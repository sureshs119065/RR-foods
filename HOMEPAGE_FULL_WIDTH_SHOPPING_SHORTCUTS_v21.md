# RR FOODS homepage layout upgrade — Version 21

Base archive: RR_Foods_Product_Page_Full_Width_Images_v20.zip

## Homepage changes
- Expanded the lower homepage shelves and bottom content to a 1600px maximum width with responsive side gutters.
- Rebalanced Recently Viewed and Our Story into a wider two-column desktop layout.
- Removed the constrained, scroll-box feel from Recently Viewed; product cards now use a responsive two-column grid on wide and medium screens.
- Increased story panel height, padding, typography and CTA sizing for a more deliberate full-width brand section.
- Improved Customer Reviews spacing and card layout.
- Added a new **Your shopping shortcuts** section with working links to:
  - Browse all products
  - Offers & combo
  - Track orders (or sign in if the visitor is not signed in)
  - Customer support message form
- Preserved existing Offers, Categories, New Arrivals, How to Order, review, and product catalogue functionality.
- Kept mobile layout responsive: sections stack vertically, shortcut cards become two columns, then one column on narrow phones.
- Updated the storefront asset cache key to `rr-home-layout-21`.

## Validation
- Jinja parsing passed for home and shared layout templates.
- Python app entrypoint compilation passed.
- Shopping shortcut endpoint references checked against existing templates/routes.
- CSS brace balance and mirrored app files checked.
- ZIP archive integrity checked.

No database schema or order workflow changes were made.
