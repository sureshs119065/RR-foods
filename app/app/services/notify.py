"""Notifications: always an in-app row; also queued as an email for the kinds customers expect by email (see mailer.EMAIL_KINDS)."""
from ..extensions import db
from ..models import Notification
from .mailer import EMAIL_KINDS, queue_email


def notify(user_id: int, kind: str, title: str, body: str | None = None, link: str | None = None) -> None:
    """Queue an in-app notification (and an email for some kinds). The caller commits."""
    db.session.add(Notification(user_id=user_id, channel="in_app", kind=kind[:40], title=title[:150],
                                body=(body or None) and body[:500], link=link[:300] if link else None))
    if kind in EMAIL_KINDS:
        queue_email(user_id, kind, title, body, link)
