from datetime import datetime, timezone
from pathlib import Path
import re
from flask import abort, flash, g, redirect, render_template, request, url_for
from sqlalchemy import select
from ..extensions import db
from ..models import Bundle, Product, Reel, RecipeVideo, Order, OrderStatusHistory, Notification
from ..uploads import save_image, save_video, UploadError, delete_files
from . import bp

def _slug(value):
    value = re.sub(r"[^a-z0-9]+", "-", (value or "").lower()).strip("-")
    return value[:180] or "content"

def _products():
    return db.session.scalars(select(Product).where(Product.is_deleted.is_(False)).order_by(Product.name)).all()

@bp.get("/reels")
def reels():
    from ..models import SiteSetting
    setting = db.session.get(SiteSetting, "home_reels")
    cfg = setting.value if setting and isinstance(setting.value, dict) else {"enabled": True, "max_count": 8, "selected_ids": []}
    return render_template("admin/content_list.html", title="Reels", kind="reels",
        items=db.session.scalars(select(Reel).order_by(Reel.sort_order, Reel.id)).all(), reels_cfg=cfg)

@bp.route("/reels/new", methods=["GET", "POST"])
@bp.route("/reels/<int:item_id>/edit", methods=["GET", "POST"])
def reel_form(item_id=None):
    item = db.session.get(Reel, item_id) if item_id else Reel()
    if item_id and item is None: abort(404)
    if request.method == "POST":
        try:
            item.title = request.form.get("title", "").strip()[:160]
            if not item.title: raise ValueError("Enter a reel title.")
            video = save_video(request.files.get("video"), "reels")
            if video: item.video_url = video
            thumb = request.files.get("thumbnail")
            if thumb and thumb.filename: item.thumbnail_url = save_image(thumb, "reels-thumbs")[0]
            pid = request.form.get("linked_product_id", "")
            item.linked_product_id = int(pid) if pid.isdigit() else None
            item.sort_order = int(request.form.get("sort_order") or 0)
            item.is_active = request.form.get("is_active") == "1"
            if not item.video_url: raise ValueError("Upload a video file.")
            db.session.add(item); db.session.commit()
            flash("Reel saved.", "success")
            return redirect(url_for("admin.reels"))
        except (ValueError, UploadError) as exc:
            db.session.rollback(); flash(str(exc), "error")
    return render_template("admin/content_form.html", title="Reel", kind="reels", item=item, products=_products())

@bp.post("/reels/<int:item_id>/delete")
def reel_delete(item_id):
    item = db.session.get(Reel, item_id)
    if item:
        delete_files(item.video_url, item.thumbnail_url); db.session.delete(item); db.session.commit()
        flash("Reel deleted.", "success")
    return redirect(url_for("admin.reels"))

@bp.post("/reels/reorder")
def reels_reorder():
    ids = [int(x) for x in request.form.getlist("ids") if x.isdigit()]
    for pos, ident in enumerate(ids):
        item = db.session.get(Reel, ident)
        if item: item.sort_order = pos
    db.session.commit(); flash("Reel order updated.", "success")
    return redirect(url_for("admin.reels"))

@bp.post("/reels/settings")
def reels_settings():
    from ..models import SiteSetting
    setting = db.session.get(SiteSetting, "home_reels") or SiteSetting(key="home_reels", value={})
    setting.value = {"enabled": request.form.get("enabled") == "1",
                     "max_count": max(1, min(20, int(request.form.get("max_count") or 8))),
                     "selected_ids": [int(x) for x in request.form.getlist("selected_ids") if x.isdigit()]}
    db.session.add(setting); db.session.commit()
    flash("Home reels settings saved.", "success")
    return redirect(url_for("admin.reels"))

@bp.get("/recipes")
def recipes():
    return render_template("admin/content_list.html", title="Recipes", kind="recipes",
        items=db.session.scalars(select(RecipeVideo).order_by(RecipeVideo.created_at.desc())).all())

@bp.route("/recipes/new", methods=["GET", "POST"])
@bp.route("/recipes/<int:item_id>/edit", methods=["GET", "POST"])
def recipe_form(item_id=None):
    item = db.session.get(RecipeVideo, item_id) if item_id else RecipeVideo(ingredients=[], linked_product_ids=[])
    if item_id and item is None: abort(404)
    if request.method == "POST":
        try:
            title = request.form.get("title", "").strip()
            if not title: raise ValueError("Enter a recipe title.")
            item.title = title[:180]; item.slug = _slug(title)
            collision = db.session.scalar(select(RecipeVideo).where(RecipeVideo.slug == item.slug, RecipeVideo.id != (item.id or 0)))
            if collision: item.slug = f"{item.slug}-{uuid.uuid4().hex[:6]}"
            item.description = request.form.get("description", "").strip()
            item.category = request.form.get("category", "").strip()[:100]
            item.ingredients = [x.strip() for x in request.form.get("ingredients", "").splitlines() if x.strip()]
            item.linked_product_ids = [int(x) for x in request.form.getlist("product_ids") if x.isdigit()]
            item.youtube_url = request.form.get("youtube_url", "").strip() or None
            video = save_video(request.files.get("video"), "recipes")
            if video: item.video_url = video
            thumb = request.files.get("thumbnail")
            if thumb and thumb.filename: item.thumbnail_url = save_image(thumb, "recipe-thumbs")[0]
            if item.youtube_url and not re.match(r"^https://(www\.)?(youtube\.com|youtu\.be)/", item.youtube_url):
                raise ValueError("Enter a valid YouTube URL.")
            if not item.video_url and not item.youtube_url: raise ValueError("Upload a video or enter a YouTube URL.")
            item.is_published = request.form.get("is_published") == "1"
            item.published_at = datetime.now(timezone.utc) if item.is_published else None
            db.session.add(item); db.session.commit()
            flash("Recipe saved.", "success"); return redirect(url_for("admin.recipes"))
        except (ValueError, UploadError) as exc:
            db.session.rollback(); flash(str(exc), "error")
    return render_template("admin/content_form.html", title="Recipe", kind="recipes", item=item, products=_products())

@bp.post("/recipes/<int:item_id>/delete")
def recipe_delete(item_id):
    item = db.session.get(RecipeVideo, item_id)
    if item:
        delete_files(item.video_url, item.thumbnail_url); db.session.delete(item); db.session.commit()
        flash("Recipe deleted.", "success")
    return redirect(url_for("admin.recipes"))

@bp.get("/bundles")
def bundles():
    return render_template("admin/content_list.html", title="Bundles", kind="bundles",
        items=db.session.scalars(select(Bundle).order_by(Bundle.created_at.desc())).all())

@bp.route("/bundles/new", methods=["GET", "POST"])
@bp.route("/bundles/<int:item_id>/edit", methods=["GET", "POST"])
def bundle_form(item_id=None):
    item = db.session.get(Bundle, item_id) if item_id else Bundle(product_quantities=[])
    if item_id and item is None: abort(404)
    if request.method == "POST":
        try:
            name = request.form.get("name", "").strip()
            if not name: raise ValueError("Enter a bundle name.")
            item.name = name[:180]; item.slug = _slug(name)
            collision = db.session.scalar(select(Bundle).where(Bundle.slug == item.slug, Bundle.id != (item.id or 0)))
            if collision: item.slug = f"{item.slug}-{uuid.uuid4().hex[:6]}"
            item.description = request.form.get("description", "").strip()
            item.bundle_price = float(request.form.get("bundle_price") or 0)
            if item.bundle_price < 0: raise ValueError("Bundle price cannot be negative.")
            items = []
            seen_products = set()
            for pid, qty in zip(request.form.getlist("product_id"), request.form.getlist("quantity")):
                if pid.isdigit() and qty.isdigit() and int(qty) > 0 and db.session.get(Product, int(pid)):
                    if int(pid) in seen_products: raise ValueError("Choose each product only once in a bundle.")
                    seen_products.add(int(pid))
                    items.append({"product_id": int(pid), "quantity": min(int(qty), 50)})
            if not items: raise ValueError("Choose at least one product.")
            regular_total = sum((db.session.get(Product, line["product_id"]).final_price * line["quantity"] for line in items), 0)
            if item.bundle_price <= 0 or item.bundle_price >= float(regular_total):
                raise ValueError("Bundle price must be positive and lower than the combined product price.")
            item.product_quantities = items
            image = request.files.get("image")
            if image and image.filename: item.image_url = save_image(image, "bundles")[0]
            item.is_active = request.form.get("is_active") == "1"
            def parse_dt(value):
                if not value: return None
                parsed = datetime.fromisoformat(value)
                return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed
            item.starts_at = parse_dt(request.form.get("starts_at", ""))
            item.ends_at = parse_dt(request.form.get("ends_at", ""))
            if item.starts_at and item.ends_at and item.ends_at <= item.starts_at:
                raise ValueError("Bundle end date must be after its start date.")
            db.session.add(item); db.session.commit()
            flash("Bundle saved.", "success"); return redirect(url_for("admin.bundles"))
        except (ValueError, UploadError) as exc:
            db.session.rollback(); flash(str(exc), "error")
    return render_template("admin/content_form.html", title="Bundle", kind="bundles", item=item, products=_products())

@bp.post("/bundles/<int:item_id>/delete")
def bundle_delete(item_id):
    item = db.session.get(Bundle, item_id)
    if item:
        delete_files(item.image_url); db.session.delete(item); db.session.commit()
        flash("Bundle deleted.", "success")
    return redirect(url_for("admin.bundles"))

@bp.get("/orders")
def orders():
    from ..models import Order
    from sqlalchemy.orm import joinedload
    q = request.args.get("q", "").strip()[:80]
    status = request.args.get("status", "").strip()
    stmt = select(Order).options(joinedload(Order.user)).order_by(Order.created_at.desc())
    if status: stmt = stmt.where(Order.status == status)
    if q: stmt = stmt.where(Order.order_number.ilike(f"%{q}%"))
    items = db.session.scalars(stmt.limit(200)).unique().all()
    return render_template("admin/orders.html", items=items, q=q, status=status)

@bp.get("/orders/<int:order_id>")
def order_detail(order_id):
    from ..models import Order
    from sqlalchemy.orm import joinedload
    order = db.session.scalar(select(Order).where(Order.id == order_id).options(joinedload(Order.user), joinedload(Order.items)))
    if not order: abort(404)
    history = db.session.scalars(select(OrderStatusHistory).where(OrderStatusHistory.order_id == order.id).order_by(OrderStatusHistory.created_at, OrderStatusHistory.id)).all()
    return render_template("admin/order_detail.html", order=order, history=history,
                           next_actions=_ADMIN_ORDER_TRANSITIONS.get(order.status, ()))


# ---------------------------------------------------------------- order status management
_ADMIN_ORDER_TRANSITIONS = {
    "placed": ("confirmed", "rejected", "cancelled"),
    "confirmed": ("packed", "cancelled"),
    "packed": ("shipped", "cancelled"),
    "shipped": ("delivered", "returned"),
    "out_for_delivery": ("delivered", "returned"),
    "delivered": ("returned",),
    "return_requested": ("returned", "delivered"),
    "returned": ("refunded",),
    "rejected": ("refunded",),
    "cancelled": ("refunded",),
    "refunded": (),
}
_ADMIN_STATUS_COPY = {
    "confirmed": ("Order confirmed", "Your order #{n} has been confirmed. We're getting it ready."),
    "packed": ("Order packed", "Your order #{n} is packed and ready to ship."),
    "shipped": ("Order shipped", "Your order #{n} is on its way."),
    "delivered": ("Order delivered", "Your order #{n} was delivered. Tell us how you liked it!"),
    "rejected": ("Order rejected", "Sorry, we couldn't accept order #{n}. Reason: {reason}"),
    "cancelled": ("Order cancelled", "Your order #{n} has been cancelled."),
    "returned": ("Order returned", "We've received the return for order #{n}."),
    "refunded": ("Refund processed", "Your refund of ₹{total} for order #{n} has been processed."),
}

@bp.post("/orders/<int:order_id>/status")
def order_status_update(order_id):
    from ..models import AuditLog
    from ..services.inventory import restore_order_stock
    from ..services.coupons import release as release_coupon
    from ..models.base import utcnow
    order = db.session.scalar(select(Order).where(Order.id == order_id).with_for_update())
    if order is None:
        abort(404)
    target = (request.form.get("status") or "").strip().lower()
    reason = " ".join((request.form.get("reason") or "").split())[:300]
    allowed = _ADMIN_ORDER_TRANSITIONS.get(order.status, ())
    if target not in allowed:
        flash("That status change is not allowed for this order.", "error")
        return redirect(url_for("admin.order_detail", order_id=order.id))
    if target in ("rejected", "returned") and len(reason) < 5:
        flash("Please provide a reason of at least 5 characters.", "error")
        return redirect(url_for("admin.order_detail", order_id=order.id))
    if target == "refunded" and order.payment_status != "paid":
        flash("Only paid orders can be marked refunded.", "error")
        return redirect(url_for("admin.order_detail", order_id=order.id))
    old = order.status
    order.status = target
    order.updated_at = utcnow()
    if target in ("rejected", "cancelled", "returned"):
        restore_order_stock(order, f"order {order.order_number} {target} by admin", g.user.id)
        if target in ("rejected", "cancelled"):
            release_coupon(order)
        if target == "rejected":
            order.rejection_reason = reason
    if target == "refunded":
        order.payment_status = "refunded"
        for payment in order.payments:
            if payment.status == "paid":
                payment.status = "refunded"
    if target == "delivered" and order.payment_method == "cod" and order.payment_status == "pending":
        order.payment_status = "paid"
        for payment in order.payments:
            if payment.status == "pending":
                payment.status = "paid"
    db.session.add(OrderStatusHistory(order_id=order.id, from_status=old, to_status=target,
                                      changed_by=g.user.id, note=reason or None))
    title, body = _ADMIN_STATUS_COPY[target]
    body = body.format(n=order.order_number, reason=reason or "not specified", total=f"{order.total:,.2f}")
    db.session.add(Notification(user_id=order.user_id, channel="in_app", kind="order_status",
                                title=title.format(n=order.order_number), body=body,
                                link=f"/account/orders/{order.order_number}", is_read=False))
    db.session.add(AuditLog(actor_id=g.user.id, action=f"order.{target}",
                            entity_type="order", entity_id=str(order.id),
                            before={"status": old}, after={"status": target, "reason": reason or None}))
    db.session.commit()
    flash(f"Order {order.order_number} updated to {target.replace('_', ' ').title()}.", "success")
    return redirect(url_for("admin.order_detail", order_id=order.id))
