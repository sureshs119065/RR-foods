# RR FOODS seed and category overlay update

- Added canonical seed file: `app/seed_data/seed_products.csv`.
- Included all 32 product records from the supplied RR FOODS catalogue.
- Preserved source SKUs, names, categories, MRP, selling-price discount amounts and supplied pack sizes.
- Added a `Breakfast` subcategory for seven relevant breakfast/mix products, without inventing new products.
- Kept missing ingredients, nutrition, allergens, preparation instructions and FSSAI details blank.
- Stock quantities remain blank in the seed so new imported products default to zero and re-imports do not overwrite existing stock.
- Fixed desktop category mega-menu overlay: `[hidden]` is now enforced with `display:none !important`, preventing the menu from covering page content when closed.
- Updated `flask import-rr-foods` default path to `app/seed_data/seed_products.csv`.

## Import

From the project root, after configuring PostgreSQL in `.env` and applying migrations:

```powershell
flask db upgrade
flask import-rr-foods --yes
```

The import creates missing categories and subcategories and updates products by SKU.

## Validation

- CSV rows: 32
- Unique SKUs: 32
- Breakfast subcategory assignments: 7
- Mega-menu hidden-state CSS assertion: passed
- Python AST syntax errors: see packaging validation; database/browser integration still needs local testing.
