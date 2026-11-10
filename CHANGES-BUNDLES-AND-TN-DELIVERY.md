# Changes: bundle edit fix and Tamil Nadu delivery

## 1. Bundle edit (and reel / recipe edit) not working
Cause: `app/templates/admin/layout.html` and `owner/layout.html` defined a menu macro called `item`. It hid the
`item` variable that the edit forms receive, so the form opened with the name "item", an empty price and no
products selected. Saving that form then failed.
Fix: the macro is now called `navitem` (both layouts).

Also fixed in `app/admin/bundles.py` (and the matching `app/owner/bundles.py`):
- A failed save now keeps everything you typed and shows the error (before, the form was wiped).
- Editing no longer changes the bundle's slug (it used to change on every rename).
- Editing a bundle that belongs to a festival combo now updates that combo too (price, name, products, active).
- The old image file is removed when you upload a new one.

## 2. Delivery to all of Tamil Nadu
New file `app/services/delivery.py`. Every pincode from 600001 to 643999 is deliverable by rule, with no list to
maintain. The product-page pincode check (/api/pincode/<pin>), checkout and place-order all use it.
- Default for Tamil Nadu pincodes: 3 days, free delivery. Change with env vars DEFAULT_DELIVERY_DAYS and DEFAULT_DELIVERY_FEE.
- A row in `delivery_zones` still overrides one pincode (custom fee/days, or switch it off): `python add_pincodes.py 641001 --eta 1 --fee 0`
  and `python add_pincodes.py 605001 --disable`.
- Puducherry and Karaikal share the Tamil Nadu pincode range (for example 605xxx and 609602-609609). They are
  deliverable by default; switch them off with --disable if you do not deliver there.

Tests: `tests/test_bundles_and_delivery.py`.
