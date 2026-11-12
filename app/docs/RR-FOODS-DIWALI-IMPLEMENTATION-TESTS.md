# RR FOODS feature test checklist

## About / Our Quality Journey
- Open `/about` on desktop and mobile.
- Scroll the journey into view: six cards should reveal in sequence, the line should fill, the marker should travel and the final Quality Assured badge should appear.
- Verify the stage order: Sourcing; Cleaning and Sorting; Traditional Processing; Quality Testing; Hygienic Packaging; Delivery.
- Verify the count-up metrics (`0 preservatives added` and `6 journey stages`). Other quality-check quantities are intentionally not asserted because no verified number was supplied.
- Emulate `prefers-reduced-motion: reduce`: all text should remain visible without the slide/pulse/count animation.
- Disable JavaScript: all six stages should still be readable.

## Diwali Offers / cart
- Run `flask db upgrade`.
- Ensure at least two active products have stock and do not require variants.
- Run `flask seed-diwali-combos` once to create three sample database records.
- Open `/admin/combos`; edit combo contents, original/discounted price, image, active state and countdown end time. Create and delete a test combo too.
- Open `/offers`; verify only active Diwali-tagged Combo records render, actual product names appear, original prices are struck through, discounted prices and discount ribbons are correct.
- Sign in as a customer, add a combo to cart and verify the existing bundle cart pricing equals the configured combo price.
- Change the end date in Admin and verify the Offers countdown updates. Expired dates should display that the offer period has ended.

## Fireworks / performance
- Scroll the Diwali section into view: rockets should launch roughly every 1.2 seconds.
- Click the section background or combo-card area: a burst should appear; Add to Cart and other controls must remain usable.
- Click Celebrate!: multiple bursts should launch.
- Scroll the section off-screen: animation should pause. Scroll back: it should resume.
- Switch to another browser tab: animation should pause and resume on return.
- Emulate reduced motion: automatic fireworks should be disabled; Celebrate changes to a static acknowledgement.
- Confirm the canvas has pointer-events disabled and does not intercept cards or buttons.

## Existing storefront regression
- Check the Shop All and Bestsellers links, categories dropdown, search, filters, cart and checkout pages. No existing navbar or filter JavaScript was replaced.

## Automated checks in the build workspace
- Python source and migration AST parsing: passed.
- Jinja template parsing: passed.
- Node syntax checks for both new scripts and existing shop shell scripts: passed.
- Flask/PostgreSQL integration tests could not be executed in the build container because Flask and its project dependencies are not installed there. Run `pytest` from the project's configured virtual environment after migrating the database.
