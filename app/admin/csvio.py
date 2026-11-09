"""CSV export and import for products.

Export protects against spreadsheet formula injection (a cell starting with = + - @ would run as a formula in Excel).
Import checks every row first and changes nothing unless the whole file is valid.
"""
import csv
import io
import re
from decimal import Decimal

from flask import g
from sqlalchemy import func, select

from ..extensions import db
from ..models import Category, InventoryLog, Product, ProductImage
from ..seed import slugify
from .helpers import to_decimal, to_int, unique_slug

COLUMNS = ["sku", "name", "category", "subcategory", "brand", "pack_size", "mrp", "discount_type", "discount_value", "stock_qty",
           "low_stock_threshold", "short_description", "description", "ingredients", "how_to_use", "fssai", "video_id", "tags",
           "is_active", "is_bestseller", "image_urls"]
ALIASES = {"id": "sku", "price": "mrp", "weight": "pack_size", "shortdescription": "short_description", "howtouse": "how_to_use",
           "videoid": "video_id", "image": "image_urls", "images": "image_urls", "instock": "in_stock"}
MAX_ROWS = 2000
MAX_BYTES = 2 * 1024 * 1024
URL_OK = re.compile(r"^(/uploads/|/images/|/static/img/products/|https://)[^\s]+$")


def safe_cell(value):
    text = "" if value is None else str(value)
    if text[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + text
    return text


def export_csv(products) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(COLUMNS)
    for p in products:
        w.writerow([safe_cell(x) for x in [
            p.sku, p.name, p.category.name, p.subcategory.name if p.subcategory else "", p.brand, p.pack_size, p.mrp, p.discount_type,
            p.discount_value, p.stock_qty, p.low_stock_threshold, p.short_description, p.description, p.ingredients, p.how_to_use,
            p.fssai, p.video_id, ", ".join(p.tags or []), "yes" if p.is_active else "no", "yes" if p.is_bestseller else "no",
            "|".join(i.url for i in p.images)]])
    return buf.getvalue()


def _truthy(value: str, default=True) -> bool:
    v = (value or "").strip().lower()
    if not v:
        return default
    return v in ("1", "yes", "y", "true", "on")


class ImportResult:
    def __init__(self):
        self.errors: list[str] = []
        self.created = self.updated = 0


def import_csv(raw: bytes, *, create_categories: bool, default_stock: int) -> ImportResult:
    res = ImportResult()
    if len(raw) > MAX_BYTES:
        res.errors.append("The file is larger than 2 MB.")
        return res
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        res.errors.append("The file is not UTF-8 text. In Excel choose “CSV UTF-8” when saving.")
        return res
    rows = list(csv.reader(io.StringIO(text)))
    if not rows or len(rows) < 2:
        res.errors.append("The file has no product rows.")
        return res
    if len(rows) - 1 > MAX_ROWS:
        res.errors.append(f"Too many rows. Import at most {MAX_ROWS} products at a time.")
        return res
    head = [ALIASES.get(h.strip().lower().replace(" ", "_"), h.strip().lower().replace(" ", "_")) for h in rows[0]]
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
        have = {i.url for i in p.images}
        for url in plan["urls"]:
            if url not in have:
                p.images.append(ProductImage(url=url, alt=p.name, sort_order=len(p.images), is_primary=not p.images))
        res.created += is_new
        res.updated += not is_new
    return res
