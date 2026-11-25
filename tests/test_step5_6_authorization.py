"""Step 5.6: one customer cannot read or change another customer's address, order, cart, wishlist, review, notification
(or message thread / push subscription). Every attempt must answer 404/403 AND leave the victim's data exactly as it was.
Staff routes (/admin, /owner) must reject customers, and each other, even with real ids.

Setup: `cust` (the victim, user@test.com) owns one of everything; `mallory` (two@x.com) is a second, signed-in customer.
"""
import json
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.models import (
    Address, CartItem, Coupon, CustomerMessage, CustomerMessageThread, Notification, Order, OrderItem, Product, PushSubscription, Review,
    ReviewVote, WishlistItem, User,
)
from app.services import customer_inbox
from tests.helpers import make_user, post, sign_in, token
from tests.test_step5_owner import mk_order
from tests.test_step6_shop import JSON, add, catalog, cust, mk, pj  # noqa: F401  (fixtures)
from tests.test_step7_engage import delivered, second_customer

MARK = "Victim Marker Lane"
ENDPOINT = "https://push.example.test/victim-endpoint-0001"


# ------------------------------------------------------------------ the world
@pytest.fixture()
def world(app, session, cust, catalog):
    """The victim's data (ids and a snapshot of every row) plus a second signed-in customer."""
    cat, product = catalog
    victim = cust.user
    other = mk(session, cat, 2, name="Victim Only Millet", stock_qty=10, final_price=Decimal("50"), mrp=Decimal("60"))
    addr = session.scalar(select(Address).where(Address.user_id == victim.id))
    addr.line1 = f"77 {MARK}"
    order = delivered(session, cust, product, number="NK-V1")
    order.shipping_address = {**order.shipping_address, "line1": f"77 {MARK}"}
    item = order.items[0]
    session.add(WishlistItem(user_id=victim.id, product_id=other.id))
    review = Review(user_id=victim.id, product_id=product.id, order_item_id=item.id, rating=5, title="Victim review title",
                    body="victim review body", status="approved", is_verified_purchase=True)
    session.add(review)
    note = Notification(user_id=victim.id, kind="order_status", title="Victim note title", link="/account/orders/NK-V1")
    session.add(note)
    thread = customer_inbox.create_thread(victim, "Victim subject", "Victim secret body")
    session.add(PushSubscription(user_id=victim.id, endpoint=ENDPOINT, p256dh="p256-victim", auth="auth-victim"))
    session.commit()
    assert add(cust, other).status_code == 200
    cart_item = session.scalar(select(CartItem).where(CartItem.user_id == victim.id))

    mallory = second_customer(app, session)
    mallory.user = session.scalar(select(User).where(User.email == "two@x.com"))
    session.add(Address(user_id=mallory.user.id, label="Home", full_name="Mallory", phone="9876500000", line1="1 Mallory Street",
                        city="Coimbatore", state="Tamil Nadu", pincode="641001", is_default=True))
    session.commit()

    class W:
        pass
    w = W()
    w.victim, w.mallory, w.product, w.other = victim, mallory, product, other
    w.address_id, w.order, w.order_item, w.review_id = addr.id, order, item, review.id
    w.note_id, w.thread_id, w.cart_item_id = note.id, thread.id, cart_item.id
    w.client = cust
    return w


def snapshot(session, w) -> dict:
    """Everything the victim owns, as plain values, so 'unchanged' can be compared exactly."""
    session.expire_all()
    a = session.get(Address, w.address_id)
    o = session.scalar(select(Order).where(Order.order_number == "NK-V1"))
    r = session.get(Review, w.review_id)
    n = session.get(Notification, w.note_id)
    c = session.get(CartItem, w.cart_item_id)
    t = session.get(CustomerMessageThread, w.thread_id)
    p = session.scalar(select(PushSubscription).where(PushSubscription.endpoint == ENDPOINT))
    return {
        "address": a and (a.user_id, a.label, a.full_name, a.phone, a.line1, a.line2, a.city, a.state, a.pincode, a.is_default),
        "address_count": session.scalar(select(func.count(Address.id)).where(Address.user_id == w.victim.id)),
        "order": o and (o.user_id, o.status, o.payment_status, o.total, o.courier_name, o.tracking_id, o.cancelled_at if hasattr(o, "cancelled_at") else None),
        "order_count": session.scalar(select(func.count(Order.id)).where(Order.user_id == w.victim.id)),
        "order_history": session.scalar(select(func.count()).select_from(Order).join(Order.history).where(Order.id == o.id)) if hasattr(Order, "history") else 0,
        "cart": c and (c.user_id, c.session_id, c.product_id, c.quantity, c.saved_for_later),
        "cart_count": session.scalar(select(func.count(CartItem.id)).where(CartItem.user_id == w.victim.id)),
        "wishlist": sorted(session.scalars(select(WishlistItem.product_id).where(WishlistItem.user_id == w.victim.id))),
        "review": r and (r.user_id, r.rating, r.title, r.body, r.status, r.is_deleted, r.helpful_count if hasattr(r, "helpful_count") else None),
        "review_count": session.scalar(select(func.count(Review.id)).where(Review.user_id == w.victim.id)),
        "notification": n and (n.user_id, n.is_read, n.title),
        "thread": t and (t.user_id, t.status, t.subject),
        "messages": session.scalar(select(func.count(CustomerMessage.id)).where(CustomerMessage.thread_id == w.thread_id)),
        "push": p and (p.user_id, p.is_enabled, p.p256dh, p.auth),
        "product_stock": session.scalar(select(Product.stock_qty).where(Product.id == w.product.id)),
    }


def act(c, method, url, data=None, page="/account/addresses", json_reply=False):
    if method == "GET":
        return c.get(url, headers=JSON if json_reply else {})
    return c.post(url, data={**(data or {}), "csrf_token": token(c, page)}, headers=JSON if json_reply else {})


def assert_denied(resp, w, what):
    assert resp.status_code in (403, 404), f"{what}: got {resp.status_code}"
    body = resp.get_data(as_text=True)
    for secret in (MARK, "Victim review title", "Victim note title", "Victim secret body", "Victim subject", "p256-victim"):
        assert secret not in body, f"{what} leaked {secret!r}"


# ------------------------------------------------------------------ orders
ORDER_ROUTES = [
    ("GET", "/account/orders/NK-V1"),
    ("GET", "/account/orders/NK-V1/status.json"),
    ("GET", "/account/orders/NK-V1/invoice.pdf"),
    ("GET", "/order-placed/NK-V1"),
    ("POST", "/account/orders/NK-V1/cancel"),
    ("POST", "/account/orders/NK-V1/return"),
    ("POST", "/account/orders/NK-V1/reorder"),
]


@pytest.mark.parametrize("method,url", ORDER_ROUTES)
def test_another_customers_order_is_a_404_and_unchanged(app, session, world, method, url):
    before = snapshot(session, world)
    resp = act(world.mallory, method, url, {"reason": "damaged", "note": "x"}, page="/account/orders")
    assert_denied(resp, world, f"{method} {url}")
    assert resp.status_code == 404
    assert snapshot(session, world) == before
    assert session.scalar(select(func.count(CartItem.id)).where(CartItem.user_id == world.mallory.user.id)) == 0   # reorder added nothing


def test_the_owner_of_the_order_can_still_use_every_one_of_those_routes(app, session, world):
    """The 404s above are about ownership, not a broken route: the victim gets through."""
    c = world.client
    for method, url in ORDER_ROUTES[:4]:
        resp = act(c, method, url, page="/account/orders")
        assert resp.status_code in (200, 302), f"{url} -> {resp.status_code}"
    assert act(c, "POST", "/account/orders/NK-V1/reorder", page="/account/orders").status_code == 302


def test_my_orders_list_shows_only_my_orders(app, session, world):
    mk_order(session, world.mallory.user, world.product, number="NK-M1")
    mine = world.mallory.get("/account/orders").get_data(as_text=True)
    assert "NK-M1" in mine and "NK-V1" not in mine
    theirs = world.client.get("/account/orders").get_data(as_text=True)
    assert "NK-V1" in theirs and "NK-M1" not in theirs


def test_order_numbers_cannot_be_enumerated_through_error_differences(app, session, world):
    """A real-but-foreign order and a made-up one answer identically (same status, same page)."""
    foreign = world.mallory.get("/account/orders/NK-V1")
    missing = world.mallory.get("/account/orders/NK-NOPE")
    assert foreign.status_code == missing.status_code == 404
    strip = lambda r, n: r.get_data(as_text=True).replace(n, "ORDER")   # the page only echoes the address that was asked for
    assert strip(foreign, "NK-V1") == strip(missing, "NK-NOPE")


# ------------------------------------------------------------------ addresses
@pytest.mark.parametrize("method,suffix,data", [
    ("GET", "edit", None),
    ("POST", "edit", {"label": "X", "full_name": "Mallory", "phone": "9876543210", "line1": "9 Hacked Road", "city": "Chennai",
                      "state": "Tamil Nadu", "pincode": "600001"}),
    ("POST", "default", None),
    ("POST", "delete", None),
])
def test_another_customers_address_is_a_404_and_unchanged(app, session, world, method, suffix, data):
    before = snapshot(session, world)
    resp = act(world.mallory, method, f"/account/addresses/{world.address_id}/{suffix}", data)
    assert_denied(resp, world, f"{method} address {suffix}")
    assert resp.status_code == 404
    assert snapshot(session, world) == before


def test_my_address_list_never_contains_someone_elses(app, session, world):
    page = world.mallory.get("/account/addresses").get_data(as_text=True)
    assert "1 Mallory Street" in page and MARK not in page
    assert MARK in world.client.get("/account/addresses").get_data(as_text=True)


def test_checkout_refuses_another_customers_address(app, session, world):
    """The delivery address id comes from the form, so it is the one place a stranger's id can arrive in a POST."""
    from tests.helpers import checkout_post
    m = world.mallory
    assert add(m, world.product).status_code == 200
    before = snapshot(session, world)
    r = checkout_post(m, {"address_id": world.address_id, "method": "upi_manual"}, page="/", follow=True)
    assert r.status_code == 200
    assert session.scalar(select(func.count(Order.id)).where(Order.user_id == world.mallory.user.id)) == 0
    assert "Choose a delivery address" in r.get_data(as_text=True)
    assert MARK not in r.get_data(as_text=True)
    assert snapshot(session, world) == before   # no stock taken, victim's data untouched
    # the same checkout with Mallory's own address works, so the refusal was about ownership only
    own = session.scalar(select(Address.id).where(Address.user_id == world.mallory.user.id))
    r = checkout_post(m, {"address_id": own, "method": "upi_manual"}, page="/", follow=False)
    assert r.status_code == 302 and "/order-placed/" in r.headers["Location"]


# ------------------------------------------------------------------ cart
@pytest.mark.parametrize("url,data", [
    ("/cart/{id}/qty", {"action": "inc"}),
    ("/cart/{id}/qty", {"qty": "9"}),
    ("/cart/{id}/save", {"saved": "1"}),
    ("/cart/{id}/remove", {}),
])
def test_another_customers_cart_line_cannot_be_changed(app, session, world, url, data):
    before = snapshot(session, world)
    resp = act(world.mallory, "POST", url.format(id=world.cart_item_id), data, page="/cart", json_reply=True)
    assert resp.status_code in (200, 404)
    assert snapshot(session, world) == before
    assert world.other.name not in world.mallory.get("/cart").get_data(as_text=True)


def test_a_guest_cannot_touch_a_signed_in_customers_cart_or_another_guests(app, session, world):
    before = snapshot(session, world)
    guest = app.test_client()
    for url, data in ((f"/cart/{world.cart_item_id}/qty", {"action": "inc"}), (f"/cart/{world.cart_item_id}/remove", {}),
                      (f"/cart/{world.cart_item_id}/save", {"saved": "1"})):
        resp = act(guest, "POST", url, data, page="/", json_reply=True)
        assert resp.status_code in (200, 404)
    assert snapshot(session, world) == before
    # a guest line belongs to that browser only
    assert add(guest, world.product).status_code == 200
    line = session.scalar(select(CartItem).where(CartItem.user_id.is_(None)))
    assert line is not None
    other_guest = app.test_client()
    assert other_guest.get("/cart").status_code == 200
    for url, data in ((f"/cart/{line.id}/qty", {"qty": "5"}), (f"/cart/{line.id}/remove", {}), (f"/cart/{line.id}/save", {"saved": "1"})):
        act(other_guest, "POST", url, data, page="/", json_reply=True)
        act(world.mallory, "POST", url, data, page="/", json_reply=True)
    session.expire_all()
    line = session.get(CartItem, line.id)
    assert line is not None and line.quantity == 1 and not line.saved_for_later


def test_signing_in_never_pulls_in_a_cart_that_is_not_yours(app, session, world):
    """merge_guest_cart only takes the browser's own guest session, never a session id or user id from the request."""
    before = snapshot(session, world)
    c = world.mallory
    resp = c.post("/cart/add", data={"product_id": world.product.id, "qty": 1, "user_id": world.victim.id, "session_id": "x",
                                     "csrf_token": token(c, "/")}, headers=JSON)
    assert resp.status_code == 200
    session.expire_all()
    assert session.scalar(select(func.count(CartItem.id)).where(CartItem.user_id == world.mallory.user.id)) == 1
    assert snapshot(session, world) == before


# ------------------------------------------------------------------ wishlist
def test_wishlist_is_private_and_toggle_only_touches_my_own_row(app, session, world):
    before = snapshot(session, world)
    assert "Victim Only Millet" not in world.mallory.get("/account/wishlist").get_data(as_text=True)
    assert "Victim Only Millet" in world.client.get("/account/wishlist").get_data(as_text=True)
    # Mallory saves and removes the same product: that is her row, and the victim's row stays
    for _ in range(2):
        resp = act(world.mallory, "POST", "/wishlist/toggle", {"product_id": world.other.id}, page="/", json_reply=True)
        assert resp.status_code == 200
        assert snapshot(session, world)["wishlist"] == before["wishlist"]
    # ids that are not hers to send change nothing either
    resp = act(world.mallory, "POST", "/wishlist/toggle", {"product_id": world.other.id, "user_id": world.victim.id}, page="/", json_reply=True)
    assert snapshot(session, world)["wishlist"] == before["wishlist"]
    assert session.scalar(select(func.count(WishlistItem.id)).where(WishlistItem.user_id == world.mallory.user.id)) == 1


def test_wishlist_needs_a_signed_in_customer(app, session, world):
    before = snapshot(session, world)
    guest = app.test_client()
    assert guest.get("/account/wishlist").status_code == 302
    resp = act(guest, "POST", "/wishlist/toggle", {"product_id": world.other.id}, page="/", json_reply=True)
    assert resp.status_code in (302, 401, 403)
    assert session.scalar(select(func.count(WishlistItem.id))) == 1
    assert snapshot(session, world) == before


# ------------------------------------------------------------------ reviews
def test_another_customers_review_cannot_be_deleted(app, session, world):
    before = snapshot(session, world)
    resp = act(world.mallory, "POST", f"/review/{world.review_id}/delete", page="/")
    assert resp.status_code == 404
    assert snapshot(session, world) == before
    assert session.get(Review, world.review_id).is_deleted is False


def test_another_customers_purchase_cannot_be_used_to_post_or_overwrite_a_review(app, session, world):
    """Mallory has bought nothing: sending the victim's order line id must not create or change a review."""
    before = snapshot(session, world)
    slug = world.product.slug
    resp = world.mallory.post(f"/product/{slug}/review", data={"csrf_token": token(world.mallory, f"/product/{slug}"), "rating": "1",
                                                                "title": "Hijack", "body": "hijack", "order_item_id": world.order_item.id})
    assert resp.status_code == 302
    session.expire_all()
    assert session.scalar(select(func.count(Review.id)).where(Review.user_id == world.mallory.user.id)) == 0
    assert snapshot(session, world) == before


def test_reviewing_with_my_own_purchase_never_edits_the_victims_review(app, session, world):
    delivered(session, world.mallory, world.product, number="NK-M2")
    before = snapshot(session, world)
    slug = world.product.slug
    # her own purchase, but the victim's order line id in the form: the review is hers, tied to her line, victim's untouched
    world.mallory.post(f"/product/{slug}/review", data={"csrf_token": token(world.mallory, f"/product/{slug}"), "rating": "2", "title": "Mine",
                                                        "order_item_id": world.order_item.id})
    session.expire_all()
    assert snapshot(session, world) == before
    mine = session.scalars(select(Review).where(Review.user_id == world.mallory.user.id)).all()
    assert len(mine) <= 1 and all(r.order_item_id != world.order_item.id for r in mine)


def test_a_review_vote_is_recorded_for_the_voter_only(app, session, world):
    resp = act(world.mallory, "POST", f"/review/{world.review_id}/helpful", page="/", json_reply=True)
    assert resp.status_code == 200
    votes = session.scalars(select(ReviewVote).where(ReviewVote.review_id == world.review_id)).all()
    assert [v.user_id for v in votes] == [world.mallory.user.id]


# ------------------------------------------------------------------ notifications
def test_another_customers_notification_is_a_404_and_stays_unread(app, session, world):
    before = snapshot(session, world)
    resp = act(world.mallory, "GET", f"/notifications/{world.note_id}/go")
    assert_denied(resp, world, "notification go")
    assert resp.status_code == 404
    assert snapshot(session, world) == before and before["notification"][1] is False


def test_notification_lists_counts_and_read_all_are_per_person(app, session, world):
    before = snapshot(session, world)
    assert "Victim note title" not in world.mallory.get("/notifications").get_data(as_text=True)
    data = world.mallory.get("/notifications/unread.json").get_json()
    assert data["count"] == 0 and data["latest"] == []
    assert world.client.get("/notifications/unread.json").get_json()["count"] >= 1
    act(world.mallory, "POST", "/notifications/read-all", page="/notifications")
    assert snapshot(session, world) == before   # the victim's note is still unread


# ------------------------------------------------------------------ messages and push
@pytest.mark.parametrize("method", ["GET", "POST"])
def test_another_customers_message_thread_is_a_404(app, session, world, method):
    before = snapshot(session, world)
    resp = act(world.mallory, method, f"/account/messages/{world.thread_id}", {"body": "I am not the owner of this thread"}, page="/account/messages")
    assert_denied(resp, world, f"{method} thread")
    assert resp.status_code == 404
    assert snapshot(session, world) == before
    assert "Victim subject" not in world.mallory.get("/account/messages").get_data(as_text=True)


def test_another_customers_push_subscription_cannot_be_switched_off(app, session, world):
    before = snapshot(session, world)
    resp = world.mallory.post("/account/push/unsubscribe", data=json.dumps({"endpoint": ENDPOINT}), content_type="application/json",
                              headers={"X-CSRFToken": token(world.mallory, "/account/orders")})
    assert resp.status_code == 200
    assert snapshot(session, world) == before and before["push"][1] is True


# ------------------------------------------------------------------ nothing is reachable when signed out
SIGNED_OUT = [
    ("GET", "/account/orders/NK-V1"), ("GET", "/account/orders/NK-V1/status.json"), ("GET", "/account/orders/NK-V1/invoice.pdf"),
    ("GET", "/order-placed/NK-V1"), ("POST", "/account/orders/NK-V1/cancel"), ("POST", "/account/orders/NK-V1/reorder"),
    ("GET", "/account/addresses/{a}/edit"), ("POST", "/account/addresses/{a}/delete"), ("POST", "/account/addresses/{a}/default"),
    ("POST", "/review/{r}/delete"), ("GET", "/notifications/{n}/go"), ("GET", "/account/messages/{t}"), ("GET", "/account/wishlist"),
    ("GET", "/notifications"), ("GET", "/account/addresses"),
]


@pytest.mark.parametrize("method,url", SIGNED_OUT)
def test_signed_out_visitors_are_sent_to_login(app, session, world, method, url):
    before = snapshot(session, world)
    url = url.format(a=world.address_id, r=world.review_id, n=world.note_id, t=world.thread_id)
    resp = act(app.test_client(), method, url, page="/login")
    assert resp.status_code in (302, 401), f"{method} {url} -> {resp.status_code}"
    assert "/login" in resp.headers.get("Location", "/login")
    assert snapshot(session, world) == before


# ------------------------------------------------------------------ staff routes reject customers (and each other)
@pytest.fixture()
def staff_world(app, session, world):
    admin, owner = make_user(session, "admin"), make_user(session, "owner")
    coupon = Coupon(code="SAVE10", discount_type="percent", discount_value=Decimal("10"), is_active=True)
    session.add(coupon)
    session.commit()
    world.admin_id, world.owner_id, world.coupon_id = admin.id, owner.id, coupon.id
    world.admin, world.owner = app.test_client(), app.test_client()
    sign_in(world.admin, "admin")
    sign_in(world.owner, "owner")
    return world


def staff_urls(w):
    o, p, u, r, c = w.order.id, w.product.id, w.victim.id, w.review_id, w.coupon_id
    return [
        ("POST", f"/admin/orders/{o}/tracking", "admin"), ("POST", f"/admin/products/{p}/archive", "admin"),
        ("POST", f"/admin/products/{p}/delete", "admin"), ("POST", f"/admin/products/{p}/edit", "admin"),
        ("POST", f"/admin/products/bulk", "admin"), ("POST", f"/admin/coupons/{c}/toggle", "admin"), ("POST", f"/admin/coupons/{c}/delete", "admin"),
        ("POST", f"/admin/users/{u}/block", "admin"), ("POST", f"/admin/users/{u}/reset-password", "admin"),
        ("POST", f"/admin/reviews/{r}/toggle", "admin"), ("POST", f"/admin/reviews/{r}/set", "admin"),
        ("GET", f"/admin/products/{p}/edit", "admin"), ("GET", "/admin/users", "admin"), ("GET", "/admin/products/export.csv", "admin"),
        ("POST", f"/owner/orders/{o}/status", "owner"), ("POST", f"/owner/orders/{o}/payment", "owner"),
        ("POST", f"/owner/orders/{o}/tracking", "owner"), ("POST", f"/owner/inventory/product/{p}/threshold", "owner"),
        ("POST", f"/owner/inventory/product/{p}/batch", "owner"), ("POST", "/owner/inventory/bulk", "owner"),
        ("GET", f"/owner/orders/{o}", "owner"), ("GET", "/owner/orders", "owner"), ("GET", "/owner/inventory", "owner"),
    ]


def staff_state(session, w):
    session.expire_all()
    o = session.get(Order, w.order.id)
    p = session.get(Product, w.product.id)
    u = session.get(User, w.victim.id)
    r = session.get(Review, w.review_id)
    c = session.get(Coupon, w.coupon_id)
    return (o.status, o.payment_status, o.courier_name, o.tracking_id, p.is_active, p.is_deleted, p.stock_qty, p.final_price, p.low_stock_threshold,
            u.is_blocked, u.password_hash, r.status, r.is_deleted, c and c.is_active)


def test_staff_routes_reject_customers_even_with_real_ids_and_change_nothing(app, session, staff_world):
    w = staff_world
    before = staff_state(session, w)
    bad = []
    for method, url, area in staff_urls(w):
        resp = act(w.mallory, method, url, {"status": "cancelled", "is_active": "0", "stock_qty": "0", "tracking_id": "X"}, page="/account/orders")
        if resp.status_code != 403:
            bad.append(f"customer {method} {url} -> {resp.status_code}")
        resp = act(w.client, method, url, {"status": "cancelled"}, page="/account/orders")   # the victim is a customer too
        if resp.status_code != 403:
            bad.append(f"victim {method} {url} -> {resp.status_code}")
    assert not bad, "\n".join(bad)
    assert staff_state(session, w) == before


def test_admin_and_owner_areas_are_separate_and_signed_out_visitors_are_sent_to_login(app, session, staff_world):
    w = staff_world
    before = staff_state(session, w)
    bad = []
    for method, url, area in staff_urls(w):
        wrong = w.owner if area == "admin" else w.admin
        code = act(wrong, method, url, {"status": "cancelled"}, page="/owner/" if area == "admin" else "/admin/").status_code
        if code != 403:
            bad.append(f"{'owner' if area == 'admin' else 'admin'} {method} {url} -> {code}")
        code = act(app.test_client(), method, url, {"status": "cancelled"}, page="/login").status_code
        if code not in (302, 401):
            bad.append(f"signed out {method} {url} -> {code}")
    assert not bad, "\n".join(bad)
    assert staff_state(session, w) == before


def test_the_right_staff_role_still_gets_in(app, session, staff_world):
    """Proof the 403s above come from the role check and not from a broken URL."""
    w = staff_world
    assert w.admin.get(f"/admin/products/{w.product.id}/edit").status_code == 200
    assert w.owner.get(f"/owner/orders/{w.order.id}").status_code == 200


# ------------------------------------------------------------------ a new object route cannot slip in untested
# every customer-facing URL that carries an id or a slug, and why it is safe. Add new ones here on purpose.
TESTED_ABOVE = {
    "shop.order_detail", "shop.order_status_json", "shop.order_invoice", "shop.order_placed", "shop.order_cancel", "shop.order_return",
    "shop.order_reorder", "shop.address_form", "shop.address_default", "shop.address_delete", "shop.cart_qty", "shop.cart_remove",
    "shop.cart_save", "shop.review_delete", "shop.review_helpful", "shop.review_save", "shop.notification_go", "shop.message_thread",
}
PUBLIC_BY_DESIGN = {   # no private object behind the id: catalogue pages, public tools, or an action that only ever uses g.user
    "shop.api_pincode", "shop.category_listing", "shop.product", "shop.recipe_detail", "auth.reset", "media.uploaded",
    "shop.add_bundle", "shop.add_recipe_ingredients",       # add shop items to the caller's own cart
    "shop.stock_alert_toggle",         # keyed by product slug, row is (g.user, product)
}


def test_every_customer_route_with_an_id_is_covered_here_or_public_by_design(app):
    seen = set()
    for rule in app.url_map.iter_rules():
        if rule.arguments and not str(rule).startswith(("/admin", "/owner")) and rule.endpoint != "static":
            seen.add(rule.endpoint)
    missing = seen - TESTED_ABOVE - PUBLIC_BY_DESIGN
    assert not missing, f"new customer routes with an id need an authorization test in test_step5_6_authorization.py: {sorted(missing)}"
    assert not (TESTED_ABOVE | PUBLIC_BY_DESIGN) - seen, "a listed route no longer exists; update the lists"
