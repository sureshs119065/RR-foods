from flask import abort, flash, g, jsonify, redirect, render_template, request, session, url_for
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from ..auth.service import PORTALS, safe_next
from .. import ratelimits as limits
from ..extensions import db, limiter
from ..models import CartItem, Product, ProductVariant
from ..services import cart as svc
from ..services import coupons
from ..services.storefront import LIVE, active_variants
from ..services.suspicious import log_suspicious, note_tampered_fields
from ..admin.helpers import to_int
from . import bp, reply, wants_json

def _need_login():
    """Wishlist, reviews and other account-only actions: JSON callers get a 401 with the login link, form posts are sent to sign in and back."""
    nxt = safe_next(request.form.get("next"), "/cart")
    login = f"{PORTALS['user']['login']}?next={nxt}"
    if wants_json():
        return jsonify(ok=False, message="Please sign in to do that.", login=login), 401
    return redirect(login)


def _staff_blocked() -> bool:
    """Owner/admin accounts do not shop. Guests and customers both may use the cart."""
    return g.get("user") is not None and g.user.role != "user"


def _staff_reply():
    return reply(False, "Only customer accounts can shop. Sign in with a customer account.", "/", 403)


def guest_cart(view):
    """Decorator: the cart works for guests (cookie-session cart) and customers; staff accounts get 403."""
    from functools import wraps

    @wraps(view)
    def wrapped(*args, **kwargs):
        if _staff_blocked():
            return _staff_reply() if wants_json() else abort(403)
        return view(*args, **kwargs)
    return wrapped


@bp.get("/cart")
@guest_cart
def cart():
    view = svc.build(svc.cart_owner(), session.get("coupon"))
    if session.get("coupon") and view.coupon is None and view.coupon_error:
        pass  # keep the code visible with its error so the customer can see why and remove it
    from ..services.recommendations import cart_suggestions
    cart_product_ids = [line.product.id for line in view.lines]
    suggestions = cart_suggestions(cart_product_ids)
    return render_template("shop/cart.html", view=view, max_qty=svc.MAX_LINE_QTY, suggestions=suggestions)


def _add_one(owner, product_id, variant_id, qty, *, replace=False):
    """Add to (or raise) one cart line. Returns (message, ok). Quantity is clamped to stock and the per-line maximum."""
    p = db.session.scalar(select(Product).where(Product.id == product_id, LIVE))
    if p is None:
        log_suspicious("unknown_or_hidden_product", f"product_id={product_id}")
        return "That product is not available.", False
    options = active_variants(p)
    v = None
    if options:
        v = next((x for x in options if x.id == variant_id), None)
        if v is None:
            if variant_id:
                log_suspicious("invalid_variant", f"product_id={p.id} variant_id={variant_id}")
            return "Choose an option first.", False
    elif variant_id:
        log_suspicious("invalid_variant", f"product_id={p.id} variant_id={variant_id}")
        return "That option does not exist.", False
    stock = v.stock_qty if v else p.stock_qty
    if stock <= 0:
        return f"Sorry, {p.name} is out of stock.", False
    limit = min(stock, svc.MAX_LINE_QTY)
    if owner.is_guest:  # keep anonymous carts bounded
        lines = db.session.scalar(select(func.count(CartItem.id)).where(owner.where())) or 0
        if lines >= svc.MAX_GUEST_LINES:
            return "Your cart is full. Sign in or remove something first.", False
    for attempt in (1, 2):
        item = db.session.scalar(select(CartItem).where(owner.where(), CartItem.product_id == p.id,
                                                        CartItem.bundle_id.is_(None),
                                                        CartItem.variant_id.is_(None) if v is None else CartItem.variant_id == v.id))
        had = item.quantity if item and not item.saved_for_later else 0
        new = min(qty if replace else had + qty, limit)
        try:
            if item is None:
                db.session.add(CartItem(**owner.values(), product_id=p.id, variant_id=v.id if v else None, quantity=new))
            else:
                item.quantity, item.saved_for_later = new, False
            db.session.commit()
            break
        except IntegrityError:  # two taps at once created the same line: retry once against the row that won
            db.session.rollback()
            if attempt == 2:
                return "Could not update your cart. Please try again.", False
    name = p.name + (f" ({v.option_value})" if v else "")
    if (qty if replace else had + qty) > limit:
        return f"Added {name}. You can have at most {limit} of this item (stock or order limit).", True
    return f"Added {name} to your cart.", True


@bp.post("/buy-now")
@limiter.limit("30 per minute")
@limiter.limit(limits.limit("cart_add"))
@guest_cart
def buy_now():
    """Add the selected quantity once, then go straight to checkout (guests are asked to sign in there)."""
    errs: dict = {}
    note_tampered_fields()
    pid = to_int(request.form.get("product_id"), "p", errs, min_=1, max_=2_000_000_000)
    vid = to_int(request.form.get("variant_id"), "v", errs, min_=1, max_=2_000_000_000, required=False, default=None)
    qty = to_int(request.form.get("qty") or "1", "q", errs, min_=1, max_=svc.MAX_LINE_QTY)
    if errs:
        log_suspicious("invalid_product_or_quantity", f"product_id={request.form.get('product_id')} qty={request.form.get('qty')}")
        flash("Choose a valid quantity before continuing.", "error")
        return redirect(request.form.get("next") or url_for("shop.listing"))
    msg, ok = _add_one(svc.cart_owner(create=True), pid, vid, qty, replace=True)
    if not ok:
        flash(msg, "error")
        return redirect(request.form.get("next") or url_for("shop.listing"))
    return redirect(url_for("shop.checkout_page"))


@bp.post("/cart/add")
@limiter.limit(limits.limit("cart_add"))
@guest_cart
def cart_add():
    errs: dict = {}
    note_tampered_fields()
    pid = to_int(request.form.get("product_id"), "p", errs, min_=1, max_=2_000_000_000)
    vid = to_int(request.form.get("variant_id"), "v", errs, min_=1, max_=2_000_000_000, required=False, default=None)
    qty = to_int(request.form.get("qty") or "1", "q", errs, min_=1, max_=svc.MAX_LINE_QTY)
    if errs:
        log_suspicious("invalid_product_or_quantity", f"product_id={request.form.get('product_id')} qty={request.form.get('qty')}")
        return reply(False, "Choose a quantity from 1 to %d." % svc.MAX_LINE_QTY, "/cart", 422)
    owner = svc.cart_owner(create=True)
    msg, ok = _add_one(owner, pid, vid, qty)
    if ok and request.form.get("buy_now"):
        return redirect(url_for("shop.checkout_page"))
    return reply(ok, msg, "/cart", 200 if ok else 409, count=svc.count_in_cart(owner))


@bp.post("/cart/add-many")
@guest_cart
@limiter.limit("30 per minute")
def cart_add_many():
    """Add one of each selected product/variant in the frequently-bought-together set."""
    raw_ids = request.form.getlist("product_id")[:6]
    raw_variants = request.form.getlist("variant_id")[:6]
    owner = svc.cart_owner(create=True)
    added, problems = 0, []
    for index, raw_pid in enumerate(raw_ids):
        if not raw_pid.isdigit():
            continue
        raw_vid = raw_variants[index] if index < len(raw_variants) else ""
        variant_id = int(raw_vid) if raw_vid.isdigit() else None
        msg, ok = _add_one(owner, int(raw_pid), variant_id, 1)
        added += ok
        if not ok:
            problems.append(msg)
    text = f"Added {added} item{'s' if added != 1 else ''} to your cart." + (" " + " ".join(problems) if problems else "")
    return reply(added > 0, text, "/cart", count=svc.count_in_cart(owner))


def _own_item(item_id: int) -> CartItem | None:
    owner = svc.cart_owner()
    if owner is None:
        return None
    item = db.session.get(CartItem, item_id)
    if item is None:
        return None
    mine = item.user_id == owner.user_id if owner.user_id is not None else (item.user_id is None and item.session_id == owner.session_id)
    if not mine:
        log_suspicious("other_customers_cart_line", f"cart_item_id={item_id}")
    return item if mine else None


@bp.post("/cart/<int:item_id>/qty")
@limiter.limit(limits.limit("cart_change"))
@guest_cart
def cart_qty(item_id):
    note_tampered_fields()
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
            log_suspicious("invalid_quantity", f"cart_item_id={item_id} qty={request.form.get('qty')}")
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
@limiter.limit(limits.limit("cart_change"))
@guest_cart
def cart_remove(item_id):
    item = _own_item(item_id)
    if item is not None:
        db.session.delete(item)
        db.session.commit()
    return reply(True, "Removed from your cart.", "/cart")


@bp.post("/cart/<int:item_id>/save")
@limiter.limit(limits.limit("cart_change"))
@guest_cart
def cart_save(item_id):
    """Save for later / move back to cart (saved=1 or 0)."""
    item = _own_item(item_id)
    if item is None:
        return reply(False, "That item is no longer in your cart.", "/cart", 404)
    item.saved_for_later = request.form.get("saved") == "1"
    db.session.commit()
    return reply(True, "Saved for later." if item.saved_for_later else "Moved back to your cart.", "/cart")


@bp.post("/cart/coupon")
@guest_cart
@limiter.limit(limits.limit("coupon"))
def cart_coupon():
    note_tampered_fields()  # a "discount" sent from the browser is logged and ignored: the server works out every discount itself
    from .. import validation as v
    code_errors: dict = {}
    code = v.coupon_code(request.form.get("code"), "code", code_errors)
    if code_errors:
        return reply(False, code_errors["code"], "/cart", 422)
    view = svc.build(svc.cart_owner(), code)
    if view.coupon is None or view.coupon_error:
        return reply(False, view.coupon_error or "That coupon code does not exist.", "/cart", 422)
    session["coupon"] = view.coupon.code
    return reply(True, f"Coupon {view.coupon.code} applied. You save ₹{view.totals.discount:,.2f}.", "/cart")


@bp.post("/cart/coupon/remove")
@guest_cart
def cart_coupon_remove():
    session.pop("coupon", None)
    return reply(True, "Coupon removed.", "/cart")
