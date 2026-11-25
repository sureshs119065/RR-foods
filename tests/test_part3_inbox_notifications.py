"""Part 3: one Questions & Feedback page (two tabs) in both panels, old /inbox URLs redirect, and the redesigned notification pages."""
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.extensions import limiter
from app.models import Notification, ProductQuestion
from app.models.base import utcnow
from app.services import customer_inbox
from app.services.notification_view import classify
from tests.helpers import post
from tests.test_step6_shop import catalog, cust  # noqa: F401  (fixtures)
from tests.test_step7_engage import staff


@pytest.fixture(autouse=True)
def _fresh_limits():
    limiter.reset()


@pytest.mark.parametrize("kind,title,group", [
    ("out_of_stock", "", "urgent"), ("order_cancelled", "", "urgent"), ("order_return", "", "urgent"), ("order_new", "", "urgent"),
    ("order_status", "Order X could not be accepted", "urgent"), ("low_stock", "", "warning"),
    ("order_status", "Order X confirmed", "order"), ("order_status", "Order X is out for delivery", "order"),
    ("order_status", "Order X delivered", "success"), ("review_status", "", "success"),
    ("customer_message", "", "message"), ("question_answered", "", "message"), ("offer", "", "offer"), ("back_in_stock", "", "info"),
])
def test_every_kind_gets_its_group(kind, title, group):
    assert classify(kind, title) == group


def test_customer_notification_centre_filters_and_urgent_first(app, cust, session):
    uid = cust.user.id
    assert "No notifications yet" in cust.get("/notifications").get_data(as_text=True)
    old = utcnow() - timedelta(days=3)
    session.add_all([
        Notification(user_id=uid, kind="order_status", title="Order A1 confirmed", created_at=utcnow() - timedelta(minutes=5)),
        Notification(user_id=uid, kind="order_status", title="Order A2 could not be accepted", created_at=old),
        Notification(user_id=uid, kind="offer", title="Festival offer", created_at=utcnow() - timedelta(minutes=1)),
        Notification(user_id=uid, kind="message_reply", title="RR FOODS replied", is_read=True),
    ])
    session.commit()
    html = cust.get("/notifications").get_data(as_text=True)
    assert "Immediate attention" in html and "Order update" in html and "Offer" in html and "is-new" in html and "min ago" in html
    assert html.index("A2 could not be accepted") < html.index("Festival offer") < html.index("A1 confirmed")   # unread urgent first
    urgent = cust.get("/notifications?f=urgent").get_data(as_text=True)
    assert "A2 could not" in urgent and "Festival offer" not in urgent
    assert "RR FOODS replied" in cust.get("/notifications?f=messages").get_data(as_text=True)
    unread = cust.get("/notifications?f=unread").get_data(as_text=True)
    assert "RR FOODS replied" not in unread and "Festival offer" in unread
    assert "Nothing in Messages" not in cust.get("/notifications?f=messages").get_data(as_text=True)
    post(cust, "/notifications/read-all", {}, page="/notifications")
    assert "You are all caught up" in cust.get("/notifications").get_data(as_text=True)


def test_admin_notification_centre_same_design_and_open_marks_read(app, session):
    ad = staff(app, session, "admin")
    from app.models import User
    admin = session.scalar(select(User).where(User.role == "admin"))
    session.add(Notification(user_id=admin.id, kind="out_of_stock", title="Out of stock: Ragi", body="0 left", link="/admin/stock-alerts"))
    session.add(Notification(user_id=admin.id, kind="low_stock", title="Low stock: Jowar", link="/admin/stock-alerts"))
    session.commit()
    html = ad.get("/admin/notifications").get_data(as_text=True)
    assert "Immediate attention" in html and "Warning" in html and "nt__chip" in html and "Mark all read" in html
    assert html.index("Out of stock: Ragi") < html.index("Low stock: Jowar")
    n = session.scalar(select(Notification).where(Notification.user_id == admin.id, Notification.kind == "out_of_stock"))
    r = ad.get(f"/admin/notifications/{n.id}/go")
    assert r.status_code == 302 and r.headers["Location"].endswith("/admin/stock-alerts")
    session.expire_all()
    assert session.get(Notification, n.id).is_read


def test_questions_page_has_no_feedback_tab_in_both_panels(app, cust, session, catalog):
    _, p = catalog
    thread = customer_inbox.create_thread(cust.user, "Where is my parcel", "Please help")
    session.add(ProductQuestion(product_id=p.id, user_id=cust.user.id, question="Is this suitable for kids?"))
    session.commit()
    for role in ("owner", "admin"):
        c = staff(app, session, role)
        html = c.get(f"/{role}/questions").get_data(as_text=True)
        assert "Is this suitable for kids?" in html and "Feedback" not in html and "Customer Inbox" not in html
        assert "Where is my parcel" not in c.get(f"/{role}/questions?tab=feedback").get_data(as_text=True)
        assert "Feedback" not in c.get(f"/{role}/").get_data(as_text=True)
        for old in (f"/{role}/inbox", f"/{role}/inbox/{thread.id}", f"/{role}/feedback/{thread.id}"):
            r = c.get(old)
            assert r.status_code == 301 and r.headers["Location"].endswith(f"/{role}/questions")


def test_admin_can_answer_a_question(app, cust, session, catalog):
    _, p = catalog
    q = ProductQuestion(product_id=p.id, user_id=cust.user.id, question="Is this suitable for kids?")
    session.add(q)
    session.commit()
    ad = staff(app, session, "admin")
    r = post(ad, f"/admin/questions/{q.id}/answer", {"answer": "Yes, it has no added sugar."}, page="/admin/questions")
    assert r.status_code == 302
    session.expire_all()
    assert session.get(ProductQuestion, q.id).answer == "Yes, it has no added sugar."
