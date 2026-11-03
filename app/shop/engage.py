"""Wishlist, compare, reviews (with photos and helpful votes), questions, and the notifications inbox."""
from flask import abort, flash, g, jsonify, redirect, render_template, request, session, url_for
from sqlalchemy import func, select
from sqlalchemy.orm import joinedload, selectinload

from ..admin.helpers import clean, page_number, to_int
from ..auth.decorators import roles_required
from ..auth.service import audit, safe_next
from ..extensions import db, limiter
from ..models import Notification, Product, ProductQuestion, Review, ReviewVote, User, WishlistItem
from ..models.base import utcnow
from ..services import reviews as rv
from ..services.notify import notify
from ..services.storefront import LIVE, active_variants, get_product
from ..uploads import UploadError, save_image
from . import bp, reply
from .cart import _need_login

user_only = roles_required("user")
MAX_COMPARE = 4
MAX_PHOTOS = 3


# ---------------------------------------------------------------- template helpers (global, so imported macros can use them)
def in_wishlist(product_id: int) -> bool:
    u = g.get("user")
    if u is None or u.role != "user":
        return False
    ids = request.environ.get("nk.wishlist")  # cached for this one request only (not on g, which can outlive a request in tests)
    if ids is None:
        ids = request.environ["nk.wishlist"] = set(db.session.scalars(select(WishlistItem.product_id).where(WishlistItem.user_id == u.id)))
    return product_id in ids


def unread_count() -> int:
    u = g.get("user")
    if u is None:
        return 0
    return db.session.scalar(select(func.count(Notification.id)).where(Notification.user_id == u.id, Notification.channel == "in_app", Notification.is_read.is_(False))) or 0


def review_thanks():
    """The thank-you popup shows once, right after a review was saved (never when the form is merely opened)."""
    return session.pop("review_thanks", None)


def compare_count() -> int:
    return len(session.get("cmp", []))


@bp.record_once
def _register_globals(state):
    state.app.jinja_env.globals.update(in_wishlist=in_wishlist, unread_count=unread_count, compare_count=compare_count, review_thanks=review_thanks)


def _shopper_or_response():
    """None when a signed-in customer; otherwise the right reply for a guest or for staff."""
    if g.get("user") is None:
        return _need_login()
    if g.user.role != "user":
        return reply(False, "Only customer accounts can do this.", "/", 403)
    return None


# ---------------------------------------------------------------- wishlist
@bp.post("/wishlist/toggle")
@limiter.limit("60 per minute")
def wishlist_toggle():
    blocked = _shopper_or_response()
    if blocked is not None:
        return blocked
    errs: dict = {}
    pid = to_int(request.form.get("product_id"), "p", errs, min_=1, max_=2_000_000_000)
    p = None if errs else db.session.scalar(select(Product).where(Product.id == pid, LIVE))
    if p is None:
        return reply(False, "That product is not available.", "/", 404)
    row = db.session.scalar(select(WishlistItem).where(WishlistItem.user_id == g.user.id, WishlistItem.product_id == p.id))
    if row:
        db.session.delete(row)
        on, msg = False, "Removed from your wishlist."
    else:
        db.session.add(WishlistItem(user_id=g.user.id, product_id=p.id))
        on, msg = True, "Saved to your wishlist."
    db.session.commit()
    return reply(True, msg, "/account/wishlist", on=on)


@bp.get("/account/wishlist")
@user_only
def wishlist():
    items = db.session.scalars(select(WishlistItem).where(WishlistItem.user_id == g.user.id).order_by(WishlistItem.id.desc())
                               .options(joinedload(WishlistItem.product).selectinload(Product.images), joinedload(WishlistItem.product).selectinload(Product.variants))).unique().all()
    products = [i.product for i in items if i.product.is_active and not i.product.is_deleted]
    return render_template("shop/wishlist.html", products=products, plain={p.id: not active_variants(p) for p in products})


# ---------------------------------------------------------------- compare
@bp.post("/compare/toggle")
@limiter.limit("60 per minute")
def compare_toggle():
    errs: dict = {}
    pid = to_int(request.form.get("product_id"), "p", errs, min_=1, max_=2_000_000_000)
    p = None if errs else db.session.scalar(select(Product).where(Product.id == pid, LIVE))
    if p is None:
        return reply(False, "That product is not available.", "/compare", 404)
    ids = [i for i in session.get("cmp", []) if isinstance(i, int)]
    if p.id in ids:
        ids.remove(p.id)
        msg = "Removed from compare."
    elif len(ids) >= MAX_COMPARE:
        return reply(False, f"You can compare up to {MAX_COMPARE} products. Remove one first.", "/compare", 409, count=len(ids))
    else:
        ids.append(p.id)
        msg = "Added to compare."
    session["cmp"] = ids
    return reply(True, msg, "/compare", count=len(ids))


@bp.get("/compare")
def compare():
    ids = [i for i in session.get("cmp", []) if isinstance(i, int)]
    rows = {p.id: p for p in db.session.scalars(select(Product).where(Product.id.in_(ids or [0]), LIVE).options(selectinload(Product.images), selectinload(Product.variants)))} if ids else {}
    products = [rows[i] for i in ids if i in rows]
    spec_keys = []
    for p in products:
        for k in (p.specifications or {}):
            if k not in spec_keys:
                spec_keys.append(k)
    return render_template("shop/compare.html", products=products, spec_keys=spec_keys)


# ---------------------------------------------------------------- reviews
def _back(slug: str, anchor: str = "reviews") -> str:
    return url_for("shop.product", slug=slug) + f"#{anchor}"


@bp.post("/product/<slug>/review")
@user_only
@limiter.limit("20 per hour")
def review_save(slug):
    p = get_product(slug)
    if p is None:
        abort(404)
    back = safe_next(request.form.get("next"), _back(slug))  # the order page sends people back to itself
    item_id = to_int(request.form.get("order_item_id"), "i", {}, min_=1, max_=2_000_000_000) if request.form.get("order_item_id") else None
    item = rv.purchase_for(g.user.id, p.id, item_id)
    if item is None:
        flash("You can review a product after it has been delivered to you.", "error")
        return redirect(back)
    errs: dict = {}
    rating = to_int(request.form.get("rating"), "rating", errs, min_=1, max_=5)
    title, body = clean(request.form.get("title"), 150), (request.form.get("body") or "").strip()[:2000]
    if errs:
        flash("Choose a star rating from 1 to 5.", "error")
        return redirect(back)
    files = [f for f in request.files.getlist("photos") if f and f.filename][:MAX_PHOTOS]
    if len(request.files.getlist("photos")) > MAX_PHOTOS and any(f.filename for f in request.files.getlist("photos")[MAX_PHOTOS:]):
        flash(f"You can add up to {MAX_PHOTOS} photos. The extra ones were ignored.", "info")
    photos = []
    try:
        for f in files:
            photos.append(save_image(f, "reviews", max_side=1200, thumb_side=None)[0])
    except UploadError as e:
        flash(str(e), "error")
        return redirect(back)

    review = db.session.scalar(select(Review).where(Review.user_id == g.user.id, Review.product_id == p.id))
    if review is None:
        review = Review(user_id=g.user.id, product_id=p.id)
        db.session.add(review)
    review.rating, review.title, review.body = rating, title or None, body or None
    needs_ok = rv.moderation_on()
    review.order_item_id, review.is_verified_purchase, review.status, review.is_deleted = item.id, True, "pending" if needs_ok else "approved", False
    if photos:
        review.photos = photos
    elif review.photos is None:
        review.photos = []
    db.session.flush()
    rv.refresh_rating(p.id)
    db.session.commit()
    flash("Thank you! Your review will appear on the product page once the shop approves it." if needs_ok else "Thank you! Your review is now live.", "success")
    session["review_thanks"] = {"product": p.name[:80], "pending": needs_ok}  # shows the thank-you popup once, on the next page
    return redirect(back)


@bp.post("/review/<int:review_id>/delete")
@user_only
def review_delete(review_id):
    r = db.session.get(Review, review_id)
    if r is None or r.user_id != g.user.id:
        abort(404)
    r.is_deleted = True
    db.session.flush()
    rv.refresh_rating(r.product_id)
    db.session.commit()
    flash("Your review was removed.", "success")
    return redirect(safe_next(request.form.get("next"), "/"))


@bp.post("/review/<int:review_id>/helpful")
@limiter.limit("60 per minute")
def review_helpful(review_id):
    blocked = _shopper_or_response()
    if blocked is not None:
        return blocked
    r = db.session.get(Review, review_id)
    if r is None or r.is_deleted or r.status != "approved":
        return reply(False, "That review is not available.", "/", 404)
    if r.user_id == g.user.id:
        return reply(False, "You cannot vote on your own review.", "/", 409)
    vote = db.session.scalar(select(ReviewVote).where(ReviewVote.review_id == r.id, ReviewVote.user_id == g.user.id))
    if vote:
        db.session.delete(vote)
    else:
        db.session.add(ReviewVote(review_id=r.id, user_id=g.user.id))
    db.session.flush()
    n = rv.refresh_helpful(r.id)
    db.session.commit()
    return reply(True, "Thanks for your feedback.", "/", helpful=n, on=vote is None)


# ---------------------------------------------------------------- questions
@bp.post("/product/<slug>/ask")
@user_only
@limiter.limit("10 per hour")
def ask_question(slug):
    p = get_product(slug)
    if p is None:
        abort(404)
    q = " ".join((request.form.get("question") or "").split())
    if not 10 <= len(q) <= 500:
        flash("Write your question in 10 to 500 characters.", "error")
        return redirect(_back(slug, "qa"))
    waiting = db.session.scalar(select(func.count(ProductQuestion.id)).where(ProductQuestion.user_id == g.user.id, ProductQuestion.product_id == p.id,
                                                                            ProductQuestion.answer.is_(None), ProductQuestion.is_deleted.is_(False))) or 0
    if waiting >= 3:
        flash("You already have questions waiting for an answer on this product.", "error")
        return redirect(_back(slug, "qa"))
    db.session.add(ProductQuestion(product_id=p.id, user_id=g.user.id, question=q))
    for oid in db.session.scalars(select(User.id).where(User.role == "owner", User.is_deleted.is_(False), User.is_blocked.is_(False))):
        notify(oid, "question", f"New question about {p.name}", q[:200], link="/owner/questions")
    db.session.commit()
    flash("Thanks! We will answer your question soon. It will appear here once answered.", "success")
    return redirect(_back(slug, "qa"))


# ---------------------------------------------------------------- notifications inbox (customers and owners)
inbox_roles = roles_required("user", "owner")


@bp.get("/notifications")
@inbox_roles
def notifications():
    q = select(Notification).where(Notification.user_id == g.user.id, Notification.channel == "in_app").order_by(Notification.id.desc())
    return render_template("shop/notifications.html", page=db.paginate(q, page=page_number(), per_page=20, error_out=False),
                           layout="owner/layout.html" if g.user.role == "owner" else "shop/layout.html")


@bp.get("/notifications/unread.json")
@inbox_roles
def notifications_unread():
    """Polled by the bell every 30 seconds: the unread count and the newest unread ones (only this person's own)."""
    rows = db.session.scalars(select(Notification).where(Notification.user_id == g.user.id, Notification.channel == "in_app", Notification.is_read.is_(False))
                              .order_by(Notification.id.desc()).limit(5)).all()
    resp = jsonify(count=unread_count(), latest=[{"id": n.id, "title": n.title, "body": n.body, "url": url_for("shop.notification_go", nid=n.id)} for n in rows])
    resp.headers["Cache-Control"] = "no-store"
    return resp


@bp.get("/notifications/<int:nid>/go")
@inbox_roles
def notification_go(nid):
    n = db.session.get(Notification, nid)
    if n is None or n.user_id != g.user.id:
        abort(404)
    if not n.is_read:
        n.is_read = True
        db.session.commit()
    return redirect(safe_next(n.link, url_for("shop.notifications")))


@bp.post("/notifications/read-all")
@inbox_roles
def notifications_read_all():
    db.session.execute(Notification.__table__.update().where(Notification.user_id == g.user.id, Notification.channel == "in_app", Notification.is_read.is_(False)).values(is_read=True))
    db.session.commit()
    flash("All notifications marked as read.", "success")
    return redirect(url_for("shop.notifications"))
