"""How a notification looks and which list it belongs to (customer, admin and owner pages share this).

Every row has a free-text `kind` written by whoever raised it. `meta()` maps kind (and, for order updates, the title) to one of
seven display groups; the SQL clauses below mirror the same rules so filtering and "urgent first" work on the database side too.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import and_, case, func, or_, select

from ..admin.helpers import local_display
from ..extensions import db
from ..models import Notification

# key -> (chip label, icon name used by shared/_notifications.html)
GROUPS = {
    "urgent": ("Immediate attention", "alert-triangle"),
    "warning": ("Warning", "alert-circle"),
    "order": ("Order update", "package"),
    "success": ("Success", "check"),
    "message": ("Message", "message-circle"),
    "offer": ("Offer", "tag"),
    "info": ("Info", "info"),
}
FILTERS = (("all", "All"), ("unread", "Unread"), ("urgent", "Urgent"), ("orders", "Orders"), ("messages", "Messages"))

URGENT_KINDS = {"out_of_stock", "order_cancelled", "order_return", "order_new", "new_order", "order_placed", "order_unconfirmed"}
WARNING_KINDS = {"low_stock", "stock_alert"}
ORDER_KINDS = {"order_status", "return_status", "order_cancelled", "order_return", "order_new", "new_order", "order_placed", "order_unconfirmed"}
MESSAGE_KINDS = {"customer_message", "message_reply", "question", "question_answered"}
OFFER_KINDS = {"offer", "offers", "promo", "coupon", "offer_new"}
SUCCESS_KINDS = {"review_status"}
# order updates that are really bad news / good news are recognised by their (fixed) title wording
_BAD_TITLE = ("cancelled", "could not be accepted")
_GOOD_TITLE = ("delivered",)


def classify(kind: str, title: str = "") -> str:
    t = (title or "").lower()
    if kind in URGENT_KINDS or (kind in ("order_status", "return_status") and any(w in t for w in _BAD_TITLE)):
        return "urgent"
    if kind in WARNING_KINDS:
        return "warning"
    if kind in SUCCESS_KINDS or (kind == "order_status" and any(w in t for w in _GOOD_TITLE)):
        return "success"
    if kind in ORDER_KINDS:
        return "order"
    if kind in MESSAGE_KINDS:
        return "message"
    if kind in OFFER_KINDS:
        return "offer"
    return "info"


def relative(dt: datetime | None, now: datetime | None = None) -> str:
    if not dt:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    now = now or datetime.now(timezone.utc)
    seconds = max(0, int((now - dt).total_seconds()))
    if seconds < 60:
        return "Just now"
    if seconds < 3600:
        return f"{seconds // 60} min ago"
    if seconds < 86400:
        return f"{seconds // 3600} h ago"
    days = seconds // 86400
    if days == 1:
        return "Yesterday"
    if days < 7:
        return f"{days} days ago"
    return local_display(dt)


def decorate(rows) -> list[dict]:
    now = datetime.now(timezone.utc)
    out = []
    for n in rows:
        key = classify(n.kind, n.title)
        label, icon = GROUPS[key]
        at = n.created_at.replace(tzinfo=timezone.utc) if n.created_at and n.created_at.tzinfo is None else n.created_at
        out.append({"n": n, "key": key, "label": label, "icon": icon, "when": relative(at, now),
                    "iso": at.isoformat() if at else "", "full": local_display(at)})
    return out


# ---- the same rules in SQL
def urgent_clause():
    title = func.lower(Notification.title)
    return or_(Notification.kind.in_(URGENT_KINDS),
               and_(Notification.kind.in_(("order_status", "return_status")), or_(*[title.like(f"%{w}%") for w in _BAD_TITLE])))


def _mine(user_id: int):
    return (Notification.user_id == user_id, Notification.channel == "in_app")


def clean_filter(value: str | None) -> str:
    return value if value in {k for k, _ in FILTERS} else "all"


def notification_page(user_id: int, filt: str, page: int, per_page: int = 20):
    """(pagination, counts). Unread urgent items come first, then newest first."""
    filt = clean_filter(filt)
    q = select(Notification).where(*_mine(user_id))
    if filt == "unread":
        q = q.where(Notification.is_read.is_(False))
    elif filt == "urgent":
        q = q.where(urgent_clause())
    elif filt == "orders":
        q = q.where(Notification.kind.in_(ORDER_KINDS))
    elif filt == "messages":
        q = q.where(Notification.kind.in_(MESSAGE_KINDS))
    first = case((and_(urgent_clause(), Notification.is_read.is_(False)), 0), else_=1)
    pagination = db.paginate(q.order_by(first, Notification.created_at.desc(), Notification.id.desc()), page=page, per_page=per_page, error_out=False)
    unread = db.session.scalar(select(func.count(Notification.id)).where(*_mine(user_id), Notification.is_read.is_(False))) or 0
    urgent = db.session.scalar(select(func.count(Notification.id)).where(*_mine(user_id), Notification.is_read.is_(False), urgent_clause())) or 0
    return pagination, {"unread": unread, "urgent": urgent}


def mark_all_read(user_id: int) -> None:
    db.session.execute(Notification.__table__.update().where(*_mine(user_id), Notification.is_read.is_(False)).values(is_read=True))
