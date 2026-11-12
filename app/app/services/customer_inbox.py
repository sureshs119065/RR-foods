from sqlalchemy import select
from ..extensions import db
from ..models import CustomerMessage, CustomerMessageThread, Notification, User
from ..models.base import utcnow


def create_thread(customer, subject: str, body: str):
    thread = CustomerMessageThread(user_id=customer.id, subject=subject, status="open", last_message_at=utcnow())
    db.session.add(thread)
    db.session.flush()
    db.session.add(CustomerMessage(thread_id=thread.id, sender_id=customer.id, body=body))
    # A shared inbox: both Admin and Shop Owner can see and reply to every customer conversation.
    staff = db.session.scalars(select(User).where(User.role.in_(("admin", "owner")), User.is_blocked.is_(False), User.is_deleted.is_(False))).all()
    for person in staff:
        db.session.add(Notification(user_id=person.id, kind="customer_message", title="New customer message", body=f"{customer.name}: {subject}"[:500], link=f"/{'admin' if person.role == 'admin' else 'owner'}/inbox/{thread.id}"))
    return thread


def add_reply(thread, sender, body: str):
    db.session.add(CustomerMessage(thread_id=thread.id, sender_id=sender.id, body=body))
    thread.last_message_at = utcnow()
    thread.status = "open"
    if sender.role == "user":
        staff = db.session.scalars(select(User).where(User.role.in_(("admin", "owner")), User.is_blocked.is_(False), User.is_deleted.is_(False))).all()
        for person in staff:
            db.session.add(Notification(user_id=person.id, kind="customer_message", title="Customer replied", body=f"{sender.name}: {thread.subject}"[:500], link=f"/{'admin' if person.role == 'admin' else 'owner'}/inbox/{thread.id}"))
    else:
        db.session.add(Notification(user_id=thread.user_id, kind="message_reply", title="RR FOODS replied to your message", body=thread.subject, link=f"/account/messages/{thread.id}"))
