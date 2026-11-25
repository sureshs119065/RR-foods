"""Review rules: who may review, and keeping the product's average rating right."""
from sqlalchemy import func, or_, select, update

from ..extensions import db
from ..models import Order, OrderItem, Product, Review, ReviewVote, User

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


def existing_for(user_id: int, item: OrderItem) -> Review | None:
    """This customer's review of the product in the order that `item` belongs to (deleted ones included, so writing again revives it).
    Two lines of the same product in one order share one review: one review per product per order."""
    sibling_ids = select(OrderItem.id).where(OrderItem.order_id == item.order_id, OrderItem.product_id == item.product_id)
    return db.session.scalar(select(Review).where(Review.user_id == user_id, Review.order_item_id.in_(sibling_ids)).order_by(Review.id).limit(1))


def refresh_rating(product_id: int) -> None:
    """Recalculate average and count from the visible reviews only."""
    avg, n = db.session.execute(select(func.coalesce(func.avg(Review.rating), 0), func.count(Review.id))
                                .where(Review.product_id == product_id, Review.status == "approved", Review.is_deleted.is_(False))).one()
    db.session.execute(update(Product).where(Product.id == product_id).values(avg_rating=round(float(avg), 2), review_count=n))
    from . import home_cache
    home_cache.mark_dirty(db.session)  # product cards on the home page show the rating; Core updates skip the ORM events


def refresh_helpful(review_id: int) -> int:
    n = db.session.scalar(select(func.count(ReviewVote.id)).where(ReviewVote.review_id == review_id)) or 0
    db.session.execute(update(Review).where(Review.id == review_id).values(helpful_count=n))
    return n


# ------------------------------------------------------------------ home page "What our customers say"
HOME_REVIEW_LIMIT = 6
HOME_REVIEW_CHARS = 150


def trim(text: str, limit: int = HOME_REVIEW_CHARS) -> str:
    """At most `limit` characters; a cut text ends with an ellipsis (which counts in the limit)."""
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "\u2026"


def first_name(full: str | None) -> str:
    parts = (full or "").split()
    return parts[0] if parts else "Customer"


def _load_home_reviews(session) -> list[dict]:
    """Newest first, max 6: approved, not deleted, flagged for the home page. Plain dicts, so the cache holds no ORM objects."""
    rows = session.execute(
        select(Review.rating, Review.body, Review.title, User.name, Product.name)
        .join(Product, Product.id == Review.product_id)
        .join(User, User.id == Review.user_id)
        .where(Review.status == "approved", Review.is_deleted.is_(False), Review.show_on_home.is_(True), Product.is_deleted.is_(False),
               or_(func.length(func.trim(func.coalesce(Review.body, ""))) > 0, func.length(func.trim(func.coalesce(Review.title, ""))) > 0))
        .order_by(Review.created_at.desc(), Review.id.desc()).limit(HOME_REVIEW_LIMIT)).all()
    return [{"rating": int(r), "text": trim(body or title or ""), "name": first_name(user_name), "product": product_name}
            for r, body, title, user_name, product_name in rows]


def home_reviews() -> list[dict]:
    """Cached with the rest of the home fragments; changing a review's status or its home flag empties the cache (see home_cache)."""
    from . import home_cache
    return home_cache.get("home_reviews", _load_home_reviews)
