"""Review management: see every review with its product, rating and order, approve or reject it, and choose whether new reviews need approval first.

Statuses: pending (waiting for the admin, only when moderation is on), approved (counts in the product rating), hidden (rejected or hidden, not shown).
An approved review can also be switched on for "What our customers say" on the home page (max 6 are shown, newest first).
"""
from flask import abort, flash, redirect, render_template, request, url_for
from sqlalchemy import func, or_, select
from sqlalchemy.orm import joinedload

from ..auth.service import safe_next
from ..extensions import db
from ..models import Order, OrderItem, Product, Review, SiteSetting
from ..services.notify import notify
from ..services import home_cache
from ..services.reviews import HOME_REVIEW_LIMIT, moderation_on, refresh_rating
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
    on_home = db.session.scalar(select(func.count(Review.id)).where(Review.is_deleted.is_(False), Review.status == "approved", Review.show_on_home.is_(True))) or 0
    return render_template("admin/reviews.html", page=page, products=products, orders=orders, show=show, counts=counts, avg=float(avg) if avg else None,
                           on_home=on_home, home_limit=HOME_REVIEW_LIMIT, moderation=moderation_on(), args={k: v for k, v in request.args.items() if k != "page" and v})


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
    if target != "approved":
        r.show_on_home = False  # only approved reviews can be on the home page; re-approving does not bring it back by itself
    db.session.flush()
    refresh_rating(r.product_id)
    log(f"review.{action}", "review", r.id, before={"status": before}, after={"status": target})
    if target == "approved" and before == "pending":  # tell the customer their review was accepted
        p = db.session.get(Product, r.product_id)
        if p is not None:
            number = db.session.scalar(select(Order.order_number).join(OrderItem, OrderItem.order_id == Order.id).where(OrderItem.id == r.order_item_id)) if r.order_item_id else None
            notify(r.user_id, "review_status", "Your review was approved", f"Thank you! Your review of {p.name} has been approved.", link=f"/account/orders/{number}#rate" if number else f"/product/{p.slug}")
    db.session.commit()
    flash("Review approved. It now counts in the product rating." if target == "approved" else "Review rejected. It is hidden and does not count in the product rating.", "success")
    return redirect(back)


@bp.post("/reviews/<int:review_id>/toggle")
def review_toggle(review_id):
    r = db.session.get(Review, review_id)
    if r is None or r.is_deleted:
        abort(404)
    before = r.status
    r.status = "hidden" if r.status == "approved" else "approved"
    if r.status != "approved":
        r.show_on_home = False
    db.session.flush()
    refresh_rating(r.product_id)
    log("review.hide" if r.status == "hidden" else "review.show", "review", r.id, before={"status": before}, after={"status": r.status})
    db.session.commit()
    flash("Review hidden. It no longer counts in the product rating." if r.status == "hidden" else "Review is visible again.", "success")
    return redirect(safe_next(request.form.get("next"), url_for("admin.reviews")))


@bp.post("/reviews/<int:review_id>/home")
def review_home(review_id):
    """Switch "Show on home page" on or off for one approved review (the home cache is emptied when this commits)."""
    r = db.session.get(Review, review_id)
    if r is None or r.is_deleted:
        abort(404)
    back = safe_next(request.form.get("next"), url_for("admin.reviews"))
    if r.status != "approved":
        flash("Only approved reviews can be shown on the home page.", "error")
        return redirect(back)
    r.show_on_home = not r.show_on_home
    db.session.flush()
    home_cache.mark_dirty(db.session)
    log("review.home_on" if r.show_on_home else "review.home_off", "review", r.id, before={"show_on_home": not r.show_on_home}, after={"show_on_home": r.show_on_home})
    db.session.commit()
    flash("Review will be shown on the home page." if r.show_on_home else "Review removed from the home page.", "success")
    return redirect(back)


@bp.post("/reviews/moderation")
def review_moderation():
    """On (default): new reviews wait for approval. Off: they go live straight away."""
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
