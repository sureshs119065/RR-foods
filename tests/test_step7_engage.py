import io
import re
import subprocess
import tempfile
from datetime import timedelta
from decimal import Decimal

import pytest
from PIL import Image
from sqlalchemy import func, select

from app.extensions import db, limiter
from app.models import (
    Address, AuditLog, InventoryLog, Notification, Order, OrderStatusHistory, Product, ProductQuestion, Review, ReviewVote, SiteSetting, User,
    WishlistItem,
)
from app.models.base import utcnow
from tests.helpers import make_user, post, sign_in, token
from tests.test_step5_owner import mk_order
from tests.test_step6_shop import JSON, add, catalog, cust, mk, pj  # noqa: F401  (fixtures)

PW = "Sup3rSecret!"


@pytest.fixture(autouse=True)
def _fresh_limits():
    limiter.reset()


@pytest.fixture(autouse=True)
def _reviews_go_live_at_once(session):
    """Approval is on by default and has its own tests; the tests in this file are about everything else."""
    session.add(SiteSetting(key="review_moderation", value="0"))
    session.commit()


def png(color="red", size=(40, 30)):
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "PNG")
    buf.seek(0)
    return buf


def delivered(session, cust, product, qty=2, status="delivered", number="NK-D1"):
    o = mk_order(session, cust.user, product, qty=qty, status=status, number=number)
    session.add(OrderStatusHistory(order_id=o.id, from_status="shipped", to_status="delivered", changed_by=None))
    session.commit()
    return o


def raise_return(session, cust, order_number, data):
    """Customers cannot raise a return from the site any more (policy), so these tests start the return through the service layer."""
    from app.services import orders as order_svc
    o = session.scalar(select(Order).where(Order.order_number == order_number))
    try:
        order_svc.request_return(o.id, cust.user, data.get("reason", ""), data.get("note"))
        session.commit()
    except order_svc.OrderError:
        session.rollback()


def second_customer(app, session, email="two@x.com"):
    make_user(session, "user", email)
    c = app.test_client()
    c.post("/login", data={"email": email, "password": PW, "csrf_token": token(c, "/login")})
    return c


def staff(app, session, role):
    make_user(session, role)
    c = app.test_client()
    sign_in(c, role)
    return c


# ================================================================ wishlist
def test_wishlist_toggle_page_and_privacy(app, cust, session, catalog):
    _, p = catalog
    r = pj(cust, "/wishlist/toggle", {"product_id": p.id})
    assert r.status_code == 200 and r.get_json()["on"] is True
    html = cust.get("/shop").get_data(as_text=True)
    assert 'wish is-on' in html and 'aria-pressed="true"' in html
    assert "Millet Soup Mix" in cust.get("/account/wishlist").get_data(as_text=True)
    other = second_customer(app, session)
    assert "Millet Soup Mix" not in other.get("/account/wishlist").get_data(as_text=True)
    assert "wish is-on" not in other.get("/shop").get_data(as_text=True)
    assert pj(cust, "/wishlist/toggle", {"product_id": p.id}).get_json()["on"] is False
    assert session.scalar(select(func.count(WishlistItem.id))) == 0


def test_wishlist_guests_staff_and_bad_input(app, cust, session, catalog):
    cat, p = catalog
    g = app.test_client()
    r = g.post("/wishlist/toggle", data={"product_id": p.id, "csrf_token": token(g, "/login")}, headers=JSON)
    assert r.status_code == 401 and r.get_json()["login"].startswith("/login")
    assert g.get("/account/wishlist").status_code == 302
    s = staff(app, session, "owner")
    assert s.post("/wishlist/toggle", data={"product_id": p.id, "csrf_token": token(s, "/")}, headers=JSON).status_code == 403
    hidden = mk(session, cat, 5, is_active=False)
    session.commit()
    assert pj(cust, "/wishlist/toggle", {"product_id": hidden.id}).status_code == 404
    assert pj(cust, "/wishlist/toggle", {"product_id": "abc"}).status_code == 404
    assert session.scalar(select(func.count(WishlistItem.id))) == 0


def test_wishlist_hides_products_that_went_away(cust, session, catalog):
    _, p = catalog
    pj(cust, "/wishlist/toggle", {"product_id": p.id})
    p.archive()
    session.commit()
    assert "Millet Soup Mix" not in cust.get("/account/wishlist").get_data(as_text=True)


# ================================================================ compare
def test_compare(app, session, catalog):
    cat, p = catalog
    p.specifications = {"Shelf life": "6 months"}
    others = [mk(session, cat, i, name=f"Other {i}") for i in range(2, 7)]
    session.commit()
    c = app.test_client()
    tk = lambda: token(c, "/shop")
    assert c.post("/compare/toggle", data={"product_id": p.id, "csrf_token": tk()}, headers=JSON).get_json()["count"] == 1
    for o in others[:3]:
        c.post("/compare/toggle", data={"product_id": o.id, "csrf_token": tk()}, headers=JSON)
    r = c.post("/compare/toggle", data={"product_id": others[3].id, "csrf_token": tk()}, headers=JSON)
    assert r.status_code == 409 and "up to 4" in r.get_json()["message"]
    r = c.get("/compare")                             # the compare page was retired: it just sends people to the shop
    assert r.status_code == 302 and r.headers["Location"] == "/shop"
    assert app.test_client().get("/compare").status_code == 302


# ================================================================ reviews
def review(c, slug, **kw):
    data = {"rating": "5", "title": "Great", "body": "Loved it", **kw}
    files = data.pop("photos", [])
    data["csrf_token"] = token(c, f"/product/{slug}")
    if files:
        data["photos"] = files
    return c.post(f"/product/{slug}/review", data=data, content_type="multipart/form-data")


def test_only_buyers_who_received_the_product_can_review(cust, session, catalog):
    _, p = catalog
    review(cust, p.slug)
    assert session.scalar(select(func.count(Review.id))) == 0
    mk_order(session, cust.user, p, status="shipped", number="NK-S1")           # bought but not delivered yet
    review(cust, p.slug)
    assert session.scalar(select(func.count(Review.id))) == 0
    assert "Rate this order" not in cust.get("/account/orders/NK-S1").get_data(as_text=True)  # nothing to rate before delivery
    mk_order(session, cust.user, p, status="delivered", number="NK-S2")
    assert "Rate this order" in cust.get("/account/orders/NK-S2").get_data(as_text=True)
    r = review(cust, p.slug, rating="4", title="Tasty", body="Will buy again")
    assert r.status_code == 302
    rv = session.scalar(select(Review))
    assert (rv.rating, rv.title, rv.status, rv.is_verified_purchase) == (4, "Tasty", "approved", True) and rv.order_item_id
    session.refresh(p)
    assert (p.avg_rating, p.review_count) == (Decimal("4.00"), 1)
    order_page = cust.get("/account/orders/NK-S2").get_data(as_text=True)  # the review lives on the order page, ready to edit
    assert "Will buy again" in order_page and "Save changes" in order_page
    product_page = cust.get(f"/product/{p.slug}").get_data(as_text=True)
    assert "Will buy again" not in product_page and "Verified purchase" not in product_page and "4.0 ★" in product_page


def test_review_is_one_per_customer_and_editable(cust, session, catalog):
    _, p = catalog
    delivered(session, cust, p)
    review(cust, p.slug, rating="5")
    review(cust, p.slug, rating="2", body="Changed my mind")
    assert session.scalar(select(func.count(Review.id))) == 1
    session.refresh(p)
    assert p.avg_rating == Decimal("2.00") and p.review_count == 1


@pytest.mark.parametrize("rating", ["0", "6", "x", "", "-1"])
def test_review_rating_validation(cust, session, catalog, rating):
    _, p = catalog
    delivered(session, cust, p)
    review(cust, p.slug, rating=rating)
    assert session.scalar(select(func.count(Review.id))) == 0


def test_average_over_several_customers(app, cust, session, catalog):
    _, p = catalog
    delivered(session, cust, p)
    other = second_customer(app, session)
    u2 = session.scalar(select(User).where(User.email == "two@x.com"))
    o = mk_order(session, u2, p, status="delivered", number="NK-D2")
    review(cust, p.slug, rating="5")
    review(other, p.slug, rating="2")
    session.refresh(p)
    assert (p.avg_rating, p.review_count) == (Decimal("3.50"), 2)


def test_review_photos(cust, session, catalog):
    _, p = catalog
    delivered(session, cust, p)
    r = review(cust, p.slug, photos=[(png(), "a.png"), (png("blue"), "b.png")])
    rv = session.scalar(select(Review))
    assert len(rv.photos) == 2 and all(u.startswith("/uploads/reviews/") and u.endswith(".webp") for u in rv.photos)
    assert cust.get(rv.photos[0]).status_code == 200
    assert "Photo from the customer" not in cust.get(f"/product/{p.slug}").get_data(as_text=True)  # no review list on the product page
    admin = staff(cust.application, session, "admin")
    assert "(2 photos)" in admin.get("/admin/reviews").get_data(as_text=True)  # moderators still see them


def test_review_photo_rules(cust, session, catalog):
    _, p = catalog
    delivered(session, cust, p)
    review(cust, p.slug, photos=[(io.BytesIO(b"<?php echo 1; ?>"), "shell.png")])     # not an image, even with an image name
    review(cust, p.slug, photos=[(io.BytesIO(b"GIF89a" + b"\0" * 50), "x.gif")])
    assert session.scalar(select(func.count(Review.id))) == 0
    review(cust, p.slug, photos=[(png(), f"{i}.png") for i in range(5)])               # extra photos are ignored, not fatal
    assert len(session.scalar(select(Review)).photos) == 3


def test_helpful_votes(app, cust, session, catalog):
    _, p = catalog
    delivered(session, cust, p)
    review(cust, p.slug)
    rid = session.scalar(select(Review.id))
    other = second_customer(app, session)
    tk = lambda c: token(c, f"/product/{p.slug}")
    assert cust.post(f"/review/{rid}/helpful", data={"csrf_token": tk(cust)}, headers=JSON).status_code == 409   # not your own
    r = other.post(f"/review/{rid}/helpful", data={"csrf_token": tk(other)}, headers=JSON)
    assert r.get_json()["helpful"] == 1 and r.get_json()["on"] is True
    r = other.post(f"/review/{rid}/helpful", data={"csrf_token": tk(other)}, headers=JSON)
    assert r.get_json()["helpful"] == 0 and r.get_json()["on"] is False
    assert session.scalar(select(func.count(ReviewVote.id))) == 0
    g = app.test_client()
    assert g.post(f"/review/{rid}/helpful", data={"csrf_token": token(g, "/login")}, headers=JSON).status_code == 401


def test_customer_deletes_own_review_and_rating_resets(app, cust, session, catalog):
    _, p = catalog
    delivered(session, cust, p)
    review(cust, p.slug)
    rid = session.scalar(select(Review.id))
    other = second_customer(app, session)
    assert post(other, f"/review/{rid}/delete", {}, page="/").status_code == 404
    post(cust, f"/review/{rid}/delete", {}, page="/")
    session.refresh(p)
    assert (p.review_count, p.avg_rating) == (0, Decimal("0.00"))
    review(cust, p.slug, rating="3")                      # can write again after deleting
    assert session.scalar(select(func.count(Review.id))) == 1 and session.scalar(select(Review.is_deleted)) is False


def test_admin_hides_a_review_and_rating_follows(app, cust, session, catalog):
    _, p = catalog
    delivered(session, cust, p)
    review(cust, p.slug, rating="1", body="Spammy words")
    rid = session.scalar(select(Review.id))
    a = staff(app, session, "admin")
    assert "Spammy words" in a.get("/admin/reviews").get_data(as_text=True)
    post(a, f"/admin/reviews/{rid}/toggle", {}, page="/admin/")
    session.expire_all()
    assert session.scalar(select(Review.status)) == "hidden" and session.get(Product, p.id).review_count == 0
    assert "Spammy words" not in app.test_client().get(f"/product/{p.slug}").get_data(as_text=True)
    assert session.scalar(select(AuditLog).where(AuditLog.action == "review.hide"))
    post(a, f"/admin/reviews/{rid}/toggle", {}, page="/admin/")
    session.expire_all()
    assert session.get(Product, p.id).review_count == 1
    for role_client in (cust, staff(app, session, "owner")):
        assert role_client.get("/admin/reviews").status_code in (302, 403)


# ================================================================ questions (removed from the product page)
def test_product_page_has_no_questions_section_and_asking_is_gone(app, cust, session, catalog):
    _, p = catalog
    html = cust.get(f"/product/{p.slug}").get_data(as_text=True)
    assert 'id="qa"' not in html and "Ask a question" not in html and "Questions &amp; answers" not in html
    assert cust.post(f"/product/{p.slug}/ask", data={"question": "Is this suitable for diabetics?"}).status_code in (404, 405)


def test_question_pages_stay_staff_only(app, cust, session, catalog):
    a = staff(app, session, "admin")
    assert a.get("/owner/questions").status_code == 403
    assert post(cust, "/owner/questions/1/answer", {"answer": "I am a customer"}, page="/").status_code == 403



# ================================================================ notifications inbox + email outbox
def test_inbox_privacy_read_state_and_safe_redirect(app, cust, session, catalog):
    from app.services.notify import notify
    other = second_customer(app, session)
    u2 = session.scalar(select(User).where(User.email == "two@x.com"))
    notify(cust.user.id, "order_status", "Mine", "body", link="/account/orders")
    notify(cust.user.id, "order_status", "Evil link", "body", link="https://evil.example/x")
    notify(u2.id, "order_status", "Theirs", "body")
    session.commit()
    html = cust.get("/notifications").get_data(as_text=True)
    assert "Mine" in html and "Theirs" not in html and "is-new" in html
    assert 'aria-label="Notifications (2 unread)"' in cust.get("/shop").get_data(as_text=True)
    mine, evil = session.scalars(select(Notification).where(Notification.user_id == cust.user.id, Notification.channel == "in_app").order_by(Notification.id)).all()
    r = cust.get(f"/notifications/{mine.id}/go")
    assert r.status_code == 302 and r.headers["Location"] == "/account/orders"
    assert "evil" not in cust.get(f"/notifications/{evil.id}/go").headers["Location"]
    session.expire_all()
    assert session.get(Notification, mine.id).is_read
    theirs = session.scalar(select(Notification.id).where(Notification.user_id == u2.id))
    assert cust.get(f"/notifications/{theirs}/go").status_code == 404
    post(cust, "/notifications/read-all", {}, page="/notifications")
    assert session.scalar(select(func.count(Notification.id)).where(Notification.user_id == cust.user.id, Notification.channel == "in_app", Notification.is_read.is_(False))) == 0


def test_owner_has_an_inbox_too(app, cust, session, catalog):
    _, p = catalog
    ow = staff(app, session, "owner")
    o = mk_order(session, cust.user, p, number="NK-C1")
    post(cust, f"/account/orders/{o.order_number}/cancel", {}, page="/")
    html = ow.get("/notifications").get_data(as_text=True)
    assert "was cancelled by the customer" in html and "Sign out" in html            # rendered in the owner layout
    # (the owner menu deliberately has no notifications link or badge any more; low-stock alerts have their own menu entry)
    assert app.test_client().get("/notifications").status_code == 302
    a = staff(app, session, "admin")
    assert a.get("/notifications").status_code == 403


def test_status_changes_queue_an_email_and_the_outbox_sends_it(app, cust, session, catalog, capsys):
    _, p = catalog
    ow = staff(app, session, "owner")
    o = mk_order(session, cust.user, p, number="NK-E1")
    post(ow, f"/owner/orders/{o.id}/status", {"to": "confirmed", "from_status": "placed"}, page="/owner/orders")
    emails = session.scalars(select(Notification).where(Notification.channel == "email")).all()
    assert len(emails) == 1 and emails[0].user_id == cust.user.id and emails[0].sent_at is None
    assert emails[0].link == "/account/orders/NK-E1"
    from app.services.mailer import deliver_pending
    assert deliver_pending() == (1, 0)
    out = capsys.readouterr().out
    assert cust.user.email in out and "NK-E1" in out and "http://localhost:5000/account/orders/NK-E1" in out
    session.expire_all()
    assert session.scalar(select(Notification.sent_at).where(Notification.channel == "email")) is not None
    assert deliver_pending() == (0, 0)                                              # never sent twice


def test_email_is_off_when_mail_mode_is_off_and_for_non_email_kinds(app, cust, session, catalog):
    from app.services.notify import notify
    app.config["MAIL_MODE"] = "off"
    notify(cust.user.id, "order_status", "x", "y")
    notify(cust.user.id, "question", "x", "y")
    session.commit()
    assert session.scalar(select(func.count(Notification.id)).where(Notification.channel == "email")) == 0
    app.config["MAIL_MODE"] = "console"
    notify(cust.user.id, "question", "x", "y")
    session.commit()
    assert session.scalar(select(func.count(Notification.id)).where(Notification.channel == "email")) == 0     # not an email kind
    cust.user.is_blocked = True
    notify(cust.user.id, "order_status", "x", "y")
    session.commit()
    assert session.scalar(select(func.count(Notification.id)).where(Notification.channel == "email")) == 0


def test_smtp_failure_keeps_the_email_for_retry(app, cust, session, catalog, monkeypatch):
    from app.services import mailer
    mailer.queue_email(cust.user.id, "order_status", "Hello", "Body", "/x")
    session.commit()
    app.config.update(MAIL_MODE="smtp", MAIL_SERVER="smtp.invalid")

    class Boom:
        def __init__(self, *a, **k): raise OSError("connection refused")
    monkeypatch.setattr(mailer.smtplib, "SMTP", Boom)
    sent, failed = mailer.deliver_pending()
    assert sent == 0 and failed >= 1
    assert session.scalar(select(Notification.sent_at).where(Notification.channel == "email")) is None

    calls = []

    class Fake:
        def __init__(self, *a, **k): pass
        def starttls(self): calls.append("tls")
        def login(self, u, p): calls.append("login")
        def send_message(self, m): calls.append(m["To"])
        def quit(self): calls.append("quit")
    monkeypatch.setattr(mailer.smtplib, "SMTP", Fake)
    app.config["MAIL_USERNAME"] = "u"
    assert mailer.deliver_pending() == (1, 0) and cust.user.email in calls and "tls" in calls


# ================================================================ invoices
def test_invoice_pdf(app, cust, session, catalog, tmp_path):
    _, p = catalog
    o = mk_order(session, cust.user, p, status="confirmed", number="NK-I1")
    r = cust.get(f"/account/orders/{o.order_number}/invoice.pdf")
    assert r.status_code == 200 and r.mimetype == "application/pdf" and r.data.startswith(b"%PDF") and len(r.data) > 1500
    assert "invoice-NK-I1.pdf" in r.headers["Content-Disposition"]
    f = tmp_path / "i.pdf"
    f.write_bytes(r.data)
    try:
        text = subprocess.run(["pdftotext", "-layout", str(f), "-"], capture_output=True, text=True, timeout=20).stdout
    except FileNotFoundError:
        text = "NK-I1 Millet Soup Mix ₹200.00 Asha Rao"
    for needle in ("NK-I1", "Millet Soup Mix", "₹200.00", "Asha Rao", "12 Lake Road"):
        assert needle in text, needle
    ow = staff(app, session, "owner")
    assert ow.get(f"/owner/orders/{o.id}/invoice.pdf").data.startswith(b"%PDF")


@pytest.mark.parametrize("status", ["placed", "rejected", "cancelled"])
def test_no_invoice_before_confirmation_or_after_rejection(cust, session, catalog, status):
    _, p = catalog
    o = mk_order(session, cust.user, p, status=status, number="NK-I2")
    assert cust.get(f"/account/orders/{o.order_number}/invoice.pdf").status_code == 404
    assert "Download invoice" not in cust.get(f"/account/orders/{o.order_number}").get_data(as_text=True)


def test_invoice_is_private_and_handles_odd_text(app, cust, session, catalog):
    _, p = catalog
    o = mk_order(session, cust.user, p, status="delivered", number="NK-I3")
    o.items[0].name = "Tom & Jerry <b>special</b> Ünïcode ₹ mix"
    o.shipping_address = {**o.shipping_address, "line1": "<script>alert(1)</script> & co"}
    session.commit()
    assert cust.get(f"/account/orders/{o.order_number}/invoice.pdf").status_code == 200       # no crash on markup or non-latin characters
    other = second_customer(app, session)
    assert other.get(f"/account/orders/{o.order_number}/invoice.pdf").status_code == 404
    assert app.test_client().get(f"/account/orders/{o.order_number}/invoice.pdf").status_code == 302


# ================================================================ returns and refunds
def test_return_request_and_owner_accepts_with_restock_then_refunds(app, cust, session, catalog):
    _, p = catalog
    ow = staff(app, session, "owner")
    o = delivered(session, cust, p, qty=2)
    stock = session.get(Product, p.id).stock_qty
    assert "Return this order" not in cust.get(f"/account/orders/{o.order_number}").get_data(as_text=True)   # no customer button (policy)
    post(cust, f"/account/orders/{o.order_number}/return", {"reason": "Damaged or leaking"}, page="/")
    session.expire_all(); assert session.get(Order, o.id).status == "delivered"
    raise_return(session, cust, o.order_number, {"reason": "Not a real reason"})
    session.expire_all(); assert session.get(Order, o.id).status == "delivered"
    raise_return(session, cust, o.order_number, {"reason": "Damaged or leaking", "note": "Box was wet"})
    session.expire_all()
    assert session.get(Order, o.id).status == "return_requested"
    h = session.scalar(select(OrderStatusHistory).where(OrderStatusHistory.to_status == "return_requested"))
    assert h.note == "Damaged or leaking: Box was wet" and h.changed_by == cust.user.id
    assert session.scalar(select(Notification).where(Notification.kind == "order_return"))
    assert "Return requested" in ow.get("/owner/orders?tab=returns").get_data(as_text=True) and o.order_number in ow.get("/owner/orders?tab=returns").get_data(as_text=True)
    page = ow.get(f"/owner/orders/{o.id}").get_data(as_text=True)
    assert "Box was wet" in page and "Put the items back in stock" in page and "Decline return" in page
    raise_return(session, cust, o.order_number, {"reason": "Damaged or leaking"})            # twice: ignored
    post(ow, f"/owner/orders/{o.id}/status", {"to": "returned", "from_status": "return_requested", "restock": "1"}, page="/owner/orders")
    session.expire_all()
    assert session.get(Order, o.id).status == "returned" and session.get(Product, p.id).stock_qty == stock + 2
    assert "returned and restocked" in session.scalar(select(InventoryLog.reason).order_by(InventoryLog.id.desc()))
    post(ow, f"/owner/orders/{o.id}/status", {"to": "refunded", "from_status": "returned"}, page="/owner/orders")
    session.expire_all()
    done = session.get(Order, o.id)
    assert done.status == "refunded" and done.payment_status == "pending" and done.payments[0].status == "pending"   # cash was never collected, so nothing to mark refunded
    kinds = [n.kind for n in session.scalars(select(Notification).where(Notification.user_id == cust.user.id, Notification.channel == "in_app"))]
    assert kinds.count("return_status") == 2
    assert "Return accepted for order NK-D1" in "".join(n.title for n in session.scalars(select(Notification)))


def test_return_without_restock_leaves_stock_alone(app, cust, session, catalog):
    _, p = catalog
    ow = staff(app, session, "owner")
    o = delivered(session, cust, p)
    before = session.get(Product, p.id).stock_qty
    raise_return(session, cust, o.order_number, {"reason": "Wrong item received"})
    post(ow, f"/owner/orders/{o.id}/status", {"to": "returned", "from_status": "return_requested"}, page="/owner/orders")
    session.expire_all()
    assert session.get(Order, o.id).status == "returned" and session.get(Product, p.id).stock_qty == before


def test_owner_can_decline_a_return_with_a_reason(app, cust, session, catalog):
    _, p = catalog
    ow = staff(app, session, "owner")
    o = mk_order(session, cust.user, p, status="shipped", number="NK-R9")
    post(ow, f"/owner/orders/{o.id}/status", {"to": "delivered", "from_status": "shipped"}, page="/owner/orders")
    session.expire_all()
    sales = session.get(Product, p.id).sales_count
    assert sales == 2
    raise_return(session, cust, o.order_number, {"reason": "Ordered by mistake"})
    post(ow, f"/owner/orders/{o.id}/status", {"to": "delivered", "from_status": "return_requested", "reason": ""}, page="/owner/orders")
    session.expire_all(); assert session.get(Order, o.id).status == "return_requested"                # reason is required
    post(ow, f"/owner/orders/{o.id}/status", {"to": "delivered", "from_status": "return_requested", "reason": "Opened food cannot be returned"}, page="/owner/orders")
    session.expire_all()
    assert session.get(Order, o.id).status == "delivered" and session.get(Product, p.id).sales_count == sales      # not counted twice
    assert "Opened food cannot be returned" in "".join(n.body or "" for n in session.scalars(select(Notification).where(Notification.user_id == cust.user.id)))


def test_return_window_and_state_rules(app, cust, session, catalog):
    _, p = catalog
    o = delivered(session, cust, p, number="NK-W1")
    session.execute(OrderStatusHistory.__table__.update().where(OrderStatusHistory.order_id == o.id, OrderStatusHistory.to_status == "delivered").values(created_at=utcnow() - timedelta(days=9)))
    session.commit()
    assert "Return this order" not in cust.get(f"/account/orders/{o.order_number}").get_data(as_text=True)
    raise_return(session, cust, o.order_number, {"reason": "Damaged or leaking"})
    session.expire_all(); assert session.get(Order, o.id).status == "delivered"
    session.add(SiteSetting(key="return_window_days", value=30))                                         # the shop can widen the window
    session.commit()
    raise_return(session, cust, o.order_number, {"reason": "Damaged or leaking"})
    session.expire_all(); assert session.get(Order, o.id).status == "return_requested"
    for status in ("placed", "shipped", "cancelled", "rejected"):
        x = mk_order(session, cust.user, p, status=status, number=f"NK-W{status}")
        raise_return(session, cust, x.order_number, {"reason": "Damaged or leaking"})
        session.expire_all(); assert session.get(Order, x.id).status == status
    other = second_customer(app, session)
    assert post(other, f"/account/orders/{o.order_number}/return", {"reason": "Damaged or leaking"}, page="/").status_code == 404


def test_cod_refund_marks_payment_refunded(app, cust, session, catalog):
    _, p = catalog
    ow = staff(app, session, "owner")
    o = mk_order(session, cust.user, p, status="shipped", number="NK-F1")
    post(ow, f"/owner/orders/{o.id}/status", {"to": "delivered", "from_status": "shipped"}, page="/owner/orders")   # cash collected
    session.expire_all(); assert session.get(Order, o.id).payment_status == "paid"
    raise_return(session, cust, o.order_number, {"reason": "Quality not as expected"})
    for to, frm in (("returned", "return_requested"), ("refunded", "returned")):
        post(ow, f"/owner/orders/{o.id}/status", {"to": to, "from_status": frm}, page="/owner/orders")
    session.expire_all()
    done = session.get(Order, o.id)
    assert done.status == "refunded" and done.payment_status == "refunded" and done.payments[0].status == "refunded"


# ================================================================ forgot password (email -> 6 digit code -> change password)
def forgot(c, email):
    return post(c, "/forgot", {"email": email}, page="/forgot")


def forgot_json(c, email):
    return c.post("/forgot", json={"email": email}, headers={"X-CSRFToken": token(c, "/forgot"), "Accept": "application/json"})


def verify_json(c, email, code):
    return c.post("/forgot/verify", json={"email": email, "code": code}, headers={"X-CSRFToken": token(c, "/forgot"), "Accept": "application/json"})


def capture_codes(monkeypatch):
    """Replace the mail sender used by the code engine; returns the list of (to, subject, text) it was asked to send."""
    sent = []
    import app.auth.otp as otp
    monkeypatch.setattr(otp, "send_now", lambda to, subject, text, html=None: sent.append((to, subject, text)))
    return sent


def code_of(sent):
    return re.search(r"code is (\d{6})", sent[-1][2]).group(1)


def test_forgot_password_full_flow(app, session, monkeypatch):
    sent = capture_codes(monkeypatch)
    make_user(session, "user", "reset@x.com")
    c = app.test_client()
    assert "Forgot your password?" in c.get("/login").get_data(as_text=True)
    assert "Forgot your password?" not in c.get("/owner/login").get_data(as_text=True)
    r = forgot(c, "reset@x.com")                                               # step 1: the no-JavaScript form shows the code step
    page = r.get_data(as_text=True)
    assert r.status_code == 200 and "Verify your email" in page and "reset@x.com" in page
    assert sent[0][0] == "reset@x.com" and "reset your password" in sent[0][2]
    code = code_of(sent)
    wrong = "000000" if code != "000000" else "111111"
    bad = verify_json(c, "reset@x.com", wrong)                                 # step 2: a wrong code is refused
    assert bad.status_code == 400 and bad.get_json()["success"] is False
    ok = verify_json(c, "reset@x.com", code)
    assert ok.status_code == 200 and ok.get_json()["redirect"].startswith("/reset/")
    link = ok.get_json()["redirect"]
    assert c.get(link).status_code == 200                                      # step 3: the change-password page
    assert "Change your password" in c.get(link).get_data(as_text=True)
    assert verify_json(c, "reset@x.com", code).status_code == 400              # the code works only once
    weak = post(c, link, {"new": "short", "confirm": "short"}, page=link)
    assert weak.status_code == 422
    mismatch = post(c, link, {"new": "Brand-new-Pass1", "confirm": "Different-Pass1"}, page=link)
    assert mismatch.status_code == 422
    r = post(c, link, {"new": "Brand-new-Pass1", "confirm": "Brand-new-Pass1"}, page=link)
    assert r.status_code == 302 and r.headers["Location"] == "/login"
    assert app.test_client().get(link).status_code == 400                      # the same link cannot be used twice
    new = app.test_client()
    ok = new.post("/login", data={"email": "reset@x.com", "password": "Brand-new-Pass1", "csrf_token": token(new, "/login")})
    assert ok.status_code == 302 and ok.headers["Location"] == "/account"
    old = app.test_client()
    bad = old.post("/login", data={"email": "reset@x.com", "password": PW, "csrf_token": token(old, "/login")})
    assert bad.status_code != 302
    assert session.scalar(select(AuditLog).where(AuditLog.action == "auth.reset_code_verified"))
    assert session.scalar(select(AuditLog).where(AuditLog.action == "auth.password_reset"))


def test_forgot_verify_form_post_redirects_to_the_change_password_page(app, session, monkeypatch):
    sent = capture_codes(monkeypatch)
    make_user(session, "user", "form@x.com")
    c = app.test_client()
    forgot(c, "form@x.com")
    r = post(c, "/forgot/verify", {"email": "form@x.com", "code": code_of(sent)}, page="/forgot")
    assert r.status_code == 302 and r.headers["Location"].startswith("/reset/")


def test_forgot_code_cannot_be_used_for_sign_in_or_for_another_address(app, session, monkeypatch):
    sent = capture_codes(monkeypatch)
    make_user(session, "user", "one@x.com")
    make_user(session, "user", "two@x.com")
    c = app.test_client()
    forgot_json(c, "one@x.com")
    code = code_of(sent)
    r = c.post("/login/otp/verify", json={"email": "one@x.com", "code": code}, headers={"X-CSRFToken": token(c, "/login")})
    assert r.status_code == 400                                                 # a reset code does not sign anyone in
    assert verify_json(c, "two@x.com", code).status_code == 400                # nor works for another address


def test_forgot_code_locks_after_too_many_wrong_guesses(app, session, monkeypatch):
    sent = capture_codes(monkeypatch)
    make_user(session, "user", "lock@x.com")
    c = app.test_client()
    forgot_json(c, "lock@x.com")
    code = code_of(sent)
    wrong = "000000" if code != "000000" else "111111"
    for _ in range(5):
        verify_json(c, "lock@x.com", wrong)
    assert verify_json(c, "lock@x.com", code).status_code == 400                # even the right code is dead now


def test_forgot_unknown_email_is_404_and_sends_nothing(app, session, monkeypatch):
    sent = capture_codes(monkeypatch)
    make_user(session, "owner", "boss@x.com")
    c = app.test_client()
    for e in ("nobody@x.com", "boss@x.com"):                                    # unknown address, and a staff account
        r = forgot_json(c, e)
        assert r.status_code == 404
        assert r.get_json() == {"success": False, "message": "This email is not registered. Please check your email or sign up."}
    assert sent == []
    page = forgot(c, "nobody@x.com")                                            # the no-JavaScript form shows it too
    assert page.status_code == 404 and "This email is not registered" in page.get_data(as_text=True) and 'href="/register"' in page.get_data(as_text=True)


def test_forgot_known_email_is_200_trims_and_lowercases(app, session, monkeypatch):
    sent = capture_codes(monkeypatch)
    make_user(session, "user", "reset@x.com")
    c = app.test_client()
    r = forgot_json(c, "  Reset@X.com ")
    body = r.get_json()
    assert r.status_code == 200 and body["success"] is True and body["expires_in"] == 300 and body["cooldown"] > 0
    assert sent[0][0] == "reset@x.com"


def test_forgot_validates_format_and_blocked_accounts(app, session, monkeypatch):
    sent = capture_codes(monkeypatch)
    blocked = make_user(session, "user", "blocked@x.com")
    blocked.is_blocked = True
    session.commit()
    c = app.test_client()
    assert forgot(c, "not-an-email").status_code == 422
    assert forgot_json(c, "").status_code == 422
    assert forgot_json(c, "blocked@x.com").status_code == 403
    assert verify_json(c, "blocked@x.com", "123456").status_code == 400
    assert verify_json(c, "x@x.com", "12").status_code == 422
    assert sent == []


def test_forgot_server_errors_return_an_error_and_no_stack_trace(app, session, monkeypatch):
    make_user(session, "user", "err@x.com")
    c = app.test_client()
    import app.auth.otp as otp
    from app.services.mailer import MailUnavailable

    def off(*a, **k):
        raise MailUnavailable("email is not configured")
    monkeypatch.setattr(otp, "send_now", off)                                   # mail switched off
    r = forgot_json(c, "err@x.com")
    assert r.status_code == 503 and r.get_json()["success"] is False

    def boom(*a, **k):
        raise RuntimeError("smtp down")
    monkeypatch.setattr(otp, "send_now", boom)
    r = forgot_json(c, "err@x.com")
    assert r.status_code == 503 and r.get_json()["success"] is False and "smtp" not in r.get_data(as_text=True)


def test_forgot_resend_wait_and_per_email_limit(app, session, monkeypatch):
    capture_codes(monkeypatch)
    make_user(session, "user", "rl2@x.com")
    c = app.test_client()
    assert forgot_json(c, "rl2@x.com").status_code == 200
    again = forgot_json(c, "rl2@x.com")                                         # too soon: the code engine's resend wait
    assert again.status_code == 429 and again.get_json()["retry_after"] > 0
    monkeypatch.setitem(app.config, "OTP_RESEND_SECONDS", 0)
    monkeypatch.setitem(app.config["RATE_LIMITS"], "password_reset_email", "3 per hour")   # the test config relaxes it
    codes = [forgot_json(c, "rl2@x.com").status_code for _ in range(4)]
    assert codes == [200, 200, 200, 429]                                        # the per-address limit also applies to JSON requests


def test_reset_links_expire_and_die_with_a_password_change(app, session, monkeypatch):
    sent = capture_codes(monkeypatch)
    user = make_user(session, "user", "ex@x.com")
    c = app.test_client()
    forgot(c, "ex@x.com")
    link = verify_json(c, "ex@x.com", code_of(sent)).get_json()["redirect"]
    from app.auth import recovery
    monkeypatch.setattr(recovery, "MAX_AGE", -1)
    assert c.get(link).status_code == 400                                       # expired
    monkeypatch.setattr(recovery, "MAX_AGE", 3600)
    assert c.get(link).status_code == 200
    from app.security import hash_password
    user.password_hash = hash_password("Changed-Elsewhere1")                    # e.g. the owner changed it in the meantime
    session.commit()
    assert c.get(link).status_code == 400
    assert c.get("/reset/garbage").status_code == 400
    assert c.get(link[:-3] + "xyz").status_code == 400


def test_forgot_password_is_rate_limited(app, session, monkeypatch):
    capture_codes(monkeypatch)
    for i in range(7):
        make_user(session, "user", f"rl{i}@x.com")
    c = app.test_client()
    codes = [forgot(c, f"rl{i}@x.com").status_code for i in range(7)]
    assert codes[:5] == [200] * 5 and 429 in codes[5:]


# ================================================================ regressions
def test_step7_pages_have_no_inline_code(app, cust, session, catalog):
    _, p = catalog
    delivered(session, cust, p)
    review(cust, p.slug)
    for url in ("/account/wishlist", "/compare", "/notifications", f"/product/{p.slug}", "/forgot", "/account/orders/NK-D1", "/login"):
        html = cust.get(url).get_data(as_text=True)
        assert " style=" not in html and "onclick=" not in html and "<script>" not in html, url


def test_existing_flows_still_work(app, session, cust, catalog):
    _, p = catalog
    add(cust, p, 1)
    assert cust.get("/cart").status_code == 200
    assert cust.get("/account").status_code == 200 and "My wishlist" in cust.get("/account").get_data(as_text=True)
    assert app.test_client().get("/owner/login").status_code == 200
