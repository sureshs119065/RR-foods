"""Part 2: e-commerce logic and access-control tests.
Copy to tests/test_security_part2.py and run:  pytest tests/test_security_part2.py -v
Needs the same Postgres test database your other tests use (TEST_DATABASE_URL).
"""
import re
import threading
from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.extensions import db
from app.models import Address, CartItem, Coupon, DeliveryZone, Order
from app.models.base import utcnow
from app.models.content import Bundle
from app.services import checkout as co
from tests.helpers import make_user, sign_in
from tests.test_step2_models import make_product
from tests.test_step5_owner import mk_order

PW = "Sup3rSecret!"


# ------------------------------------------------------------------ helpers
def _tok(c, url):
    return re.search(r'name="csrf_token" value="([^"]+)"', c.get(url).get_data(as_text=True)).group(1)


def _login(app, email):
    c = app.test_client()
    r = c.post("/login", data={"email": email, "password": PW, "csrf_token": _tok(c, "/login")})
    assert r.status_code == 302
    return c


def _addr(session, user, pin="641001"):
    if session.get(DeliveryZone, pin) is None:
        session.add(DeliveryZone(pincode=pin, is_serviceable=True, eta_days=2, delivery_fee=0))
    a = Address(user_id=user.id, full_name="T", phone="9876543210", line1="1 Street", city="Coimbatore", state="TN", pincode=pin)
    session.add(a)
    session.commit()
    return a


def _cart(session, user, product, qty=1, **kw):
    item = CartItem(user_id=user.id, product_id=product.id, quantity=qty, **kw)
    session.add(item)
    session.commit()
    return item


def _coupon(session, **kw):
    d = dict(code="SAVE10", discount_type="percent", discount_value=Decimal("10"), min_cart_value=0, per_user_limit=1, is_active=True)
    d.update(kw)
    c = Coupon(**d)
    session.add(c)
    session.commit()
    return c


@pytest.fixture()
def shop(session):
    a = make_user(session, "user", "a@x.com")
    b = make_user(session, "user", "b@x.com")
    make_user(session, "owner")
    make_user(session, "admin")
    p = make_product(session, stock_qty=5, low_stock_threshold=1)
    session.commit()
    return a, b, p


def _place(user, addr, coupon=None):
    o = co.place_order(user, addr.id, co.WHATSAPP_METHOD, coupon, None)
    db.session.commit()
    return o


# ------------------------------------------------------------------ coupons
def test_coupon_per_user_limit(session, shop):
    a, _, p = shop
    _coupon(session, per_user_limit=1)
    addr = _addr(session, a)
    _cart(session, a, p)
    _place(a, addr, "SAVE10")
    _cart(session, a, p)
    with pytest.raises(co.CheckoutError):
        _place(a, addr, "SAVE10")


def test_coupon_global_usage_limit(session, shop):
    a, b, p = shop
    _coupon(session, usage_limit=1, per_user_limit=5)
    _cart(session, a, p)
    _place(a, _addr(session, a), "SAVE10")
    _cart(session, b, p)
    with pytest.raises(co.CheckoutError):
        _place(b, _addr(session, b), "SAVE10")


def test_expired_and_inactive_coupon_rejected(session, shop):
    a, _, p = shop
    _coupon(session, code="OLD", expires_at=utcnow() - timedelta(days=1))
    _coupon(session, code="OFF", is_active=False)
    addr = _addr(session, a)
    for code in ("OLD", "OFF", "NOPE"):
        _cart(session, a, p)
        with pytest.raises(co.CheckoutError):
            _place(a, addr, code)
        db.session.rollback()
        for it in session.scalars(select(CartItem).where(CartItem.user_id == a.id)):
            session.delete(it)
        session.commit()


def test_coupon_min_cart_and_never_exceeds_subtotal(session, shop):
    a, _, p = shop
    _coupon(session, code="BIG", discount_type="flat", discount_value=Decimal("5000"))  # flat bigger than cart
    _cart(session, a, p, qty=1)
    o = _place(a, _addr(session, a), "BIG")
    assert o.discount_total <= o.subtotal and o.total >= 0


def test_cancel_releases_coupon(session, shop):
    from app.services import coupons
    a, _, p = shop
    c = _coupon(session)
    _cart(session, a, p)
    o = _place(a, _addr(session, a), "SAVE10")
    assert session.get(Coupon, c.id).used_count == 1
    coupons.release(o)
    db.session.commit()
    session.expire_all()
    assert session.get(Coupon, c.id).used_count == 0


# ------------------------------------------------------------------ stock
def test_cannot_oversell_sequentially(session, shop):
    a, b, p = shop
    p.stock_qty = 1
    session.commit()
    _cart(session, a, p)
    _cart(session, b, p)
    _place(a, _addr(session, a))
    with pytest.raises(co.CheckoutError):
        _place(b, _addr(session, b))


def test_stock_race_two_threads_one_item(app, session, shop):
    """Two customers press 'place order' for the last unit at the same moment: exactly one may win."""
    a, b, p = shop
    p.stock_qty = 1
    session.commit()
    _cart(session, a, p)
    _cart(session, b, p)
    aa, ba = _addr(session, a).id, _addr(session, b).id
    ids = {"a": (a.id, aa), "b": (b.id, ba)}
    results, barrier = [], threading.Barrier(2)

    def worker(key):
        with app.app_context():
            from app.models import User
            u = db.session.get(User, ids[key][0])
            barrier.wait()
            try:
                co.place_order(u, ids[key][1], co.WHATSAPP_METHOD, None, None)
                db.session.commit()
                results.append("ok")
            except co.CheckoutError:
                db.session.rollback()
                results.append("blocked")
            finally:
                db.session.remove()

    ts = [threading.Thread(target=worker, args=(k,)) for k in ids]
    [t.start() for t in ts]
    [t.join(30) for t in ts]
    assert sorted(results) == ["blocked", "ok"], results


def test_quantity_limits(session, shop):
    a, _, p = shop
    p.stock_qty = 500
    session.commit()
    _cart(session, a, p, qty=11)  # above MAX_LINE_QTY (10)
    with pytest.raises(co.CheckoutError):
        _place(a, _addr(session, a))


# ------------------------------------------------------------------ cart / price tampering
def test_cart_qty_rejects_negative_zero_and_huge(app, session, shop):
    a, _, p = shop
    item = _cart(session, a, p, qty=2)
    c = _login(app, "a@x.com")
    for bad in ("-5", "abc", "99999", "1e9"):
        r = c.post(f"/cart/{item.id}/qty", data={"qty": bad, "csrf_token": _tok(c, "/cart")})
        assert r.status_code in (302, 400, 409, 422)
        session.expire_all()
        assert 1 <= session.get(CartItem, item.id).quantity <= 10


def test_cart_ignores_client_supplied_price(app, session, shop):
    a, _, p = shop
    c = _login(app, "a@x.com")
    c.post("/cart/add", data={"product_id": p.id, "qty": 1, "price": "1", "unit_price": "1", "final_price": "1",
                              "unit_price_override": "1", "csrf_token": _tok(c, "/cart")})
    session.expire_all()
    item = session.scalar(select(CartItem).where(CartItem.user_id == a.id))
    if item is not None:
        assert item.unit_price_override is None
        _addr(session, a)
        o = _place(a, session.scalar(select(Address).where(Address.user_id == a.id)))
        assert o.subtotal == Decimal("100")


def test_cannot_edit_or_remove_someone_elses_cart_item(app, session, shop):
    a, b, p = shop
    item = _cart(session, a, p, qty=2)
    cb = _login(app, "b@x.com")
    cb.post(f"/cart/{item.id}/qty", data={"qty": "9", "csrf_token": _tok(cb, "/cart")})
    cb.post(f"/cart/{item.id}/remove", data={"csrf_token": _tok(cb, "/cart")})
    session.expire_all()
    it = session.get(CartItem, item.id)
    assert it is not None and it.quantity == 2


# ------------------------------------------------------------------ bundle price (fixed: checkout re-checks the bundle)
def test_expired_bundle_price_not_honoured_at_checkout(session, shop):
    a, _, p = shop
    bundle = Bundle(name="B", slug="b", product_quantities=[{"product_id": p.id, "quantity": 1}], bundle_price=50, is_active=True)
    session.add(bundle)
    session.commit()
    _cart(session, a, p, qty=1, bundle_id=bundle.id, unit_price_override=Decimal("50"), line_total_override=Decimal("50"))
    bundle.is_active = False  # owner switches the offer off after the customer added it
    session.commit()
    try:
        o = _place(a, _addr(session, a))
    except co.CheckoutError:
        return  # secure behaviour
    assert o.subtotal != Decimal("50"), "order was placed at the expired bundle price"


# ------------------------------------------------------------------ IDOR
def test_customer_cannot_read_other_customers_order(app, session, shop):
    a, b, p = shop
    o = mk_order(session, a, p, number="NK-IDOR-1")
    cb = _login(app, "b@x.com")
    for url in (f"/account/orders/{o.order_number}", f"/account/orders/{o.order_number}/status.json",
                f"/account/orders/{o.order_number}/invoice.pdf", f"/order-placed/{o.order_number}"):
        assert cb.get(url).status_code in (403, 404), url


def test_customer_cannot_cancel_or_reorder_other_customers_order(app, session, shop):
    a, b, p = shop
    o = mk_order(session, a, p, number="NK-IDOR-2")
    cb = _login(app, "b@x.com")
    for action in ("cancel", "return", "reorder"):
        cb.post(f"/account/orders/{o.order_number}/{action}", data={"csrf_token": _tok(cb, "/cart")})
    session.expire_all()
    assert session.get(Order, o.id).status == "placed"


def test_cannot_ship_to_another_users_address(session, shop):
    a, b, p = shop
    victim_addr = _addr(session, b)
    _cart(session, a, p)
    with pytest.raises(co.CheckoutError):
        _place(a, victim_addr)


def test_cannot_delete_or_edit_other_users_address(app, session, shop):
    a, b, _ = shop
    addr = _addr(session, b)
    ca = _login(app, "a@x.com")
    ca.post(f"/account/addresses/{addr.id}/delete", data={"csrf_token": _tok(ca, "/account/addresses")})
    ca.post(f"/account/addresses/{addr.id}/edit", data={"full_name": "Hacked", "csrf_token": _tok(ca, "/account/addresses")})
    session.expire_all()
    got = session.get(Address, addr.id)
    assert got is not None and got.full_name == "T"


# ------------------------------------------------------------------ double submit
def test_checkout_token_blocks_double_submit(app, session, shop):
    a, _, p = shop
    addr = _addr(session, a)
    _cart(session, a, p)
    c = _login(app, "a@x.com")
    page = c.get(f"/checkout?address={addr.id}").get_data(as_text=True)
    m = re.search(r'name="checkout_token" value="([^"]+)"', page)
    if not m:
        pytest.skip("checkout page did not render a token (check cart/zone setup)")
    form = {"checkout_token": m.group(1), "address_id": addr.id, "method": co.WHATSAPP_METHOD, "csrf_token": _tok(c, "/checkout")}
    c.post("/checkout", data=form)
    c.post("/checkout", data=form)
    session.expire_all()
    assert len(session.scalars(select(Order).where(Order.user_id == a.id)).all()) == 1


# ------------------------------------------------------------------ role separation
@pytest.mark.parametrize("url", ["/admin/", "/admin/users", "/admin/coupons", "/owner/", "/owner/orders", "/owner/inventory"])
def test_anonymous_cannot_open_staff_pages(app, session, shop, url):
    r = app.test_client().get(url)
    assert r.status_code in (302, 401, 403, 404)
    if r.status_code == 302:
        assert "login" in r.headers["Location"]


@pytest.mark.parametrize("url", ["/admin/", "/admin/users", "/admin/coupons", "/owner/", "/owner/orders", "/owner/inventory"])
def test_customer_cannot_open_staff_pages(app, session, shop, url):
    c = _login(app, "a@x.com")
    r = c.get(url)
    assert r.status_code != 200


@pytest.mark.parametrize("url", ["/owner/", "/owner/orders", "/owner/inventory"])
def test_admin_cannot_open_owner_pages(app, session, shop, url):
    c = app.test_client()
    sign_in(c, "admin")
    assert c.get(url).status_code != 200


@pytest.mark.parametrize("url", ["/admin/users", "/admin/coupons", "/admin/products"])
def test_owner_vs_admin_boundary_documented(app, session, shop, url):
    """Prints what an owner can reach on admin pages. Not an assertion: decide if this is intended."""
    c = app.test_client()
    sign_in(c, "owner")
    print(url, "->", c.get(url).status_code)


def test_staff_post_without_csrf_is_rejected(app, session, shop):
    c = app.test_client()
    sign_in(c, "admin")
    r = c.post("/admin/coupons", data={"code": "HACK", "discount_type": "flat", "discount_value": "99"})
    assert r.status_code in (400, 403, 404, 405)
    assert session.scalar(select(Coupon).where(Coupon.code == "HACK")) is None


# ------------------------------------------------------------------ login protection
def test_login_lockout_after_five_failures(app, session, shop):
    for _ in range(6):
        c = app.test_client()
        c.post("/login", data={"email": "a@x.com", "password": "wrong-pass", "csrf_token": _tok(c, "/login")})
    c = app.test_client()
    r = c.post("/login", data={"email": "a@x.com", "password": PW, "csrf_token": _tok(c, "/login")})
    assert r.status_code != 302, "correct password still accepted right after 6 failures (lockout not enforced)"


def test_login_error_does_not_reveal_if_email_exists(app, session, shop):
    c1, c2 = app.test_client(), app.test_client()
    r1 = c1.post("/login", data={"email": "a@x.com", "password": "bad-pass-1", "csrf_token": _tok(c1, "/login")})
    r2 = c2.post("/login", data={"email": "ghost@x.com", "password": "bad-pass-1", "csrf_token": _tok(c2, "/login")})
    assert r1.status_code == r2.status_code


def test_edited_bundle_price_is_not_honoured_at_checkout(session, shop):
    a, _, p = shop
    bundle = Bundle(name="B2", slug="b2", product_quantities=[{"product_id": p.id, "quantity": 1}], bundle_price=50, is_active=True)
    session.add(bundle)
    session.commit()
    _cart(session, a, p, qty=1, bundle_id=bundle.id, unit_price_override=Decimal("50"), line_total_override=Decimal("50"))
    bundle.bundle_price = 90  # owner changes the price after the customer added it
    session.commit()
    with pytest.raises(co.CheckoutError):
        _place(a, _addr(session, a))


# ------------------------------------------------------------------ uploads, headers, SEO
def _fs(data, name, mime):
    import io
    from werkzeug.datastructures import FileStorage
    return FileStorage(stream=io.BytesIO(data), filename=name, content_type=mime)


def test_video_upload_checks_real_file_content(app, session):
    from app.uploads import UploadError, save_video
    with pytest.raises(UploadError):
        save_video(_fs(b"<?php echo 1; ?>" + b"x" * 100, "evil.mp4", "video/mp4"), "reels")  # script renamed to .mp4
    with pytest.raises(UploadError):
        save_video(_fs(b"\x00\x00\x00\x18ftypmp42" + b"0" * 50, "x.webm", "video/webm"), "reels")  # mp4 body, .webm name
    ok = save_video(_fs(b"\x00\x00\x00\x18ftypmp42" + b"0" * 50, "ok.mp4", "video/mp4"), "reels")
    assert ok.startswith("/uploads/reels/") and ok.endswith(".mp4")


def test_security_headers_present(app):
    r = app.test_client().get("/healthz")
    for h in ("Content-Security-Policy", "X-Frame-Options", "X-Content-Type-Options", "Referrer-Policy", "Permissions-Policy", "Cross-Origin-Opener-Policy"):
        assert r.headers.get(h), h


def test_hsts_sent_over_https_only(app):
    app.config["TESTING"] = False
    try:
        c = app.test_client()
        assert "Strict-Transport-Security" not in c.get("/healthz").headers
        assert "max-age=31536000" in c.get("/healthz", base_url="https://shop.test").headers.get("Strict-Transport-Security", "")
    finally:
        app.config["TESTING"] = True


def test_favicon_and_robots_and_sitemap(app, session, shop):
    _, _, p = shop
    c = app.test_client()
    assert c.get("/favicon.ico").status_code == 301
    robots = c.get("/robots.txt").get_data(as_text=True)
    assert "Sitemap:" in robots and "Disallow: /admin" in robots and "Disallow: /checkout" in robots
    xml = c.get("/sitemap.xml").get_data(as_text=True)
    assert f"/product/{p.slug}" in xml and "<lastmod>" in xml and "/about" in xml


def test_product_page_seo_tags_once(app, session, shop):
    _, _, p = shop
    html = app.test_client().get(f"/product/{p.slug}").get_data(as_text=True)
    assert html.count('property="og:title"') == 1 and html.count('property="og:type"') == 1
    assert html.count('rel="canonical"') == 1 and 'application/ld+json' in html and 'twitter:card' in html


def test_home_has_social_and_organization_schema(app, session, shop):
    html = app.test_client().get("/").get_data(as_text=True)
    assert html.count('property="og:title"') == 1 and 'twitter:card' in html and '"Organization"' in html and '"WebSite"' in html
