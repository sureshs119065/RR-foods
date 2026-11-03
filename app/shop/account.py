import re

from flask import abort, flash, g, make_response, redirect, render_template, request, url_for
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from ..admin.helpers import clean, page_number
from ..auth.decorators import roles_required
from ..extensions import db
from ..models import Address, Order, OrderStatusHistory
from ..models.base import utcnow
from ..services import invoice as invoice_svc
from ..services import orders as order_svc
from . import bp
from .cart import _add_one

user_only = roles_required("user")
MAX_ADDRESSES = 10
STEPS = (("placed", "Placed"), ("confirmed", "Confirmed"), ("packed", "Packed"), ("shipped", "Shipped"), ("delivered", "Delivered"))


# ---------------------------------------------------------------- orders
@bp.get("/account/orders")
@user_only
def orders():
    q = select(Order).where(Order.user_id == g.user.id).options(selectinload(Order.items)).order_by(Order.created_at.desc(), Order.id.desc())
    return render_template("shop/orders.html", page=db.paginate(q, page=page_number(), per_page=10, error_out=False), labels=order_svc.LABELS)


def _mine(order_number: str) -> Order:
    order = db.session.scalar(select(Order).where(Order.order_number == order_number, Order.user_id == g.user.id).options(selectinload(Order.items), selectinload(Order.payments)))
    if order is None:
        abort(404)
    return order


@bp.get("/account/orders/<order_number>")
@user_only
def order_detail(order_number):
    order = _mine(order_number)
    history = db.session.scalars(select(OrderStatusHistory).where(OrderStatusHistory.order_id == order.id).order_by(OrderStatusHistory.created_at, OrderStatusHistory.id)).all()
    when = {h.to_status: h.created_at for h in history}
    reached = [i for i, (k, _) in enumerate(STEPS) if k in when]
    current = max(reached) if reached else 0
    return render_template("shop/order.html", order=order, steps=STEPS, when=when, current=current, labels=order_svc.LABELS,
                           can_cancel=order.status in order_svc.CANCELLABLE,
                           can_return=order.status == "delivered" and utcnow() <= order_svc.return_deadline(order), return_deadline=order_svc.return_deadline(order),
                           return_reasons=order_svc.RETURN_REASONS, can_invoice=order.status not in invoice_svc.NOT_INVOICEABLE,
                           return_note=next((h.note for h in reversed(history) if h.to_status == "return_requested"), None), closed_note=next((h.note for h in reversed(history) if h.to_status in ("rejected", "cancelled")), None))


@bp.post("/account/orders/<order_number>/cancel")
@user_only
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
def order_return(order_number):
    order = _mine(order_number)
    try:
        order_svc.request_return(order.id, g.user, request.form.get("reason", ""), request.form.get("note"))
        db.session.commit()
    except order_svc.OrderError as e:
        db.session.rollback()
        flash(str(e), "error")
    else:
        flash("Return requested. The shop will review it and tell you the decision.", "success")
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
def order_reorder(order_number):
    order = _mine(order_number)
    added, skipped = 0, []
    for it in order.items:
        if not it.product_id:
            skipped.append(it.name)
            continue
        msg, ok = _add_one(g.user, it.product_id, it.variant_id, it.quantity)
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
    d = {"label": clean(form.get("label"), 40) or "Home", "full_name": clean(form.get("full_name"), 120), "phone": re.sub(r"\D", "", form.get("phone") or ""),
         "line1": clean(form.get("line1"), 200), "line2": clean(form.get("line2"), 200) or None, "city": clean(form.get("city"), 80),
         "state": clean(form.get("state"), 80), "pincode": re.sub(r"\s", "", form.get("pincode") or "")}
    if len(d["phone"]) == 12 and d["phone"].startswith("91"):
        d["phone"] = d["phone"][2:]
    e = {}
    if len(d["full_name"]) < 2:
        e["full_name"] = "Enter the name of the person receiving the order."
    if not re.fullmatch(r"[6-9]\d{9}", d["phone"]):
        e["phone"] = "Enter a 10 digit mobile number."
    if len(d["line1"]) < 3:
        e["line1"] = "Enter house number and street."
    if len(d["city"]) < 2:
        e["city"] = "Enter the city."
    if len(d["state"]) < 2:
        e["state"] = "Enter the state."
    if not re.fullmatch(r"\d{6}", d["pincode"]):
        e["pincode"] = "Enter a 6 digit pincode."
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
