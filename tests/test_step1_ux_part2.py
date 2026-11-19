"""Step 1 UX: guest cart merge/purge (1.1), Reorder buttons (1.7), active filter chips and the In stock toggle (1.8)."""
import re
from datetime import timedelta

from sqlalchemy import func, select, update

from app.models import CartItem, Order
from app.models.base import utcnow
from app.services import cart as cart_svc
from tests.helpers import make_user, post, sign_in, token
from tests.test_step6_shop import JSON, add, cust, catalog, many, place  # noqa: F401  (fixtures)


# ---------------------------------------------------------------- 1.1 guest cart
def test_guest_cart_is_merged_into_the_account_at_sign_in(app, session, catalog):
    _, p = catalog
    make_user(session, "user")
    c = app.test_client()
    assert c.post("/cart/add", data={"product_id": p.id, "qty": 2, "csrf_token": token(c, "/login")}, headers=JSON).status_code == 200
    assert session.scalar(select(func.count(CartItem.id)).where(CartItem.session_id.is_not(None))) == 1
    sign_in(c, "user")
    session.expire_all()
    rows = session.scalars(select(CartItem)).all()
    assert len(rows) == 1 and rows[0].user_id is not None and rows[0].session_id is None and rows[0].quantity == 2


def test_merge_adds_same_lines_together_and_caps_at_the_line_maximum(app, session, cust, catalog):
    _, p = catalog
    add(cust, p, 8)                                         # signed-in cart already holds 8
    guest = app.test_client()
    guest.post("/cart/add", data={"product_id": p.id, "qty": 5, "csrf_token": token(guest, "/login")}, headers=JSON)
    gid = session.scalar(select(CartItem.session_id).where(CartItem.session_id.is_not(None)))
    moved = cart_svc.merge_guest_cart(cust.user, gid)
    session.commit()
    assert moved == 1
    rows = session.scalars(select(CartItem)).all()
    assert len(rows) == 1 and rows[0].quantity == cart_svc.MAX_LINE_QTY


def test_a_cart_row_needs_an_owner(session, catalog):
    _, p = catalog
    from sqlalchemy.exc import IntegrityError
    import pytest
    session.add(CartItem(product_id=p.id, quantity=1))
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_purge_guest_carts_removes_only_old_guest_rows(app, session, cust, catalog):
    _, p = catalog
    add(cust, p, 1)                                         # a customer's row must never be purged
    old, fresh = app.test_client(), app.test_client()
    for c in (old, fresh):
        c.post("/cart/add", data={"product_id": p.id, "csrf_token": token(c, "/login")}, headers=JSON)
    guest_ids = session.scalars(select(CartItem.id).where(CartItem.user_id.is_(None)).order_by(CartItem.id)).all()
    session.execute(update(CartItem).where(CartItem.id == guest_ids[0]).values(updated_at=utcnow() - timedelta(days=15)))
    session.commit()
    assert cart_svc.purge_guest_carts(14) == 1
    left = session.scalars(select(CartItem)).all()
    assert len(left) == 2 and {r.user_id is None for r in left} == {True, False}


# ---------------------------------------------------------------- 1.7 reorder
def test_reorder_buttons_are_on_the_orders_list_and_the_account_page(cust, session, catalog):
    _, p = catalog
    o = place(cust, session, p, 2)
    action = f'action="/account/orders/{o.order_number}/reorder"'
    assert action in cust.get("/account/orders").get_data(as_text=True)
    assert action in cust.get("/account").get_data(as_text=True)


def test_reorder_adds_the_items_to_my_cart_and_goes_to_the_cart(cust, session, catalog):
    _, p = catalog
    o = place(cust, session, p, 2)
    session.query(CartItem).delete()
    session.commit()
    r = post(cust, f"/account/orders/{o.order_number}/reorder", {}, page="/account/orders")
    assert r.status_code == 302 and r.headers["Location"].endswith("/cart")
    session.expire_all()
    row = session.scalar(select(CartItem).where(CartItem.user_id == cust.user.id))
    assert row.product_id == p.id and row.quantity == 2


def test_reorder_is_owner_only_and_needs_sign_in(app, session, cust, catalog):
    _, p = catalog
    o = place(cust, session, p, 1)
    make_user(session, "user", "other@x.com")
    other = app.test_client()
    other.post("/login", data={"email": "other@x.com", "password": "Sup3rSecret!", "csrf_token": token(other, "/login")})
    assert post(other, f"/account/orders/{o.order_number}/reorder", {}, page="/").status_code == 404
    anon = app.test_client()
    r = anon.post(f"/account/orders/{o.order_number}/reorder", data={"csrf_token": token(anon, "/login")})
    assert r.status_code in (302, 401, 403)


# ---------------------------------------------------------------- 1.8 listing chips and In stock toggle
def test_active_filter_chips_each_remove_one_filter(app, many):
    c = app.test_client()
    html = c.get("/shop?avail=1&min_price=100&max_price=400&rating=3&discount=10&brand=Amma").get_data(as_text=True)
    assert 'aria-label="Active filters"' in html
    links = {m[1]: m[0] for m in re.findall(r'href="([^"]+)" aria-label="Remove filter: ([^"]+)"', html)}
    assert set(links) == {"In stock", "₹100 – ₹400", "3★ &amp; up", "10% off or more", "Amma"}
    stock = links["In stock"].replace("&amp;", "&")
    assert "avail" not in stock and "min_price=100" in stock and "brand=Amma" in stock
    price = links["₹100 – ₹400"].replace("&amp;", "&")
    assert "min_price" not in price and "max_price" not in price and "avail=1" in price
    brand = links["Amma"].replace("&amp;", "&")
    assert "brand" not in brand and "avail=1" in brand


def test_no_chips_without_filters_and_removing_a_chip_works(app, many):
    c = app.test_client()
    assert 'aria-label="Active filters"' not in c.get("/shop").get_data(as_text=True)
    html = c.get("/shop?avail=1").get_data(as_text=True)
    href = re.search(r'href="([^"]+)" aria-label="Remove filter: In stock"', html).group(1).replace("&amp;", "&")
    assert c.get(href).status_code == 200 and "Remove filter" not in c.get(href).get_data(as_text=True)


def test_chips_keep_the_category_and_in_stock_toggle_is_one_control(app, many):
    c = app.test_client()
    html = c.get("/category/snacks?avail=1&rating=4").get_data(as_text=True)
    assert re.search(r'href="/category/snacks\?[^"]*rating=4[^"]*" aria-label="Remove filter: In stock"', html)
    assert html.count('name="avail"') == 1 and 'role="switch"' in html and "checked" in re.search(r'<input[^>]*name="avail"[^>]*>', html).group(0)
