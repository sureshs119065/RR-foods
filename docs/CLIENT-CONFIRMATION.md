# Please confirm with the client

## 1. Is the 8 % discount an official offer?
In `RR_FOODS_PRODUCT_CATALOGUE_-_FINAL.xlsx` (sheet "Product Catalogue") the column **Selling Price** is the formula `=MRP*0.92` for all 20 products.
No column or note calls it a discount, an offer or a sale. The website currently shows every product at MRP less 8 % (for example Rs 129 -> Rs 118.68)
with an "8% off" badge, and the Offers page lists all 20 as "Product offers". If the client does not confirm, set `discount_value` to 0 in
`app/seed_data/seed_products.csv` (or in Admin > Products) and the badges and offer listings disappear.

**Message to send:** "In the catalogue, the Selling Price is MRP less 8 % for all 20 products, but it is not labelled as a discount. Do you want the website to
show this as an 8 % discount (strike-through MRP and an '8% off' badge)? And is the Rs 999 combo (7 products, total MRP Rs 1,044) the only other offer?"

## 2. Names
- Product 13 is "Millet Pasta Sample" in the master sheet but "Multi Millet Pasta" in the Combo Offer sheet. Which is the final retail name? (The product page currently uses the master-sheet name; the combo list uses the combo-sheet name.)
- "Biotin" appears in the kanji mix label name only. It is not in the ingredients, so it is not shown on the site. Keep it out?
- The combo's 130 g soup is shown as Moringa Leaf Soup Mix (the sheet's own mapping). Confirm it is not Soup Base Mix.

## 3. Other wording not in the catalogue (left as is, please confirm)
"Home-style" and "Delivered in Tamil Nadu" on the home page; free delivery above an amount appears only if the owner sets `free_delivery_above` (off by default).
