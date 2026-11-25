"""Step 8: the whole shop, start to finish, using only the real pages and forms (no shortcuts into the database for the steps).

Sign up > address > search > cart > coupon > checkout > owner confirms, packs, ships, delivers > invoice > review > helpful vote
> return > owner accepts and restocks > refund. Then the admin's paper trail, notifications and email.
"""
import re

import pytest
from decimal import Decimal

from sqlalchemy import func, select

from app.models import (
    Address, AuditLog, Coupon, CouponUsage, DeliveryZone, InventoryLog, Notification, Order, OrderStatusHistory, Product, Review,
)
from tests.helpers import PW, checkout_post, checkout_token, confirm_requests, make_user, post, sign_in, signup, token
from tests.test_step2_models import make_category, make_product


def _login(app, session, email):
    make_user(session, "user", email)
    c = app.test_client()
    r = c.post("/login", data={"email": email, "password": PW, "csrf_token": token(c, "/login")})
    assert r.status_code == 302, "sign-in failed"
    return c


def test_full_shop_journey(app, session, monkeypatch):
    # ---- setup the admin would do once
    cat = make_category(session, "Snacks")
    p = make_product(session, category=cat, sku="E2E-1", slug="millet-mix", name="Millet Soup Mix", stock_qty=10,
                     final_price=Decimal("100"), mrp=Decimal("120"))
    session.add(DeliveryZone(pincode="641001", is_serviceable=True, eta_days=2, delivery_fee=40))
    session.add(Coupon(code="SAVE10", discount_type="percent", discount_value=10, min_cart_value=100, per_user_limit=1))
    session.commit()
    pid = p.id
    make_user(session, "owner")
    make_user(session, "admin")
    owner, admin = app.test_client(), app.test_client()
    sign_in(owner, "owner")
    sign_in(admin, "admin")

    # ---- customer signs up through the real form
    cust = app.test_client()
    r = signup(cust, monkeypatch, {"name": "Asha Rao", "email": "asha@example.com", "phone": "9876543210", "password": PW, "confirm": PW})
    assert r.status_code == 302 and r.headers["Location"] == "/account"
    r = post(cust, "/account/addresses/new", {"label": "Home", "full_name": "Asha Rao", "phone": "9876543210", "line1": "12 Lake Road",
                                              "city": "Coimbatore", "state": "Tamil Nadu", "pincode": "641001"},
             page="/account/addresses/new")
    assert r.status_code == 302

    # ---- browse: home, search with a typo, product page
    assert cust.get("/").status_code == 200
    assert "Millet Soup Mix" in cust.get("/shop?q=milet").get_data(as_text=True)
    assert "Millet Soup Mix" in cust.get("/product/millet-mix").get_data(as_text=True)

    # ---- cart and coupon
    assert post(cust, "/cart/add", {"product_id": pid, "qty": 3}, page="/account").status_code in (200, 302)
    assert "Millet Soup Mix" in cust.get("/cart").get_data(as_text=True)
    assert post(cust, "/cart/coupon", {"code": "save10"}, page="/cart").status_code in (200, 302)
    assert "SAVE10" in cust.get("/cart").get_data(as_text=True)

    # ---- checkout, cash on delivery: 3 x 100 = 300, 10% off = 30, delivery 40, total 310
    addr_id = session.scalar(select(Address.id))
    r = checkout_post(cust, {"address_id": addr_id, "method": "upi_manual"}, page="/account")
    assert r.status_code == 302
    number = re.search(r"(NK\d+)", r.headers["Location"]).group(1)
    session.expire_all()
    order = session.scalar(select(Order).where(Order.order_number == number))
    oid = order.id
    assert (order.status, order.subtotal, order.payment_method) == ("pending_whatsapp", Decimal("300.00"), "upi_manual")
    assert order.total == Decimal("310.00")
    assert session.get(Product, pid).stock_qty == 10                      # only a request so far: nothing left the shelf
    assert number not in owner.get("/owner/orders").get_data(as_text=True)  # and the owner's order queue does not show it
    confirm_requests(session)                                             # the shop got the WhatsApp message
    order = session.scalar(select(Order).where(Order.order_number == number))
    assert order.status == "placed"
    assert session.get(Product, pid).stock_qty == 7                       # now the stock left the shelf
    assert session.scalar(select(func.count(CouponUsage.id))) == 1
    assert "empty" in cust.get("/cart").get_data(as_text=True).lower()
    assert number in cust.get("/account/orders").get_data(as_text=True)
    assert cust.get(f"/account/orders/{number}/invoice.pdf").status_code != 200   # no invoice before the owner confirms

    # ---- owner works the order one step at a time; an out-of-order jump is refused
    def move(to, frm, **extra):
        post(owner, f"/owner/orders/{oid}/status", {"to": to, "from_status": frm, **extra}, page="/owner/")
        session.expire_all()
        return session.get(Order, oid).status

    assert number in owner.get("/owner/orders").get_data(as_text=True)
    assert move("shipped", "placed") == "placed"
    assert move("confirmed", "placed") == "confirmed"
    assert move("packed", "confirmed") == "packed"
    assert move("shipped", "packed") == "shipped"
    pdf = cust.get(f"/account/orders/{number}/invoice.pdf")
    assert pdf.status_code == 200 and pdf.data.startswith(b"%PDF") and pdf.mimetype == "application/pdf"
    assert owner.get(f"/owner/orders/{oid}/invoice.pdf").status_code == 200
    assert move("delivered", "shipped") == "delivered"
    assert session.get(Order, oid).payment_status == "pending"            # WhatsApp orders are marked paid by the owner, not by delivery
    page = cust.get(f"/account/orders/{number}").get_data(as_text=True)
    assert all(word in page for word in ("Order received", "Confirmed", "Packed", "Shipped", "Delivered"))

    # ---- notifications and queued email
    assert cust.get("/notifications").status_code == 200
    n_in_app = session.scalar(select(func.count(Notification.id)).where(Notification.user_id == order.user_id, Notification.channel == "in_app"))
    assert n_in_app >= 4
    res = app.test_cli_runner().invoke(args=["send-emails"])
    assert res.exit_code == 0

    # ---- verified review, helpful vote from someone else, admin sees it
    assert post(cust, "/product/millet-mix/review", {"rating": "5", "title": "Great", "body": "Tastes like home"}, page="/account").status_code == 302
    rv = session.scalar(select(Review))
    rid = rv.id
    assert rv.is_verified_purchase and rv.rating == 5
    other = _login(app, session, "other@example.com")
    assert post(other, f"/review/{rid}/helpful", {}, page="/account").status_code in (200, 302)
    session.expire_all()
    assert session.get(Review, rid).helpful_count == 1
    product_page = other.get("/product/millet-mix").get_data(as_text=True)
    assert "Tastes like home" not in product_page and "5.0 ★" in product_page   # only the small average rating, no review list
    assert admin.get("/admin/reviews").status_code == 200

    # ---- return accepted with restock, then refunded
    post(cust, f"/account/orders/{number}/return", {"reason": "Damaged or leaking"}, page="/account")
    session.expire_all()
    assert session.get(Order, oid).status == "delivered"      # customers cannot raise returns any more
    session.get(Order, oid).status = "return_requested"       # an older request still goes through the owner flow
    session.commit()
    assert move("returned", "return_requested", restock="1") == "returned"
    assert session.get(Product, pid).stock_qty == 10                      # all three are back on the shelf
    assert move("refunded", "returned") == "refunded"

    # ---- the paper trail
    statuses = [h.to_status for h in session.scalars(
        select(OrderStatusHistory).where(OrderStatusHistory.order_id == oid).order_by(OrderStatusHistory.id))]
    assert statuses[:2] == ["pending_whatsapp", "placed"] and statuses[-1] == "refunded" and "delivered" in statuses
    assert number in " ".join(r or "" for r in session.scalars(select(InventoryLog.reason).where(InventoryLog.product_id == pid)))
    assert session.scalar(select(func.count(AuditLog.id))) >= 5
    assert admin.get("/admin/audit").status_code == 200


def test_two_customers_race_for_the_last_item(app, session):
    """Two customers request the last unit. Both requests are only requests; the shop can confirm exactly one of them."""
    from app.services import orders as order_svc
    cat = make_category(session, "Snacks")
    p = make_product(session, category=cat, sku="R-1", slug="last-one", name="Last One", stock_qty=1,
                     final_price=Decimal("50"), mrp=Decimal("60"))
    session.add(DeliveryZone(pincode="641001", is_serviceable=True, eta_days=2, delivery_fee=0))
    session.commit()
    pid = p.id
    buyers = []
    for i in (1, 2):
        c = _login(app, session, f"buyer{i}@x.com")
        from app.models import User
        u = session.scalar(select(User).where(User.email == f"buyer{i}@x.com"))
        session.add(Address(user_id=u.id, label="Home", full_name="Buyer", phone="9876543210", line1="1 Road", city="CBE",
                            state="TN", pincode="641001", is_default=True))
        session.commit()
        assert post(c, "/cart/add", {"product_id": pid, "qty": 1}, page="/account").status_code in (200, 302)  # both carts fill while 1 is left
        buyers.append((c, u.id))
    for c, uid in buyers:
        aid = session.scalar(select(Address.id).where(Address.user_id == uid))
        assert "/order-placed/NK" in checkout_post(c, {"address_id": aid, "method": "upi_manual"}, page="/account").headers.get("Location", "")
    session.expire_all()
    assert session.get(Product, pid).stock_qty == 1                       # requests hold nothing
    owner = session.scalar(select(User).where(User.role == "owner")) or make_user(session, "owner", "race-owner@x.com")
    first, second = session.scalars(select(Order).order_by(Order.id)).all()
    order_svc.confirm_whatsapp_received(first.id, owner)
    session.commit()
    with pytest.raises(order_svc.OrderError, match="out of stock"):
        order_svc.confirm_whatsapp_received(second.id, owner)
    session.rollback()
    session.expire_all()
    assert session.get(Order, first.id).status == "placed" and session.get(Order, second.id).status == "pending_whatsapp"
    assert session.get(Product, pid).stock_qty == 0


def test_truly_simultaneous_confirmations_for_the_last_item(app, session):
    """The shop confirming two requests for the last unit at the same instant (two threads, two DB connections), 6 rounds.
    Every round exactly one may become an order, and stock may never go below zero."""
    import threading

    from app.models import User
    from app.services import orders as order_svc

    cat = make_category(session, "Snacks")
    session.add(DeliveryZone(pincode="641001", is_serviceable=True, eta_days=2, delivery_fee=0))
    session.commit()
    cat_id = cat.id
    owner_id = (session.scalar(select(User).where(User.role == "owner")) or make_user(session, "owner", "race-owner@x.com")).id
    users = []
    for i in (1, 2):
        c = _login(app, session, f"racer{i}@x.com")
        u = session.scalar(select(User).where(User.email == f"racer{i}@x.com"))
        session.add(Address(user_id=u.id, label="Home", full_name="R", phone="9876543210", line1="1 Road", city="CBE",
                            state="TN", pincode="641001", is_default=True))
        session.commit()
        users.append((c, u.id))

    for rnd in range(6):
        p = make_product(session, category=session.get(type(cat), cat_id), sku=f"RACE-{rnd}", slug=f"race-{rnd}", name=f"Race {rnd}",
                         stock_qty=1, final_price=Decimal("50"), mrp=Decimal("60"))
        session.commit()
        pid = p.id
        for c, uid in users:
            assert post(c, "/cart/add", {"product_id": pid, "qty": 1}, page="/account").status_code in (200, 302)
            aid = session.scalar(select(Address.id).where(Address.user_id == uid))
            assert "/order-placed/NK" in checkout_post(c, {"address_id": aid, "method": "upi_manual"}, page="/account").headers.get("Location", "")
        from app.models import OrderItem
        order_ids = list(session.scalars(select(Order.id).join(OrderItem, OrderItem.order_id == Order.id).where(OrderItem.product_id == pid, Order.status == "pending_whatsapp")))
        assert len(order_ids) == 2
        gate, results = threading.Barrier(2), []

        def go(order_id):
            with app.app_context():
                from app.extensions import db
                actor = db.session.get(User, owner_id)
                gate.wait()
                try:
                    order_svc.confirm_whatsapp_received(order_id, actor)
                    db.session.commit()
                    results.append("ok")
                except order_svc.OrderError:
                    db.session.rollback()
                    results.append("refused")
                finally:
                    db.session.remove()

        threads = [threading.Thread(target=go, args=(oid,)) for oid in order_ids]
        [t.start() for t in threads]
        [t.join(30) for t in threads]
        session.expire_all()
        assert sorted(results) == ["ok", "refused"], f"round {rnd}: {results}"
        assert session.get(Product, pid).stock_qty == 0, f"round {rnd}: stock {session.get(Product, pid).stock_qty}"
        # close the loser's request and clear the carts so the next round starts clean
        for oid in order_ids:
            if session.get(Order, oid).status == "pending_whatsapp":
                order_svc.discard_request(oid, session.get(User, owner_id))
        from app.models import CartItem
        session.execute(CartItem.__table__.delete())
        session.commit()
