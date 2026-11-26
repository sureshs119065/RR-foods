"""The 20 RR FOODS products: seed CSV, prices, product pages, internal notes kept off the site, archive of old products."""
import csv
import io
import re
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import select

from app.admin.csvio import COLUMNS, import_csv
from app.extensions import db
from app.models import Product
from app.services.product_catalogue import PRODUCT_CATALOGUE, catalogue_for_product

ROOT = Path(__file__).resolve().parent.parent
SEED = ROOT / "app" / "seed_data" / "seed_products.csv"
EXCEL = ROOT / "data" / "RR_FOODS_PRODUCT_CATALOGUE_-_FINAL.xlsx"
CATEGORIES = {"Millet Instant Noodles", "Millet Vermicelli (Semiya)", "Other RR Foods Products"}
# Wording the Excel "Guidelines & Checks" sheet says must not appear until finished-product testing and review are done.
BANNED = ["high fibre", "high-fibre", "high dietary", "rich in", "high protein", "protein-rich", "low gi", "glycemic", "glycaemic",
          "diabetic", "weight management", "weight-management", "immunity", "blood sugar", "anti-inflammatory", "cough"]
INTERNAL = ["Catalogue notes and information to verify", "information to verify", "Confirm whether", "provisional", "to be confirmed",
            "Editorial / Compliance", "confirm before publication"]


def seed_rows():
    with SEED.open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


@pytest.fixture()
def loaded(app, session):
    res = import_csv(SEED.read_bytes(), create_categories=True, default_stock=0)
    assert res.errors == [] and res.created == 20
    session.commit()
    return {p.sku: p for p in session.scalars(select(Product)).all()}


def test_seed_file_has_exactly_the_20_products_and_the_importer_columns():
    rows = seed_rows()
    assert list(rows[0].keys()) == COLUMNS
    assert len(rows) == 20 and len({r["sku"] for r in rows}) == 20
    assert {r["category"] for r in rows} == CATEGORIES
    for r in rows:
        assert r["brand"] == "RR FOODS" and r["stock_qty"] == "0" and r["low_stock_threshold"] == "5"
        assert (r["discount_type"], r["discount_value"], r["is_active"]) == ("percent", "8", "yes")
        assert re.fullmatch(r"\d+ g", r["pack_size"])
        assert (ROOT / "app" / r["image_urls"].lstrip("/")).exists(), r["image_urls"]


def test_no_old_demo_wording_is_left_in_the_seed_file():
    text = SEED.read_text(encoding="utf-8-sig").lower()
    for word in ("details are being verified", "details-pending", "thokku", "pickle", "laddu", "wellness powder", "kuzhambu", "sample pack"):
        assert word not in text


def test_every_final_price_equals_the_excel_selling_price(loaded):
    from openpyxl import load_workbook
    rows = list(load_workbook(EXCEL, data_only=True)["Product Catalogue"].iter_rows(values_only=True))
    head = rows[0]
    excel = {r[head.index("Product Name")]: dict(zip(head, r)) for r in rows[1:] if r[0]}
    assert len(excel) == 20 and len(loaded) == 20
    for p in loaded.values():
        e = excel[p.name]
        assert p.mrp == Decimal(str(e["MRP (₹)"])).quantize(Decimal("0.01"))
        assert p.final_price == Decimal(str(e["Selling Price"])).quantize(Decimal("0.01")), p.name
        assert p.stock_qty == 0 and p.low_stock_threshold == 5 and p.is_active
        assert p.category.name == e["Category"] and p.pack_size == f"{int(e['Net Weight (g)'])} g"


def test_catalogue_content_is_found_by_sku_for_all_20(loaded):
    assert len(PRODUCT_CATALOGUE) == 20
    for sku, p in loaded.items():
        item = catalogue_for_product(p)
        assert item is not None and item["sku"] == sku and item["name"] == p.name


def test_product_pages_show_content_but_no_internal_notes_or_banned_claims(app, loaded):
    client = app.test_client()
    for p in loaded.values():
        r = client.get(f"/product/{p.slug}")
        assert r.status_code == 200, p.sku
        html = r.get_data(as_text=True)
        low = html.lower()
        assert "Ingredients" in html and "Serving suggestions" in html
        for phrase in INTERNAL:
            assert phrase.lower() not in low, (p.sku, phrase)
        for phrase in BANNED:
            assert phrase not in low, (p.sku, phrase)


def test_fields_the_excel_leaves_open_show_nothing(app, loaded):
    client = app.test_client()
    kanji = client.get(f"/product/{loaded['RR-TNF-004'].slug}").get_data(as_text=True)      # no storage, no preparation, no recipes
    assert "Storage instructions" not in kanji and "Preparation" not in kanji and "Recipe ideas" not in kanji
    assert "Biotin Kanji" not in kanji.split("RR FOODS SPECIAL COMBO")[0]                    # label-name claim not shown as the page eyebrow
    noodles = client.get(f"/product/{loaded['RR-MN-001'].slug}").get_data(as_text=True)     # all given
    assert "Storage instructions" in noodles and "Preparation" in noodles and "Contains wheat." in noodles
    soup = client.get(f"/product/{loaded['RR-BTM-005'].slug}").get_data(as_text=True)
    assert "Allergen information" not in soup and "Storage instructions" not in soup        # "Not captured" in the Excel


def test_catalogue_module_has_no_internal_columns_or_placeholders():
    for item in PRODUCT_CATALOGUE:
        assert "editorial_notes" not in item
        for value in item.values():
            text = " ".join(value) if isinstance(value, list) else str(value or "")
            assert not re.search(r"\bnot (specified|captured|available)\b", text, re.I), item["name"]


def test_archive_others_archives_strays_keeps_the_20_and_dry_run_saves_nothing(app, loaded, session):
    stray = "sku,name,category,mrp\nRR-OLD-001,Old Product,Old Category,99\n"
    assert import_csv(stray.encode(), create_categories=True, default_stock=0).errors == []
    session.commit()
    runner = app.test_cli_runner()

    dry = runner.invoke(args=["import-rr-foods", "--dry-run", "--archive-others"])
    assert dry.exit_code == 0 and "RR-OLD-001" in dry.output and "Dry run" in dry.output
    session.expire_all()
    assert session.scalar(select(Product.is_deleted).where(Product.sku == "RR-OLD-001")) is False

    done = runner.invoke(args=["import-rr-foods", "--yes", "--archive-others"])
    assert done.exit_code == 0 and "0 errors" in done.output
    session.expire_all()
    assert session.scalar(select(Product.is_deleted).where(Product.sku == "RR-OLD-001")) is True
    assert session.scalar(select(db.func.count(Product.id)).where(Product.is_deleted.is_(False))) == 20


def test_rerunning_the_import_warns_that_stock_goes_back_to_zero(app, loaded, session):
    loaded["RR-MN-001"].stock_qty = 25
    session.commit()
    out = app.test_cli_runner().invoke(args=["import-rr-foods", "--yes"])
    assert out.exit_code == 0 and "sets their stock to 0" in out.output
    session.expire_all()
    assert session.scalar(select(Product.stock_qty).where(Product.sku == "RR-MN-001")) == 0
