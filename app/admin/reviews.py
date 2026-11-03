"""Review moderation: hide a review that breaks the rules (it stops counting in the product's rating), or show it again."""
from flask import abort, flash, redirect, render_template, request, url_for
from sqlalchemy import func, or_, select
from sqlalchemy.orm import joinedload

from ..auth.service import safe_next
from ..extensions import db
from ..models import Product, Review
from ..services.reviews import refresh_rating
from . import bp
from .helpers import log, page_number


@bp.route("/reviews")
def reviews():
    q = select(Review).where(Review.is_deleted.is_(False)).options(joinedload(Review.user))
    show = request.args.get("show", "")
    if show == "hidden":
        q = q.where(Review.status == "hidden")
    term = (request.args.get("q") or "").strip().lower()
    if term:
        q = q.join(Product, Product.id == Review.product_id).where(or_(func.lower(Product.name).contains(term, autoescape=True), func.lower(func.coalesce(Review.body, "")).contains(term, autoescape=True)))
    page = db.paginate(q.order_by(Review.id.desc()), page=page_number(), per_page=25, error_out=False)
    products = {p.id: p for p in db.session.scalars(select(Product).where(Product.id.in_({r.product_id for r in page.items} or {0})))}
    return render_template("admin/reviews.html", page=page, products=products, show=show, args={k: v for k, v in request.args.items() if k != "page" and v})


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
