"""Reads and validates the product form. Returns clean values plus friendly per-field errors."""
import re
from decimal import Decimal

from flask import request
from sqlalchemy import func, select

from ..extensions import db
from ..models import Category, Offer, Product, ProductVariant
from .helpers import checked, clean, clean_multiline, to_decimal, to_int

MAX_IMAGES = 10
NUTRITION_FIELDS = ("calories", "protein", "carbs", "fibre", "fat")
DISCOUNT_CHOICES = [("none", "No discount"), ("percent", "Percent off (%)"), ("flat", "Flat amount off (₹)")]


def form_ids(name: str) -> list[int]:
    return sorted({int(v) for v in request.form.getlist(name) if v.isdigit()})


def parse_specs(text: str, errors: dict) -> dict:
    specs = {}
    for n, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        if ":" not in line:
            errors["specifications"] = f"Line {n}: write it as  Name: Value  (for example  Shelf life: 6 months)."
            return {}
        key, value = (part.strip() for part in line.split(":", 1))
        if not key or not value or len(key) > 60 or len(value) > 200:
            errors["specifications"] = f"Line {n}: both the name (60 characters max) and the value (200 max) are needed."
            return {}
        specs[key] = value
    if len(specs) > 40:
        errors["specifications"] = "Use 40 specifications or fewer."
    return specs


def parse_tags(text: str, errors: dict) -> list[str]:
    tags = []
    for raw in re.split(r"[,\n]", text):
        tag = clean(raw, 30)
        if tag and tag.lower() not in [t.lower() for t in tags]:
            tags.append(tag)
    if len(tags) > 20:
        errors["tags"] = "Use 20 tags or fewer."
    return tags


def variant_rows_from_request() -> list[dict]:
    g = request.form.getlist
    cols = [g("variant_id"), g("variant_option_name"), g("variant_option_value"), g("variant_sku"),
            g("variant_mrp"), g("variant_price"), g("variant_stock")]
    n = max((len(c) for c in cols), default=0)
    rows = []
    for i in range(n):
        pick = lambda c: (c[i] if i < len(c) else "").strip()
        rows.append(dict(id=pick(cols[0]), option_name=pick(cols[1]), option_value=pick(cols[2]), sku=pick(cols[3]),
                         mrp=pick(cols[4]), price=pick(cols[5]), stock=pick(cols[6])))
    return rows


def parse_variants(rows: list[dict], product_sku: str, product_id: int | None, errors: dict) -> list[dict]:
    """Blank rows are skipped. Each used row needs a value and a price."""
    clean_rows = []
    seen_skus = set()
    for i, row in enumerate(rows, 1):
        # "Option" (Size/Colour) is only a label that comes pre-filled, so it does not count as a filled-in row
        if not any(row[k] for k in ("option_value", "sku", "mrp", "price", "stock")):
            continue
        key = f"variants"
        local: dict = {}
        name = clean(row["option_name"], 40) or "Option"
        value = clean(row["option_value"], 80)
        if not value:
            errors[key] = f"Variant row {i}: enter the option value (for example 500 g)."
            continue
        price = to_decimal(row["price"], "_", local, min_=Decimal(0), max_=Decimal(1_000_000))
        mrp = to_decimal(row["mrp"], "_", local, min_=Decimal(0), max_=Decimal(1_000_000), required=False, default=None)
        stock = to_int(row["stock"], "_", local, min_=0, max_=1_000_000, required=False, default=0)
        if "_" in local or price is None:
            errors[key] = f"Variant row {i}: price must be a number (0 or more), stock a whole number."
            continue
        if mrp is not None and mrp < price:
            errors[key] = f"Variant row {i}: the MRP cannot be lower than the price."
            continue
        sku = clean(row["sku"], 60) or f"{product_sku}-{len(clean_rows) + 1}"
        if sku.lower() in seen_skus:
            errors[key] = f"Variant row {i}: the SKU “{sku}” is used twice."
            continue
        seen_skus.add(sku.lower())
        clash = select(ProductVariant.id).where(func.lower(ProductVariant.sku) == sku.lower())
        if row["id"].isdigit():
            clash = clash.where(ProductVariant.id != int(row["id"]))
        if db.session.scalar(clash):
            errors[key] = f"Variant row {i}: the SKU “{sku}” already exists on another product."
            continue
        clean_rows.append(dict(id=int(row["id"]) if row["id"].isdigit() else None, option_name=name,
                               option_value=value, sku=sku, mrp=mrp, price=price, stock=stock))
    return clean_rows


def parse_product(product: Product | None):
    """Returns (data, errors). `data` holds values ready to assign to a Product."""
    f = request.form
    errors: dict[str, str] = {}

    name = clean(f.get("name"), 200)
    if len(name) < 2:
        errors["name"] = "Enter the product name (at least 2 characters)."

    sku = clean(f.get("sku"), 60).upper()
    if not sku:
        errors["sku"] = "Enter a SKU (a short unique code, for example P013)."
    elif not re.fullmatch(r"[A-Z0-9][A-Z0-9._\-]*", sku):
        errors["sku"] = "Use only letters, numbers, dot, dash and underscore."
    else:
        q = select(Product.id).where(func.upper(Product.sku) == sku)
        if product is not None:
            q = q.where(Product.id != product.id)
        if db.session.scalar(q):
            errors["sku"] = "This SKU is already used by another product."

    category = None
    cat_raw = f.get("category_id", "")
    if cat_raw.isdigit():
        category = db.session.get(Category, int(cat_raw))
    if category is None or category.is_deleted or category.parent_id is not None:
        errors["category_id"] = "Choose a category."
        category = None
    sub = None
    if f.get("subcategory_id", "").isdigit():
        sub = db.session.get(Category, int(f["subcategory_id"]))
        if sub is None or sub.is_deleted or category is None or sub.parent_id != category.id:
            errors["subcategory_id"] = "Choose a subcategory that belongs to the selected category."
            sub = None

    mrp = to_decimal(f.get("mrp"), "mrp", errors, min_=Decimal("0.01"), max_=Decimal(1_000_000))
    dtype = f.get("discount_type", "none")
    if dtype not in ("none", "percent", "flat"):
        errors["discount_type"] = "Choose a discount type."
        dtype = "none"
    dval = Decimal(0)
    if dtype != "none":
        dval = to_decimal(f.get("discount_value"), "discount_value", errors,
                          min_=Decimal(0), max_=Decimal(100) if dtype == "percent" else Decimal(1_000_000))
        if dval is not None and dtype == "percent" and dval > 100:
            errors["discount_value"] = "A percentage discount cannot be more than 100."
        if dval is not None and dtype == "flat" and mrp is not None and dval > mrp:
            errors["discount_value"] = "A flat discount cannot be more than the MRP (the price would be negative)."
        dval = dval if dval is not None else Decimal(0)

    stock = to_int(f.get("stock_qty"), "stock_qty", errors, min_=0, max_=1_000_000, required=False, default=0)
    low = to_int(f.get("low_stock_threshold"), "low_stock_threshold", errors, min_=0, max_=100_000, required=False, default=5)

    video = clean(f.get("video_id"), 20)
    if video and not re.fullmatch(r"[A-Za-z0-9_-]{11}", video):
        errors["video_id"] = "A YouTube video id has 11 letters, numbers, dashes or underscores (the part after v= in the link)."

    nutrition = {}
    for key in NUTRITION_FIELDS:
        raw = (f.get(f"nutrition_{key}") or "").strip()
        if raw:
            val = to_decimal(raw, f"nutrition_{key}", errors, min_=Decimal(0), max_=Decimal(100_000))
            if val is not None:
                nutrition[key] = float(val) if val % 1 else int(val)

    specs = parse_specs(clean_multiline(f.get("specifications"), 6000), errors)
    tags = parse_tags(f.get("tags", ""), errors)

    offer_ids = [i for i in form_ids("offer_ids") if db.session.get(Offer, i)]
    related_ids = [i for i in form_ids("related_ids") if (product is None or i != product.id) and db.session.get(Product, i)]

    variants = parse_variants(variant_rows_from_request(), sku or "SKU", product.id if product else None, errors)

    data = dict(
        name=name, sku=sku, brand=clean(f.get("brand"), 120) or None, category=category, subcategory=sub,
        pack_size=clean(f.get("pack_size"), 40) or None,
        short_description=clean(f.get("short_description"), 300) or None,
        description=clean_multiline(f.get("description"), 5000) or None,
        ingredients=clean_multiline(f.get("ingredients"), 2000) or None,
        how_to_use=clean_multiline(f.get("how_to_use"), 2000) or None,
        fssai=clean(f.get("fssai"), 30) or None, video_id=video or None,
        mrp=mrp, discount_type=dtype, discount_value=dval, stock_qty=stock, low_stock_threshold=low,
        tags=tags, specifications=specs, nutrition=nutrition,
        is_active=checked("is_active"), is_bestseller=checked("is_bestseller"),
        offer_ids=offer_ids, related_ids=related_ids, variants=variants,
    )
    return data, errors


def values_from_request() -> dict:
    """Raw strings, so a form with errors comes back exactly as typed."""
    f = request.form
    keys = ["name", "sku", "brand", "category_id", "subcategory_id", "pack_size", "short_description", "description", "ingredients",
            "how_to_use", "fssai", "video_id", "mrp", "discount_type", "discount_value", "stock_qty", "low_stock_threshold",
            "tags", "specifications"] + [f"nutrition_{k}" for k in NUTRITION_FIELDS]
    values = {k: f.get(k, "") for k in keys}
    values.update(is_active=checked("is_active"), is_bestseller=checked("is_bestseller"),
                  offer_ids=form_ids("offer_ids"), related_ids=form_ids("related_ids"), variants=variant_rows_from_request())
    return values


def values_from_product(p: Product | None) -> dict:
    if p is None:
        return dict(name="", sku="", brand="", category_id="", subcategory_id="", pack_size="", short_description="", description="",
                    ingredients="", how_to_use="", fssai="", video_id="", mrp="", discount_type="none", discount_value="0",
                    stock_qty="0", low_stock_threshold="5", tags="", specifications="", is_active=True, is_bestseller=False,
                    offer_ids=[], related_ids=[], variants=[], **{f"nutrition_{k}": "" for k in NUTRITION_FIELDS})
    values = dict(
        name=p.name, sku=p.sku, brand=p.brand or "", category_id=p.category_id, subcategory_id=p.subcategory_id or "",
        pack_size=p.pack_size or "", short_description=p.short_description or "", description=p.description or "",
        ingredients=p.ingredients or "", how_to_use=p.how_to_use or "", fssai=p.fssai or "", video_id=p.video_id or "",
        mrp=p.mrp, discount_type=p.discount_type, discount_value=p.discount_value, stock_qty=p.stock_qty,
        low_stock_threshold=p.low_stock_threshold, tags=", ".join(p.tags or []),
        specifications="\n".join(f"{k}: {v}" for k, v in (p.specifications or {}).items()),
        is_active=p.is_active, is_bestseller=p.is_bestseller, offer_ids=[o.id for o in p.offers],
        related_ids=[r.id for r in p.related],
        variants=[dict(id=v.id, option_name=v.option_name, option_value=v.option_value, sku=v.sku, mrp=v.mrp or "", price=v.price, stock=v.stock_qty)
                  for v in p.variants],
    )
    for k in NUTRITION_FIELDS:
        values[f"nutrition_{k}"] = (p.nutrition or {}).get(k, "")
    return values
