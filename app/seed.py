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
    path = Path(path) if path else SEED_DIR / "products.csv"
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

    out["products"] = import_products_csv()

    # Sample coupon and offer labels (edit or delete in the admin panel in Step 4)
    if not db.session.scalar(select(Coupon).where(func.upper(Coupon.code) == "WELCOME10")):
        db.session.add(Coupon(code="WELCOME10", description="Sample: 10% off your first order", discount_type="percent",
                              discount_value=10, min_cart_value=299, per_user_limit=1, usage_limit=1000))
    for tag in ("Deal of the Day", "Buy 1 Get 1", "New Arrival"):
        if not db.session.scalar(select(Offer).where(Offer.tag == tag)):
            db.session.add(Offer(name=tag, tag=tag, description=f"Label shown on products tagged '{tag}'"))

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
    now = utcnow()
    samples = [
        dict(title="Diwali Mega Sale", subtitle="Festival offers on sweets and snacks", badge_text="FESTIVAL",
             bg_color="#7a1f3d", button_text="Shop festival offers", link_type="category", link_target="sweets",
             start_at=now - timedelta(days=1), end_at=now + timedelta(days=12), countdown_enabled=True),
        dict(title="Today's Special", subtitle="Freshly packed breakfast mixes", badge_text="TODAY",
             bg_color="#1b5e3b", button_text="See today's special", link_type="category", link_target="breakfast"),
        dict(title="Flash Sale", subtitle="Ends soon. Prices drop for a few hours", badge_text="FLASH SALE",
             bg_color="#b4234f", button_text="Grab the deal", link_type="url", link_target="/shop?sort=price-asc",
             start_at=now - timedelta(hours=1), end_at=now + timedelta(hours=6), countdown_enabled=True),
        dict(title="Extra 10% off with coupon", subtitle="Use code WELCOME10 on orders above 299", badge_text="COUPON",
             bg_color="#0f3d27", button_text="Copy offer", link_type="coupon", link_target="WELCOME10"),
    ]
    added = 0
    for i, data in enumerate(samples):
        if db.session.scalar(select(HeaderBanner.id).where(HeaderBanner.title == data["title"])):
            continue
        db.session.add(HeaderBanner(sort_order=i, text_color="#ffffff", **data))
        added += 1
    return added
