from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.extensions import db
from app.models import (
    AuditLog, Coupon, CouponUsage, InventoryLog, Notification, Order, OrderItem, OrderStatusHistory, Payment, Product, ProductVariant,
)
from app.models.base import utcnow
from tests.helpers import make_user, post, sign_in
from tests.test_step2_models import make_category, make_product

ADDR = {"full_name": "Asha Rao", "phone": "9876543210", "line1": "12 Lake Road", "city": "Chennai", "state": "Tamil Nadu", "pincode": "600001"}


@pytest.fixture()
def owner(app, session):
    make_user(session, "owner")
    c = app.test_client()
    sign_in(c, "owner")
    return c


def mk_order(session, customer, product, qty=2, status="placed", number="NK-1001", method="cod", variant=None, coupon=None, **kw):
    """An order as checkout (Step 6) will leave it: stock already taken off the shelf."""
    unit = Decimal("100")
    order = Order(order_number=number, user_id=customer.id, status=status, shipping_address=ADDR, subtotal=unit * qty,
                  total=unit * qty, payment_method=method, payment_status="pending", coupon_id=coupon.id if coupon else None, **kw)
    order.items.append(OrderItem(product_id=product.id, variant_id=variant.id if variant else None, name=product.name, sku=product.sku,
                                 unit_price=unit, mrp=unit, quantity=qty, line_total=unit * qty))
    order.payments.append(Payment(provider="cod" if method == "cod" else "razorpay", amount=unit * qty, status="pending"))
    session.add(order)
    session.commit()
    return order


@pytest.fixture()
def shop(session):
    customer = make_user(session, "user", "buyer@x.com")
    product = make_product(session, stock_qty=10, low_stock_threshold=3)
    session.commit()
    return customer, product


# ---------------------------------------------------------------- access
@pytest.mark.parametrize("url", ["/owner/", "/owner/orders", "/owner/inventory", "/owner/stock-history", "/owner/orders/1", "/owner/password"])
def test_owner_pages_are_owner_only(app, session, url):
    for role in ("user", "admin"):
        make_user(session, role)
        c = app.test_client()
        sign_in(c, role)
        assert c.get(url).status_code == 403
    assert app.test_client().get(url).status_code == 302  # signed out: sent to the owner login


@pytest.mark.parametrize("url", ["/owner/inventory/bulk", "/owner/inventory/product/1/stock", "/owner/inventory/product/1/threshold", "/owner/orders/1/status"])
def test_owner_posts_refuse_admins_and_customers(app, session, url):
    for role in ("user", "admin"):
        make_user(session, role)
        c = app.test_client()
        sign_in(c, role)
        assert post(c, url, {}, page="/").status_code == 403


def test_owner_cannot_reach_admin(app, owner):
    assert owner.get("/admin/").status_code == 403
    assert owner.get("/admin/products").status_code == 403


def test_all_owner_pages_render(owner, session, shop):
    customer, product = shop
    order = mk_order(session, customer, product)
    for url in ("/owner/", "/owner/orders", "/owner/orders?tab=all&q=asha", "/owner/inventory", "/owner/inventory?stock=attention",
                "/owner/stock-history", f"/owner/stock-history?product={product.id}", f"/owner/orders/{order.id}", "/owner/password"):
        r = owner.get(url)
        assert r.status_code == 200, url
    assert owner.get("/owner/orders/99999").status_code == 404


# ---------------------------------------------------------------- dashboard
def test_dashboard_numbers(owner, session, shop):
    customer, product = shop
    mk_order(session, customer, product, status="placed", number="NK-1")
    mk_order(session, customer, product, status="confirmed", number="NK-2")
    mk_order(session, customer, product, status="delivered", number="NK-3")
    mk_order(session, customer, product, status="rejected", number="NK-4")  # never counts as revenue
    low = make_product(session, sku="L1", slug="l1", name="Almost Gone", stock_qty=2, low_stock_threshold=5, category=product.category)
    make_product(session, sku="Z0", slug="z0", name="Sold Out", stock_qty=0, category=product.category)
    session.commit()
    html = owner.get("/owner/").get_data(as_text=True)
    assert "₹400.00" in html            # confirmed + delivered = 2 x 200
    assert "Almost Gone" in html and "Sold Out" in html and "Out of stock" in html
    assert "NK-1" in html                # waiting for confirmation list
    assert ">4<" in html.replace(" ", "") or "4</b>Orders today" in html  # four orders were placed today


# ---------------------------------------------------------------- inline stock edit
def stock_url(kind, id_):
    return f"/owner/inventory/{kind}/{id_}/stock"


def test_inline_stock_edit_logs_who_when_old_new(owner, session, shop):
    _, product = shop
    r = post(owner, stock_url("product", product.id), {"qty": "25", "expected": "10"}, page="/owner/inventory")
    assert r.status_code == 302
    session.expire_all()
    assert session.get(Product, product.id).stock_qty == 25
    log = session.scalar(select(InventoryLog))
    assert (log.old_qty, log.new_qty, log.reason) == (10, 25, "owner edit")
    assert log.changed_by is not None and log.created_at is not None
    assert session.scalar(select(AuditLog).where(AuditLog.action == "stock.set"))
    html = owner.get(f"/owner/stock-history?product={product.id}").get_data(as_text=True)
    assert "10 → <b>25</b>" in html and "Owner" in html and "+15" in html


def test_inline_edit_json_response(owner, session, shop):
    _, product = shop
    r = owner.post(stock_url("product", product.id), data={"qty": "2", "expected": "10", "csrf_token": _tok(owner)}, headers={"Accept": "application/json"})
    assert r.status_code == 200
    body = r.get_json()
    assert body["ok"] and body["qty"] == 2 and body["state"] == "low"  # threshold is 3


def _tok(client):
    from tests.helpers import token
    return token(client, "/owner/inventory")


def test_stale_edit_is_refused_so_an_order_deduction_is_not_overwritten(owner, session, shop):
    _, product = shop
    product.stock_qty = 7  # a customer ordered 3 after the owner opened the page showing 10
    session.commit()
    r = owner.post(stock_url("product", product.id), data={"qty": "50", "expected": "10", "csrf_token": _tok(owner)}, headers={"Accept": "application/json"})
    assert r.status_code == 409 and r.get_json()["current"] == 7
    session.expire_all()
    assert session.get(Product, product.id).stock_qty == 7
    assert session.scalar(select(InventoryLog)) is None


@pytest.mark.parametrize("bad", ["-1", "abc", "", "1.5", "99999999", " "])
def test_inline_edit_validation(owner, session, shop, bad):
    _, product = shop
    r = owner.post(stock_url("product", product.id), data={"qty": bad, "csrf_token": _tok(owner)}, headers={"Accept": "application/json"})
    assert r.status_code == 422
    session.expire_all()
    assert session.get(Product, product.id).stock_qty == 10


def test_unchanged_value_writes_no_history(owner, session, shop):
    _, product = shop
    post(owner, stock_url("product", product.id), {"qty": "10"}, page="/owner/inventory")
    assert session.scalar(select(InventoryLog)) is None


def test_variant_stock_edit(owner, session, shop):
    _, product = shop
    v = ProductVariant(product_id=product.id, option_name="Weight", option_value="500 g", sku="T1-500", price=Decimal("90"), stock_qty=4)
    session.add(v)
    session.commit()
    assert post(owner, stock_url("variant", v.id), {"qty": "9"}, page="/owner/inventory").status_code == 302
    session.expire_all()
    assert session.get(ProductVariant, v.id).stock_qty == 9
    log = session.scalar(select(InventoryLog))
    assert log.variant_id == v.id and log.product_id == product.id and (log.old_qty, log.new_qty) == (4, 9)
    assert "500 g" in owner.get("/owner/inventory").get_data(as_text=True)


def test_archived_product_cannot_be_edited(owner, session, shop):
    _, product = shop
    product.archive()
    session.commit()
    assert owner.post(stock_url("product", product.id), data={"qty": "5", "csrf_token": _tok(owner)}, headers={"Accept": "application/json"}).status_code == 404
    assert product.name not in owner.get("/owner/inventory").get_data(as_text=True)


def test_threshold_edit(owner, session, shop):
    _, product = shop
    r = owner.post(f"/owner/inventory/product/{product.id}/threshold", data={"threshold": "12", "csrf_token": _tok(owner)}, headers={"Accept": "application/json"})
    assert r.status_code == 200 and r.get_json()["state"] == "low"  # 10 <= 12
    session.expire_all()
    assert session.get(Product, product.id).low_stock_threshold == 12
    assert owner.post(f"/owner/inventory/product/{product.id}/threshold", data={"threshold": "-2", "csrf_token": _tok(owner)}, headers={"Accept": "application/json"}).status_code == 422


# ---------------------------------------------------------------- bulk
def two_products(session):
    cat = make_category(session, "Bulk")
    a = make_product(session, sku="A", slug="a", name="Alpha", stock_qty=10, category=cat)
    b = make_product(session, sku="B", slug="b", name="Beta", stock_qty=4, category=cat)
    session.commit()
    return a, b


@pytest.mark.parametrize("action,value,expect", [("set", "7", (7, 7)), ("add", "5", (15, 9)), ("subtract", "3", (7, 1))])
def test_bulk_update(owner, session, action, value, expect):
    a, b = two_products(session)
    r = post(owner, "/owner/inventory/bulk", {"ids": [f"p{a.id}", f"p{b.id}"], "action": action, "value": value, "reason": "stock take"}, page="/owner/inventory")
    assert r.status_code == 302
    session.expire_all()
    assert (session.get(Product, a.id).stock_qty, session.get(Product, b.id).stock_qty) == expect
    assert all(l.reason == f"bulk {action}: stock take" for l in session.scalars(select(InventoryLog)))


def test_bulk_is_all_or_nothing(owner, session):
    a, b = two_products(session)  # b only has 4
    r = post(owner, "/owner/inventory/bulk", {"ids": [f"p{a.id}", f"p{b.id}"], "action": "subtract", "value": "5"}, page="/owner/inventory", follow=True)
    assert "Nothing was changed" in r.get_data(as_text=True)
    session.expire_all()
    assert (session.get(Product, a.id).stock_qty, session.get(Product, b.id).stock_qty) == (10, 4)
    assert session.scalar(select(InventoryLog)) is None


def test_bulk_threshold_and_variants(owner, session):
    a, b = two_products(session)
    v = ProductVariant(product_id=a.id, option_name="Size", option_value="L", sku="A-L", price=Decimal("5"), stock_qty=1)
    session.add(v)
    session.commit()
    post(owner, "/owner/inventory/bulk", {"ids": [f"p{a.id}", f"p{b.id}"], "action": "threshold", "value": "9"}, page="/owner/inventory")
    session.expire_all()
    assert session.get(Product, a.id).low_stock_threshold == session.get(Product, b.id).low_stock_threshold == 9
    post(owner, "/owner/inventory/bulk", {"ids": [f"v{v.id}", f"p{b.id}"], "action": "add", "value": "2"}, page="/owner/inventory")
    session.expire_all()
    assert session.get(ProductVariant, v.id).stock_qty == 3 and session.get(Product, b.id).stock_qty == 6


@pytest.mark.parametrize("data", [
    {"ids": [], "action": "set", "value": "1"},
    {"ids": ["p1"], "action": "", "value": "1"},
    {"ids": ["p1"], "action": "set", "value": "-5"},
    {"ids": ["p1"], "action": "add", "value": "0"},
    {"ids": ["p1"], "action": "set", "value": "x"},
    {"ids": ["p99999"], "action": "set", "value": "1"},
    {"ids": ["1; drop table products"], "action": "set", "value": "1"},
])
def test_bulk_rejects_bad_input(owner, session, data):
    a, _ = two_products(session)
    post(owner, "/owner/inventory/bulk", data, page="/owner/inventory")
    session.expire_all()
    assert session.get(Product, a.id).stock_qty == 10 and session.scalar(select(InventoryLog)) is None


# ---------------------------------------------------------------- inventory list filters
def test_inventory_filters_and_search(owner, session):
    cat = make_category(session, "Mixes")
    make_product(session, sku="S1", slug="s1", name="Soup Mix", stock_qty=0, category=cat)
    make_product(session, sku="S2", slug="s2", name="Millet Bar", stock_qty=3, low_stock_threshold=5, category=cat)
    make_product(session, sku="S3", slug="s3", name="Rice Pack", stock_qty=50, category=cat)
    session.commit()
    names = lambda qs: [n for n in ("Soup Mix", "Millet Bar", "Rice Pack") if n in owner.get("/owner/inventory" + qs).get_data(as_text=True)]
    assert names("?stock=out") == ["Soup Mix"]
    assert names("?stock=low") == ["Millet Bar"]
    assert names("?stock=attention") == ["Soup Mix", "Millet Bar"]
    assert names("?stock=in") == ["Rice Pack"]
    assert names("?q=s3") == ["Rice Pack"]
    assert names("?q=%25") == []  # a percent sign is searched literally, not as a wildcard


# ---------------------------------------------------------------- order workflow
def move(owner, order, to, **extra):
    data = {"to": to, "from_status": order.status, **extra}
    return post(owner, f"/owner/orders/{order.id}/status", data, page="/owner/orders")


def test_happy_path_placed_to_delivered_notifies_and_records(owner, session, shop):
    customer, product = shop
    order = mk_order(session, customer, product)
    for step in ("confirmed", "packed", "shipped", "delivered"):
        session.refresh(order)
        assert move(owner, order, step).status_code == 302
        session.expire_all()
        order = session.get(Order, order.id)
        assert order.status == step
    hist = session.scalars(select(OrderStatusHistory).order_by(OrderStatusHistory.id)).all()
    assert [(h.from_status, h.to_status) for h in hist] == [("placed", "confirmed"), ("confirmed", "packed"), ("packed", "shipped"), ("shipped", "delivered")]
    assert all(h.changed_by for h in hist)
    notes = session.scalars(select(Notification).where(Notification.user_id == customer.id, Notification.channel == "in_app").order_by(Notification.id)).all()
    assert len(notes) == 4 and notes[0].title == "Order NK-1001 confirmed" and notes[-1].link == "/account/orders/NK-1001"
    assert {a.action for a in session.scalars(select(AuditLog))} >= {"order.confirmed", "order.delivered"}
    assert order.payment_status == "paid" and order.payments[0].status == "paid"  # cash collected on delivery
    assert session.get(Product, product.id).stock_qty == 10  # delivering never touches stock


def test_online_payment_status_is_not_changed_by_delivery(owner, session, shop):
    customer, product = shop
    order = mk_order(session, customer, product, status="shipped", method="online")
    move(owner, order, "delivered")
    session.expire_all()
    assert session.get(Order, order.id).payment_status == "pending"


@pytest.mark.parametrize("start,target", [
    ("placed", "packed"), ("placed", "shipped"), ("placed", "delivered"), ("confirmed", "shipped"), ("confirmed", "placed"),
    ("shipped", "rejected"), ("delivered", "shipped"), ("delivered", "rejected"), ("rejected", "confirmed"), ("cancelled", "confirmed"),
    ("shipped", "packed"), ("placed", "bogus"), ("placed", "cancelled"),
])
def test_illegal_moves_are_refused(owner, session, shop, start, target):
    customer, product = shop
    order = mk_order(session, customer, product, status=start)
    move(owner, order, target, reason="a good reason")
    session.expire_all()
    assert session.get(Order, order.id).status == start
    assert session.scalar(select(OrderStatusHistory)) is None and session.scalar(select(Notification)) is None


def test_stale_page_cannot_double_confirm(owner, session, shop):
    customer, product = shop
    order = mk_order(session, customer, product)
    move(owner, order, "confirmed")
    # a second owner/tab still believes it is "placed"
    r = post(owner, f"/owner/orders/{order.id}/status", {"to": "confirmed", "from_status": "placed"}, page="/owner/orders", follow=True)
    assert "nothing was changed" in r.get_data(as_text=True).lower()
    assert len(session.scalars(select(OrderStatusHistory)).all()) == 1


def test_reject_needs_reason_then_restores_stock_and_tells_customer(owner, session, shop):
    customer, product = shop
    product.stock_qty = 8  # 10 on the shelf, 2 taken by this order at checkout
    session.commit()
    order = mk_order(session, customer, product, qty=2)
    for reason in ("", "no", "   x   "):
        move(owner, order, "rejected", reason=reason)
    session.expire_all()
    assert session.get(Order, order.id).status == "placed" and session.get(Product, product.id).stock_qty == 8

    move(owner, order, "rejected", reason="Item is out of stock.")
    session.expire_all()
    o = session.get(Order, order.id)
    assert o.status == "rejected" and o.rejection_reason == "Item is out of stock."
    assert session.get(Product, product.id).stock_qty == 10
    log = session.scalar(select(InventoryLog))
    assert (log.old_qty, log.new_qty) == (8, 10) and "NK-1001 rejected" in log.reason and log.changed_by
    n = session.scalar(select(Notification))
    assert "could not be accepted" in n.title and "out of stock" in n.body
    assert session.scalar(select(OrderStatusHistory)).note == "Item is out of stock."
    assert "Item is out of stock." in owner.get(f"/owner/orders/{order.id}").get_data(as_text=True)


def test_reject_twice_restores_stock_only_once(owner, session, shop):
    customer, product = shop
    product.stock_qty = 8
    session.commit()
    order = mk_order(session, customer, product, qty=2)
    move(owner, order, "rejected", reason="Out of stock today")
    r = post(owner, f"/owner/orders/{order.id}/status", {"to": "rejected", "from_status": "placed", "reason": "Out of stock today"}, page="/owner/orders")
    r2 = post(owner, f"/owner/orders/{order.id}/status", {"to": "rejected", "reason": "Out of stock today"}, page="/owner/orders")
    session.expire_all()
    assert session.get(Product, product.id).stock_qty == 10
    assert len(session.scalars(select(InventoryLog)).all()) == 1


def test_reject_after_confirm_and_pack_is_allowed(owner, session, shop):
    customer, product = shop
    product.stock_qty = 8
    session.commit()
    order = mk_order(session, customer, product, qty=2, status="packed")
    move(owner, order, "rejected", reason="Damaged in packing")
    session.expire_all()
    assert session.get(Order, order.id).status == "rejected" and session.get(Product, product.id).stock_qty == 10


def test_reject_restores_variant_stock_and_coupon(owner, session, shop):
    customer, product = shop
    v = ProductVariant(product_id=product.id, option_name="Weight", option_value="1 kg", sku="T1-1K", price=Decimal("100"), stock_qty=1)
    coupon = Coupon(code="SAVE10", discount_type="percent", discount_value=10, used_count=3)
    session.add_all([v, coupon])
    session.commit()
    order = mk_order(session, customer, product, qty=3, variant=v, coupon=coupon)
    session.add(CouponUsage(coupon_id=coupon.id, user_id=customer.id, order_id=order.id))
    session.commit()
    move(owner, order, "rejected", reason="Cannot deliver there")
    session.expire_all()
    assert session.get(ProductVariant, v.id).stock_qty == 4 and session.get(Product, product.id).stock_qty == 10
    assert session.get(Coupon, coupon.id).used_count == 2
    assert session.scalar(select(CouponUsage)) is None


def test_reject_of_order_whose_product_was_deleted_still_works(owner, session, shop):
    customer, product = shop
    order = mk_order(session, customer, product)
    order.items[0].product_id = None  # permanently deleted product (FK set null)
    session.commit()
    move(owner, order, "rejected", reason="Product discontinued")
    session.expire_all()
    assert session.get(Order, order.id).status == "rejected"


def test_paid_online_rejection_warns_the_owner_about_a_refund(owner, session, shop):
    customer, product = shop
    order = mk_order(session, customer, product, status="placed", method="online")
    order.payment_status = "paid"
    session.commit()
    move(owner, order, "rejected", reason="Out of stock today")
    html = owner.get(f"/owner/orders/{order.id}").get_data(as_text=True)
    assert "Refund the customer" in html
    assert "refunded" in session.scalar(select(Notification)).body


def test_failed_transition_rolls_everything_back(owner, session, shop, monkeypatch):
    customer, product = shop
    product.stock_qty = 8
    session.commit()
    order = mk_order(session, customer, product, qty=2)
    from app.services import orders as svc
    monkeypatch.setattr(svc, "notify", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    owner.application.config["PROPAGATE_EXCEPTIONS"] = False
    r = move(owner, order, "rejected", reason="Out of stock today")
    assert r.status_code == 500
    session.rollback()
    session.expire_all()
    assert session.get(Order, order.id).status == "placed" and session.get(Product, product.id).stock_qty == 8
    assert session.scalar(select(InventoryLog)) is None and session.scalar(select(OrderStatusHistory)) is None


# ---------------------------------------------------------------- orders list
def test_orders_tabs_search_and_counts(owner, session, shop):
    customer, product = shop
    mk_order(session, customer, product, number="NK-A1", status="placed")
    mk_order(session, customer, product, number="NK-B2", status="confirmed")
    mk_order(session, customer, product, number="NK-C3", status="delivered")
    html = owner.get("/owner/orders").get_data(as_text=True)
    assert "NK-A1" in html and "NK-B2" not in html and "Confirm order" in html
    assert "NK-B2" in owner.get("/owner/orders?tab=pack").get_data(as_text=True)
    assert "Mark packed" in owner.get("/owner/orders?tab=pack").get_data(as_text=True)
    all_html = owner.get("/owner/orders?tab=all").get_data(as_text=True)
    assert all(n in all_html for n in ("NK-A1", "NK-B2", "NK-C3"))
    assert "NK-C3" in owner.get("/owner/orders?tab=all&q=c3").get_data(as_text=True)
    assert "NK-A1" in owner.get("/owner/orders?tab=all&q=ASHA").get_data(as_text=True)          # shipping name, any case
    assert "NK-A1" in owner.get("/owner/orders?tab=all&q=98765").get_data(as_text=True)         # phone
    assert "NK-A1" not in owner.get("/owner/orders?tab=all&q=nobody").get_data(as_text=True)
    assert "NK-A1" not in owner.get("/owner/orders?tab=all&q=%25").get_data(as_text=True)
    assert owner.get("/owner/orders?tab=nonsense").status_code == 200


def test_owner_does_not_see_customer_email(owner, session, shop):
    customer, product = shop
    order = mk_order(session, customer, product)
    assert customer.email not in owner.get(f"/owner/orders/{order.id}").get_data(as_text=True)
    assert customer.email not in owner.get("/owner/orders").get_data(as_text=True)


def test_next_redirect_cannot_leave_the_site(owner, session, shop):
    customer, product = shop
    order = mk_order(session, customer, product)
    r = move(owner, order, "confirmed", next="https://evil.example/")
    assert r.status_code == 302 and "evil.example" not in r.headers["Location"]


def test_order_actions_need_csrf(owner, session, shop):
    customer, product = shop
    order = mk_order(session, customer, product)
    assert owner.post(f"/owner/orders/{order.id}/status", data={"to": "confirmed"}).status_code == 400
    assert owner.post(stock_url("product", product.id), data={"qty": "1"}).status_code == 400


def test_pages_send_no_inline_scripts_or_styles(owner, session, shop):
    """The site's CSP only allows files from this site, so inline code would silently not run."""
    customer, product = shop
    order = mk_order(session, customer, product)
    for url in ("/owner/", "/owner/orders", "/owner/inventory", f"/owner/orders/{order.id}", "/owner/stock-history"):
        html = owner.get(url).get_data(as_text=True)
        assert " style=" not in html and "onclick=" not in html and "<script>" not in html, url
