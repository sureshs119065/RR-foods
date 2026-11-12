"""Review rules: who may review, and keeping the product's average rating right."""
from sqlalchemy import func, select, update

from ..extensions import db
from ..models import Order, OrderItem, Product, Review, ReviewVote

REVIEWABLE_ORDER_STATUSES = ("delivered", "return_requested", "returned", "refunded")


def moderation_on() -> bool:
    """Site setting `review_moderation` (admin > Reviews). Off by default: reviews go live at once. On: they wait for the admin to approve."""
    from .storefront import setting
    return str(setting("review_moderation", "0")).lower() in ("1", "true", "on", "yes")


def purchase_for(user_id: int, product_id: int, order_item_id: int | None = None) -> OrderItem | None:
    """The delivered order line that lets this customer review the product (None = they never received it).
    With order_item_id, only that line counts (it must belong to this customer, be this product and be delivered)."""
    q = (select(OrderItem).join(Order, Order.id == OrderItem.order_id)
         .where(Order.user_id == user_id, OrderItem.product_id == product_id, Order.status.in_(REVIEWABLE_ORDER_STATUSES)))
    if order_item_id:
        q = q.where(OrderItem.id == order_item_id)
    return db.session.scalar(q.order_by(OrderItem.id.desc()).limit(1))


def refresh_rating(product_id: int) -> None:
    """Recalculate average and count from the visible reviews only."""
    avg, n = db.session.execute(select(func.coalesce(func.avg(Review.rating), 0), func.count(Review.id))
                                .where(Review.product_id == product_id, Review.status == "approved", Review.is_deleted.is_(False))).one()
    db.session.execute(update(Product).where(Product.id == product_id).values(avg_rating=round(float(avg), 2), review_count=n))


def refresh_helpful(review_id: int) -> int:
    n = db.session.scalar(select(func.count(ReviewVote.id)).where(ReviewVote.review_id == review_id)) or 0
    db.session.execute(update(Review).where(Review.id == review_id).values(helpful_count=n))
    return n
