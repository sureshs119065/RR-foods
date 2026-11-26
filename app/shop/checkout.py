import re

from flask import abort, flash, g, redirect, render_template, request, session, url_for
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from ..auth.decorators import roles_required
from ..extensions import db, limiter
from ..models import Address, Order
from ..models.orders import DRAFT_STATUS
from ..services import cart as cart_svc
from ..services import checkout as svc
from ..services.cart import totals_for
from ..services.suspicious import note_tampered_fields
from . import bp

user_only = roles_required("user")
_TOKEN_OK = re.compile(r"[A-Za-z0-9_-]{16,64}")  # what secrets.token_urlsafe(24) produces


def _addresses():
    return list(db.session.scalars(select(Address).where(Address.user_id == g.user.id).order_by(Address.is_default.desc(), Address.id.desc())))


def _is_buy_now() -> bool:
    """/checkout?buy_now=1 is the "Buy now" checkout (one product, cart untouched). Plain /checkout is the whole cart."""
    return request.values.get("buy_now") == "1"


@bp.get("/checkout")
@user_only
def checkout_page():
    buy_now = _is_buy_now()
    only = cart_svc.buy_now_items(g.user.id) if buy_now else None
    if not buy_now:
        session.pop(cart_svc.BUY_NOW_KEY, None)  # checking out the cart: a leftover "Buy now" choice must not mix in
    elif not only:
        flash("That product is no longer available. Please choose it again.", "info")
        return redirect(url_for("shop.listing"))
    view = cart_svc.build(g.user.id, session.get("coupon"), only=only)
    if not view.lines:
        flash("Your cart is empty.", "info")
        return redirect(url_for("shop.cart"))
    if not view.can_checkout:
        if buy_now:
            flash("; ".join(view.problems) or "This product cannot be ordered right now.", "error")
            return redirect(url_for("shop.listing"))
        flash("Fix the highlighted problems in your cart first.", "error")
        return redirect(url_for("shop.cart"))
    addrs = _addresses()
    chosen = next((a for a in addrs if str(a.id) == request.args.get("address")), None) or (addrs[0] if addrs else None)
    quotes = {}
    for a in addrs:
        zone = svc.zone_for(a.pincode)
        ok = zone is not None and zone.is_serviceable
        t = totals_for(view.lines, view.totals.discount, zone if ok else None)
        quotes[a.id] = {"ok": ok, "delivery": t.delivery, "total": t.total, "eta": zone.eta_days if ok else None}
    sel = quotes.get(chosen.id) if chosen else None
    totals = totals_for(view.lines, view.totals.discount, svc.zone_for(chosen.pincode) if chosen and sel and sel["ok"] else None)
    import secrets
    checkout_token = session.get("checkout_token") or secrets.token_urlsafe(24)
    session["checkout_token"] = checkout_token
    last_address = max(addrs, key=lambda a: (a.updated_at or a.created_at, a.id), default=None)
    from flask import get_flashed_messages
    errors = get_flashed_messages(category_filter=["error"])  # shown in the inline summary, not as a separate banner
    field_errors = {}
    for msg in errors:
        low = msg.lower()
        if "address" in low or "deliver to" in low:
            field_errors.setdefault("address_id", msg)
    return render_template("shop/checkout.html", errors=errors, field_errors=field_errors, view=view, addrs=addrs, chosen=chosen, last_address=last_address, quotes=quotes, totals=totals, methods=svc.payment_methods(), checkout_token=checkout_token, buy_now=buy_now)


@bp.post("/checkout")
@user_only
@limiter.limit("20 per minute")
def checkout_place():
    """The browser sends only: the address, the payment method, text notes and the form's one-time token. Prices, stock, the coupon,
    the delivery fee and the total are all worked out again here from the database; any price-like field sent is logged and ignored."""
    note_tampered_fields()
    buy_now = _is_buy_now()
    keep = {"buy_now": 1} if buy_now else {}
    submitted_token = (request.form.get("checkout_token") or "").strip()
    if not _TOKEN_OK.fullmatch(submitted_token):
        flash("This checkout expired. Please review your order and try again.", "info")
        return redirect(url_for("shop.checkout_page", **keep))
    if submitted_token != session.get("checkout_token"):
        # Back button / refresh after the order was already saved: show that order instead of an error (and never create a second).
        earlier = svc.order_for_key(g.user.id, submitted_token)
        if earlier is not None:
            return redirect(url_for("shop.order_placed", order_number=earlier.order_number))
        flash("This checkout has already been submitted or expired. Please review your order.", "info")
        return redirect(url_for("shop.orders"))
    from .. import validation as v
    note_errors: dict = {}
    notes = v.multiline(request.form.get("notes"), "notes", note_errors, label="Order notes", max_=v.MAX["notes"])
    if note_errors:
        flash(note_errors["notes"], "error")
        return redirect(url_for("shop.checkout_page", address=request.form.get("address_id"), **keep))
    try:
        order = svc.create_pending_order(g.user, int(request.form.get("address_id") or 0) if (request.form.get("address_id") or "").isdigit() else 0,
                                request.form.get("method", ""), session.get("coupon"), notes,
                                idempotency_key=submitted_token, only_items=cart_svc.buy_now_items(g.user.id) if buy_now else None)
        db.session.commit()
        session.pop("checkout_token", None)
        if buy_now:
            session.pop(cart_svc.BUY_NOW_KEY, None)
    except svc.CheckoutError as e:
        db.session.rollback()
        flash(str(e), "error")  # e.g. "“Ragi flour” is down to 1. Update your cart and try again." The other cart items are untouched.
        return redirect(url_for("shop.checkout_page", address=request.form.get("address_id"), **keep))
    # The cart and the coupon stay as they are: this is only a request until the shop receives the WhatsApp message.
    return redirect(url_for("shop.order_placed", order_number=order.order_number))


# ---------------------------------------------------------------- order request: send it to the shop on WhatsApp
@bp.get("/order-placed/<order_number>")
@user_only
def order_placed(order_number):
    """Shown right after checkout. The order is NOT placed yet: the big button opens WhatsApp with the whole order already written,
    and the order is placed only when the shop confirms that the message arrived."""
    order = db.session.scalar(select(Order).where(Order.order_number == order_number, Order.user_id == g.user.id).options(selectinload(Order.items)))
    if order is None:
        abort(404)
    if order.status != DRAFT_STATUS:  # already confirmed by the shop (or closed): the tracking page is the right place
        return redirect(url_for("shop.order_detail", order_number=order.order_number))
    from ..services.whatsapp import owner_link, order_message
    wa = owner_link(order)
    return render_template("shop/order_placed.html", order=order, wa=wa, wa_text=order_message(order))
