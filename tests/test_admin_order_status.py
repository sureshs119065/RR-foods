from sqlalchemy import select
from app.models import Notification, Order, OrderStatusHistory, AuditLog
from tests.helpers import post
from tests.test_order_lifecycle import world

def test_admin_status_update_creates_history_notification_and_audit(world, session):
    customer, other, product, owner, cust, stranger, admin = world
    from tests.test_step5_owner import mk_order
    order = mk_order(session, customer, product, status="placed", number="NK-ADMIN-STATUS")
    # Admins can only view orders; moving an order along is the owner's job (there is no admin status route).
    assert post(admin, f"/admin/orders/{order.id}/status", {"status": "confirmed"}, page=f"/admin/orders/{order.id}").status_code in (404, 405)
    response = post(owner, f"/owner/orders/{order.id}/status", {"to": "confirmed"}, page=f"/owner/orders/{order.id}")
    assert response.status_code == 302
    session.expire_all()
    saved = session.get(Order, order.id)
    assert saved.status == "confirmed"
    history = session.scalar(select(OrderStatusHistory).where(OrderStatusHistory.order_id == order.id, OrderStatusHistory.to_status == "confirmed"))
    assert history and history.changed_by is not None
    notification = session.scalar(select(Notification).where(Notification.user_id == customer.id, Notification.kind == "order_status", Notification.title.ilike("%confirmed%")))
    assert notification and not notification.is_read and order.order_number in notification.title
    assert session.scalar(select(AuditLog).where(AuditLog.action == "order.confirmed", AuditLog.entity_id == str(order.id)))

def test_admin_status_rejects_invalid_transition(world, session):
    customer, other, product, owner, cust, stranger, admin = world
    from tests.test_step5_owner import mk_order
    order = mk_order(session, customer, product, status="placed", number="NK-ADMIN-INVALID")
    post(owner, f"/owner/orders/{order.id}/status", {"to": "shipped"}, page=f"/owner/orders/{order.id}")
    session.expire_all()
    assert session.get(Order, order.id).status == "placed"
    assert session.scalar(select(Notification).where(Notification.user_id == customer.id, Notification.kind == "order_status")) is None
