"""Task 5: no overselling (races, double submits, double restores) and nothing price-like is taken from the browser."""
import logging
import threading
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models import Address, Bundle, CartItem, Coupon, CouponUsage, DeliveryZone, Order, OrderItem, Product, User
from app.models.base import utcnow
from app.services import orders as svc
from app.services.inventory import restore_order_stock
from tests.helpers import checkout_post, checkout_token, confirm_requests, make_user, post, sign_in
from tests.test_step5_owner import ADDR, mk_order
from tests.test_step6_shop import add, address_id, cust, catalog, checkout, mk, pj  # noqa: F401  (fixtures and helpers)

DRAFT = "pending_whatsapp"


@pytest.fixture()
def staff(session):
    return make_user(session, "owner", "task5-owner@x.com")


# ---------------------------------------------------------------- A: last item, two buyers at the same instant
def test_two_simultaneous_confirmations_of_the_last_item_place_exactly_one_order(app, session, staff):
    buyer_a, buyer_b = make_user(session, "user", "a@x.com"), make_user(session, "user", "b@x.com")
    from tests.test_step2_models import make_product
    product = make_product(session, stock_qty=1)
    session.commit()
    a = mk_order(session, buyer_a, product, qty=1, status=DRAFT, number="NK-R1")
    b = mk_order(session, buyer_b, product, qty=1, status=DRAFT, number="NK-R2")
    ids, staff_id, product_id = [a.id, b.id], staff.id, product.id
    barrier, results = threading.Barrier(2), []

    def confirm(order_id):
        with app.app_context():
            actor = db.session.get(User, staff_id)
            barrier.wait()
            try:
                svc.confirm_whatsapp_received(order_id, actor)
                db.session.commit()
                results.append("placed")
            except svc.OrderError:
                db.session.rollback()
                results.append("refused")
            finally:
                db.session.remove()

    threads = [threading.Thread(target=confirm, args=(i,)) for i in ids]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sorted(results) == ["placed", "refused"]
    session.expire_all()
    assert session.get(Product, product_id).stock_qty == 0          # never -1: one wins, the other is told it is sold out
    assert sorted(o.status for o in session.scalars(select(Order))) == [DRAFT, "placed"]


def test_the_database_itself_refuses_negative_stock(app, session):
    from tests.test_step2_models import make_product
    product = make_product(session, stock_qty=1)
    session.commit()
    with pytest.raises(IntegrityError):
        session.execute(Product.__table__.update().where(Product.id == product.id).values(stock_qty=-1))
    session.rollback()


# ---------------------------------------------------------------- A: restore only once
def test_stock_goes_back_only_once_per_order(app, session, staff):
    buyer = make_user(session, "user", "r@x.com")
    from tests.test_step2_models import make_product
    product = make_product(session, stock_qty=5)
    session.commit()
    order = mk_order(session, buyer, product, qty=2, status="placed", number="NK-ONCE")
    product.stock_qty = 3                                            # the 2 units were taken when it was placed
    session.commit()
    svc.change_status(order.id, "rejected", staff, reason="out of milk")
    session.commit()
    assert session.get(Product, product.id).stock_qty == 5
    assert restore_order_stock(session.get(Order, order.id), "retry", None) == 0     # a retry or double click changes nothing
    session.commit()
    assert session.get(Product, product.id).stock_qty == 5 and session.get(Order, order.id).stock_restored_at is not None


# ---------------------------------------------------------------- A: coupon limits re-checked when the order is really placed
def test_coupon_limit_is_rechecked_under_lock_when_placing(app, session, staff):
    from tests.test_step2_models import make_product
    product = make_product(session, stock_qty=10)
    coupon = Coupon(code="ONEONLY", discount_type="flat", discount_value=10, usage_limit=1, per_user_limit=1)
    session.add(coupon)
    u1, u2 = make_user(session, "user", "c1@x.com"), make_user(session, "user", "c2@x.com")
    session.commit()
    a = mk_order(session, u1, product, qty=1, status=DRAFT, number="NK-C1", coupon=coupon)    # both requests passed checkout together
    b = mk_order(session, u2, product, qty=1, status=DRAFT, number="NK-C2", coupon=coupon)
    svc.confirm_whatsapp_received(a.id, staff)
    session.commit()
    with pytest.raises(svc.OrderError, match="coupon ONEONLY"):
        svc.confirm_whatsapp_received(b.id, staff)
    session.rollback()
    assert session.get(Product, product.id).stock_qty == 9           # the refused one took nothing
    assert session.scalar(select(func.count(CouponUsage.id))) == 1 and session.get(Coupon, coupon.id).used_count == 1


# ---------------------------------------------------------------- A: one checkout form = one order
def test_same_token_cannot_create_two_orders_even_after_the_session_token_is_gone(cust, session, catalog):
    _, p = catalog
    add(cust, p, 1)
    tok = checkout_token(cust)
    data = {"address_id": address_id(session, cust.user), "method": "upi_manual", "checkout_token": tok}
    r1 = checkout_post(cust, data, page="/")
    r2 = checkout_post(cust, data, page="/")                          # back button / refresh: the session token was already used up
    assert r1.status_code == r2.status_code == 302 and r1.headers["Location"] == r2.headers["Location"]
    assert session.scalar(select(func.count(Order.id))) == 1


def test_database_refuses_two_orders_with_one_token(app, session):
    u = make_user(session, "user", "idem@x.com")
    for n in ("NK-I1", "NK-I2"):
        session.add(Order(order_number=n, user_id=u.id, shipping_address=ADDR, subtotal=1, total=1, idempotency_key="tok-1234567890abcdef"))
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_checkout_tells_the_customer_which_item_sold_out_and_keeps_the_rest(cust, session, catalog):
    cat, p = catalog
    other = mk(session, cat, 2, name="Ragi Flour", stock_qty=5, final_price=Decimal("50"), mrp=Decimal("50"))
    session.commit()
    add(cust, p, 2)
    add(cust, other, 1)
    session.get(Product, p.id).stock_qty = 1                           # someone else bought one in the meantime
    session.commit()
    r = checkout(cust, session, cust.user)
    assert session.scalar(select(func.count(Order.id))) == 0
    page = cust.get(r.headers["Location"], follow_redirects=True).get_data(as_text=True)
    assert "Only 1" in page and "Millet Soup Mix" in page
    assert session.scalar(select(func.count(CartItem.id))) == 2        # both lines are still in the cart
    session.get(Product, p.id).stock_qty = 0                           # now it is gone completely
    session.commit()
    from app.services import checkout as co
    with pytest.raises(co.CheckoutError, match="just sold out"):
        co.create_pending_order(cust.user, address_id(session, cust.user), "upi_manual", None, None)
    session.rollback()
    assert session.scalar(select(func.count(Order.id))) == 0


# ---------------------------------------------------------------- B: the browser cannot set prices, totals or discounts
def test_price_total_and_discount_fields_are_ignored_and_logged(cust, session, catalog, caplog):
    _, p = catalog
    add(cust, p, 2)
    caplog.set_level(logging.WARNING)
    r = checkout_post(cust, {"address_id": address_id(session, cust.user), "method": "upi_manual", "price": "1", "total": "1", "discount": "99",
                             "delivery_fee": "0", "unit_price": "1"}, page="/")
    assert r.status_code == 302
    order = session.scalar(select(Order))
    assert order.subtotal == Decimal("160.00") and order.discount_total == 0 and order.delivery_fee == Decimal("40.00") and order.total == Decimal("200.00")
    assert order.items[0].unit_price == Decimal("80.00") and order.items[0].mrp == Decimal("100.00")   # snapshot of what the database said
    assert any("SUSPICIOUS price_or_total_field_sent" in m and f"user_id={cust.user.id}" in m for m in caplog.messages)


@pytest.mark.parametrize("qty", ["0", "-1", "1.5", "11", "abc", "99999999999999999999", ""])
def test_bad_quantities_are_rejected_and_logged(cust, session, catalog, caplog, qty):
    _, p = catalog
    caplog.set_level(logging.WARNING)
    r = pj(cust, "/cart/add", {"product_id": p.id, "qty": qty})
    if qty.strip() == "":
        assert r.status_code == 200                                    # an empty box means the default of 1
        return
    assert r.status_code == 422 and session.scalar(select(func.count(CartItem.id))) == 0
    assert any("SUSPICIOUS invalid_product_or_quantity" in m for m in caplog.messages)


def test_hidden_inactive_or_unknown_products_cannot_be_added(cust, session, catalog):
    _, p = catalog
    p.is_active = False
    session.commit()
    assert pj(cust, "/cart/add", {"product_id": p.id, "qty": 1}).status_code == 409
    assert pj(cust, "/cart/add", {"product_id": 987654, "qty": 1}).status_code == 409
    assert session.scalar(select(func.count(CartItem.id))) == 0


def test_a_bundle_price_cannot_be_sent_from_the_browser(cust, session, catalog):
    _, p = catalog
    bundle = Bundle(name="Pair", slug="pair", product_quantities=[{"product_id": p.id, "quantity": 2}], bundle_price=150, is_active=True)
    session.add(bundle)
    session.commit()
    r = post(cust, f"/bundles/{bundle.id}/add", {"bundle_price": "1", "price": "1"}, page="/bundles")
    assert r.status_code == 302
    line = session.scalar(select(CartItem))
    assert line.line_total_override == Decimal("150.00")


# ---------------------------------------------------------------- B: other customers' orders and carts
def test_another_customers_order_is_a_404_and_is_logged(app, session, cust, catalog, caplog):
    other = make_user(session, "user", "other@x.com")
    product = mk(session, catalog[0], 9, stock_qty=5)
    session.commit()
    mk_order(session, other, product, status="placed", number="NK-THEIRS")
    caplog.set_level(logging.WARNING)
    for method, url in (("get", "/account/orders/NK-THEIRS"), ("get", "/account/orders/NK-THEIRS/invoice.pdf"), ("get", "/account/orders/NK-THEIRS/status.json")):
        assert getattr(cust, method)(url).status_code == 404, url
    for action in ("cancel", "return", "reorder"):
        assert post(cust, f"/account/orders/NK-THEIRS/{action}", page="/").status_code == 404, action
    assert session.get(Order, session.scalar(select(Order.id))).status == "placed"
    assert any("SUSPICIOUS other_customers_order" in m and f"user_id={cust.user.id}" in m for m in caplog.messages)


def test_customer_cannot_change_an_order_status_or_open_staff_pages(app, session, cust, catalog):
    product = mk(session, catalog[0], 9, stock_qty=5)
    session.commit()
    order = mk_order(session, cust.user, product, status="placed", number="NK-MINE")
    for url in (f"/owner/orders/{order.id}/status", f"/admin/orders/{order.id}/status", "/owner/inventory"):
        assert post(cust, url, {"status": "delivered", "payment_status": "paid"}, page="/").status_code in (403, 404, 405), url
    assert session.get(Order, order.id).status == "placed" and session.get(Order, order.id).payment_status == "pending"


# ---------------------------------------------------------------- out of stock shows everywhere, including the combo cards
def test_sold_out_combo_shows_out_of_stock_and_notify_me(app, session, catalog):
    _, p = catalog
    p.stock_qty = 0
    session.add(Bundle(name="Festive Pair", slug="festive-pair", product_quantities=[{"product_id": p.id, "quantity": 1}], bundle_price=70, is_active=True))
    session.commit()
    html = app.test_client().get("/offers").get_data(as_text=True)
    assert "Out of stock" in html and f"/product/{p.slug}#notify" in html and "Add bundle to cart" not in html
