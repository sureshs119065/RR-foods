"""An order exists only after the WhatsApp step is done.

Bug this covers: "Buy Now" showed the WhatsApp page and the order was already recorded on the website, even if the customer never
sent the message or closed the site. Now checkout only records a REQUEST (pending_whatsapp). It becomes an order when the shop
confirms the customer's WhatsApp message arrived, and until then it takes no stock, uses no coupon, empties no cart and does
not appear in the owner's orders, dashboard counts or sales.
"""
from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.models import AuditLog, CartItem, Coupon, CouponUsage, InventoryLog, Notification, Order, OrderStatusHistory, Product
from app.models.base import utcnow
from app.services import orders as order_svc
from tests.helpers import confirm_requests, make_user, post, sign_in
from app.models import User
from tests.test_step6_shop import add, catalog, checkout, coupon, cust  # noqa: F401  (fixtures and helpers)


@pytest.fixture()
def owner_client(app, session, cust):
    make_user(session, "owner")
    c = app.test_client()
    sign_in(c, "owner")
    return c


def buy_now(c, product, qty=2):
    r = post(c, "/buy-now", {"product_id": product.id, "qty": qty}, page="/")
    assert r.status_code == 302 and r.headers["Location"].endswith("/checkout")
    return r


def untouched(session, product, stock=10):
    """Nothing about the shop changed: no stock taken, no coupon used, no sale, no owner/customer announcement."""
    session.expire_all()
    assert session.get(Product, product.id).stock_qty == stock
    assert session.scalar(select(InventoryLog)) is None and session.scalar(select(CouponUsage)) is None
    assert session.scalar(select(Notification)) is None
    assert session.scalar(select(AuditLog).where(AuditLog.action == "order.place")) is None


def test_buy_now_then_whatsapp_page_does_not_place_an_order(app, cust, session, catalog):
    _, p = catalog
    app.config["ADMIN_WHATSAPP_NUMBER"] = "919876500000"
    try:
        buy_now(cust, p, 2)
        r = checkout(cust, session, cust.user)
        assert r.headers["Location"].startswith("/order-placed/NK")
        o = session.scalar(select(Order))
        assert o.status == "pending_whatsapp"
        html = cust.get(r.headers["Location"]).get_data(as_text=True)      # the WhatsApp page, opened and reloaded
        cust.get(r.headers["Location"])
        assert "not placed" in html.lower() and "Open WhatsApp" in html and "https://wa.me/919876500000?text=" in html
        untouched(session, p)
        assert session.scalar(select(CartItem.quantity)) == 2              # the cart is still there: the customer can come back
    finally:
        app.config["ADMIN_WHATSAPP_NUMBER"] = ""


def test_closing_the_site_without_sending_leaves_no_order(cust, session, catalog, owner_client):
    _, p = catalog
    buy_now(cust, p)
    checkout(cust, session, cust.user)                # ...and the customer closes the website here
    untouched(session, p)
    queue = owner_client.get("/owner/orders").get_data(as_text=True)
    o = session.scalar(select(Order))
    assert o.order_number not in queue and "No orders found" in queue
    assert "pending_whatsapp" not in order_svc.REVENUE_STATUSES
    assert session.scalar(select(func.count(Order.id)).where(Order.status.in_(("placed", "confirmed")))) == 0


def test_request_shows_on_its_own_tab_and_the_shop_confirms_it(cust, session, catalog, owner_client):
    _, p = catalog
    cp = coupon(session, code="TEN")
    add(cust, p, 3)
    post(cust, "/cart/coupon", {"code": "TEN"}, page="/cart")
    checkout(cust, session, cust.user)
    o = session.scalar(select(Order))
    assert o.order_number not in owner_client.get("/owner/orders").get_data(as_text=True)
    detail = owner_client.get(f"/owner/orders/{o.id}").get_data(as_text=True)
    assert "Message received" in detail and "Awaiting WhatsApp" not in owner_client.get("/owner/orders").get_data(as_text=True)
    assert owner_client.get(f"/owner/orders/{o.id}/packing-slip").status_code == 404
    # the shop cannot skip the WhatsApp step by moving the status forward
    post(owner_client, f"/owner/orders/{o.id}/status", {"to": "confirmed", "from_status": "pending_whatsapp"}, page="/owner/orders")
    session.expire_all()
    assert session.get(Order, o.id).status == "pending_whatsapp"
    # message received -> a real order
    r = post(owner_client, f"/owner/orders/{o.id}/whatsapp-received", {}, page="/owner/orders")
    assert r.status_code == 302
    session.expire_all()
    o = session.get(Order, o.id)
    assert o.status == "placed" and session.get(Product, p.id).stock_qty == 7
    assert session.get(Coupon, cp.id).used_count == 1 and session.scalar(select(func.count(CartItem.id))) == 0
    assert o.order_number in owner_client.get("/owner/orders").get_data(as_text=True)
    assert "received on WhatsApp" in session.scalar(select(Notification.title).where(Notification.user_id == cust.user.id))
    # pressing it twice changes nothing more
    post(owner_client, f"/owner/orders/{o.id}/whatsapp-received", {}, page="/owner/orders")
    session.expire_all()
    assert session.get(Product, p.id).stock_qty == 7 and session.get(Coupon, cp.id).used_count == 1
    # and the order then follows the normal flow
    post(owner_client, f"/owner/orders/{o.id}/status", {"to": "confirmed", "from_status": "placed"}, page="/owner/orders")
    session.expire_all()
    assert session.get(Order, o.id).status == "confirmed"


def test_confirmation_is_refused_when_the_stock_is_gone(cust, session, catalog, owner_client):
    _, p = catalog
    add(cust, p, 5)
    checkout(cust, session, cust.user)
    o = session.scalar(select(Order))
    p.stock_qty = 2                                   # someone else got it in the meantime
    session.commit()
    post(owner_client, f"/owner/orders/{o.id}/whatsapp-received", {}, page="/owner/orders")
    session.expire_all()
    assert session.get(Order, o.id).status == "pending_whatsapp" and session.get(Product, p.id).stock_qty == 2
    assert session.scalar(select(InventoryLog)) is None and session.scalar(select(CartItem.quantity)) == 5


def test_shop_can_close_a_request_that_never_arrived(cust, session, catalog, owner_client):
    _, p = catalog
    add(cust, p)
    checkout(cust, session, cust.user)
    o = session.scalar(select(Order))
    post(owner_client, f"/owner/orders/{o.id}/discard-request", {}, page="/owner/orders")
    session.expire_all()
    assert session.get(Order, o.id).status == "cancelled"
    untouched(session, p)
    with pytest.raises(order_svc.OrderError):         # a closed request cannot be turned into an order afterwards
        order_svc.confirm_whatsapp_received(o.id, session.scalar(select(User).where(User.role == "owner")))
    session.rollback()


def test_customer_can_cancel_a_request_without_touching_stock_or_the_owner(cust, session, catalog):
    _, p = catalog
    make_user(session, "owner", "o2@x.com")
    add(cust, p, 2)
    checkout(cust, session, cust.user)
    o = session.scalar(select(Order))
    post(cust, f"/account/orders/{o.order_number}/cancel", {}, page="/", follow=True)
    session.expire_all()
    assert session.get(Order, o.id).status == "cancelled"
    untouched(session, p)                             # stock was never taken, so none is "given back", and no owner notification exists
    assert session.scalar(select(InventoryLog)) is None


def test_same_checkout_twice_is_one_request_and_a_changed_cart_replaces_it(cust, session, catalog):
    _, p = catalog
    add(cust, p, 2)
    checkout(cust, session, cust.user)
    checkout(cust, session, cust.user)                # new token, same cart: still the same request (and the same WhatsApp order number)
    assert session.scalar(select(func.count(Order.id))) == 1
    add(cust, p, 1)                                   # the customer changes the cart: a new request replaces the old one
    checkout(cust, session, cust.user)
    session.expire_all()
    statuses = sorted(o.status for o in session.scalars(select(Order)))
    assert statuses == ["cancelled", "pending_whatsapp"]
    assert [i.quantity for i in session.scalar(select(Order).where(Order.status == "pending_whatsapp")).items] == [3]
    untouched(session, p)


def test_requests_do_not_count_as_orders_anywhere(cust, session, catalog):
    _, p = catalog
    add(cust, p)
    checkout(cust, session, cust.user)
    assert "pending_whatsapp" in order_svc.NO_PAYMENT_CHANGE and "pending_whatsapp" not in order_svc.REVENUE_STATUSES
    from app.services.invoice import NOT_INVOICEABLE
    assert "pending_whatsapp" in NOT_INVOICEABLE
    assert cust.get("/account").status_code == 200
    o = session.scalar(select(Order))
    assert cust.get(f"/account/orders/{o.order_number}").status_code == 200
    assert "not placed yet" in cust.get(f"/account/orders/{o.order_number}").get_data(as_text=True).lower()
    assert cust.get(f"/account/orders/{o.order_number}/invoice.pdf").status_code != 200


def test_order_page_for_a_confirmed_order_goes_to_tracking_not_the_whatsapp_page(cust, session, catalog):
    _, p = catalog
    add(cust, p)
    r = checkout(cust, session, cust.user)
    confirm_requests(session)
    o = session.scalar(select(Order))
    r2 = cust.get(r.headers["Location"])
    assert r2.status_code == 302 and r2.headers["Location"].endswith(f"/account/orders/{o.order_number}")


def test_stale_requests_expire_and_leave_no_trace(app, cust, session, catalog):
    _, p = catalog
    add(cust, p)
    checkout(cust, session, cust.user)
    o = session.scalar(select(Order))
    assert order_svc.expire_stale_requests(48) == 0   # fresh: kept
    o.created_at = utcnow() - timedelta(hours=49)
    session.commit()
    res = app.test_cli_runner().invoke(args=["expire-order-requests", "--hours", "48"])
    assert res.exit_code == 0 and "closed 1" in res.output
    session.expire_all()
    assert session.get(Order, o.id).status == "cancelled"
    untouched(session, p)
    assert [h.to_status for h in session.scalars(select(OrderStatusHistory).order_by(OrderStatusHistory.id))] == ["pending_whatsapp", "cancelled"]


# ================================================================ cancellation rules and shipment details
from datetime import date  # noqa: E402

from app.services import tracking as tracking_svc  # noqa: E402


def _placed_with_shipment(cust, session, p):
    """A placed order that already carries courier details and an expected delivery date (as if set earlier)."""
    add(cust, p, 2)
    checkout(cust, session, cust.user)
    o = confirm_requests(session)[0]
    o.courier_name, o.tracking_id, o.tracking_url = "DTDC", "TRK123", "https://courier.example/t/TRK123"
    o.delivery_date = date(2026, 12, 1)
    session.commit()
    return o


@pytest.mark.parametrize("status", ["confirmed", "packed", "shipped", "out_for_delivery"])
def test_customer_cannot_cancel_once_the_shop_has_confirmed(cust, session, catalog, status):
    _, p = catalog
    o = _placed_with_shipment(cust, session, p)
    o.status = status
    session.commit()
    page = cust.get(f"/account/orders/{o.order_number}").get_data(as_text=True)
    assert "Cancel order" not in page and "/cancel" not in page                      # no button on the tracking page
    assert "can no longer be cancelled" in page
    r = post(cust, f"/account/orders/{o.order_number}/cancel", {}, page="/", follow=True)   # and a direct request is refused too
    assert "can no longer be cancelled" in r.get_data(as_text=True)
    session.expire_all()
    o = session.get(Order, o.id)
    assert o.status == status and o.courier_name == "DTDC" and session.get(Product, p.id).stock_qty == 8


def test_customer_can_still_cancel_before_the_shop_confirms(cust, session, catalog):
    _, p = catalog
    o = _placed_with_shipment(cust, session, p)
    page = cust.get(f"/account/orders/{o.order_number}").get_data(as_text=True)
    assert "Cancel order" in page and "until the shop confirms" in page
    post(cust, f"/account/orders/{o.order_number}/cancel", {}, page="/", follow=True)
    session.expire_all()
    assert session.get(Order, o.id).status == "cancelled"


def test_cancelled_order_shows_no_shipment_or_delivery_date_anywhere(cust, session, catalog, owner_client):
    _, p = catalog
    o = _placed_with_shipment(cust, session, p)
    before = cust.get(f"/account/orders/{o.order_number}").get_data(as_text=True)
    assert "Shipment details" in before and "TRK123" in before                      # (shown while it is a live order)
    post(cust, f"/account/orders/{o.order_number}/cancel", {}, page="/", follow=True)
    session.expire_all()
    o = session.get(Order, o.id)
    assert (o.courier_name, o.tracking_id, o.tracking_url, o.delivery_date, o.delivery_slot) == (None, None, None, None, None)   # removed, not just hidden
    page = cust.get(f"/account/orders/{o.order_number}").get_data(as_text=True)
    for gone in ("Shipment details", "Expected delivery", "TRK123", "DTDC", "Track package", "01 Dec", "1 December", "Courier"):
        assert gone not in page, gone
    j = cust.get(f"/account/orders/{o.order_number}/status.json").get_json()
    assert j["status"] == "cancelled" and not any(j[k] for k in ("courier_name", "tracking_id", "tracking_url", "delivery_date", "delivery_slot"))
    # the shop's own screens do not offer or show shipment details either, and cannot add them
    owner_page = owner_client.get(f"/owner/orders/{o.id}").get_data(as_text=True)
    assert "Courier tracking details" not in owner_page and "Expected delivery" not in owner_page and "Download invoice" not in owner_page
    assert "Expected delivery" not in owner_client.get("/owner/orders").get_data(as_text=True)
    post(owner_client, f"/owner/orders/{o.id}/tracking", {"courier_name": "DTDC", "tracking_id": "NEW", "expected_delivery": "2026-12-05"}, page=f"/owner/orders/{o.id}")
    session.expire_all()
    assert session.get(Order, o.id).tracking_id is None and session.get(Order, o.id).delivery_date is None
    with pytest.raises(ValueError):
        tracking_svc.update_tracking(session.get(Order, o.id), "X", "Y", "", None)


def test_rejected_order_also_loses_its_shipment_details(cust, session, catalog, owner_client):
    _, p = catalog
    o = _placed_with_shipment(cust, session, p)
    post(owner_client, f"/owner/orders/{o.id}/status", {"to": "rejected", "from_status": "placed", "reason": "Not deliverable"}, page="/owner/orders")
    session.expire_all()
    o = session.get(Order, o.id)
    assert o.status == "rejected" and (o.courier_name, o.tracking_id, o.delivery_date) == (None, None, None)
    page = cust.get(f"/account/orders/{o.order_number}").get_data(as_text=True)
    assert "Shipment details" not in page and "Expected delivery" not in page
