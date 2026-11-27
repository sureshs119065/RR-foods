"""Rebuild the RR FOODS product data from the approved Excel catalogue.

    python tools/build_catalogue_from_excel.py [path-to-xlsx]

Reads the "Product Catalogue" sheet (default: data/RR_FOODS_PRODUCT_CATALOGUE_-_FINAL.xlsx) and writes:

  app/seed_data/seed_products.csv      what `flask import-rr-foods` loads (SKU, price, tagline, ingredients, preparation, image)
  app/services/product_catalogue.py    product-page content (description, benefits, serving, recipes, storage, allergen ...)
  docs/INTERNAL-catalogue-review.md    internal notes only; never shown on the website

Nothing is invented: every text comes from the Excel. Cells that say "Not specified / Not captured / Not available" become
empty and the product page shows nothing for them. The few places where public text differs from the Excel are listed in
PUBLIC_TEXT_CHANGES below and are repeated in the internal review file.
"""
import csv
import importlib.util
import pprint
import re
import sys
from decimal import Decimal
from pathlib import Path

from openpyxl import load_workbook

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_XLSX = ROOT / "data" / "RR_FOODS_PRODUCT_CATALOGUE_-_FINAL.xlsx"
IMG_DIR = ROOT / "app" / "static" / "img" / "products"

# Excel product number -> (existing SKU, existing image file). Existing SKUs are kept so orders and images still match.
SKU_MAP = {
    1: ("RR-MN-001", "barnyard-millet-noodles"), 2: ("RR-MN-002", "foxtail-millet-noodles"),
    3: ("RR-MN-003", "kodo-millet-noodles"), 4: ("RR-MN-004", "little-millet-noodles"),
    5: ("RR-MN-005", "multi-millet-noodles"),
    6: ("RR-MV-001", "barnyard-millet-semiya"), 7: ("RR-MV-002", "foxtail-millet-semiya"),
    8: ("RR-MV-003", "kodo-millet-semiya"), 9: ("RR-MV-004", "little-millet-semiya"),
    10: ("RR-MV-005", "mapillai-samba-semiya"), 11: ("RR-MV-006", "multi-millet-semiya"),
    12: ("RR-PCB-002", "multi-millet-muesli"), 13: ("RR-PCB-006", "multi-millet-pasta"),
    14: ("RR-PCB-005", "beetroot-pasta"), 15: ("RR-BTM-001", "multi-millet-chapati-mix"),
    16: ("RR-BTM-003", "inippu-ellu-idli-podi"), 17: ("RR-BTM-004", "tirunelveli-idli-podi"),
    18: ("RR-BTM-005", "moringa-soup-mix"), 19: ("RR-BTM-006", "soup-base-mix"),
    20: ("RR-TNF-004", "karuppu-kavuni-kanji-mix"),
}
DISCOUNT_PERCENT = Decimal(8)
NOT_GIVEN = re.compile(r"^\s*(not (specified|captured|available)\b|to be confirmed)", re.I)

# (product number, field, old text, new text, why). Applied to the public text only; the Excel is never edited.
PUBLIC_TEXT_CHANGES = [
    (1, "nutrition_context", "Barnyard millet has a notably high dietary-fibre profile, supporting",
     "Barnyard millet has a dietary-fibre profile, supporting",
     'Claims rule: "high fibre" is not to be used.'),
    (6, "nutrition_context", "High dietary-fibre profile supports", "Dietary fibre supports",
     'Claims rule: "high fibre" is not to be used.'),
    (12, "allergen", "; confirm final declaration)", ")",
     "Internal instruction removed; the allergen names (wheat, barley, oats) are kept."),
    (13, "description", " Confirm the product-to-label mapping before publishing this entry as a separate SKU.", "",
     "Internal instruction removed."),
]
LOCAL_NAME_CHANGES = {
    13: ("Multi Millet Pasta", '"provisional label mapping" is an internal note.'),
    20: (None, 'The label name contains "Biotin", flagged in the Compliance Notes for product 20; not shown.'),
}
COMMON_NOTE = ("Serving suggestions and recipe ideas are editorial suggestions, not manufacturer instructions.")
MILLET_NOTE = "These benefits describe the grain ingredients, not measured nutrient levels in the finished RR FOODS product. "
OTHER_NOTE = "These notes describe the ingredients, not measured nutrient levels in the finished RR FOODS product. "
# Product pages that show the combo card: exactly the 7 products in the Excel "Combo Offer" sheet (Soup Mix = Moringa Leaf Soup Mix,
# product 18). Soup Base Mix (19) is NOT in the combo, so its page does not show it. Product 16 (Inippu Ellu Idli Podi) is not in it either.
COMBO_PRODUCTS = (5, 11, 13, 15, 17, 18, 20)
PRODUCT_NAME_OVERRIDES = {}   # product names are exactly the Excel master-sheet names (tests/test_rr_catalogue.py enforces this)


def blank(value):
    text = "" if value is None else str(value).strip()
    return "" if (not text or NOT_GIVEN.match(text)) else text


def lines(value, bullet=True):
    out = []
    for raw in blank(value).split("\n"):
        raw = raw.strip()
        if bullet:
            raw = re.sub(r"^[•\-\u2022]\s*", "", raw)
        if raw:
            out.append(raw)
    return out


def steps(value):
    text = blank(value)
    if not text:
        return []
    if re.match(r"^1\.\s", text):
        return [re.sub(r"^\d+\.\s*", "", s).strip() for s in re.split(r"\s+(?=\d\.\s)", text)]
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]


def money(value):
    d = Decimal(str(value))
    return f"{d:.2f}"


def load_rows(xlsx):
    book = load_workbook(xlsx, data_only=True)
    rows = list(book["Product Catalogue"].iter_rows(values_only=True))
    head = rows[0]
    return [dict(zip(head, r)) for r in rows[1:] if r[0] is not None]


def build(xlsx):
    items, csv_rows, applied = [], [], []
    for r in load_rows(xlsx):
        n = int(r["Product ID"])
        sku, image = SKU_MAP[n]
        if not (IMG_DIR / f"{image}.webp").exists():
            raise SystemExit(f"Missing image for product {n}: {image}.webp")
        mrp = Decimal(str(r["MRP (₹)"]))
        price = (mrp * (100 - DISCOUNT_PERCENT) / 100).quantize(Decimal("0.01"))
        if price != Decimal(str(r["Selling Price"])).quantize(Decimal("0.01")):
            raise SystemExit(f"Product {n}: Excel selling price {r['Selling Price']} is not {DISCOUNT_PERCENT}% below MRP ({price})")
        weight = f"{int(r['Net Weight (g)'])} g"
        item = {
            "number": n, "sku": sku, "name": PRODUCT_NAME_OVERRIDES.get(n, r["Product Name"].strip()),
            "local_name": blank(r["Alternate / Label Name"]) or None,
            "strapline": blank(r["Tagline"]) or None,
            "description": blank(r["Description"]),
            "ingredients": blank(r["Ingredients"]),
            "perfect_for": lines(r["Perfect For"]),
            "serving": blank(r["Serving Suggestions"]) or None,
            "recipe_ideas": lines(r["Recipe Ideas"], bullet=False),
            "preparation": steps(r["Preparation"]),
            "storage": blank(r["Storage Instructions"]) or None,
            "allergen": blank(r["Allergen Warning"]) or None,
            "net_weight": weight, "best_before": blank(r["Best Before"]) or None,
            "nutrition_context": lines(r["Nutritional Benefits"]),
            "blend_details": [],
            "catalogue_mrp": f"₹{mrp.normalize():f}",
            "catalogue_net_weight": weight, "catalogue_best_before": blank(r["Best Before"]) or None,
            "nutrition_disclaimer": (MILLET_NOTE if n <= 11 else OTHER_NOTE) + COMMON_NOTE,
        }
        if n in LOCAL_NAME_CHANGES:
            item["local_name"] = LOCAL_NAME_CHANGES[n][0]
        for num, field, old, new, why in PUBLIC_TEXT_CHANGES:
            if num != n:
                continue
            value = item[field]
            if isinstance(value, list):
                hit = [i for i, line in enumerate(value) if old in line]
                if not hit:
                    raise SystemExit(f"Change for product {n} did not match: {old}")
                value[hit[0]] = value[hit[0]].replace(old, new)
            else:
                if old not in value:
                    raise SystemExit(f"Change for product {n} did not match: {old}")
                item[field] = value.replace(old, new)
            applied.append((num, field, old, new, why))
        items.append(item)
        csv_rows.append({
            "sku": sku, "name": item["name"], "category": r["Category"].strip(), "subcategory": "", "brand": "RR FOODS",
            "pack_size": weight, "mrp": money(mrp), "discount_type": "percent", "discount_value": str(DISCOUNT_PERCENT),
            "stock_qty": "0", "low_stock_threshold": "5", "short_description": item["strapline"] or "",
            "description": item["description"], "ingredients": item["ingredients"], "how_to_use": blank(r["Preparation"]),
            "fssai": "", "video_id": "", "tags": "", "is_active": "yes", "is_bestseller": "no",
            "image_urls": f"/static/img/products/{image}.webp",
        })
    return items, csv_rows, applied, load_rows(xlsx)


def write_csv(csv_rows):
    from importlib import import_module
    sys.path.insert(0, str(ROOT))
    columns = import_module("app.admin.csvio").COLUMNS
    path = ROOT / "app" / "seed_data" / "seed_products.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=columns, lineterminator="\n")
        w.writeheader()
        w.writerows(csv_rows)
    return path


def old_combo():
    """The combo block is Part C: carry it over exactly as it is now."""
    path = ROOT / "app" / "services" / "product_catalogue.py"
    spec = importlib.util.spec_from_file_location("old_catalogue", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.CATALOGUE_COMBO_OFFER


MODULE_HEAD = '''"""Product-page content for the 20 RR FOODS products. GENERATED from the Excel catalogue:

    python tools/build_catalogue_from_excel.py

Do not edit by hand; change the Excel and run the script again. Every text comes from the Excel. A field the Excel marks
"Not specified / Not captured" is None or empty and the product page shows nothing for it. The Excel column
"Editorial / Compliance Notes" is internal and is NOT stored here (see docs/INTERNAL-catalogue-review.md).
Ingredient-level nutrition text describes the grain or ingredient, never the finished product, and carries no health claim.
"""
import re
import unicodedata

PRODUCT_CATALOGUE = '''

MODULE_TAIL = '''

CATALOGUE_COMBO_OFFER = {combo}
for _number in {combo_numbers}:
    PRODUCT_CATALOGUE[_number - 1]["combo_offer"] = CATALOGUE_COMBO_OFFER


def _normalise(value):
    value = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode().lower()
    return " ".join(re.findall(r"[a-z0-9]+", value))


def catalogue_for_product(product):
    """The catalogue entry for a store product: by SKU first, then by product name."""
    sku = (getattr(product, "sku", "") or "").strip().upper()
    for item in PRODUCT_CATALOGUE:
        if item["sku"] == sku:
            return item
    name = _normalise(getattr(product, "name", ""))
    for item in PRODUCT_CATALOGUE:
        if name and name == _normalise(item["name"]):
            return item
    return None
'''


def write_module(items, combo):
    path = ROOT / "app" / "services" / "product_catalogue.py"
    body = pprint.pformat(items, width=118, sort_dicts=False)
    path.write_text(MODULE_HEAD + body + MODULE_TAIL.format(combo=pprint.pformat(combo, width=118, sort_dicts=False),
                                                           combo_numbers=COMBO_PRODUCTS), encoding="utf-8")
    return path


def write_internal(rows, items, applied):
    path = ROOT / "docs" / "INTERNAL-catalogue-review.md"
    out = ["# RR FOODS: internal catalogue review (do not publish)", "",
           "Source: `RR_FOODS_PRODUCT_CATALOGUE_-_FINAL.xlsx`, working draft of 3 November 2026. This file holds the Excel column",
           '"Editorial / Compliance Notes" and the "Confirm before publication" checklist. None of it is shown on the website.', "",
           "## 1. Editorial / Compliance Notes (Excel, per product)", "", "| # | Product | SKU | Note |", "|---|---|---|---|"]
    for r, it in zip(rows, items):
        out.append(f"| {it['number']:02d} | {it['name']} | {it['sku']} | {str(r['Editorial / Compliance Notes'] or '').replace('|', '/')} |")
    out += ["", "## 2. Fields the Excel leaves open (shown as nothing on the site)", "", "| # | Product | Not given in Excel |", "|---|---|---|"]
    for r, it in zip(rows, items):
        gaps = [label for label, key in (("Preparation", "Preparation"), ("Recipe ideas", "Recipe Ideas"), ("Storage", "Storage Instructions"),
                                         ("Allergen", "Allergen Warning")) if not blank(r[key])]
        if gaps:
            out.append(f"| {it['number']:02d} | {it['name']} | {', '.join(gaps)} |")
    out += ["", "## 3. Public text that differs from the Excel", "",
            "The Excel itself is not changed. These are the only differences on the public site.", "",
            "| # | Field | Excel text | Public text | Reason |", "|---|---|---|---|---|"]
    for num, field, old, new, why in applied:
        out.append(f"| {num:02d} | {field} | …{old.strip()}… | …{new.strip() or '(removed)'}… | {why} |")
    for num, (new, why) in LOCAL_NAME_CHANGES.items():
        excel_name = next(str(r["Alternate / Label Name"]) for r in rows if int(r["Product ID"]) == num)
        out.append(f"| {num:02d} | alternate / label name | {excel_name} | {new or '(not shown)'} | {why} |")
    out += ["", "## 4. Claims rule (Excel sheet \"Guidelines & Checks\")", "",
            'No product page adds or shows "high fibre", "rich in iron", "high protein", "low GI", "diabetic-friendly", weight, immunity',
            "or disease claims. Grain benefits are worded as describing the ingredient, not the finished product. Label claims flagged for",
            "products 15, 18, 19 and 20 (fibre, protein, glycaemic index, weight management, diabetic suitability, blood sugar,",
            "antioxidant, anti-inflammatory, cold and cough, immunity, heart, bone, digestion, muscle, hair, skin, Biotin) are not used.", ""]
    path.write_text("\n".join(out), encoding="utf-8")
    return path


def main():
    xlsx = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_XLSX
    combo = old_combo()
    items, csv_rows, applied, rows = build(xlsx)
    print("wrote", write_csv(csv_rows))
    print("wrote", write_module(items, combo))
    print("wrote", write_internal(rows, items, applied))


if __name__ == "__main__":
    main()
