"""WhatsApp-first ordering: the owner confirms and records payment; no gateway, no API."""
import pytest
from sqlalchemy import select

from app.models import AuditLog, Notification, OrderStatusHistory
from app.services import orders as svc
from app.services import whatsapp as wa
from tests.helpers import make_user, post
from tests.test_step5_owner import mk_order, owner, shop  # noqa: F401  (fixtures and the order builder)


@pytest.fixture()
def staff(session):
    return make_user(session, "owner", "svc-owner@x.com")


def test_clean_number_adds_country_code(app):
    with app.test_request_context():
        assert wa.clean_number("98765 43210") == "919876543210"
        assert wa.clean_number("+91 98765-43210") == "919876543210"
        assert wa.clean_number("09876543210") == "919876543210"
        assert wa.clean_number("") == ""
        assert wa.link("", "x") is None
        assert wa.link("919876543210", "a b\nc") == "https://wa.me/919876543210?text=a%20b%0Ac"


def test_set_payment_is_recorded_notified_and_reversible(app, session, shop, staff):
    customer, product = shop
    order = mk_order(session, customer, product, status="confirmed", method="upi_manual")
    o, changed = svc.set_payment(order.id, True, staff)
    session.commit()
    assert changed and o.payment_status == "paid" and all(p.status == "paid" for p in o.payments)
    assert session.scalar(select(Notification).where(Notification.title.like("Payment received%")))
    assert session.scalar(select(AuditLog).where(AuditLog.action == "order.payment_paid"))
    assert svc.set_payment(order.id, True, staff)[1] is False                      # twice: nothing happens
    o, changed = svc.set_payment(order.id, False, staff)
    session.commit()
    assert changed and o.payment_status == "pending" and o.status == "confirmed"   # the order status is untouched
    notes = [h.note for h in session.scalars(select(OrderStatusHistory).order_by(OrderStatusHistory.id)) if h.note]
    assert notes == ["Payment marked as received", "Payment marked as not received"]


def test_confirm_with_paid_flag_marks_the_order_paid(app, session, shop, staff):
    customer, product = shop
    a = mk_order(session, customer, product, status="placed", method="upi_manual", number="NK-W1")
    b = mk_order(session, customer, product, status="placed", method="upi_manual", number="NK-W2")
    assert svc.change_status(a.id, "confirmed", staff, expected_from="placed", mark_paid=True).payment_status == "paid"
    assert svc.change_status(b.id, "confirmed", staff, expected_from="placed").payment_status == "pending"
    session.commit()


def test_payment_cannot_change_on_closed_orders(app, session, shop, staff):
    customer, product = shop
    order = mk_order(session, customer, product, status="rejected", method="upi_manual")
    with pytest.raises(svc.OrderError, match="cannot be changed"):
        svc.set_payment(order.id, True, staff)


def test_owner_pages_confirm_paid_and_filter(app, session, shop, owner):
    customer, product = shop
    a = mk_order(session, customer, product, status="placed", method="upi_manual", number="NK-W1")
    b = mk_order(session, customer, product, status="placed", method="upi_manual", number="NK-W2")
    html = owner.get(f"/owner/orders/{a.id}").get_data(as_text=True)
    assert "Message customer on WhatsApp" in html and "https://wa.me/919876543210?text=" in html
    assert "Payment already received on WhatsApp" in html and "Mark as paid" in html
    post(owner, f"/owner/orders/{a.id}/status", {"to": "confirmed", "from_status": "placed", "paid": "1"}, page=f"/owner/orders/{a.id}")
    post(owner, f"/owner/orders/{b.id}/status", {"to": "confirmed", "from_status": "placed"}, page=f"/owner/orders/{b.id}")
    session.expire_all()
    assert (a.status, a.payment_status, b.status, b.payment_status) == ("confirmed", "paid", "confirmed", "pending")
    unpaid = owner.get("/owner/orders?tab=all&pay=pending").get_data(as_text=True)
    assert "NK-W2" in unpaid and "NK-W1" not in unpaid
    post(owner, f"/owner/orders/{b.id}/payment", {"paid": "1"}, page=f"/owner/orders/{b.id}")
    post(owner, f"/owner/orders/{a.id}/payment", {"paid": "0"}, page=f"/owner/orders/{a.id}")
    session.expire_all()
    assert (a.payment_status, b.payment_status) == ("pending", "paid")


def test_status_message_matches_the_order_status(app, session, shop):
    customer, product = shop
    order = mk_order(session, customer, product, status="confirmed", method="upi_manual")
    with app.test_request_context():
        assert "is confirmed" in wa.status_message(order) and "Please pay" in wa.status_message(order)
        order.payment_status = "paid"
        assert "Payment received" in wa.status_message(order)
        order.status, order.rejection_reason = "rejected", "Out of stock"
        assert "could not accept" in wa.status_message(order) and "Out of stock" in wa.status_message(order)
        assert wa.customer_link(order).startswith("https://wa.me/919876543210?text=")
        assert "Order: NK-1001" in wa.order_message(order)
        session.rollback()
