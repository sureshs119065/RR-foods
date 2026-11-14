import re
from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.extensions import db
from app.models import (
    Address, AuditLog, CartItem, Category, Coupon, CouponUsage, DeliveryZone, HeaderBanner, InventoryLog, Notification, Order, OrderStatusHistory,
    Product, ProductVariant, SiteSetting,
)
from app.models.base import utcnow
from app.services import header_banners
from tests.helpers import checkout_post, checkout_token, make_user, post, sign_in, token
from tests.test_step2_models import make_category, make_product

JSON = {"Accept": "application/json"}


def mk(session, cat, n, **kw):
    kw.setdefault("name", f"Item {n}")
    return make_product(session, category=cat, sku=f"S{n}", slug=f"item-{n}", **kw)


@pytest.fixture()
def catalog(session):
    cat = make_category(session, "Snacks")
    p = mk(session, cat, 1, name="Millet Soup Mix", stock_qty=10, final_price=Decimal("80"), mrp=Decimal("100"), brand="Kitchen", pack_size="200 g")
    session.add(DeliveryZone(pincode="641001", is_serviceable=True, eta_days=2, delivery_fee=40))
    session.add(DeliveryZone(pincode="600001", is_serviceable=False))
    session.commit()
    return cat, p


@pytest.fixture()
def cust(app, session, catalog):
    user = make_user(session, "user")
    c = app.test_client()
    sign_in(c, "user")
    session.add(Address(user_id=user.id, label="Home", full_name="Asha Rao", phone="9876543210", line1="12 Lake Road", city="Coimbatore",
                        state="Tamil Nadu", pincode="641001", is_default=True))
    session.commit()
    c.user = user
    return c


def pj(c, url, data=None, page="/"):
    return c.post(url, data={**(data or {}), "csrf_token": token(c, page)}, headers=JSON)


def add(c, product, qty=1, variant=None):
    return pj(c, "/cart/add", {"product_id": product.id, "qty": qty, **({"variant_id": variant.id} if variant else {})})


def address_id(session, user):
    return session.scalar(select(Address.id).where(Address.user_id == user.id))


def checkout(c, session, user, method="upi_manual", **extra):
    return checkout_post(c, {"address_id": address_id(session, user), "method": method, **extra}, page="/")


# ================================================================ public pages
def test_public_pages_render_and_have_no_inline_code(app, session, catalog):
    _, p = catalog
    c = app.test_client()
    for url in ("/", "/shop", f"/product/{p.slug}", "/offers", "/category/snacks", "/shop?category=snacks", "/offline", "/login", "/register"):
        r = c.get(url)
        assert r.status_code == 200, url
        html = r.get_data(as_text=True)
        assert " style=" not in html and "onclick=" not in html and "<script>" not in html, url  # the CSP would silently block them
    assert c.get("/manifest.webmanifest").get_json()["start_url"] == "/"
    assert "javascript" in c.get("/sw.js").content_type
    assert "Disallow: /admin" in c.get("/robots.txt").get_data(as_text=True)
    assert f"/product/{p.slug}" in c.get("/sitemap.xml").get_data(as_text=True)
    assert c.get("/static/img/icon-192.png").status_code == 200


def test_hidden_archived_and_unknown_things_are_404(app, session, catalog):
    cat, p = catalog
    hidden = mk(session, cat, 2, is_active=False)
    gone = mk(session, cat, 3)
    gone.archive()
    session.commit()
    c = app.test_client()
    assert c.get(f"/product/{hidden.slug}").status_code == 404
    assert c.get(f"/product/{gone.slug}").status_code == 404
    assert c.get("/product/nope").status_code == 404
    assert c.get("/shop?category=nope").status_code == 404
    listing = c.get("/shop").get_data(as_text=True)
    assert p.name in listing and hidden.name not in listing and gone.name not in listing
    assert gone.slug not in c.get("/sitemap.xml").get_data(as_text=True)


def test_product_page_content_and_seo(app, session, catalog):
    cat, p = catalog
    p.specifications = {"Shelf life": "6 months"}
    p.short_description = "Warm and filling."
    session.add(ProductVariant(product_id=p.id, option_name="Weight", option_value="500 g", sku="S1-500", price=Decimal("150"), mrp=Decimal("180"), stock_qty=2))
    session.commit()
    html = app.test_client().get(f"/product/{p.slug}").get_data(as_text=True)
    for needle in ("Millet Soup Mix", "20% off", "Shelf life", "6 months", "500 g", "Check", '"@type": "Product"', 'rel="canonical"', "application/ld+json", "Frequently" if False else "Ratings"):
        assert needle in html, needle
    assert "name=\"variant_id\"" in html and 'data-price="150.00"' in html




def test_shop_all_and_bestsellers_are_separate_admin_controlled_pages(app, session, catalog):
    cat, _ = catalog
    manual = mk(session, cat, 200, name="Manual Bestseller", sales_count=0, is_bestseller=True)
    regular = mk(session, cat, 201, name="Regular Product", sales_count=500, is_bestseller=False)
    session.commit()

    c = app.test_client()
    shop_html = c.get("/shop").get_data(as_text=True)
    best_html = c.get("/bestsellers").get_data(as_text=True)
    assert "Shop All Products" in shop_html
    assert "Manual Bestseller" in shop_html and "Regular Product" in shop_html
    assert "Our Bestsellers" in best_html
    assert "Manual Bestseller" in best_html
    assert "Regular Product" not in best_html
    assert c.get("/shop?bestsellers=1").status_code == 200  # ignored legacy parameter; /shop remains Shop All


def test_carousel_hidden_without_banners_and_single_banner_has_no_controls(app, session, catalog):
    header_banners.bust_cache()
    c = app.test_client()
    assert "data-hc" not in c.get("/").get_data(as_text=True)
    session.add(HeaderBanner(title="Only One", bg_color="#1b5e3b", text_color="#ffffff", link_type="url", link_target="/shop"))
    session.commit()
    header_banners.bust_cache()
    html = c.get("/").get_data(as_text=True)
    assert "Only One" in html and 'data-autoplay="0"' in html and "data-hc-prev" not in html and "data-hc-dot" not in html
    header_banners.bust_cache()


def test_css_cannot_be_injected_through_banner_colours(app, session, catalog):
    session.add(HeaderBanner(title="Evil", bg_color="red;}a{b:", text_color="#fff", link_type="url", link_target="/shop"))
    session.commit()
    header_banners.bust_cache()
    css = app.test_client().get("/banner-colors.css").get_data(as_text=True)
    assert "a{b:" not in css and "#1b5e3b" in css  # falls back to the default
    header_banners.bust_cache()


# ================================================================ search, filters, sort
@pytest.fixture()
def many(session, catalog):
    cat, p = catalog
    mk(session, cat, 2, name="Rice Idli Podi", final_price=Decimal("50"), mrp=Decimal("50"), stock_qty=0, brand="Amma", avg_rating=Decimal("4.5"), review_count=10, sales_count=50)
    mk(session, cat, 3, name="Ragi Cookies", final_price=Decimal("120"), mrp=Decimal("200"), stock_qty=5, brand="Amma", avg_rating=Decimal("3.2"), review_count=4, sales_count=5)
    sub = Category(name="Sweets", slug="sweets", parent_id=cat.id)
    session.add(sub)
    session.flush()
    q = mk(session, cat, 4, name="Jaggery Laddu", final_price=Decimal("300"), mrp=Decimal("300"), stock_qty=3, brand="Kitchen")
    q.subcategory_id = sub.id
    session.commit()
    return cat


def names(c, qs):
    html = c.get("/shop" + qs).get_data(as_text=True)
    return [n for n in ("Millet Soup Mix", "Rice Idli Podi", "Ragi Cookies", "Jaggery Laddu") if n in html and f'pc__name">{n}' in html]


def order_of(c, qs):
    html = c.get("/shop" + qs).get_data(as_text=True)
    found = [(html.index(f'pc__name">{n}'), n) for n in ("Millet Soup Mix", "Rice Idli Podi", "Ragi Cookies", "Jaggery Laddu") if f'pc__name">{n}' in html]
    return [n for _, n in sorted(found)]


def test_search_is_typo_tolerant_and_literal(app, many):
    c = app.test_client()
    assert names(c, "?q=millet") == ["Millet Soup Mix"]
    assert names(c, "?q=milet+sop") == ["Millet Soup Mix"]       # typos
    assert names(c, "?q=RAGI") == ["Ragi Cookies"]               # any case
    assert names(c, "?q=amma") == ["Rice Idli Podi", "Ragi Cookies"] or set(names(c, "?q=amma")) == {"Rice Idli Podi", "Ragi Cookies"}  # brand
    assert names(c, "?q=%25") == [] and names(c, "?q=zzzzqq") == []
    assert "No products match your filters" in c.get("/shop?q=zzzzqq").get_data(as_text=True)
    assert c.get("/shop?q=" + "a" * 500).status_code == 200


def test_filters(app, many):
    c = app.test_client()
    assert set(names(c, "?avail=1")) == {"Millet Soup Mix", "Ragi Cookies", "Jaggery Laddu"}
    assert set(names(c, "?min_price=100&max_price=200")) == {"Ragi Cookies"}
    assert set(names(c, "?brand=Amma")) == {"Rice Idli Podi", "Ragi Cookies"}
    assert set(names(c, "?brand=Amma&brand=Kitchen")) == {"Millet Soup Mix", "Rice Idli Podi", "Ragi Cookies", "Jaggery Laddu"}
    assert set(names(c, "?rating=4")) == {"Rice Idli Podi"}
    assert set(names(c, "?discount=30")) == {"Ragi Cookies"}          # 40% off
    assert set(names(c, "?discount=20")) == {"Millet Soup Mix", "Ragi Cookies"}
    assert set(names(c, "?category=sweets")) == {"Jaggery Laddu"}
    assert set(names(c, "?category=snacks")) == {"Millet Soup Mix", "Rice Idli Podi", "Ragi Cookies", "Jaggery Laddu"}  # parent includes child items
    assert set(names(c, "?avail=1&brand=Amma&min_price=100")) == {"Ragi Cookies"}
    for junk in ("?min_price=abc", "?max_price=-5", "?rating=99", "?discount=zzz", "?page=-3", "?page=99999", "?sort=drop", "?brand=" + "x" * 300):
        assert c.get("/shop" + junk).status_code == 200, junk


def test_sorting(app, many):
    c = app.test_client()
    assert order_of(c, "?sort=price-asc") == ["Rice Idli Podi", "Millet Soup Mix", "Ragi Cookies", "Jaggery Laddu"]
    assert order_of(c, "?sort=price-desc") == ["Jaggery Laddu", "Ragi Cookies", "Millet Soup Mix", "Rice Idli Podi"]
    assert order_of(c, "?sort=popular")[0] == "Rice Idli Podi"
    assert order_of(c, "?sort=rating")[:2] == ["Rice Idli Podi", "Ragi Cookies"]
    assert order_of(c, "?sort=discount")[0] == "Ragi Cookies"
    assert order_of(c, "?sort=newest")[0] == "Jaggery Laddu"


def test_pagination(app, session, catalog):
    cat, _ = catalog
    for i in range(10, 40):
        mk(session, cat, i, name=f"Bulk {i}")
    session.commit()
    c = app.test_client()
    from app.services.storefront import PER_PAGE
    pages = -(-31 // PER_PAGE)                         # 1 catalogue item + 30 bulk items
    assert f"Page 1 of {pages}" in c.get("/shop").get_data(as_text=True)
    assert f"Page 2 of {pages}" in c.get("/shop?page=2").get_data(as_text=True)


def test_suggest_and_pincode_apis(app, many):
    c = app.test_client()
    d = c.get("/api/suggest?q=milet").get_json()
    assert d["products"][0]["name"] == "Millet Soup Mix" and d["products"][0]["url"] == "/product/item-1"
    assert c.get("/api/suggest?q=sn").get_json()["categories"][0]["name"] == "Snacks"
    short = c.get("/api/suggest?q=a").get_json()      # too short to search: the popular picks are offered instead
    assert short["popular"] is True and "products" in short and "categories" in short
    ok = c.get("/api/pincode/641001").get_json()
    assert ok["deliverable"] and ok["eta_days"] == 2 and ok["fee"] == 40
    assert c.get("/api/pincode/600001").get_json()["deliverable"] is False
    assert c.get("/api/pincode/999999").get_json()["deliverable"] is False
    assert c.get("/api/pincode/12ab").status_code in (404, 422)


def test_recently_viewed_you_may_like_and_bought_together(app, session, many, cust):
    cat = many
    a, b, c3 = (session.scalar(select(Product).where(Product.slug == f"item-{i}")) for i in (1, 3, 4))
    c = app.test_client()
    c.get(f"/product/{b.slug}")
    html = c.get(f"/product/{a.slug}").get_data(as_text=True)
    assert "You may also like" in html
    home = c.get("/").get_data(as_text=True)          # recently viewed lives on the home page
    assert "Recently viewed" in home and "Ragi Cookies" in home
    # "bought together": two past orders contained a + b
    from tests.test_step5_owner import mk_order
    for i in (1, 2):
        o = mk_order(session, cust.user, a, number=f"NK-T{i}")
        o.items.append(__import__("app.models", fromlist=["OrderItem"]).OrderItem(product_id=b.id, name=b.name, unit_price=1, mrp=1, quantity=1, line_total=1))
    session.commit()
    from app.services import recommendations as _rec
    _rec._CACHE.clear()
    def fbt(slug):
        html = app.test_client().get(f"/product/{slug}").get_data(as_text=True)
        return html.split('id="fbt-h"')[1].split("</section>")[0] if 'id="fbt-h"' in html else ""
    assert "Ragi Cookies" in fbt(a.slug)
    rej = mk_order(session, cust.user, a, number="NK-T9", status="rejected")
    rej.items.append(__import__("app.models", fromlist=["OrderItem"]).OrderItem(product_id=c3.id, name=c3.name, unit_price=1, mrp=1, quantity=1, line_total=1))
    session.commit()
    from app.services import recommendations as rec   # the section also fills up from the same category, so check the co-purchase data itself
    rec._CACHE.clear()                                  # results are cached for six hours; start fresh
    with app.app_context():
        related = rec._related_ids(a.id, 12)
    assert b.id in related and c3.id not in related   # rejected orders do not count




def test_listing_filters_and_pagination_are_shareable_and_preserved(app, session, catalog):
    cat, _ = catalog
    mk(session, cat, 301, name="Low Price Product", final_price=Decimal("40"), mrp=Decimal("50"),
       avg_rating=Decimal("4.5"), review_count=8, sales_count=4)
    mk(session, cat, 302, name="High Price Product", final_price=Decimal("140"), mrp=Decimal("150"),
       avg_rating=Decimal("5.0"), review_count=0, sales_count=10)
    for n in range(303, 315):
        mk(session, cat, n, name=f"Page Product {n}", final_price=Decimal("80"), mrp=Decimal("90"),
           avg_rating=Decimal("4.2"), review_count=1)
    session.commit()

    c = app.test_client()
    response = c.get("/shop?min_price=30&max_price=100&rating=4&sort=price-asc")
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "Low Price Product" in html
    assert "High Price Product" not in html
    assert 'name="min_price"' in html and 'value="30"' in html
    assert 'name="max_price"' in html and 'value="100"' in html
    assert 'value="4" checked' in html
    assert "Page 1 of" in html

    best = c.get("/bestsellers?min_price=30&sort=price-desc")
    assert best.status_code == 200
    assert "Our Bestsellers" in best.get_data(as_text=True)


# ================================================================ cart
def test_guest_and_staff_cannot_use_the_cart(app, session, catalog):
    _, p = catalog
    g = app.test_client()
    r = g.post("/cart/add", data={"product_id": p.id, "csrf_token": token(g, "/login")}, headers=JSON)
    assert r.status_code == 401 and r.get_json()["login"].startswith("/login?next=")
    r = g.post("/cart/add", data={"product_id": p.id, "csrf_token": token(g, "/login"), "next": f"/product/{p.slug}"})
    assert r.status_code == 302 and r.headers["Location"].startswith("/login")
    assert g.get("/cart").status_code == 302
    for role in ("owner", "admin"):
        make_user(session, role)
        s = app.test_client()
        sign_in(s, role)
        assert s.get("/cart").status_code == 403 and s.get("/checkout").status_code == 403
        assert s.post("/cart/add", data={"product_id": p.id, "csrf_token": token(s, "/")}, headers=JSON).status_code == 403


def test_add_increase_clamp_and_count(cust, session, catalog):
    _, p = catalog
    r = add(cust, p, 2)
    assert r.status_code == 200 and r.get_json()["count"] == 2
    add(cust, p, 3)
    assert session.scalar(select(CartItem.quantity)) == 5
    r = add(cust, p, 10)  # stock is 10, line max is 10
    assert r.get_json()["count"] == 10 and "at most 10" in r.get_json()["message"]
    p.stock_qty = 4
    session.commit()
    r = add(cust, p, 1)
    assert session.scalar(select(CartItem.quantity)) == 4 and "at most 4" in r.get_json()["message"]
    assert session.scalar(select(func.count(CartItem.id))) == 1


@pytest.mark.parametrize("qty", ["0", "-1", "11", "x", "1.5", ""])
def test_add_rejects_bad_quantity(cust, session, catalog, qty):
    _, p = catalog
    r = cust.post("/cart/add", data={"product_id": p.id, "qty": qty, "csrf_token": token(cust, "/")}, headers=JSON)
    assert r.status_code == (200 if qty == "" else 422)  # empty means 1
    assert session.scalar(select(func.count(CartItem.id))) == (1 if qty == "" else 0)


def test_cannot_add_unavailable_or_wrong_things(cust, session, catalog):
    cat, p = catalog
    out = mk(session, cat, 5, stock_qty=0)
    hidden = mk(session, cat, 6, is_active=False)
    other = mk(session, cat, 7)
    v_other = ProductVariant(product_id=other.id, option_name="Size", option_value="L", sku="S7-L", price=Decimal("5"), stock_qty=5)
    v = ProductVariant(product_id=p.id, option_name="Weight", option_value="1 kg", sku="S1-1K", price=Decimal("150"), stock_qty=0)
    session.add_all([v_other, v])
    session.commit()
    assert add(cust, out).status_code == 409
    assert add(cust, hidden).status_code == 409
    assert add(cust, p).status_code == 409                       # has options, none chosen
    assert add(cust, p, variant=v_other).status_code == 409      # option of another product
    assert add(cust, p, variant=v).status_code == 409            # option out of stock
    assert pj(cust, "/cart/add", {"product_id": 999999}).status_code == 409
    assert pj(cust, "/cart/add", {"product_id": other.id, "variant_id": 12345}).status_code == 409
    assert session.scalar(select(func.count(CartItem.id))) == 0


def test_variant_prices_and_stock_come_from_the_variant(cust, session, catalog):
    _, p = catalog
    v = ProductVariant(product_id=p.id, option_name="Weight", option_value="1 kg", sku="S1-1K", price=Decimal("150"), mrp=Decimal("180"), stock_qty=3)
    session.add(v)
    session.commit()
    assert add(cust, p, 5, variant=v).get_json()["count"] == 3
    html = cust.get("/cart").get_data(as_text=True)
    assert "₹150.00" in html and "Weight: 1 kg" in html and "₹450.00" in html


def test_cart_quantity_remove_and_save_for_later(cust, session, catalog):
    _, p = catalog
    add(cust, p, 2)
    item = session.scalar(select(CartItem))
    post(cust, f"/cart/{item.id}/qty", {"action": "inc"}, page="/cart")
    session.expire_all(); assert session.get(CartItem, item.id).quantity == 3
    post(cust, f"/cart/{item.id}/qty", {"action": "dec"}, page="/cart")
    session.expire_all(); assert session.get(CartItem, item.id).quantity == 2
    post(cust, f"/cart/{item.id}/qty", {"qty": "50"}, page="/cart")
    session.expire_all(); assert session.get(CartItem, item.id).quantity == 2     # over the limit: refused
    post(cust, f"/cart/{item.id}/save", {"saved": "1"}, page="/cart")
    session.expire_all(); assert session.get(CartItem, item.id).saved_for_later
    html = cust.get("/cart").get_data(as_text=True)
    assert "Saved for later (1)" in html and "Move to cart" in html
    assert pj(cust, "/cart/add", {"product_id": p.id}).get_json()["count"] == 1  # adding again brings it back to the cart, not on top of the saved qty
    post(cust, f"/cart/{item.id}/qty", {"action": "dec"}, page="/cart")
    assert session.scalar(select(func.count(CartItem.id))) == 0                   # going below 1 removes the line


def test_cart_item_of_another_customer_is_untouchable(app, cust, session, catalog):
    _, p = catalog
    add(cust, p)
    item = session.scalar(select(CartItem))
    make_user(session, "user", "other@x.com")
    other = app.test_client()
    other.post("/login", data={"email": "other@x.com", "password": "Sup3rSecret!", "csrf_token": token(other, "/login")})
    for url, data in ((f"/cart/{item.id}/qty", {"action": "inc"}), (f"/cart/{item.id}/remove", {}), (f"/cart/{item.id}/save", {"saved": "1"})):
        pj(other, url, data)
    session.expire_all()
    it = session.get(CartItem, item.id)
    assert it is not None and it.quantity == 1 and not it.saved_for_later


def test_cart_flags_problems_and_blocks_checkout(cust, session, catalog):
    _, p = catalog
    add(cust, p, 5)
    p.stock_qty = 2
    session.commit()
    html = cust.get("/cart").get_data(as_text=True)
    assert "Only 2 available" in html and "Fix these before checkout" in html
    assert cust.get("/checkout").status_code == 302
    p.stock_qty = 0
    session.commit()
    assert "Out of stock" in cust.get("/cart").get_data(as_text=True)


def test_cart_is_persistent_across_sessions(app, cust, session, catalog):
    _, p = catalog
    add(cust, p, 2)
    again = app.test_client()
    sign_in(again, "user")
    assert "Millet Soup Mix" in again.get("/cart").get_data(as_text=True)


# ================================================================ coupons and totals
def coupon(session, **kw):
    c = Coupon(code=kw.pop("code", "SAVE10"), discount_type=kw.pop("discount_type", "percent"), discount_value=kw.pop("discount_value", 10), **kw)
    session.add(c)
    session.commit()
    return c


def test_coupon_rules(cust, session, catalog):
    _, p = catalog
    add(cust, p, 2)  # 2 x 80 = 160
    cp = lambda code: post(cust, "/cart/coupon", {"code": code}, page="/cart", follow=True).get_data(as_text=True)
    assert "does not exist" in cp("NOPE")
    coupon(session, code="BIG", min_cart_value=500)
    assert "more to use BIG" in cp("big")
    coupon(session, code="OLD", expires_at=utcnow() - timedelta(days=1))
    assert "expired" in cp("OLD")
    coupon(session, code="OFF", is_active=False)
    assert "not active" in cp("OFF")
    coupon(session, code="USED", usage_limit=3, used_count=3)
    assert "fully used" in cp("USED")
    ok = coupon(session, code="TEN", discount_value=10, max_discount=Decimal("5"))
    html = cp("ten")
    assert "Coupon TEN applied" in html and "− ₹5.00" in html   # 10% of 160 = 16, capped at 5
    flat = coupon(session, code="FLAT", discount_type="flat", discount_value=500)
    assert "− ₹160.00" in cp("FLAT")                            # never more than the cart
    post(cust, "/cart/coupon/remove", {}, page="/cart")
    assert "Coupon TEN" not in cust.get("/cart").get_data(as_text=True)


def test_totals_math_and_delivery_zone_fee(cust, session, catalog):
    from app.services.cart import build, totals_for
    from app.services.checkout import zone_for
    _, p = catalog
    add(cust, p, 2)
    html = cust.get("/cart").get_data(as_text=True)
    assert "₹200.00" in html and "₹160.00" in html and "You save ₹40.00" in html
    session.add(SiteSetting(key="free_delivery_min_cart", value=1))  # legacy threshold cannot override the zone fee
    session.commit()
    view = build(cust.user.id, None)
    totals = totals_for(view.lines, view.totals.discount, zone_for("641001"))
    assert totals.delivery == Decimal("40.00")
    assert totals.total == Decimal("200.00")
    assert "free delivery" not in cust.get("/cart").get_data(as_text=True).lower()


# ================================================================ checkout
def test_checkout_places_order_and_everything_changes_together(cust, session, catalog):
    _, p = catalog
    cp = coupon(session, code="TEN", discount_value=10, per_user_limit=1)
    add(cust, p, 3)                                   # 3 x 80 = 240
    post(cust, "/cart/coupon", {"code": "TEN"}, page="/cart")
    r = checkout(cust, session, cust.user, notes="Call me")
    assert r.status_code == 302
    session.expire_all()
    o = session.scalar(select(Order))
    assert r.headers["Location"] == f"/order-placed/{o.order_number}"
    assert o.status == "placed" and o.payment_method == "upi_manual" and o.payment_status == "pending" and o.user_id == cust.user.id
    assert (o.subtotal, o.discount_total, o.delivery_fee, o.total) == (Decimal("240.00"), Decimal("24.00"), Decimal("40.00"), Decimal("256.00"))
    assert o.coupon_code == "TEN" and o.customer_notes == "Call me"
    assert o.shipping_address["pincode"] == "641001" and o.shipping_address["full_name"] == "Asha Rao"
    it = o.items[0]
    assert (it.name, it.sku, it.quantity, it.unit_price, it.mrp, it.line_total) == ("Millet Soup Mix", "S1", 3, Decimal("80.00"), Decimal("100.00"), Decimal("240.00"))
    assert session.get(Product, p.id).stock_qty == 7
    log = session.scalar(select(InventoryLog))
    assert (log.old_qty, log.new_qty) == (10, 7) and o.order_number in log.reason
    assert session.get(Coupon, cp.id).used_count == 1 and session.scalar(select(CouponUsage)).order_id == o.id
    assert session.scalar(select(func.count(CartItem.id))) == 0
    assert [(h.from_status, h.to_status) for h in session.scalars(select(OrderStatusHistory))] == [(None, "placed")]
    assert o.payments[0].amount == Decimal("256.00") and o.payments[0].provider == "upi_manual"
    assert "placed" in session.scalar(select(Notification.title))
    assert session.scalar(select(AuditLog).where(AuditLog.action == "order.place"))
    assert o.order_number in cust.get(r.headers["Location"]).get_data(as_text=True)
    # a coupon with per_user_limit 1 cannot be used a second time
    add(cust, p, 1)
    assert "already used" in post(cust, "/cart/coupon", {"code": "TEN"}, page="/cart", follow=True).get_data(as_text=True)


def test_prices_come_from_the_database_not_the_form(cust, session, catalog):
    _, p = catalog
    add(cust, p, 1)
    checkout(cust, session, cust.user, unit_price="1", total="1", price="1", final_price="1")
    o = session.scalar(select(Order))
    assert o.items[0].unit_price == Decimal("80.00") and o.subtotal == Decimal("80.00")


def test_stock_is_rechecked_at_placement(cust, session, catalog):
    _, p = catalog
    add(cust, p, 5)
    tok = checkout_token(cust)                        # the customer has the checkout page open...
    p.stock_qty = 3                                   # ...while someone else buys some meanwhile
    session.commit()
    r = checkout(cust, session, cust.user, checkout_token=tok)
    assert r.status_code == 302 and r.headers["Location"].startswith("/checkout")
    session.expire_all()
    assert session.scalar(select(Order)) is None and session.get(Product, p.id).stock_qty == 3
    assert session.scalar(select(CartItem.quantity)) == 5 and session.scalar(select(InventoryLog)) is None
    assert "Only 3 available" in cust.get("/cart").get_data(as_text=True)


def test_last_item_cannot_be_sold_twice(app, cust, session, catalog):
    _, p = catalog
    p.stock_qty = 1
    session.commit()
    make_user(session, "user", "second@x.com")
    other = app.test_client()
    other.post("/login", data={"email": "second@x.com", "password": "Sup3rSecret!", "csrf_token": token(other, "/login")})
    u2 = session.scalar(select(Address.user_id).limit(1))
    from app.models import User
    second = session.scalar(select(User).where(User.email == "second@x.com"))
    session.add(Address(user_id=second.id, label="Home", full_name="B", phone="9876543211", line1="1 Road", city="C", state="TN", pincode="641001", is_default=True))
    session.commit()
    add(cust, p)
    add(other, p)
    checkout(cust, session, cust.user)
    r = checkout_post(other, {"address_id": address_id(session, second), "method": "upi_manual"}, page="/")
    session.expire_all()
    assert session.scalar(select(func.count(Order.id))) == 1 and session.get(Product, p.id).stock_qty == 0
    assert "out of stock" in other.get("/cart").get_data(as_text=True).lower()


def test_checkout_address_rules(app, cust, session, catalog):
    _, p = catalog
    add(cust, p)
    other = make_user(session, "user", "o@x.com")
    foreign = Address(user_id=other.id, label="X", full_name="Z", phone="9876543299", line1="1 Rd", city="C", state="S", pincode="641001")
    far = Address(user_id=cust.user.id, label="Far", full_name="F", phone="9876543298", line1="1 Rd", city="C", state="S", pincode="600001")
    session.add_all([foreign, far])
    session.commit()
    for aid in (foreign.id, far.id, 0, 99999):
        checkout_post(cust, {"address_id": aid, "method": "upi_manual"}, page="/checkout")
    checkout_post(cust, {"method": "upi_manual"}, page="/checkout")
    checkout_post(cust, {"address_id": address_id(session, cust.user), "method": "bitcoin"}, page="/checkout")
    assert session.scalar(select(Order)) is None and session.scalar(select(CartItem)) is not None
    assert "do not deliver" in cust.get("/checkout").get_data(as_text=True)


def test_checkout_without_address_or_cart(cust, session, catalog):
    assert cust.get("/checkout").status_code == 302                      # empty cart
    _, p = catalog
    add(cust, p)
    session.execute(Address.__table__.delete())
    session.commit()
    assert "Add a delivery address" in cust.get("/checkout").get_data(as_text=True)


def test_double_submit_creates_one_order(cust, session, catalog):
    _, p = catalog
    add(cust, p, 2)
    tok = checkout_token(cust)                        # one page load, then the button is pressed twice
    checkout(cust, session, cust.user, checkout_token=tok)
    r = checkout_post(cust, {"address_id": address_id(session, cust.user), "method": "upi_manual", "checkout_token": tok}, page="/", follow=True)
    assert session.scalar(select(func.count(Order.id))) == 1 and session.get(Product, p.id).stock_qty == 8
    assert "already been submitted" in r.get_data(as_text=True)


def test_saved_for_later_items_stay_after_checkout(cust, session, catalog):
    cat, p = catalog
    q = mk(session, cat, 8, name="Later Item", stock_qty=10)
    session.commit()
    add(cust, p)
    add(cust, q)
    qi = session.scalar(select(CartItem).where(CartItem.product_id == q.id))
    post(cust, f"/cart/{qi.id}/save", {"saved": "1"}, page="/cart")
    checkout(cust, session, cust.user)
    session.expire_all()
    left = session.scalars(select(CartItem)).all()
    assert len(left) == 1 and left[0].product_id == q.id and left[0].saved_for_later
    assert session.get(Product, q.id).stock_qty == 10


def test_only_whatsapp_ordering_is_offered(app, cust, session, catalog):
    _, p = catalog
    add(cust, p)
    html = cust.get("/checkout").get_data(as_text=True)
    assert "Order and pay on WhatsApp" in html and "Pay online" not in html and "Cash on delivery" not in html
    for old_method in ("online", "cod"):  # the old payment options are gone
        checkout_post(cust, {"address_id": address_id(session, cust.user), "method": old_method}, page="/checkout")
        assert session.scalar(select(Order)) is None
    assert cust.get("/pay/NK-1").status_code == 404


def test_order_placed_page_opens_whatsapp_with_the_order(app, cust, session, catalog):
    _, p = catalog
    app.config["ADMIN_WHATSAPP_NUMBER"] = "919876500000"
    try:
        add(cust, p, 2)
        r = checkout(cust, session, cust.user, notes="Call me")
        o = session.scalar(select(Order))
        html = cust.get(r.headers["Location"]).get_data(as_text=True)
        assert "https://wa.me/919876500000?text=" in html and "Open WhatsApp and send order" in html
        assert o.order_number in html and "Millet Soup Mix" in html and "Call me" in html and "Please confirm my order" in html
        assert "Test mode" not in html and "Razorpay" not in html
        app.config["ADMIN_WHATSAPP_NUMBER"] = ""
        assert "not configured" in cust.get(r.headers["Location"]).get_data(as_text=True)
        other = app.test_client()
        assert other.get(r.headers["Location"]).status_code == 302          # signed-out visitors are sent to sign in
    finally:
        app.config["ADMIN_WHATSAPP_NUMBER"] = ""


# ================================================================ my orders, cancel, reorder
def place(cust, session, p, qty=2):
    add(cust, p, qty)
    checkout(cust, session, cust.user)
    return session.scalar(select(Order).order_by(Order.id.desc()))


def test_order_list_and_detail_are_private(app, cust, session, catalog):
    _, p = catalog
    o = place(cust, session, p)
    html = cust.get("/account/orders").get_data(as_text=True)
    assert o.order_number in html and "Millet Soup Mix" in html
    det = cust.get(f"/account/orders/{o.order_number}").get_data(as_text=True)
    assert "Order placed" in det and "Confirmed" in det and "Cancel order" in det and "12 Lake Road" in det
    make_user(session, "user", "peek@x.com")
    other = app.test_client()
    other.post("/login", data={"email": "peek@x.com", "password": "Sup3rSecret!", "csrf_token": token(other, "/login")})
    assert other.get(f"/account/orders/{o.order_number}").status_code == 404
    assert o.order_number not in other.get("/account/orders").get_data(as_text=True)
    assert post(other, f"/account/orders/{o.order_number}/cancel", {}, page="/").status_code == 404
    assert post(other, f"/account/orders/{o.order_number}/reorder", {}, page="/").status_code == 404
    session.expire_all()
    assert session.get(Order, o.id).status == "placed"


def test_tracking_timeline_follows_owner_actions(app, cust, session, catalog):
    _, p = catalog
    o = place(cust, session, p)
    make_user(session, "owner")
    ow = app.test_client()
    sign_in(ow, "owner")
    for step in ("confirmed", "packed"):
        session.refresh(o)
        post(ow, f"/owner/orders/{o.id}/status", {"to": step, "from_status": o.status}, page="/owner/orders")
    html = cust.get(f"/account/orders/{o.order_number}").get_data(as_text=True)
    assert html.count("is-done") >= 2 and 'aria-current="step"' in html and re.search(r'is-done is-now"[^>]*>\s*<span[^>]*></span>\s*<b>Packed</b>', html)  # the current step is Packed
    n = session.scalars(select(Notification).where(Notification.user_id == cust.user.id)).all()
    assert any(f"/account/orders/{o.order_number}" == x.link for x in n)
    assert cust.get(n[-1].link).status_code == 200                      # the notification link from Step 5 now works


def test_customer_cancels_and_stock_and_coupon_come_back(app, cust, session, catalog):
    _, p = catalog
    cp = coupon(session, code="TEN")
    add(cust, p, 3)
    post(cust, "/cart/coupon", {"code": "TEN"}, page="/cart")
    checkout(cust, session, cust.user)
    o = session.scalar(select(Order))
    make_user(session, "owner")
    assert session.get(Product, p.id).stock_qty == 7 and session.get(Coupon, cp.id).used_count == 1
    r = post(cust, f"/account/orders/{o.order_number}/cancel", {}, page="/", follow=True)
    assert "cancelled" in r.get_data(as_text=True)
    session.expire_all()
    assert session.get(Order, o.id).status == "cancelled" and session.get(Product, p.id).stock_qty == 10
    assert session.get(Coupon, cp.id).used_count == 0 and session.scalar(select(CouponUsage)) is None
    assert [h.to_status for h in session.scalars(select(OrderStatusHistory).order_by(OrderStatusHistory.id))] == ["placed", "cancelled"]
    assert session.scalar(select(Notification).where(Notification.kind == "order_cancelled"))      # the owner is told
    post(cust, f"/account/orders/{o.order_number}/cancel", {}, page="/")                            # again: nothing more happens
    session.expire_all()
    assert session.get(Product, p.id).stock_qty == 10 and len(session.scalars(select(InventoryLog)).all()) == 2


@pytest.mark.parametrize("status", ["shipped", "delivered", "rejected", "cancelled"])
def test_cannot_cancel_after_shipping_or_when_closed(cust, session, catalog, status):
    _, p = catalog
    o = place(cust, session, p)
    o.status = status
    session.commit()
    post(cust, f"/account/orders/{o.order_number}/cancel", {}, page="/")
    session.expire_all()
    assert session.get(Order, o.id).status == status and session.get(Product, p.id).stock_qty == 8
    assert "Cancel order" not in cust.get(f"/account/orders/{o.order_number}").get_data(as_text=True)


def test_reorder(cust, session, catalog):
    cat, p = catalog
    o = place(cust, session, p, qty=2)
    gone = mk(session, cat, 9, name="Will Vanish")
    from app.models import OrderItem
    o.items.append(OrderItem(product_id=gone.id, name="Will Vanish", unit_price=5, mrp=5, quantity=1, line_total=5))
    session.commit()
    gone.stock_qty = 0
    session.commit()
    r = post(cust, f"/account/orders/{o.order_number}/reorder", {}, page="/", follow=True)
    assert "Added 1 item" in r.get_data(as_text=True) and "Will Vanish" in r.get_data(as_text=True)
    assert session.scalar(select(CartItem.quantity).where(CartItem.product_id == p.id)) == 2


# ================================================================ addresses
GOOD = {"label": "Work", "full_name": "Ravi K", "phone": "+91 98765 43210", "line1": "5 MG Road", "city": "Coimbatore", "state": "Tamil Nadu", "pincode": "641002"}


def test_address_crud_default_and_validation(cust, session):
    r = post(cust, "/account/addresses/new", GOOD, page="/account/addresses/new")
    assert r.status_code == 302
    a = session.scalar(select(Address).where(Address.label == "Work"))
    assert a.phone == "9876543210" and not a.is_default
    post(cust, f"/account/addresses/{a.id}/default", {}, page="/account/addresses")
    session.expire_all()
    assert session.get(Address, a.id).is_default and session.scalar(select(func.count(Address.id)).where(Address.is_default)) == 1
    post(cust, f"/account/addresses/{a.id}/edit", {**GOOD, "city": "Erode"}, page="/account/addresses")
    session.expire_all(); assert session.get(Address, a.id).city == "Erode"
    post(cust, f"/account/addresses/{a.id}/delete", {}, page="/account/addresses")
    session.expire_all()
    assert session.get(Address, a.id) is None and session.scalar(select(Address.is_default)) is True   # another address became default
    for bad in ({"phone": "12345"}, {"pincode": "64100"}, {"full_name": ""}, {"line1": ""}, {"city": ""}, {"state": ""}):
        r = post(cust, "/account/addresses/new", {**GOOD, **bad}, page="/account/addresses/new")
        assert r.status_code == 422, bad
    assert session.scalar(select(func.count(Address.id))) == 1


def test_address_limit_and_ownership(app, cust, session):
    for i in range(9):
        post(cust, "/account/addresses/new", {**GOOD, "label": f"A{i}"}, page="/account/addresses/new")
    assert session.scalar(select(func.count(Address.id))) == 10
    assert post(cust, "/account/addresses/new", GOOD, page="/account/addresses/new").status_code == 422
    mine = session.scalar(select(Address.id).limit(1))
    make_user(session, "user", "z@x.com")
    other = app.test_client()
    other.post("/login", data={"email": "z@x.com", "password": "Sup3rSecret!", "csrf_token": token(other, "/login")})
    assert other.get(f"/account/addresses/{mine}/edit").status_code == 404
    assert post(other, f"/account/addresses/{mine}/delete", {}, page="/").status_code == 404
    assert post(other, f"/account/addresses/{mine}/default", {}, page="/").status_code == 404
    assert session.get(Address, mine) is not None


def test_address_next_redirect_is_safe(cust, session):
    r = post(cust, "/account/addresses/new", {**GOOD, "next": "https://evil.example/"}, page="/account/addresses/new")
    assert "evil" not in r.headers["Location"]
    r = post(cust, "/account/addresses/new", {**GOOD, "next": "/checkout"}, page="/account/addresses/new")
    assert r.headers["Location"] == "/checkout"


# ================================================================ regressions: the existing user flow
def test_existing_login_register_account_flow_still_works(app, session, catalog):
    c = app.test_client()
    r = c.post("/register", data={"name": "New Person", "email": "new@x.com", "phone": "", "password": "Sup3rSecret!x", "confirm": "Sup3rSecret!x", "csrf_token": token(c, "/register")})
    assert r.status_code == 302 and r.headers["Location"] == "/account"
    html = c.get("/account").get_data(as_text=True)
    assert "Hello, New Person" in html and "My orders" in html and "Change password" in html
    assert c.get("/account/password").status_code == 200


def test_staff_login_pages_unchanged(app, session):
    for url in ("/owner/login", "/admin/login"):
        html = app.test_client().get(url).get_data(as_text=True)
        assert "Sign in" in html or "sign in" in html.lower()
        assert 'data-shop' not in html            # staff pages do not get the storefront chrome
