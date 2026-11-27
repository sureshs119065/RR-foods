"""Seed data and the importer for the existing product CSV (the data the old site used).

Every function is idempotent: running it twice does not create duplicates.
"""
import csv
import os
import re
import secrets
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

from sqlalchemy import func, select

from .extensions import db
from .models import (
    Category, Coupon, DeliveryZone, HeaderBanner, Offer, Product, ProductImage, SiteSetting, User,
)
from .models.base import utcnow
from .security import hash_password

SEED_DIR = Path(__file__).parent / "seed_data"


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "item"


def _unique_slug(model, base: str) -> str:
    slug, n = base, 2
    while db.session.scalar(select(model.id).where(model.slug == slug)):
        slug, n = f"{base}-{n}", n + 1
    return slug


def _num(value: str):
    value = (value or "").strip()
    return int(float(value)) if value else None


def get_or_create_category(name: str, sort_order: int = 0) -> Category:
    cat = db.session.scalar(select(Category).where(func.lower(Category.name) == name.lower()))
    if cat:
        return cat
    cat = Category(name=name, slug=_unique_slug(Category, slugify(name)), sort_order=sort_order)
    db.session.add(cat)
    db.session.flush()
    return cat


def import_products_csv(path: str | Path | None = None, default_stock: int = 25) -> dict:
    """Load products from a CSV with the same columns as the old site (id,name,category,price,weight,image,...)."""
    if not path:
        raise ValueError("import_products_csv needs a path. The RR FOODS catalogue is app/seed_data/seed_products.csv "
                         "(use `flask import-rr-foods`).")
    path = Path(path)
    created = updated = 0
    with open(path, newline="", encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))
    for i, row in enumerate(rows):
        sku = (row.get("id") or "").strip()
        name = (row.get("name") or "").strip()
        if not sku or not name:
            continue
        price = Decimal((row.get("price") or "0").strip() or "0")
        if price < 0:
            raise ValueError(f"{sku}: price cannot be negative")
        tags = [t.strip() for t in (row.get("tags") or "").split(",") if t.strip()]
        in_stock = (row.get("inStock") or "TRUE").strip().upper() not in ("FALSE", "NO", "0")
        category = get_or_create_category((row.get("category") or "General").strip(), sort_order=i)

        product = db.session.scalar(select(Product).where(Product.sku == sku))
        is_new = product is None
        if is_new:
            product = Product(sku=sku, slug=_unique_slug(Product, slugify(name)), category_id=category.id)
            db.session.add(product)
        product.name = name
        product.category_id = category.id
        product.short_description = (row.get("shortDescription") or "").strip() or None
        product.ingredients = (row.get("ingredients") or "").strip() or None
        product.how_to_use = (row.get("howToUse") or "").strip() or None
        product.pack_size = (row.get("weight") or "").strip() or None
        product.fssai = (row.get("fssai") or "").strip() or None
        product.video_id = (row.get("videoId") or "").strip() or None
        product.mrp = price
        product.discount_type = product.discount_type or "none"
        product.discount_value = product.discount_value or Decimal(0)
        product.apply_pricing()
        if is_new:
            product.stock_qty = default_stock if in_stock else 0
        product.tags = [t for t in tags if t.lower() != "featured"]
        product.is_bestseller = any(t.lower() == "featured" for t in tags)
        product.nutrition = {
            k: _num(row.get(k, "")) for k in ("calories", "protein", "carbs", "fibre", "fat") if _num(row.get(k, "")) is not None
        }
        image = (row.get("image") or "").strip()
        if image and not any(img.url == image for img in product.images):
            product.images.append(ProductImage(url=image, alt=name, sort_order=len(product.images), is_primary=not product.images))
        created += is_new
        updated += not is_new
    db.session.commit()
    return {"created": created, "updated": updated}


def _user(email: str, name: str, role: str, password: str | None) -> tuple[User, str]:
    """Returns the user and a note to print: the new random password, or why no password is shown."""
    existing = db.session.scalar(select(User).where(func.lower(User.email) == email.lower()))
    if existing:
        return existing, "(account already existed, password not changed)"
    note = "(password from your .env file)"
    if not password:
        password = secrets.token_urlsafe(12)
        note = password
    user = User(email=email, name=name, role=role, password_hash=hash_password(password), email_verified_at=utcnow())
    db.session.add(user)
    return user, note


def seed_all() -> dict:
    """Creates 1 admin, 1 owner, 1 demo customer, categories, products, coupons, banners and settings."""
    out: dict = {"passwords": {}}

    for key, email_env, name, role, pw_env in [
        ("admin", "SEED_ADMIN_EMAIL", "Admin", "admin", "SEED_ADMIN_PASSWORD"),
        ("owner", "SEED_OWNER_EMAIL", "Shop Owner", "owner", "SEED_OWNER_PASSWORD"),
    ]:
        email = os.environ.get(email_env) or f"{key}@nurseskitchen.local"
        user, note = _user(email, name, role, os.environ.get(pw_env))
        out["passwords"][email] = note
    demo, note = _user("user@nurseskitchen.local", "Demo Customer", "user", os.environ.get("SEED_USER_PASSWORD"))
    out["passwords"]["user@nurseskitchen.local"] = note
    db.session.flush()

    from .admin.csvio import import_csv  # the 20 RR FOODS catalogue products (same loader as `flask import-rr-foods`)
    res = import_csv((SEED_DIR / "seed_products.csv").read_bytes(), create_categories=True, default_stock=0)
    if res.errors:
        raise ValueError("seed_products.csv: " + "; ".join(res.errors))
    out["products"] = {"created": res.created, "updated": res.updated}

    # No sample coupon, "Deal of the Day" / "Buy 1 Get 1" labels or promo banners are seeded: the client's only offers are the
    # 8% product discount (set per product in seed_products.csv) and the Rs 999 combo (see `flask seed-combo`).
    if not db.session.scalar(select(Offer).where(Offer.tag == "New Arrival")):
        db.session.add(Offer(name="New Arrival", tag="New Arrival", description="Label shown on products tagged 'New Arrival'"))

    # Sample serviceable pincodes (Coimbatore). Replace with your real delivery area.
    for pin in ("641001", "641002", "641003", "641004", "641005"):
        if not db.session.get(DeliveryZone, pin):
            db.session.add(DeliveryZone(pincode=pin, is_serviceable=True, eta_days=2, delivery_fee=0))

    settings = {
        "header_carousel_interval_ms": 5000,
        "header_carousel_autoplay": True,
        "header_carousel_transition": "slide",
        "header_carousel_max_banners": 5,
        "low_stock_default_threshold": 5,
    }
    for key, value in settings.items():
        if not db.session.get(SiteSetting, key):
            db.session.add(SiteSetting(key=key, value=value))

    out["header_banners"] = seed_header_banners()
    db.session.commit()
    return out


def seed_header_banners() -> int:
    """No sample banners are created. The client's offers are the 8% discount and the Rs 999 combo only;
    add real banners in Admin > Header banners when the client supplies them."""
    return 0
