from flask import abort, flash, g, redirect, render_template, request, session, url_for
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from ..auth.decorators import roles_required
from ..extensions import db, limiter
from ..models import Address, Order
from ..services import cart as cart_svc
from ..services import checkout as svc
from ..services.cart import totals_for
from ..services import delivery_slots
from . import bp

user_only = roles_required("user")


def _addresses():
    return list(db.session.scalars(select(Address).where(Address.user_id == g.user.id).order_by(Address.is_default.desc(), Address.id.desc())))


@bp.get("/checkout")
@user_only
def checkout_page():
    buy_now = session.get("buy_now")
    view = cart_svc.build_single(g.user.id, buy_now, session.get("coupon")) if buy_now else cart_svc.build(g.user.id, session.get("coupon"))
    if not view.lines:
        flash("Your cart is empty.", "info")
        return redirect(url_for("shop.cart"))
    if not view.can_checkout:
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
    slot_dates = delivery_slots.available_dates()
    delivery_settings = delivery_slots.get_settings()
    return render_template("shop/checkout.html", view=view, buy_now=buy_now, addrs=addrs, chosen=chosen, last_address=last_address, quotes=quotes, totals=totals, methods=svc.payment_methods(), checkout_token=checkout_token, slot_dates=slot_dates, delivery_settings=delivery_settings)


@bp.post("/checkout")
@user_only
@limiter.limit("20 per minute")
def checkout_place():
    submitted_token = request.form.get("checkout_token", "")
    if not submitted_token or submitted_token != session.get("checkout_token"):
        flash("This checkout has already been submitted or expired. Please review your order.", "info")
        return redirect(url_for("shop.orders"))
    try:
        order = svc.place_order(g.user, int(request.form.get("address_id") or 0) if (request.form.get("address_id") or "").isdigit() else 0,
                                request.form.get("method", ""), session.get("coupon"), request.form.get("notes"), request.form.get("delivery_date"), request.form.get("delivery_slot"), request.form.get("gift_message"), request.form.get("hide_prices") == "1", buy_now=session.get("buy_now"))
        db.session.commit()
        session.pop("checkout_token", None)
    except svc.CheckoutError as e:
        db.session.rollback()
        flash(str(e), "error")
        return redirect(url_for("shop.checkout_page", address=request.form.get("address_id")))
    session.pop("coupon", None)
    session.pop("buy_now", None)
    return redirect(url_for("shop.order_placed", order_number=order.order_number))


# ---------------------------------------------------------------- order placed: send it to the owner on WhatsApp
@bp.get("/order-placed/<order_number>")
@user_only
def order_placed(order_number):
    """Shown right after checkout. The big button opens WhatsApp with the whole order already written."""
    order = db.session.scalar(select(Order).where(Order.order_number == order_number, Order.user_id == g.user.id).options(selectinload(Order.items)))
    if order is None:
        abort(404)
    from ..services.whatsapp import owner_link, order_message
    wa = owner_link(order)
    return render_template("shop/order_placed.html", order=order, wa=wa, wa_text=order_message(order))


@bp.get("/checkout/delivery-slots")
@user_only
@limiter.limit("60 per minute")
def checkout_delivery_slots():
    from datetime import date
    from flask import jsonify
    raw = (request.args.get("date") or "").strip()
    try:
        day = date.fromisoformat(raw)
    except ValueError:
        return jsonify(ok=False, message="Choose a valid date.", slots=[]), 422
    settings = delivery_slots.get_settings()
    choices = {item["value"]: item for item in delivery_slots.available_dates(settings)}
    item = choices.get(day.isoformat())
    return jsonify(ok=True, slots=item["slots"] if item else [], message="" if item else "No delivery slots are available for this date.")
