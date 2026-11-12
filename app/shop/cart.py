from flask import g, jsonify, redirect, render_template, request, session, url_for
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from ..auth.decorators import roles_required
from ..auth.service import PORTALS, safe_next
from ..extensions import db, limiter
from ..models import CartItem, Product, ProductVariant
from ..services import cart as svc
from ..services import coupons
from ..services.storefront import LIVE, active_variants
from ..admin.helpers import to_int
from . import bp, reply, wants_json

user_only = roles_required("user")


def _need_login():
    """Signed-out visitors: JSON callers get a 401 with the login link, form posts are sent to sign in and then back."""
    nxt = safe_next(request.form.get("next"), "/cart")
    login = f"{PORTALS['user']['login']}?next={nxt}"
    if wants_json():
        return jsonify(ok=False, message="Please sign in to add items to your cart.", login=login), 401
    return redirect(login)


@bp.get("/cart")
@user_only
def cart():
    view = svc.build(g.user.id, session.get("coupon"))
    if session.get("coupon") and view.coupon is None and view.coupon_error:
        pass  # keep the code visible with its error so the customer can see why and remove it
    from ..services.recommendations import cart_suggestions
    cart_product_ids = [line.product.id for line in view.lines]
    suggestions = cart_suggestions(cart_product_ids)
    from ..services.delivery_slots import get_settings
    return render_template("shop/cart.html", view=view, max_qty=svc.MAX_LINE_QTY, suggestions=suggestions, delivery_settings=get_settings())


def _add_one(user, product_id, variant_id, qty):
    """Add to (or raise) one cart line. Returns (message, ok). Quantity is clamped to stock and the per-line maximum."""
    p = db.session.scalar(select(Product).where(Product.id == product_id, LIVE))
    if p is None:
        return "That product is not available.", False
    options = active_variants(p)
    v = None
    if options:
        v = next((x for x in options if x.id == variant_id), None)
        if v is None:
            return "Choose an option first.", False
    elif variant_id:
        return "That option does not exist.", False
    stock = v.stock_qty if v else p.stock_qty
    if stock <= 0:
        return f"Sorry, {p.name} is out of stock.", False
    limit = min(stock, svc.MAX_LINE_QTY)
    for attempt in (1, 2):
        item = db.session.scalar(select(CartItem).where(CartItem.user_id == user.id, CartItem.product_id == p.id,
                                                        CartItem.bundle_id.is_(None),
                                                        CartItem.variant_id.is_(None) if v is None else CartItem.variant_id == v.id))
        had = item.quantity if item and not item.saved_for_later else 0
        new = min(had + qty, limit)
        try:
            if item is None:
                db.session.add(CartItem(user_id=user.id, product_id=p.id, variant_id=v.id if v else None, quantity=new))
            else:
                item.quantity, item.saved_for_later = new, False
            db.session.commit()
            break
        except IntegrityError:  # two taps at once created the same line: retry once against the row that won
            db.session.rollback()
            if attempt == 2:
                return "Could not update your cart. Please try again.", False
    name = p.name + (f" ({v.option_value})" if v else "")
    if had + qty > limit:
        return f"Added {name}. You can have at most {limit} of this item (stock or order limit).", True
    return f"Added {name} to your cart.", True


@bp.post("/cart/add")
@limiter.limit("60 per minute")
def cart_add():
    if g.get("user") is None:
        return _need_login()
    if g.user.role != "user":
        return reply(False, "Only customer accounts can shop. Sign in with a customer account.", "/", 403)
    errs: dict = {}
    pid = to_int(request.form.get("product_id"), "p", errs, min_=1, max_=2_000_000_000)
    vid = to_int(request.form.get("variant_id"), "v", errs, min_=1, max_=2_000_000_000, required=False, default=None)
    qty = to_int(request.form.get("qty") or "1", "q", errs, min_=1, max_=svc.MAX_LINE_QTY)
    if errs:
        return reply(False, "Choose a quantity from 1 to %d." % svc.MAX_LINE_QTY, "/cart", 422)
    msg, ok = _add_one(g.user, pid, vid, qty)
    if ok and request.form.get("buy_now"):
        return redirect(url_for("shop.checkout_page"))
    return reply(ok, msg, "/cart", 200 if ok else 409, count=svc.count_in_cart(g.user.id))


@bp.post("/cart/add-many")
@user_only
@limiter.limit("30 per minute")
def cart_add_many():
    """Add one of each selected product/variant in the frequently-bought-together set."""
    raw_ids = request.form.getlist("product_id")[:6]
    raw_variants = request.form.getlist("variant_id")[:6]
    added, problems = 0, []
    for index, raw_pid in enumerate(raw_ids):
        if not raw_pid.isdigit():
            continue
        raw_vid = raw_variants[index] if index < len(raw_variants) else ""
        variant_id = int(raw_vid) if raw_vid.isdigit() else None
        msg, ok = _add_one(g.user, int(raw_pid), variant_id, 1)
        added += ok
        if not ok:
            problems.append(msg)
    text = f"Added {added} item{'s' if added != 1 else ''} to your cart." + (" " + " ".join(problems) if problems else "")
    return reply(added > 0, text, "/cart", count=svc.count_in_cart(g.user.id))


def _own_item(item_id: int) -> CartItem | None:
    item = db.session.get(CartItem, item_id)
    return item if item is not None and item.user_id == g.user.id else None


@bp.post("/cart/<int:item_id>/qty")
@user_only
def cart_qty(item_id):
    item = _own_item(item_id)
    if item is None:
        return reply(False, "That item is no longer in your cart.", "/cart", 404)
    line = svc.make_line(item)
    action = request.form.get("action")
    if action == "inc":
        new = item.quantity + 1
    elif action == "dec":
        new = item.quantity - 1
    else:
        errs: dict = {}
        new = to_int(request.form.get("qty"), "qty", errs, min_=0, max_=svc.MAX_LINE_QTY)
        if errs:
            return reply(False, "Enter a quantity from 1 to %d." % svc.MAX_LINE_QTY, "/cart", 422)
    if new <= 0:
        db.session.delete(item)
        db.session.commit()
        return reply(True, "Removed from your cart.", "/cart")
    if line.stock <= 0:
        return reply(False, "This item is out of stock. Remove it or save it for later.", "/cart", 409)
    capped = min(new, line.limit)
    item.quantity = capped
    if item.unit_price_override is not None:
        item.line_total_override = item.unit_price_override * capped
    db.session.commit()
    if capped < new:
        return reply(False, f"Only {capped} available.", "/cart", 409, qty=capped)
    return reply(True, "Cart updated.", "/cart", qty=capped)


@bp.post("/cart/<int:item_id>/remove")
@user_only
def cart_remove(item_id):
    item = _own_item(item_id)
    if item is not None:
        db.session.delete(item)
        db.session.commit()
    return reply(True, "Removed from your cart.", "/cart")


@bp.post("/cart/<int:item_id>/save")
@user_only
def cart_save(item_id):
    """Save for later / move back to cart (saved=1 or 0)."""
    item = _own_item(item_id)
    if item is None:
        return reply(False, "That item is no longer in your cart.", "/cart", 404)
    item.saved_for_later = request.form.get("saved") == "1"
    db.session.commit()
    return reply(True, "Saved for later." if item.saved_for_later else "Moved back to your cart.", "/cart")


@bp.post("/cart/coupon")
@user_only
def cart_coupon():
    code = coupons.normalize_code(request.form.get("code"))
    if not code:
        return reply(False, "Enter a coupon code.", "/cart", 422)
    view = svc.build(g.user.id, code)
    if view.coupon is None or view.coupon_error:
        return reply(False, view.coupon_error or "That coupon code does not exist.", "/cart", 422)
    session["coupon"] = view.coupon.code
    return reply(True, f"Coupon {view.coupon.code} applied. You save ₹{view.totals.discount:,.2f}.", "/cart")


@bp.post("/cart/coupon/remove")
@user_only
def cart_coupon_remove():
    session.pop("coupon", None)
    return reply(True, "Coupon removed.", "/cart")
