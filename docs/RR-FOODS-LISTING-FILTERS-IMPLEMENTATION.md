# RR FOODS listing, filters and category menu update

## Route behavior
- `/shop` uses `shop.listing` and shows every active, non-archived product.
- `/bestsellers` uses `shop.bestsellers` and filters strictly on `Product.is_bestseller == True`.
- `/category/<slug>` uses `shop.category_listing`.
- All three render the shared `shop/listing.html` template.

## Bestseller database/admin
- `Product.is_bestseller` already exists in `app/models/catalog.py` with default False.
- The initial schema migration already creates `products.is_bestseller` as a non-null boolean with server default false.
- Admin product add/edit form already parses and persists the flag; checkbox label is now `Mark as Bestseller`.
- Sales count no longer automatically promotes a product to the Bestsellers page or homepage bestseller row.

## Filters and pagination
- Server-side query params: min_price, max_price, rating, brand, discount, avail, sort, q and category.
- Rating 2/3/4 uses avg_rating and requires review_count > 0; Any includes unrated products.
- Sort options include popularity, price ascending/descending, newest and rating.
- 12 products per page; pagination preserves active query params.
- Filter selections are restored from request args; Apply and Clear all controls are available.
- Result total is based on the filtered query.

## Category mega menu
- Sticky header stacking level 1000; mega menu stacking level 1100; desktop filter sidebar stacking level 1.
- `hidden` is enforced with `display:none !important`.
- Menu opens by click, desktop hover/focus, closes on outside click, Escape and pointer leave.

## Validation
- Python AST parsing: passed.
- Jinja template parsing: passed.
- Node syntax checks for shop.js and shell.js: passed.
- pytest could not start in the packaging environment because `flask_migrate` is not installed. Run the test suite in the configured project virtual environment.
