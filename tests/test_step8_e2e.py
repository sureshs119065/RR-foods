"""Step 8: the whole shop, start to finish, using only the real pages and forms (no shortcuts into the database for the steps).

Sign up > address > search > cart > coupon > checkout > owner confirms, packs, ships, delivers > invoice > review > helpful vote
> return > owner accepts and restocks > refund. Then the admin's paper trail, notifications and email.
"""
import re
from decimal import Decimal

from sqlalchemy import func, select

from app.models import (
    Address, AuditLog, Coupon, CouponUsage, DeliveryZone, InventoryLog, Notification, Order, OrderStatusHistory, Product, Review,
)
from tests.helpers import PW, checkout_post, checkout_token, make_user, post, sign_in, token
from tests.test_step2_models import make_category, make_product


def _login(app, session, email):
    make_user(session, "user", email)
    c = app.test_client()
    r = c.post("/login", data={"email": email, "password": PW, "csrf_token": token(c, "/login")})
    assert r.status_code == 302, "sign-in failed"
    return c


def test_full_shop_journey(app, session):
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
    r = cust.post("/register", data={"name": "Asha Rao", "email": "asha@example.com", "phone": "9876543210", "password": PW,
                                     "confirm": PW, "csrf_token": token(cust, "/register")})
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
    assert (order.status, order.subtotal, order.payment_method) == ("placed", Decimal("300.00"), "upi_manual")
    assert order.total == Decimal("310.00")
    assert session.get(Product, pid).stock_qty == 7                       # stock left the shelf at once
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
    assert all(word in page for word in ("Placed", "Confirmed", "Packed", "Shipped", "Delivered"))

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
    assert "Tastes like home" in other.get("/product/millet-mix").get_data(as_text=True)
    assert admin.get("/admin/reviews").status_code == 200

    # ---- return accepted with restock, then refunded
    post(cust, f"/account/orders/{number}/return", {"reason": "Damaged or leaking"}, page="/account")
    session.expire_all()
    assert session.get(Order, oid).status == "return_requested"
    assert move("returned", "return_requested", restock="1") == "returned"
    assert session.get(Product, pid).stock_qty == 10                      # all three are back on the shelf
    assert move("refunded", "returned") == "refunded"

    # ---- the paper trail
    statuses = [h.to_status for h in session.scalars(
        select(OrderStatusHistory).where(OrderStatusHistory.order_id == oid).order_by(OrderStatusHistory.id))]
    assert statuses[0] == "placed" and statuses[-1] == "refunded" and "delivered" in statuses
    assert number in " ".join(r or "" for r in session.scalars(select(InventoryLog.reason).where(InventoryLog.product_id == pid)))
    assert session.scalar(select(func.count(AuditLog.id))) >= 5
    assert admin.get("/admin/audit").status_code == 200


def test_two_customers_race_for_the_last_item(app, session):
    """Two checkouts for one remaining unit: exactly one order is created and stock never goes negative."""
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
    wins = 0
    for c, uid in buyers:
        aid = session.scalar(select(Address.id).where(Address.user_id == uid))
        loc = checkout_post(c, {"address_id": aid, "method": "upi_manual"}, page="/account").headers.get("Location", "")
        wins += "/order-placed/NK" in loc
    session.expire_all()
    assert wins == 1
    assert session.scalar(select(func.count(Order.id))) == 1
    assert session.get(Product, pid).stock_qty == 0


def test_truly_simultaneous_checkouts_for_the_last_item(app, session):
    """Two checkouts fired at the same instant from separate threads (separate DB connections), repeated 6 times.
    Every round exactly one order may be created, and stock may never go below zero."""
    import threading

    from app.models import User

    cat = make_category(session, "Snacks")
    session.add(DeliveryZone(pincode="641001", is_serviceable=True, eta_days=2, delivery_fee=0))
    session.commit()
    cat_id = cat.id
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
        jobs = []
        for c, uid in users:
            assert post(c, "/cart/add", {"product_id": pid, "qty": 1}, page="/account").status_code in (200, 302)
            aid = session.scalar(select(Address.id).where(Address.user_id == uid))
            jobs.append((c, aid, token(c, "/account"), checkout_token(c)))
        gate, results = threading.Barrier(2), []

        def go(c, aid, tok, ctok):
            gate.wait()
            r = c.post("/checkout", data={"address_id": aid, "method": "upi_manual", "csrf_token": tok, "checkout_token": ctok})
            results.append(r.headers.get("Location", ""))

        threads = [threading.Thread(target=go, args=j) for j in jobs]
        [t.start() for t in threads]
        [t.join(30) for t in threads]
        session.expire_all()
        from app.models import OrderItem
        sold = session.scalar(select(func.count(OrderItem.id)).where(OrderItem.product_id == pid))
        assert sold == 1, f"round {rnd}: {sold} orders for 1 unit"
        assert session.get(Product, pid).stock_qty == 0, f"round {rnd}: stock {session.get(Product, pid).stock_qty}"
        assert sum("/order-placed/NK" in loc for loc in results) == 1, f"round {rnd}: {results}"
        # clear leftover cart lines of the loser so the next round starts clean
        from app.models import CartItem
        session.execute(CartItem.__table__.delete())
        session.commit()
