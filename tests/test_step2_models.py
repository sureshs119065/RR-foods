from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.models import (
    Category, CartItem, Coupon, HeaderBanner, Product, User, WishlistItem, SiteSetting,
)
from app.models.base import utcnow
from app.security import hash_password, verify_password
from app.seed import import_products_csv, seed_all


def make_category(session, name="Snacks"):
    c = Category(name=name, slug=name.lower())
    session.add(c)
    session.flush()
    return c


def make_product(session, **kw):
    cat = kw.pop("category", None) or make_category(session)
    p = Product(sku=kw.pop("sku", "T1"), slug=kw.pop("slug", "t1"), name=kw.pop("name", "Test"),
                category_id=cat.id, mrp=kw.pop("mrp", Decimal("100")), final_price=kw.pop("final_price", Decimal("100")), **kw)
    session.add(p)
    session.flush()
    return p


def make_user(session, email="a@x.com", role="user"):
    u = User(email=email, name="A", role=role, password_hash=hash_password("pw-12345"))
    session.add(u)
    session.flush()
    return u


# ---------- schema ----------
def test_all_expected_tables_exist(session):
    names = set(session.execute(text("select tablename from pg_tables where schemaname='public'")).scalars())
    required = {
        "users", "addresses", "categories", "products", "product_images", "product_variants", "offers", "coupons",
        "cart_items", "wishlist", "orders", "order_items", "order_status_history", "payments", "reviews",
        "inventory_logs", "banners", "notifications", "audit_logs", "header_banners",
    }
    assert required <= names


def test_search_indexes_exist_and_trigram_search_tolerates_typos(session):
    idx = set(session.execute(text("select indexname from pg_indexes where tablename='products'")).scalars())
    assert {"ix_products_fts", "ix_products_name_trgm", "ix_products_category_price", "ix_products_name_lower"} <= idx
    make_product(session, name="Millet Soup Mix")
    hit = session.execute(text("select name from products where similarity(name, 'milet sop mix') > 0.3")).scalars().all()
    assert hit == ["Millet Soup Mix"]


# ---------- pricing ----------
@pytest.mark.parametrize("dtype,dval,expected,pct", [
    ("none", 0, "200.00", 0), ("percent", 25, "150.00", 25), ("flat", 50, "150.00", 25), ("flat", 500, "0.00", 100),
])
def test_final_price_calculation(dtype, dval, expected, pct):
    p = Product(mrp=Decimal("200"), discount_type=dtype, discount_value=Decimal(dval))
    p.apply_pricing()
    assert p.final_price == Decimal(expected)
    assert p.discount_percent == pct


# ---------- constraints ----------
@pytest.mark.parametrize("kw", [
    dict(mrp=Decimal("-1")),
    dict(final_price=Decimal("-1")),
    dict(stock_qty=-1),
    dict(discount_type="percent", discount_value=Decimal("101")),
    dict(discount_type="flat", discount_value=Decimal("-5")),
    dict(discount_type="bogus"),
])
def test_product_validation_rules_are_enforced_by_the_database(session, kw):
    with pytest.raises(IntegrityError):
        make_product(session, **kw)
    session.rollback()


def test_duplicate_sku_and_slug_rejected(session):
    cat = make_category(session)
    make_product(session, category=cat)
    with pytest.raises(IntegrityError):
        make_product(session, category=cat, slug="other")
    session.rollback()


def test_email_unique_case_insensitive_and_role_checked(session):
    make_user(session, "Person@Example.com")
    with pytest.raises(IntegrityError):
        make_user(session, "person@example.com")
    session.rollback()
    with pytest.raises(IntegrityError):
        make_user(session, "z@z.com", role="superuser")
    session.rollback()


def test_cart_unique_per_user_product_even_without_variant(session):
    u, p = make_user(session), make_product(session)
    session.add(CartItem(user_id=u.id, product_id=p.id, quantity=1))
    session.flush()
    session.add(CartItem(user_id=u.id, product_id=p.id, quantity=2))
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()


def test_wishlist_unique_and_cascade_delete(session):
    u, p = make_user(session), make_product(session)
    session.add(WishlistItem(user_id=u.id, product_id=p.id))
    session.flush()
    session.add(WishlistItem(user_id=u.id, product_id=p.id))
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()


def test_coupon_rules(session):
    session.add(Coupon(code="SAVE10", discount_type="percent", discount_value=10))
    session.flush()
    session.add(Coupon(code="save10", discount_type="flat", discount_value=5))
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()
    session.add(Coupon(code="BAD", discount_type="percent", discount_value=150))
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()


def test_header_banner_window_must_end_after_start(session):
    now = utcnow()
    session.add(HeaderBanner(title="x", link_type="url", start_at=now, end_at=now - timedelta(hours=1)))
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()
    session.add(HeaderBanner(title="x", link_type="page"))
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()


# ---------- soft delete ----------
def test_archive_and_restore(session):
    p = make_product(session)
    p.archive()
    session.flush()
    assert p.is_deleted and p.deleted_at is not None
    p.restore()
    assert not p.is_deleted and p.deleted_at is None


# ---------- passwords ----------
def test_password_hash_verify():
    h = hash_password("correct horse")
    assert h.startswith("$argon2")
    assert verify_password(h, "correct horse")
    assert not verify_password(h, "wrong")
    assert not verify_password("not-a-hash", "x")


# ---------- seed ----------
def test_seed_creates_expected_data_and_is_idempotent(session):
    first = seed_all()
    counts = lambda: (
        session.scalar(select(text("count(*)")).select_from(text("users"))),
        session.scalar(select(text("count(*)")).select_from(text("products"))),
        session.scalar(select(text("count(*)")).select_from(text("header_banners"))),
        session.scalar(select(text("count(*)")).select_from(text("categories"))),
    )
    c1 = counts()
    assert c1 == (3, 12, 4, 5)  # users, products, header banners, categories
    assert session.scalar(select(text("count(*)")).select_from(text("users")).where(text("role='admin'"))) == 1
    assert session.scalar(select(text("count(*)")).select_from(text("users")).where(text("role='owner'"))) == 1
    assert len(first["passwords"]) == 3
    seed_all()
    assert counts() == c1
    assert session.get(SiteSetting, "header_carousel_interval_ms").value == 5000
    millet = session.scalar(select(Product).where(Product.sku == "P001"))
    assert millet.is_bestseller and millet.final_price == Decimal("180.00") and millet.nutrition["calories"] == 310
    sold_out = session.scalar(select(Product).where(Product.stock_qty == 0))
    assert sold_out is not None  # CSV rows with inStock FALSE start at 0 stock


def test_csv_import_rejects_negative_price(session, tmp_path):
    bad = tmp_path / "bad.csv"
    bad.write_text("id,name,category,price\nB1,Bad,Snacks,-5\n", encoding="utf-8")
    with pytest.raises(ValueError):
        import_products_csv(bad)
    session.rollback()
