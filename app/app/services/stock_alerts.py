"""Back-in-stock alerts. A customer taps "Notify me" on an out-of-stock product; when the product is available again they get an
in-app notification (and an email when mail is on). notify_restocked() is safe to call often: it only touches products that are
in stock again and alerts that have not been sent yet."""
import logging

from sqlalchemy import select

from ..extensions import db
from ..models import Product, StockAlert
from ..models.base import utcnow
from .notify import notify
from .storefront import LIVE, available_qty

log = logging.getLogger(__name__)


def has_alert(user_id: int, product_id: int) -> bool:
    """True while the customer is waiting for this product (not yet told)."""
    return db.session.scalar(select(StockAlert.id).where(StockAlert.user_id == user_id, StockAlert.product_id == product_id,
                                                         StockAlert.notified_at.is_(None))) is not None


def toggle(user_id: int, product_id: int) -> bool:
    """Turn the alert on or off. Returns True when it is now on. The caller commits."""
    row = db.session.scalar(select(StockAlert).where(StockAlert.user_id == user_id, StockAlert.product_id == product_id))
    if row is None:
        db.session.add(StockAlert(user_id=user_id, product_id=product_id))
        return True
    if row.notified_at is not None:  # told before, asking again for the next restock
        row.notified_at = None
        return True
    db.session.delete(row)
    return False


def waiting_counts(product_ids: list[int]) -> dict[int, int]:
    """product id -> number of customers waiting. For the owner screens."""
    from sqlalchemy import func
    if not product_ids:
        return {}
    rows = db.session.execute(select(StockAlert.product_id, func.count()).where(StockAlert.product_id.in_(product_ids),
                                                                                StockAlert.notified_at.is_(None)).group_by(StockAlert.product_id)).all()
    return {int(p): int(c) for p, c in rows}


def notify_restocked() -> int:
    """Tell everyone waiting for a product that is in stock again. Returns how many customers were told. Never raises."""
    try:
        rows = db.session.execute(select(StockAlert, Product).join(Product, Product.id == StockAlert.product_id)
                                  .where(StockAlert.notified_at.is_(None), LIVE)).all()
        told = 0
        for alert, product in rows:
            if available_qty(product) <= 0:
                continue
            notify(alert.user_id, "back_in_stock", f"{product.name} is back in stock",
                   "You asked us to tell you. Order soon, stock can run out again.", f"/product/{product.slug}")
            alert.notified_at = utcnow()
            told += 1
        db.session.commit()
        return told
    except Exception:  # a failed alert must never break the owner's stock update
        db.session.rollback()
        log.exception("back-in-stock alerts failed")
        return 0
