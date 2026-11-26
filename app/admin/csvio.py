"""CSV and Excel export, and CSV / Excel import, for products.

Export protects against spreadsheet formula injection (a cell starting with = + - @ would run as a formula in Excel).
Both formats have the same columns, so a file exported from here can be imported again.
Import checks every row first and changes nothing unless the whole file is valid.
"""
import csv
import io
import re
import zipfile
from datetime import datetime
from decimal import Decimal

from flask import g
from sqlalchemy import func, select

from ..extensions import db
from ..services.inventory import notify_admin_stock_transition
from ..models import Category, InventoryLog, Product, ProductImage
from ..seed import slugify
from ..services import report_export as rx
from ..services.inventory import stock_state
from ..services.report_export import safe_cell      # one formula guard for every export (re-exported: other modules import it from here)
from ..services.xlsx_export import INT, MIXED, MONEY, NUMBER, TEXT, Sheet, Typed, build_workbook
from .helpers import shop_tz, to_decimal, to_int, unique_slug

COLUMNS = ["sku", "name", "category", "subcategory", "brand", "pack_size", "mrp", "discount_type", "discount_value", "stock_qty",
           "low_stock_threshold", "short_description", "description", "ingredients", "how_to_use", "fssai", "video_id", "tags",
           "is_active", "is_bestseller", "image_urls"]
# What the exported file shows in row 1. The importer reads these AND the short names above, so an exported file imports straight back.
HEADERS = {"sku": "SKU", "name": "Product Name", "category": "Category", "subcategory": "Subcategory", "brand": "Brand",
           "pack_size": "Pack Size", "mrp": "MRP (₹)", "discount_type": "Discount Type", "discount_value": "Discount Value",
           "stock_qty": "Stock Qty", "low_stock_threshold": "Low-Stock Alert At", "short_description": "Short Description",
           "description": "Description", "ingredients": "Ingredients", "how_to_use": "How To Use", "fssai": "FSSAI No.",
           "video_id": "YouTube Video ID", "tags": "Tags", "is_active": "Active", "is_bestseller": "Bestseller", "image_urls": "Image URLs"}
HUMAN_TO_KEY = {v.lower(): k for k, v in HEADERS.items()}
ALIASES = {"id": "sku", "price": "mrp", "weight": "pack_size", "shortdescription": "short_description", "howtouse": "how_to_use",
           "videoid": "video_id", "image": "image_urls", "images": "image_urls", "instock": "in_stock"}
MAX_ROWS = 2000
MAX_BYTES = 2 * 1024 * 1024
MAX_XLSX_UNPACKED = 40 * 1024 * 1024      # guards against a tiny .xlsx that unpacks to gigabytes
XLSX_MAGIC = b"PK\x03\x04"                 # an .xlsx file is a zip archive
COLUMN_KINDS = {"mrp": MONEY, "discount_value": NUMBER, "stock_qty": INT, "low_stock_threshold": INT}
URL_OK = re.compile(r"^(/uploads/|/images/|/static/img/products/|https://)[^\s]+$")


def unsafe_cell(text: str) -> str:
    """Undoes safe_cell on the way back in, so exporting and importing again does not add a quote to the name."""
    if len(text) > 1 and text[0] == "'" and text[1] in ("=", "+", "-", "@", "\t", "\r"):
        return text[1:]
    return text


def product_row(p) -> list:
    """One product as the list of cells for COLUMNS. Used by both the CSV and the Excel export."""
    return [p.sku, p.name, p.category.name, p.subcategory.name if p.subcategory else "", p.brand, p.pack_size, p.mrp, p.discount_type,
            p.discount_value, p.stock_qty, p.low_stock_threshold, p.short_description, p.description, p.ingredients, p.how_to_use,
            p.fssai, p.video_id, ", ".join(p.tags or []), "yes" if p.is_active else "no", "yes" if p.is_bestseller else "no",
            "|".join(i.url for i in p.images)]


def _shown(row: list) -> list:
    """An empty text cell reads "-" in the file (the importer turns a lone "-" back into empty), and Yes/No are capitalised."""
    out = []
    for col, value in zip(COLUMNS, row):
        if col in ("is_active", "is_bestseller"):
            value = "Yes" if value == "yes" else "No"
        out.append(value if col in COLUMN_KINDS or value not in (None, "") else rx.EMPTY)
    return out


def export_csv(products) -> str:
    """UTF-8 with a byte order mark, so Excel opens ₹ and accented text correctly. The importer reads the mark too.
    No summary lines on purpose: this file is also the import template, so row 1 must be the column headings."""
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow([HEADERS[c] for c in COLUMNS])
    for p in products:
        cells = _shown(product_row(p))
        w.writerow([rx._csv_value(x, COLUMN_KINDS[c]) if c in COLUMN_KINDS else (x if x == rx.EMPTY else safe_cell(x)) for c, x in zip(COLUMNS, cells)])
    return "\ufeff" + buf.getvalue()


def _xlsx_clean(text: str) -> str:
    return text if text in ("", rx.EMPTY) else safe_cell(text)


def export_xlsx(products) -> bytes:
    """Styled Excel file: the same columns as the CSV on the first sheet (so it imports back), and a Summary sheet with the totals."""
    products = list(products)
    kinds = [COLUMN_KINDS.get(c, TEXT) for c in COLUMNS]
    now = datetime.now(shop_tz())
    states = [stock_state(p.stock_qty, p.low_stock_threshold) for p in products]
    value = sum((p.final_price or 0) * max(p.stock_qty, 0) for p in products)
    summary = [
        ("Exported on", f"{rx.dt_text(now.replace(tzinfo=None))} ({shop_tz().key})", TEXT),
        ("Products in this file", len(products), INT),
        ("Active (shown in shop)", sum(1 for p in products if p.is_active), INT),
        ("Hidden", sum(1 for p in products if not p.is_active), INT),
        ("In stock", states.count("ok"), INT), ("Low stock", states.count("low"), INT), ("Out of stock", states.count("out"), INT),
        ("Units in stock", sum(max(p.stock_qty, 0) for p in products), INT),
        ("Stock value at selling price", value, MONEY),
    ]
    main = Sheet("Products", [HEADERS[c] for c in COLUMNS], kinds, [_shown(product_row(p)) for p in products])
    totals = Sheet("Summary", ["Metric", "Value"], [TEXT, MIXED], [[lab, Typed(v, k)] for lab, v, k in summary])
    return build_workbook([main, totals], clean=_xlsx_clean)


def _truthy(value: str, default=True) -> bool:
    v = (value or "").strip().lower()
    if not v:
        return default
    return v in ("1", "yes", "y", "true", "on")


class ImportResult:
    def __init__(self):
        self.errors: list[str] = []
        self.created = self.updated = 0


def _xlsx_text(value) -> str:
    """A cell value read from Excel, as the text the CSV importer would have seen."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return str(int(value)) if value.is_integer() else format(Decimal(repr(value)), "f")
    if isinstance(value, Decimal):
        return format(value, "f")
    return str(value)


def _read_xlsx(raw: bytes) -> tuple[list[list[str]] | None, str | None]:
    """First sheet of an .xlsx file as rows of text. Returns (rows, None) or (None, problem)."""
    from openpyxl import load_workbook
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            if sum(i.file_size for i in archive.infolist()) > MAX_XLSX_UNPACKED:
                return None, "The Excel file is too large once opened. Import at most 2000 products at a time."
        book = load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
        try:
            rows: list[list[str]] = []
            for cells in book.worksheets[0].iter_rows(values_only=True):
                rows.append([_xlsx_text(c) for c in cells])
                if len(rows) > MAX_ROWS + 1000:          # empty formatted rows at the bottom are fine, a real flood is not
                    return None, f"Too many rows. Import at most {MAX_ROWS} products at a time."
        finally:
            book.close()
    except Exception:                                    # a damaged or non-Excel file: say so, never crash
        return None, "That file could not be read as an Excel workbook. Save it as .xlsx or CSV UTF-8 and try again."
    while rows and not any(c.strip() for c in rows[-1]):
        rows.pop()
    return rows, None


def import_csv(raw: bytes, *, create_categories: bool, default_stock: int) -> ImportResult:
    """Despite the name this reads a CSV file or an .xlsx file (it looks at the file itself, not at its name)."""
    res = ImportResult()
    if len(raw) > MAX_BYTES:
        res.errors.append("The file is larger than 2 MB.")
        return res
    if raw[:4] == XLSX_MAGIC:
        rows, problem = _read_xlsx(raw)
        if problem:
            res.errors.append(problem)
            return res
    else:
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            res.errors.append("The file is not UTF-8 text. In Excel choose “CSV UTF-8” when saving.")
            return res
        rows = list(csv.reader(io.StringIO(text)))
    rows = [["" if c.strip() == rx.EMPTY else unsafe_cell(c) for c in cells] for cells in rows]   # a lone "-" is how the export shows "nothing"
    if not rows or len(rows) < 2:
        res.errors.append("The file has no product rows.")
        return res
    if len(rows) - 1 > MAX_ROWS:
        res.errors.append(f"Too many rows. Import at most {MAX_ROWS} products at a time.")
        return res
    head = [HUMAN_TO_KEY.get(h.strip().lower()) or ALIASES.get(h.strip().lower().replace(" ", "_"), h.strip().lower().replace(" ", "_")) for h in rows[0]]
    missing = [c for c in ("sku", "name", "category", "mrp") if c not in head]
    if missing:
        res.errors.append("Missing column(s): " + ", ".join(missing) + ". (The old columns id, name, category, price also work.)")
        return res

    plans = []
    seen = set()
    new_categories: dict[tuple, Category] = {}
    for n, cells in enumerate(rows[1:], start=2):
        if not any(c.strip() for c in cells):
            continue
        row = {h: (cells[i].strip() if i < len(cells) else "") for i, h in enumerate(head)}
        errs: dict = {}
        label = f"Row {n}"
        sku = row["sku"].upper()
        if not sku or not re.fullmatch(r"[A-Z0-9][A-Z0-9._\-]*", sku):
            res.errors.append(f"{label}: the SKU is missing or has invalid characters.")
            continue
        label = f"Row {n} ({sku})"
        if sku in seen:
            res.errors.append(f"{label}: the SKU appears twice in the file.")
            continue
        seen.add(sku)
        name = " ".join(row["name"].split())[:200]
        if len(name) < 2:
            errs["name"] = "name is required"
        mrp = to_decimal(row["mrp"], "mrp", errs, min_=Decimal("0.01"), max_=Decimal(1_000_000))
        dtype = (row.get("discount_type") or "none").lower()
        if dtype not in ("none", "percent", "flat"):
            errs["discount_type"] = "discount_type must be none, percent or flat"
            dtype = "none"
        dval = Decimal(0)
        if dtype != "none":
            dval = to_decimal(row.get("discount_value"), "discount_value", errs, min_=Decimal(0), max_=Decimal(100) if dtype == "percent" else Decimal(1_000_000))
            dval = dval if dval is not None else Decimal(0)
            if dtype == "flat" and mrp is not None and dval > mrp:
                errs["discount_value"] = "flat discount is more than the MRP"
        stock = None
        if "stock_qty" in row and row["stock_qty"]:
            stock = to_int(row["stock_qty"], "stock_qty", errs, min_=0, max_=1_000_000)
        elif "in_stock" in row and row["in_stock"]:
            stock = default_stock if _truthy(row["in_stock"]) else 0
        low = to_int(row.get("low_stock_threshold"), "low_stock_threshold", errs, min_=0, max_=100_000, required=False, default=5)
        video = row.get("video_id", "")
        if video and not re.fullmatch(r"[A-Za-z0-9_-]{11}", video):
            errs["video_id"] = "video_id must be an 11 character YouTube id"
        urls = [u.strip() for u in row.get("image_urls", "").split("|") if u.strip()]
        bad = [u for u in urls if not URL_OK.match(u)]
        if bad:
            errs["image_urls"] = f"image link not allowed: {bad[0][:60]} (use /static/img/products/..., /uploads/... or https://...)"
        cat_name = " ".join(row["category"].split())
        category = db.session.scalar(select(Category).where(func.lower(Category.name) == cat_name.lower(), Category.parent_id.is_(None), Category.is_deleted.is_(False))) if cat_name else None
        if not cat_name:
            errs["category"] = "category is required"
        elif category is None and not create_categories:
            errs["category"] = f"category “{cat_name}” does not exist (tick “create missing categories” or add it first)"
        sub_name = " ".join((row.get("subcategory") or "").split())
        if errs:
            res.errors.append(f"{label}: " + "; ".join(errs.values()) + ".")
            continue
        plans.append(dict(sku=sku, name=name, mrp=mrp, dtype=dtype, dval=dval, stock=stock, low=low, urls=urls, category=category,
                          cat_name=cat_name, sub_name=sub_name, row=row))
        if len(res.errors) >= 25:
            res.errors.append("…and more. Fix these first.")
            return res
    if res.errors:
        return res
    if not plans:
        res.errors.append("The file has no product rows.")
        return res

    # all rows are valid: now write
    for plan in plans:
        row = plan["row"]
        category = plan["category"]
        if category is None:
            key = plan["cat_name"].lower()
            category = new_categories.get((key, None))
            if category is None:
                category = Category(name=plan["cat_name"], slug=unique_slug(Category, plan["cat_name"]))
                db.session.add(category)
                db.session.flush()
                new_categories[(key, None)] = category
        sub = None
        if plan["sub_name"]:
            sub = db.session.scalar(select(Category).where(func.lower(Category.name) == plan["sub_name"].lower(), Category.parent_id == category.id, Category.is_deleted.is_(False)))
            if sub is None and create_categories:
                sub = Category(name=plan["sub_name"], slug=unique_slug(Category, plan["sub_name"]), parent_id=category.id)
                db.session.add(sub)
                db.session.flush()
        p = db.session.scalar(select(Product).where(func.upper(Product.sku) == plan["sku"]))
        is_new = p is None
        old_stock = 0 if is_new else p.stock_qty
        if is_new:
            p = Product(sku=plan["sku"], slug=unique_slug(Product, plan["name"]), name=plan["name"], category_id=category.id,
                        mrp=plan["mrp"], final_price=plan["mrp"], stock_qty=0)
            db.session.add(p)
        p.name, p.category_id, p.subcategory_id = plan["name"], category.id, sub.id if sub else None
        p.mrp, p.discount_type, p.discount_value = plan["mrp"], plan["dtype"], plan["dval"]
        p.apply_pricing()
        p.low_stock_threshold = plan["low"]
        for src, attr, limit in (("brand", "brand", 120), ("pack_size", "pack_size", 40), ("short_description", "short_description", 300),
                                 ("description", "description", 5000), ("ingredients", "ingredients", 2000), ("how_to_use", "how_to_use", 2000),
                                 ("fssai", "fssai", 30), ("video_id", "video_id", 20)):
            if src in row:
                setattr(p, attr, row[src][:limit] or None)
        if "tags" in row:
            tags = [t.strip()[:30] for t in re.split(r"[,\n]", row["tags"]) if t.strip()]
            p.is_bestseller = any(t.lower() == "featured" for t in tags) or _truthy(row.get("is_bestseller", ""), default=p.is_bestseller if not is_new else False)
            p.tags = [t for t in tags if t.lower() != "featured"][:20]
        elif "is_bestseller" in row:
            p.is_bestseller = _truthy(row["is_bestseller"], default=False)
        if "is_active" in row:
            p.is_active = _truthy(row["is_active"], default=True)
        if plan["stock"] is not None:
            p.stock_qty = plan["stock"]
        elif is_new:
            p.stock_qty = 0
        db.session.flush()
        if old_stock != p.stock_qty:
            db.session.add(InventoryLog(product_id=p.id, changed_by=g.user.id, old_qty=old_stock, new_qty=p.stock_qty, reason="csv import"))
            notify_admin_stock_transition(p, old_stock, p.stock_qty)
        have = {i.url for i in p.images}
        for url in plan["urls"]:
            if url not in have:
                p.images.append(ProductImage(url=url, alt=p.name, sort_order=len(p.images), is_primary=not p.images))
        res.created += is_new
        res.updated += not is_new
    return res
