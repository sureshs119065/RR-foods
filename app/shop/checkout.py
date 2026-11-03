from flask import abort, current_app, flash, g, redirect, render_template, request, session, url_for
from sqlalchemy import select

from ..auth.decorators import roles_required
from ..extensions import db, limiter
from ..models import Address, Order
from ..services import cart as cart_svc
from ..services import checkout as svc
from ..services.cart import totals_for
from . import bp

user_only = roles_required("user")


def _addresses():
    return list(db.session.scalars(select(Address).where(Address.user_id == g.user.id).order_by(Address.is_default.desc(), Address.id.desc())))


@bp.get("/checkout")
@user_only
def checkout_page():
    view = cart_svc.build(g.user.id, session.get("coupon"))
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
    return render_template("shop/checkout.html", view=view, addrs=addrs, chosen=chosen, quotes=quotes, totals=totals, methods=svc.payment_methods())


@bp.post("/checkout")
@user_only
@limiter.limit("20 per minute")
def checkout_place():
    try:
        order = svc.place_order(g.user, int(request.form.get("address_id") or 0) if (request.form.get("address_id") or "").isdigit() else 0,
                                request.form.get("method", ""), session.get("coupon"), request.form.get("notes"))
        db.session.commit()
    except svc.CheckoutError as e:
        db.session.rollback()
        flash(str(e), "error")
        return redirect(url_for("shop.checkout_page", address=request.form.get("address_id")))
    session.pop("coupon", None)
    if order.payment_method == "online":
        return redirect(url_for("shop.pay", order_number=order.order_number))
    flash(f"Order {order.order_number} placed. We will confirm it shortly.", "success")
    return redirect(url_for("shop.order_detail", order_number=order.order_number))


# ---------------------------------------------------------------- online payment (stub)
def _my_order(order_number: str) -> Order:
    order = db.session.scalar(select(Order).where(Order.order_number == order_number, Order.user_id == g.user.id))
    if order is None:
        abort(404)
    return order


@bp.get("/pay/<order_number>")
@user_only
def pay(order_number):
    """Where the real gateway (Razorpay) checkout opens. Today this is a stub: see README, 'Plugging in Razorpay'."""
    order = _my_order(order_number)
    if order.payment_status == "paid":
        return redirect(url_for("shop.order_detail", order_number=order.order_number))
    return render_template("shop/pay.html", order=order, stub=current_app.config.get("ONLINE_PAYMENT_MODE") == "stub")


@bp.post("/pay/<order_number>/simulate")
@user_only
def pay_simulate(order_number):
    if current_app.config.get("ONLINE_PAYMENT_MODE") != "stub":
        abort(404)  # never available in production
    order = _my_order(order_number)
    if order.payment_status == "pending" and order.status in ("placed", "confirmed", "packed"):
        order.payment_status = "paid"
        for p in order.payments:
            if p.status == "pending":
                p.status, p.raw = "paid", {"stub": True}
        db.session.commit()
        flash("Test payment recorded. (No money moved: this is the stub gateway.)", "success")
    return redirect(url_for("shop.order_detail", order_number=order.order_number))
