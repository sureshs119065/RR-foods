from datetime import timedelta
from decimal import Decimal

from sqlalchemy import select

from app.models import CartItem, SiteSetting, User
from app.models.base import utcnow
from app.services import cart as cart_svc
from tests.helpers import PW, make_user, token
from tests.test_step2_models import make_category, make_product

JSON = {"Accept": "application/json"}


def _product(session, **kw):
    cat = make_category(session)
    p = make_product(session, category=cat, stock_qty=10, **kw)
    session.commit()
    return p


def _add(c, p, qty=1, page="/login"):
    return c.post("/cart/add", data={"product_id": p.id, "qty": qty, "csrf_token": token(c, page)}, headers=JSON)


def test_guest_cart_add_qty_save_remove(app, session):
    p = _product(session)
    c = app.test_client()
    assert _add(c, p, 2).get_json()["count"] == 2
    item = session.scalar(select(CartItem))
    assert item.user_id is None and item.session_id
    t = token(c, "/login")
    assert c.post(f"/cart/{item.id}/qty", data={"action": "inc", "csrf_token": t}, headers=JSON).status_code == 200
    assert c.post(f"/cart/{item.id}/save", data={"saved": "1", "csrf_token": t}, headers=JSON).status_code == 200
    assert b"Saved for later" in c.get("/cart").data
    assert c.post(f"/cart/{item.id}/remove", data={"csrf_token": t}, headers=JSON).status_code == 200
    session.expire_all()
    assert session.scalar(select(CartItem)) is None


def test_guest_cannot_touch_another_guests_line(app, session):
    p = _product(session)
    a, b = app.test_client(), app.test_client()
    _add(a, p)
    _add(b, p)
    item_a = session.scalars(select(CartItem).order_by(CartItem.id)).first()
    r = b.post(f"/cart/{item_a.id}/remove", data={"csrf_token": token(b, "/login")}, headers=JSON)
    session.expire_all()
    assert session.get(CartItem, item_a.id) is not None and r.status_code == 200


def test_checkout_requires_login_and_returns_to_checkout(app, session):
    p = _product(session)
    make_user(session, "user")
    c = app.test_client()
    _add(c, p)
    assert c.get("/checkout").headers["Location"].startswith("/login?next=/checkout")
    r = c.post("/login?next=/checkout", data={"email": "user@test.com", "password": PW, "csrf_token": token(c, "/login")})
    assert r.status_code == 302 and r.headers["Location"].endswith("/checkout")


def test_guest_cart_merges_on_login_and_register(app, session):
    p = _product(session)
    u = make_user(session, "user")
    c = app.test_client()
    _add(c, p, 2)
    c.post("/login", data={"email": "user@test.com", "password": PW, "csrf_token": token(c, "/login")})
    session.expire_all()
    items = session.scalars(select(CartItem)).all()
    assert len(items) == 1 and items[0].user_id == u.id and items[0].session_id is None and items[0].quantity == 2
    # same product as guest again: quantities add up
    c2 = app.test_client()
    _add(c2, p, 3)
    c2.post("/login", data={"email": "user@test.com", "password": PW, "csrf_token": token(c2, "/login")})
    session.expire_all()
    assert session.scalar(select(CartItem.quantity)) == 5
    # register
    c3 = app.test_client()
    _add(c3, p, 1)
    c3.post("/register", data={"name": "Nina Rao", "email": "nina@test.com", "phone": "", "password": "Gr3at-Passw0rd!x", "confirm": "Gr3at-Passw0rd!x", "csrf_token": token(c3, "/register")})
    session.expire_all()
    nina = session.scalar(select(User).where(User.email == "nina@test.com"))
    assert nina is not None and session.scalar(select(CartItem.quantity).where(CartItem.user_id == nina.id)) == 1


def test_owner_check_constraint(app, session):
    import pytest
    from sqlalchemy.exc import IntegrityError
    p = _product(session)
    session.add(CartItem(product_id=p.id, quantity=1))
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_purge_guest_carts_cli(app, session):
    p = _product(session)
    u = make_user(session, "user")
    old = utcnow() - timedelta(days=20)
    session.add_all([CartItem(session_id="old", product_id=p.id, quantity=1, updated_at=old),
                     CartItem(session_id="new", product_id=p.id, quantity=1),
                     CartItem(user_id=u.id, product_id=p.id, quantity=1, updated_at=old)])
    session.commit()
    res = app.test_cli_runner().invoke(args=["purge-guest-carts", "--days", "14"])
    assert "deleted 1" in res.output
    session.expire_all()
    assert {i.session_id for i in session.scalars(select(CartItem))} == {"new", None}


def test_free_delivery_bar_and_waiver(app, session):
    p = _product(session)
    c = app.test_client()
    _add(c, p)
    assert b"fdbar" not in c.get("/cart").data  # off by default
    session.add(SiteSetting(key="free_delivery_above", value="100000"))
    session.commit()
    html = c.get("/cart").get_data(as_text=True)
    assert "fdbar" not in html and "free delivery" not in html.lower()  # delivery charges are handled by the shop: no free-delivery offer is shown


def test_cart_empty_state_and_coupon_above_totals(app, session):
    c = app.test_client()
    html = c.get("/cart").get_data(as_text=True)
    assert "data-empty-cart" in html and "Your cart is empty" in html
    p = _product(session)
    _add(c, p)
    html = c.get("/cart").get_data(as_text=True)
    assert html.index('class="coupon"') < html.index("Price details")


def test_home_hides_empty_sections(app, session):
    html = app.test_client().get("/").get_data(as_text=True)
    assert "Recently viewed" not in html and "Customer Reviews" not in html and "Coming soon" not in html
    assert "home-bottom--no-recent" in html and "home-bottom--no-reviews" in html


def test_product_page_pincode_before_add_to_cart(app, session):
    p = _product(session)
    html = app.test_client().get(f"/product/{p.slug}").get_data(as_text=True)
    assert html.index('id="pinform"') < html.index('id="buyform"') and 'id="bar-price"' in html


def test_checkout_error_summary_and_plain_pincode(app, session):
    p = _product(session)
    make_user(session, "user")
    c = app.test_client()
    c.post("/login", data={"email": "user@test.com", "password": PW, "csrf_token": token(c, "/login")})
    _add(c, p, page="/cart")
    html = c.get("/checkout").get_data(as_text=True)
    assert 'id="co-errors"' in html and 'role="alert"' in html and "readonly" not in html
    from app.models import Address
    uid = session.scalar(select(User.id).where(User.email == "user@test.com"))
    session.add(Address(user_id=uid, label="Home", full_name="U", phone="9876543210", line1="1 Main St", city="Chennai", state="Tamil Nadu", pincode="600001"))
    session.commit()
    html = c.get("/checkout").get_data(as_text=True)
    assert "<b data-checkout-pincode>600001</b>" in html and "readonly" not in html
    # a server-side failure comes back inside the summary, linked to its field
    tok = html.split('name="checkout_token" value="')[1].split('"')[0]
    c.post("/checkout", data={"checkout_token": tok, "method": "upi_manual", "csrf_token": token(c, "/checkout")})
    html = c.get("/checkout").get_data(as_text=True)
    assert "Choose a delivery address" in html and 'aria-invalid="true"' in html
