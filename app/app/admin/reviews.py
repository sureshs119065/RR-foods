"""Review management: see every review with its product, rating and order, approve or reject it, and choose whether new reviews need approval first.

Statuses: pending (waiting for the admin, only when moderation is on), approved (visible, counts in the rating), hidden (rejected or hidden, not shown).
"""
from flask import abort, flash, redirect, render_template, request, url_for
from sqlalchemy import func, or_, select
from sqlalchemy.orm import joinedload

from ..auth.service import safe_next
from ..extensions import db
from ..models import Order, OrderItem, Product, Review, SiteSetting
from ..services.notify import notify
from ..services.reviews import moderation_on, refresh_rating
from . import bp
from .helpers import log, page_number


@bp.route("/reviews")
def reviews():
    q = select(Review).where(Review.is_deleted.is_(False)).options(joinedload(Review.user))
    show = request.args.get("show", "")
    if show in ("pending", "approved", "hidden"):
        q = q.where(Review.status == show)
    term = (request.args.get("q") or "").strip().lower()
    if term:
        q = q.join(Product, Product.id == Review.product_id).where(or_(func.lower(Product.name).contains(term, autoescape=True), func.lower(func.coalesce(Review.body, "")).contains(term, autoescape=True)))
    page = db.paginate(q.order_by((Review.status == "pending").desc(), Review.id.desc()), page=page_number(), per_page=25, error_out=False)
    products = {p.id: p for p in db.session.scalars(select(Product).where(Product.id.in_({r.product_id for r in page.items} or {0})))}
    orders = {i: n for i, n in db.session.execute(select(OrderItem.id, Order.order_number).join(Order, Order.id == OrderItem.order_id)
                                                  .where(OrderItem.id.in_({r.order_item_id for r in page.items if r.order_item_id} or {0}))).all()}
    counts = dict(db.session.execute(select(Review.status, func.count(Review.id)).where(Review.is_deleted.is_(False)).group_by(Review.status)).all())
    avg = db.session.scalar(select(func.avg(Review.rating)).where(Review.is_deleted.is_(False), Review.status == "approved"))
    return render_template("admin/reviews.html", page=page, products=products, orders=orders, show=show, counts=counts, avg=float(avg) if avg else None,
                           moderation=moderation_on(), args={k: v for k, v in request.args.items() if k != "page" and v})


@bp.post("/reviews/<int:review_id>/set")
def review_set(review_id):
    """Approve or reject (hide) one review. The product's average rating is recalculated from the approved reviews only."""
    r = db.session.get(Review, review_id)
    if r is None or r.is_deleted:
        abort(404)
    action = request.form.get("action")
    if action not in ("approve", "reject"):
        abort(400)
    target = "approved" if action == "approve" else "hidden"
    before = r.status
    back = safe_next(request.form.get("next"), url_for("admin.reviews"))
    if before == target:
        return redirect(back)
    r.status = target
    db.session.flush()
    refresh_rating(r.product_id)
    log(f"review.{action}", "review", r.id, before={"status": before}, after={"status": target})
    if target == "approved" and before == "pending":  # tell the customer their words are now on the product page
        p = db.session.get(Product, r.product_id)
        if p is not None:
            notify(r.user_id, "review_status", "Your review is now live", f"Thank you! Your review of {p.name} is now on the product page.", link=f"/product/{p.slug}#reviews")
    db.session.commit()
    flash("Review approved. It is now on the product page." if target == "approved" else "Review rejected. It is hidden and does not count in the product rating.", "success")
    return redirect(back)


@bp.post("/reviews/<int:review_id>/toggle")
def review_toggle(review_id):
    r = db.session.get(Review, review_id)
    if r is None or r.is_deleted:
        abort(404)
    before = r.status
    r.status = "hidden" if r.status == "approved" else "approved"
    db.session.flush()
    refresh_rating(r.product_id)
    log("review.hide" if r.status == "hidden" else "review.show", "review", r.id, before={"status": before}, after={"status": r.status})
    db.session.commit()
    flash("Review hidden. It no longer counts in the product rating." if r.status == "hidden" else "Review is visible again.", "success")
    return redirect(safe_next(request.form.get("next"), url_for("admin.reviews")))


@bp.post("/reviews/moderation")
def review_moderation():
    """On: new reviews wait for approval. Off (default): they go live straight away."""
    on = request.form.get("on") == "1"
    row = db.session.get(SiteSetting, "review_moderation")
    if row is None:
        db.session.add(SiteSetting(key="review_moderation", value="1" if on else "0"))
    else:
        row.value = "1" if on else "0"
    log("review.moderation_on" if on else "review.moderation_off", "setting", None, after={"review_moderation": on})
    db.session.commit()
    flash("New reviews now need your approval before they appear." if on else "New reviews now appear straight away.", "success")
    return redirect(url_for("admin.reviews"))
