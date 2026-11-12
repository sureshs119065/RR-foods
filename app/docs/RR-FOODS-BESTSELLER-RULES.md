# RR FOODS bestseller rules

The `/bestsellers` page includes only active, non-archived products whose `products.is_bestseller` flag is true.
The `/shop` page includes all active, non-archived products regardless of the bestseller flag.

Admin controls the flag in Admin > Products > Add/Edit Product > Visibility using the
**Mark as Bestseller** checkbox. The existing `Product.is_bestseller` model field and
initial database migration already define a non-null boolean with a default of false,
so this update does not add a duplicate field or migration.

Sales counts continue to be recorded for popularity sorting, but sales volume does not
automatically add products to the Bestsellers page.
