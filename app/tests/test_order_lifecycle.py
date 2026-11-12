"""Order lifecycle end to end: owner moves the order along, the customer is notified, the tracker follows, then the customer reviews and
the thank-you popup shows once. Also: moderation, ownership checks and no duplicate notifications."""
import re

import pytest
from sqlalchemy import func, select

from app.models import Notification, Order, OrderStatusHistory, Review
from app.services import orders as svc
from tests.helpers import make_user, post, sign_in
from tests.test_step5_owner import mk_order, move
from tests.test_step2_models import make_product

PW_PAGE = "/login"


@pytest.fixture()
def world(app, session):
    customer = make_user(session, "user", "buyer@x.com")
    other = make_user(session, "user", "other@x.com")
    make_user(session, "owner")
    make_user(session, "admin")
    product = make_product(session, stock_qty=10, low_stock_threshold=3)
    session.commit()
    owner, cust, stranger, admin = app.test_client(), app.test_client(), app.test_client(), app.test_client()
    sign_in(owner, "owner")
    sign_in(admin, "admin")
    assert cust.post("/login", data={"email": "buyer@x.com", "password": "Sup3rSecret!", "csrf_token": _tok(cust, "/login")}).status_code == 302
    assert stranger.post("/login", data={"email": "other@x.com", "password": "Sup3rSecret!", "csrf_token": _tok(stranger, "/login")}).status_code == 302
    return customer, other, product, owner, cust, stranger, admin


def _tok(c, url):
    return re.search(r'name="csrf_token" value="([^"]+)"', c.get(url).get_data(as_text=True)).group(1)


def _notes(session, user):
    return session.scalars(select(Notification).where(Notification.user_id == user.id, Notification.channel == "in_app").order_by(Notification.id)).all()


def test_full_lifecycle(world, session):
    customer, other, product, owner, cust, stranger, admin = world
    order = mk_order(session, customer, product)
    url = f"/account/orders/{order.order_number}"

    html = cust.get(url).get_data(as_text=True)
    assert "Pending" in html and "Out for delivery" in html and "Rate your products" not in html

    expected = [("confirmed", "Great news! Your order has been confirmed and is being prepared."),
                ("packed", None),
                ("shipped", "Your order is on its way! Get ready to receive your package."),
                ("out_for_delivery", "Exciting! Your order is out for delivery and will reach you soon."),
                ("delivered", "Your order has been successfully delivered. We hope you love your purchase!")]
    seen = 0
    for to, msg in expected:
        session.expire_all()
        order = session.get(Order, order.id)
        assert move(owner, order, to).status_code == 302
        session.expire_all()
        notes = _notes(session, customer)
        assert len(notes) == seen + 1, f"exactly one notification for {to}"  # no duplicates
        seen += 1
        if msg:
            assert msg in notes[-1].body and order.order_number in notes[-1].title and notes[-1].link == url
        # the tracker JSON follows the status
        assert cust.get(url + "/status.json").get_json()["status"] == to
    session.expire_all()
    hist = session.scalars(select(OrderStatusHistory).where(OrderStatusHistory.order_id == order.id).order_by(OrderStatusHistory.id)).all()
    assert [h.to_status for h in hist][-5:] == ["confirmed", "packed", "shipped", "out_for_delivery", "delivered"] and all(h.created_at for h in hist)

    # notifications are only the customer's own; the bell endpoint counts them
    assert stranger.get("/notifications/unread.json").get_json()["count"] == 0
    assert cust.get("/notifications/unread.json").get_json()["count"] == 5
    page = cust.get("/notifications").get_data(as_text=True)
    assert "View order" in page or "Rate your products" in page

    # delivered: the tracker is complete and the review form is on the order page
    html = cust.get(url).get_data(as_text=True)
    assert "Rate your products" in html and html.count("is-done") >= 5 and "Pending" not in html

    # another customer cannot see this order, its status, or review it
    assert stranger.get(url).status_code == 404 and stranger.get(url + "/status.json").status_code == 404

    # review from the order page -> popup appears once, review saved and shown
    item_id = order.items[0].id
    data = {"rating": "5", "title": "Lovely", "body": "Tastes great", "order_item_id": str(item_id), "next": url,
            "csrf_token": _tok(cust, url)}
    r = cust.post(f"/product/{product.slug}/review", data=data, content_type="multipart/form-data")
    assert r.status_code == 302 and r.headers["Location"].endswith(url)
    html = cust.get(url).get_data(as_text=True)
    assert 'data-review-thanks' in html and "Thank You for Your Love" in html and "Keep Smiling, Keep Shopping" in html
    assert 'data-review-thanks' not in cust.get(url).get_data(as_text=True)  # once only
    assert "Tastes great" in cust.get(f"/product/{product.slug}").get_data(as_text=True)
    assert 'data-review-thanks' not in cust.get(f"/product/{product.slug}").get_data(as_text=True)

    # duplicate review for the same product is an edit, not a second row
    data["rating"] = "4"; data["csrf_token"] = _tok(cust, url)
    cust.post(f"/product/{product.slug}/review", data=data, content_type="multipart/form-data")
    assert session.scalar(select(func.count(Review.id))) == 1


def test_no_review_before_delivery_and_form_hidden(world, session):
    customer, other, product, owner, cust, stranger, admin = world
    order = mk_order(session, customer, product, status="shipped")
    url = f"/account/orders/{order.order_number}"
    assert "Rate your products" not in cust.get(url).get_data(as_text=True)
    cust.post(f"/product/{product.slug}/review", data={"rating": "5", "csrf_token": _tok(cust, url)}, content_type="multipart/form-data")
    assert session.scalar(select(func.count(Review.id))) == 0


def test_cannot_review_with_someone_elses_order_item(world, session):
    customer, other, product, owner, cust, stranger, admin = world
    order = mk_order(session, customer, product, status="delivered")
    url = "/account/orders"
    r = stranger.post(f"/product/{product.slug}/review", data={"rating": "5", "order_item_id": str(order.items[0].id), "csrf_token": _tok(stranger, url)},
                      content_type="multipart/form-data")
    assert session.scalar(select(func.count(Review.id))) == 0


def test_shipped_can_skip_out_for_delivery(world, session):
    customer, other, product, owner, cust, stranger, admin = world
    order = mk_order(session, customer, product, status="shipped")
    assert move(owner, order, "delivered").status_code == 302
    session.expire_all()
    assert session.get(Order, order.id).status == "delivered"
    # but out_for_delivery cannot go backwards
    order2 = mk_order(session, customer, product, status="out_for_delivery", number="NK-2")
    move(owner, order2, "shipped")
    session.expire_all()
    assert session.get(Order, order2.id).status == "out_for_delivery"
    assert "out_for_delivery" in svc.TRANSITIONS["shipped"]


def test_owner_detail_page_offers_out_for_delivery_button(world, session):
    customer, other, product, owner, cust, stranger, admin = world
    order = mk_order(session, customer, product, status="shipped")
    html = owner.get(f"/owner/orders/{order.id}").get_data(as_text=True)
    assert "Out for delivery" in html and "Skip to delivered" in html


def test_moderation_pending_then_admin_approves(world, session):
    customer, other, product, owner, cust, stranger, admin = world
    order = mk_order(session, customer, product, status="delivered")
    url = f"/account/orders/{order.order_number}"
    assert post(admin, "/admin/reviews/moderation", {"on": "1"}, page="/admin/").status_code == 302
    cust.post(f"/product/{product.slug}/review", data={"rating": "5", "body": "Needs a check", "order_item_id": str(order.items[0].id), "next": url,
                                                      "csrf_token": _tok(cust, url)}, content_type="multipart/form-data")
    session.expire_all()
    rv = session.scalar(select(Review))
    assert rv.status == "pending" and session.get(type(product), product.id).review_count == 0
    assert "Needs a check" not in stranger.get(f"/product/{product.slug}").get_data(as_text=True)
    html = cust.get(url).get_data(as_text=True)
    assert "data-review-thanks" in html and "once the shop approves" in html  # popup still appears, with the approval note

    page = admin.get("/admin/reviews").get_data(as_text=True)
    assert "Approve" in page and "Needs a check" in page and order.order_number in page
    assert post(admin, f"/admin/reviews/{rv.id}/set", {"action": "approve"}, page="/admin/reviews").status_code == 302
    session.expire_all()
    assert session.get(Review, rv.id).status == "approved" and session.get(type(product), product.id).review_count == 1
    assert "Needs a check" in stranger.get(f"/product/{product.slug}").get_data(as_text=True)
    assert any(n.kind == "review_status" for n in _notes(session, customer))

    assert post(admin, f"/admin/reviews/{rv.id}/set", {"action": "reject"}, page="/admin/reviews").status_code == 302
    session.expire_all()
    assert session.get(Review, rv.id).status == "hidden" and session.get(type(product), product.id).review_count == 0


def test_moderation_off_by_default_and_admin_only(world, session):
    customer, other, product, owner, cust, stranger, admin = world
    order = mk_order(session, customer, product, status="delivered")
    url = f"/account/orders/{order.order_number}"
    cust.post(f"/product/{product.slug}/review", data={"rating": "3", "order_item_id": str(order.items[0].id), "next": url, "csrf_token": _tok(cust, url)},
              content_type="multipart/form-data")
    assert session.scalar(select(Review)).status == "approved"
    assert cust.get("/admin/reviews").status_code in (302, 403) and owner.get("/admin/reviews").status_code in (302, 403)
