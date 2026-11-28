import re

from flask import abort, flash, g, jsonify, make_response, redirect, render_template, request, url_for
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from ..admin.helpers import clean, page_number
from ..auth.decorators import roles_required
from ..extensions import db, limiter
from ..models import Address, Order, OrderStatusHistory, Product, Review, PushSubscription
from ..models.base import utcnow
from ..services import invoice as invoice_svc
from ..services import order_view
from ..services import orders as order_svc
from ..services import reviews as rv_svc
from ..services import tracking as tracking_svc
from .. import ratelimits as limits
from ..services.suspicious import log_suspicious
from . import bp
from ..services.cart import CartOwner
from .cart import _add_one

user_only = roles_required("user")
MAX_ADDRESSES = 10
STEPS = (("placed", "Order received"), ("confirmed", "Confirmed"), ("packed", "Packed"), ("shipped", "Shipped"), ("out_for_delivery", "Out for delivery"), ("delivered", "Delivered"))
STEP_OF = {}


# ---------------------------------------------------------------- orders
@bp.get("/account/orders")
@user_only
def orders():
    q = select(Order).where(Order.user_id == g.user.id).options(selectinload(Order.items)).order_by(Order.created_at.desc(), Order.id.desc())
    page = db.paginate(q, page=page_number(), per_page=10, error_out=False)
    return render_template("shop/orders.html", page=page, labels=order_svc.LABELS, rate_orders=_orders_to_rate(page.items),
                           item_products=order_view.item_products(page.items))


def _orders_to_rate(orders) -> set[int]:
    """Ids of the delivered orders on this page that still have a product without a review (they get the "Rate this order" button)."""
    delivered = [o for o in orders if o.status in rv_svc.REVIEWABLE_ORDER_STATUSES]
    if not delivered:
        return set()
    item_ids = [it.id for o in delivered for it in o.items]
    pids = {it.product_id for o in delivered for it in o.items if it.product_id}
    live = set(db.session.scalars(select(Product.id).where(Product.id.in_(pids or {0}), Product.is_deleted.is_(False))))
    rated = {i for i in db.session.scalars(select(Review.order_item_id).where(Review.user_id == g.user.id, Review.order_item_id.in_(item_ids or [0]), Review.is_deleted.is_(False)))}
    out = set()
    for o in delivered:
        done = {it.product_id for it in o.items if it.id in rated}  # a review on any line counts for that product in this order
        if any(it.product_id in live and it.product_id not in done for it in o.items):
            out.add(o.id)
    return out


def _mine(order_number: str) -> Order:
    order = db.session.scalar(select(Order).where(Order.order_number == order_number, Order.user_id == g.user.id).options(selectinload(Order.items), selectinload(Order.payments)))
    if order is None:
        _log_if_not_theirs(order_number)
        abort(404)
    return order


def _log_if_not_theirs(order_number: str) -> None:
    """Same 404 for "no such order" and "someone else's order" (nothing leaks); the server log keeps the difference."""
    if db.session.scalar(select(Order.id).where(Order.order_number == order_number, Order.user_id != g.user.id)) is not None:
        log_suspicious("other_customers_order", f"order_number={order_number}")


@bp.get("/account/orders/<order_number>")
@user_only
def order_detail(order_number):
    order = _mine(order_number)
    history = db.session.scalars(select(OrderStatusHistory).where(OrderStatusHistory.order_id == order.id).order_by(OrderStatusHistory.created_at, OrderStatusHistory.id)).all()
    when: dict = {"placed": order.created_at}
    for h in history:
        if h.from_status == h.to_status:  # payment notes, not a stage change
            continue
        when.setdefault(STEP_OF.get(h.to_status, h.to_status), h.created_at)
    if "delivered" in when and "shipped" not in when:  # shipped straight to delivered: still show the earlier stages as done
        when["shipped"] = when["delivered"]
    if "delivered" in when and "packed" not in when:
        when["packed"] = when.get("confirmed", when["delivered"])
    if "delivered" in when and "confirmed" not in when:
        when["confirmed"] = when.get("placed", when["delivered"])
    # a return only happens after delivery, so the timeline stays at Delivered for those
    reached = [i for i, (k, _) in enumerate(STEPS) if k in when]
    current = max(reached) if reached else 0
    reviewable = order.status in rv_svc.REVIEWABLE_ORDER_STATUSES
    products = {}
    my_reviews = {}
    review_lines = []  # one line per product (the first one), because a product is reviewed once per order
    if reviewable:
        pids = {it.product_id for it in order.items if it.product_id}
        products = {p.id: p for p in db.session.scalars(select(Product).where(Product.id.in_(pids or {0}), Product.is_deleted.is_(False)))}
        product_of_item = {it.id: it.product_id for it in order.items}
        for r in db.session.scalars(select(Review).where(Review.user_id == g.user.id, Review.order_item_id.in_(list(product_of_item) or [0]), Review.is_deleted.is_(False))):
            my_reviews[product_of_item[r.order_item_id]] = r  # this order's review of each product, not the customer's other orders
        seen = set()
        for it in order.items:
            if it.product_id in products and it.product_id not in seen:
                seen.add(it.product_id)
                review_lines.append(it)
    return render_template("shop/order.html", order=order, steps=STEPS, when=when, current=current, labels=order_svc.LABELS, item_products=order_view.item_products([order]),
                           reviewable=reviewable, review_products=products, review_lines=review_lines, my_reviews=my_reviews, moderation=rv_svc.moderation_on(),
                           can_cancel=order.status in order_svc.CANCELLABLE,
                           shipped=order.status in order_svc.SHIPPED_STATUSES,
                           can_return=False, can_invoice=order.status not in invoice_svc.NOT_INVOICEABLE,
                           return_note=next((h.note for h in reversed(history) if h.to_status == "return_requested"), None), closed_note=next((h.note for h in reversed(history) if h.to_status in ("rejected", "cancelled")), None))


@bp.get("/account/orders/<order_number>/status.json")
@user_only
def order_status_json(order_number):
    """Polled by the tracking page so it updates itself when the shop moves the order along. Only the customer's own order."""
    from flask import jsonify
    order = db.session.scalar(select(Order).where(Order.order_number == order_number, Order.user_id == g.user.id))
    if order is None:
        _log_if_not_theirs(order_number)
    if order is None:
        abort(404)
    closed = order.status in tracking_svc.NO_SHIPMENT
    resp = jsonify(status=order.status, label=order_svc.LABELS.get(order.status, order.status), updated=order.updated_at.isoformat() if order.updated_at else None, courier_name=None if closed else order.courier_name, tracking_id=None if closed else order.tracking_id, tracking_url=None if closed else order.tracking_url, delivery_date=None if closed or not order.delivery_date else order.delivery_date.isoformat(), delivery_slot=None if closed else order.delivery_slot)
    resp.headers["Cache-Control"] = "no-store"
    return resp


@bp.post("/account/orders/<order_number>/cancel")
@user_only
@limiter.limit(limits.limit("cart_change"))
def order_cancel(order_number):
    order = _mine(order_number)
    try:
        order_svc.cancel_by_customer(order.id, g.user)
        db.session.commit()
    except order_svc.OrderError as e:
        db.session.rollback()
        flash(str(e), "error")
    else:
        flash(f"Order {order_number} cancelled." + (" Your online payment will be refunded." if order.payment_status == "paid" else ""), "success")
    return redirect(url_for("shop.order_detail", order_number=order_number))


@bp.post("/account/orders/<order_number>/return")
@user_only
@limiter.limit(limits.limit("cart_change"))
def order_return(order_number):
    order = _mine(order_number)
    # Returns are not offered at the moment, so customers cannot raise one.
    flash("Returns are not available at the moment. Please contact the shop on WhatsApp if there is a problem with your order.", "info")
    return redirect(url_for("shop.order_detail", order_number=order_number))


@bp.get("/account/orders/<order_number>/invoice.pdf")
@user_only
def order_invoice(order_number):
    order = _mine(order_number)
    if order.status in invoice_svc.NOT_INVOICEABLE:
        abort(404)
    resp = make_response(invoice_svc.build_invoice(order))
    resp.mimetype = "application/pdf"
    resp.headers["Content-Disposition"] = f'attachment; filename="invoice-{order.order_number}.pdf"'
    return resp


@bp.post("/account/orders/<order_number>/reorder")
@user_only
@limiter.limit(limits.limit("cart_change"))
def order_reorder(order_number):
    order = _mine(order_number)
    added, skipped = 0, []
    for it in order.items:
        if not it.product_id:
            skipped.append(it.name)
            continue
        msg, ok = _add_one(CartOwner(user_id=g.user.id), it.product_id, it.variant_id, it.quantity)
        added += ok
        if not ok:
            skipped.append(it.name)
    if added:
        flash(f"Added {added} item{'s' if added != 1 else ''} to your cart." + (f" Not available right now: {', '.join(skipped)}." if skipped else ""), "success" if not skipped else "info")
        return redirect(url_for("shop.cart"))
    flash("None of those items are available right now.", "error")
    return redirect(url_for("shop.order_detail", order_number=order_number))


# ---------------------------------------------------------------- addresses
def parse_address(form) -> tuple[dict, dict]:
    from .. import validation as v
    e: dict = {}
    d = {"label": v.text_line(form.get("label"), "label", e, label="The label", max_=v.MAX["label"], required=False) or "Home",
         "full_name": v.person_name(form.get("full_name"), "full_name", e, label="The receiver's name"),
         "phone": v.phone(form.get("phone"), "phone", e),
         "line1": v.text_line(form.get("line1"), "line1", e, label="House number and street", min_=3, max_=v.MAX["line"]),
         "line2": v.text_line(form.get("line2"), "line2", e, label="Address line 2", max_=v.MAX["line"], required=False) or None,
         "city": v.person_name(form.get("city"), "city", e, label="The city", max_=v.MAX["city"]),
         "state": v.person_name(form.get("state"), "state", e, label="The state", max_=v.MAX["state"]),
         "pincode": v.pincode(form.get("pincode"), "pincode", e)}
    # keep the wording the page has always used for the common mistakes
    if "full_name" in e and not d["full_name"]:
        e["full_name"] = "Enter the name of the person receiving the order."
    if "line1" in e and len(d["line1"]) < 3 and "<" not in d["line1"]:
        e["line1"] = "Enter house number and street."
    for key, word in (("city", "city"), ("state", "state")):
        if key in e and not d[key]:
            e[key] = f"Enter the {word}."
    return d, e


def _addr(address_id: int) -> Address:
    a = db.session.get(Address, address_id)
    if a is None or a.user_id != g.user.id:
        abort(404)
    return a


def _after(default: str) -> str:
    from ..auth.service import safe_next
    return safe_next(request.values.get("next"), default)


@bp.get("/account/addresses")
@user_only
def addresses():
    rows = db.session.scalars(select(Address).where(Address.user_id == g.user.id).order_by(Address.is_default.desc(), Address.id.desc())).all()
    return render_template("shop/addresses.html", rows=rows, limit=MAX_ADDRESSES)


@bp.route("/account/addresses/new", methods=["GET", "POST"])
@bp.route("/account/addresses/<int:address_id>/edit", methods=["GET", "POST"])
@user_only
def address_form(address_id=None):
    a = _addr(address_id) if address_id else None
    form, errors = ({k: getattr(a, k) or "" for k in ("label", "full_name", "phone", "line1", "line2", "city", "state", "pincode")} if a else {"full_name": g.user.name, "phone": g.user.phone or "", "label": "Home"}), {}
    if request.method == "POST":
        form, errors = parse_address(request.form)
        count = db.session.scalar(select(func.count(Address.id)).where(Address.user_id == g.user.id)) or 0
        if a is None and count >= MAX_ADDRESSES:
            errors["line1"] = f"You can save up to {MAX_ADDRESSES} addresses. Delete one first."
        if not errors:
            if a is None:
                a = Address(user_id=g.user.id, is_default=count == 0)
                db.session.add(a)
            for k, v in form.items():
                setattr(a, k, v)
            if request.form.get("make_default") and not a.is_default:
                db.session.execute(Address.__table__.update().where(Address.user_id == g.user.id).values(is_default=False))
                a.is_default = True
            db.session.commit()
            flash("Address saved.", "success")
            return redirect(_after(url_for("shop.addresses")))
        return render_template("shop/address_form.html", a=a, form=form, errors=errors, next=request.values.get("next", "")), 422
    return render_template("shop/address_form.html", a=a, form=form, errors=errors, next=request.args.get("next", ""))


@bp.post("/account/addresses/<int:address_id>/default")
@user_only
def address_default(address_id):
    a = _addr(address_id)
    db.session.execute(Address.__table__.update().where(Address.user_id == g.user.id).values(is_default=False))
    a.is_default = True
    db.session.commit()
    flash("Default address updated.", "success")
    return redirect(url_for("shop.addresses"))


@bp.post("/account/addresses/<int:address_id>/delete")
@user_only
def address_delete(address_id):
    a = _addr(address_id)
    was_default = a.is_default
    db.session.delete(a)
    db.session.flush()
    if was_default:
        nxt = db.session.scalar(select(Address).where(Address.user_id == g.user.id).order_by(Address.id.desc()))
        if nxt:
            nxt.is_default = True
    db.session.commit()
    flash("Address deleted.", "success")
    return redirect(url_for("shop.addresses"))


@bp.post("/language")
@user_only
def set_language():
    from flask import session
    lang = request.form.get("language", "en")
    if lang not in ("en", "ta"): abort(400)
    g.user.preferred_language = lang; db.session.commit(); session["language"] = lang
    return redirect(request.referrer or url_for("auth.account"))

@bp.get("/account/referrals")
@user_only
def referrals():
    import secrets, string
    from ..models import PointsLedger
    if not g.user.referral_code:
        alphabet = string.ascii_uppercase + string.digits
        g.user.referral_code = "RR" + "".join(secrets.choice(alphabet) for _ in range(8)); db.session.commit()
    return render_template("account/referrals.html", referral_code=g.user.referral_code)

@bp.get("/account/points")
@user_only
def points_history():
    from ..models import PointsLedger
    entries = db.session.scalars(select(PointsLedger).where(PointsLedger.user_id == g.user.id).order_by(PointsLedger.created_at.desc()).limit(100)).all()
    return render_template("account/points.html", entries=entries, balance=g.user.wallet_points)


@bp.post("/account/push/subscribe")
@user_only
@limiter.limit("10 per hour")
def push_subscribe():
    """Save or replace a browser subscription after an explicit account-page opt-in."""
    from urllib.parse import urlparse
    payload = request.get_json(silent=True) or {}
    subscription = payload.get("subscription") or {}
    endpoint = subscription.get("endpoint")
    keys = subscription.get("keys") or {}
    if not isinstance(endpoint, str) or len(endpoint) > 2000:
        return jsonify(ok=False, message="Invalid subscription endpoint."), 400
    parsed = urlparse(endpoint)
    if parsed.scheme != "https" or not parsed.netloc:
        return jsonify(ok=False, message="Invalid subscription endpoint."), 400
    p256dh, auth = keys.get("p256dh"), keys.get("auth")
    if not isinstance(p256dh, str) or not isinstance(auth, str) or len(p256dh) > 255 or len(auth) > 255:
        return jsonify(ok=False, message="Invalid subscription keys."), 400
    row = db.session.scalar(select(PushSubscription).where(PushSubscription.endpoint == endpoint))
    if row and row.user_id != g.user.id:
        row.user_id = g.user.id
    if row is None:
        row = PushSubscription(user_id=g.user.id, endpoint=endpoint, p256dh=p256dh, auth=auth, is_enabled=True)
        db.session.add(row)
    else:
        row.p256dh, row.auth, row.is_enabled = p256dh, auth, True
    db.session.commit()
    return jsonify(ok=True, message="Notifications enabled.")


@bp.post("/account/push/unsubscribe")
@user_only
@limiter.limit("10 per hour")
def push_unsubscribe():
    payload = request.get_json(silent=True) or {}
    endpoint = payload.get("endpoint")
    if not isinstance(endpoint, str) or len(endpoint) > 2000:
        return jsonify(ok=False), 400
    row = db.session.scalar(select(PushSubscription).where(
        PushSubscription.endpoint == endpoint, PushSubscription.user_id == g.user.id))
    if row:
        row.is_enabled = False
        db.session.commit()
    return jsonify(ok=True, message="Notifications disabled.")
