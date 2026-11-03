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
    html = c.get("/compare").get_data(as_text=True)
    assert "Millet Soup Mix" in html and "Shelf life" in html and "6 months" in html and "Other 4" in html and "Other 6" not in html
    c.post("/compare/toggle", data={"product_id": p.id, "csrf_token": tk()}, headers=JSON)
    assert "Millet Soup Mix" not in c.get("/compare").get_data(as_text=True).split("<tbody>")[0]
    assert "Nothing to compare" in app.test_client().get("/compare").get_data(as_text=True)


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
    assert "after it has been delivered" in cust.get(f"/product/{p.slug}").get_data(as_text=True)
    mk_order(session, cust.user, p, status="delivered", number="NK-S2")
    r = review(cust, p.slug, rating="4", title="Tasty", body="Will buy again")
    assert r.status_code == 302
    rv = session.scalar(select(Review))
    assert (rv.rating, rv.title, rv.status, rv.is_verified_purchase) == (4, "Tasty", "approved", True) and rv.order_item_id
    session.refresh(p)
    assert (p.avg_rating, p.review_count) == (Decimal("4.00"), 1)
    html = cust.get(f"/product/{p.slug}").get_data(as_text=True)
    assert "Verified purchase" in html and "Will buy again" in html and "Edit your review" in html


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
    html = cust.get(f"/product/{p.slug}").get_data(as_text=True)
    assert "Photo from the customer" in html


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


# ================================================================ questions
def test_question_flow(app, cust, session, catalog):
    _, p = catalog
    ow = staff(app, session, "owner")
    ask = lambda q: post(cust, f"/product/{p.slug}/ask", {"question": q}, page=f"/product/{p.slug}")
    ask("short")
    ask("x" * 600)
    assert session.scalar(select(func.count(ProductQuestion.id))) == 0
    ask("Is this suitable for diabetics?")
    assert session.scalar(select(func.count(ProductQuestion.id))) == 1
    assert "Is this suitable" not in cust.get(f"/product/{p.slug}").get_data(as_text=True)      # hidden until answered
    assert session.scalar(select(Notification).where(Notification.kind == "question"))
    assert "Is this suitable" in ow.get("/owner/questions").get_data(as_text=True)
    qid = session.scalar(select(ProductQuestion.id))
    post(ow, f"/owner/questions/{qid}/answer", {"answer": "Yes, it has no added sugar."}, page="/owner/questions")
    html = cust.get(f"/product/{p.slug}").get_data(as_text=True)
    assert "Is this suitable" in html and "no added sugar" in html
    assert session.scalar(select(Notification).where(Notification.kind == "question_answered", Notification.user_id == cust.user.id))
    post(ow, f"/owner/questions/{qid}/delete", {}, page="/owner/questions")
    assert "Is this suitable" not in cust.get(f"/product/{p.slug}").get_data(as_text=True)


def test_question_limits_and_permissions(app, cust, session, catalog):
    _, p = catalog
    for i in range(5):
        post(cust, f"/product/{p.slug}/ask", {"question": f"Question number {i} about it?"}, page=f"/product/{p.slug}")
    assert session.scalar(select(func.count(ProductQuestion.id))) == 3            # at most 3 waiting
    qid = session.scalar(select(ProductQuestion.id))
    assert post(cust, f"/owner/questions/{qid}/answer", {"answer": "I am a customer"}, page="/").status_code == 403
    a = staff(app, session, "admin")
    assert a.get("/owner/questions").status_code == 403
    g = app.test_client()
    assert g.get(f"/product/{p.slug}").status_code == 200 and "Sign in</a> to ask" in g.get(f"/product/{p.slug}").get_data(as_text=True)


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
    assert "nav__count" in ow.get("/owner/").get_data(as_text=True)
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
        text = "NK-I1 Millet Soup Mix Rs. 200.00 Asha Rao"
    for needle in ("NK-I1", "Millet Soup Mix", "Rs. 200.00", "Asha Rao", "12 Lake Road"):
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
    assert "Return this order" in cust.get(f"/account/orders/{o.order_number}").get_data(as_text=True)
    post(cust, f"/account/orders/{o.order_number}/return", {"reason": "Not a real reason"}, page="/")
    session.expire_all(); assert session.get(Order, o.id).status == "delivered"
    post(cust, f"/account/orders/{o.order_number}/return", {"reason": "Damaged or leaking", "note": "Box was wet"}, page="/")
    session.expire_all()
    assert session.get(Order, o.id).status == "return_requested"
    h = session.scalar(select(OrderStatusHistory).where(OrderStatusHistory.to_status == "return_requested"))
    assert h.note == "Damaged or leaking: Box was wet" and h.changed_by == cust.user.id
    assert session.scalar(select(Notification).where(Notification.kind == "order_return"))
    assert "Return requested" in ow.get("/owner/orders?tab=returns").get_data(as_text=True) and o.order_number in ow.get("/owner/orders?tab=returns").get_data(as_text=True)
    page = ow.get(f"/owner/orders/{o.id}").get_data(as_text=True)
    assert "Box was wet" in page and "Put the items back in stock" in page and "Decline return" in page
    post(cust, f"/account/orders/{o.order_number}/return", {"reason": "Damaged or leaking"}, page="/")            # twice: ignored
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
    post(cust, f"/account/orders/{o.order_number}/return", {"reason": "Wrong item received"}, page="/")
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
    post(cust, f"/account/orders/{o.order_number}/return", {"reason": "Ordered by mistake"}, page="/")
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
    post(cust, f"/account/orders/{o.order_number}/return", {"reason": "Damaged or leaking"}, page="/")
    session.expire_all(); assert session.get(Order, o.id).status == "delivered"
    session.add(SiteSetting(key="return_window_days", value=30))                                         # the shop can widen the window
    session.commit()
    post(cust, f"/account/orders/{o.order_number}/return", {"reason": "Damaged or leaking"}, page="/")
    session.expire_all(); assert session.get(Order, o.id).status == "return_requested"
    for status in ("placed", "shipped", "cancelled", "rejected"):
        x = mk_order(session, cust.user, p, status=status, number=f"NK-W{status}")
        post(cust, f"/account/orders/{x.order_number}/return", {"reason": "Damaged or leaking"}, page="/")
        session.expire_all(); assert session.get(Order, x.id).status == status
    other = second_customer(app, session)
    assert post(other, f"/account/orders/{o.order_number}/return", {"reason": "Damaged or leaking"}, page="/").status_code == 404


def test_cod_refund_marks_payment_refunded(app, cust, session, catalog):
    _, p = catalog
    ow = staff(app, session, "owner")
    o = mk_order(session, cust.user, p, status="shipped", number="NK-F1")
    post(ow, f"/owner/orders/{o.id}/status", {"to": "delivered", "from_status": "shipped"}, page="/owner/orders")   # cash collected
    session.expire_all(); assert session.get(Order, o.id).payment_status == "paid"
    post(cust, f"/account/orders/{o.order_number}/return", {"reason": "Quality not as expected"}, page="/")
    for to, frm in (("returned", "return_requested"), ("refunded", "returned")):
        post(ow, f"/owner/orders/{o.id}/status", {"to": to, "from_status": frm}, page="/owner/orders")
    session.expire_all()
    done = session.get(Order, o.id)
    assert done.status == "refunded" and done.payment_status == "refunded" and done.payments[0].status == "refunded"


# ================================================================ forgot password
def forgot(c, email):
    return post(c, "/forgot", {"email": email}, page="/forgot")


def link_for(session, user):
    n = session.scalar(select(Notification).where(Notification.user_id == user.id, Notification.kind == "password_reset").order_by(Notification.id.desc()))
    return n.link if n else None


def test_forgot_password_full_flow(app, session):
    user = make_user(session, "user", "reset@x.com")
    c = app.test_client()
    assert "Forgot your password?" in c.get("/login").get_data(as_text=True)
    assert "Forgot your password?" not in c.get("/owner/login").get_data(as_text=True)
    r = forgot(c, "reset@x.com")
    assert "If an account exists" in r.get_data(as_text=True)
    link = link_for(session, user)
    assert link.startswith("/reset/")
    assert c.get(link).status_code == 200
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
    assert session.scalar(select(AuditLog).where(AuditLog.action == "auth.password_reset"))


def test_forgot_password_does_not_reveal_accounts_and_skips_staff_and_blocked(app, session):
    make_user(session, "owner", "boss@x.com")
    blocked = make_user(session, "user", "blocked@x.com")
    blocked.is_blocked = True
    session.commit()
    c = app.test_client()
    texts = {forgot(c, e).get_data(as_text=True).count("If an account exists") for e in ("nobody@x.com", "boss@x.com", "blocked@x.com")}
    assert texts == {1}
    assert session.scalar(select(func.count(Notification.id)).where(Notification.kind == "password_reset")) == 0
    assert forgot(c, "not-an-email").status_code == 422


def test_reset_links_expire_and_die_with_a_password_change(app, session, monkeypatch):
    user = make_user(session, "user", "ex@x.com")
    c = app.test_client()
    forgot(c, "ex@x.com")
    link = link_for(session, user)
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


def test_forgot_password_is_rate_limited(app, session):
    make_user(session, "user", "rl@x.com")
    c = app.test_client()
    codes = [forgot(c, "rl@x.com").status_code for _ in range(7)]
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
