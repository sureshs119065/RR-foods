from flask import abort, flash, g, make_response, redirect, render_template, request, url_for
from sqlalchemy import func, or_, select
from sqlalchemy.orm import joinedload, selectinload

from ..admin.helpers import page_number
from ..auth.service import safe_next
from ..extensions import db, limiter
from ..models import Order, OrderStatusHistory, User
from ..services import invoice as invoice_svc
from ..services import orders as svc
from ..services import tracking as tracking_svc
from . import bp

PER_PAGE = 20


@bp.route("/orders")
def orders():
    # One consolidated queue: newest orders first, with search and payment filtering.
    q = select(Order).join(User, User.id == Order.user_id).options(joinedload(Order.user), selectinload(Order.items))
    unpaid = request.args.get("pay") == "pending"
    if unpaid:
        q = q.where(Order.payment_status == "pending", Order.status.notin_(svc.NO_PAYMENT_CHANGE))
    term = (request.args.get("q") or "").strip().lower()
    if term:
        q = q.where(or_(
            func.lower(Order.order_number).contains(term, autoescape=True),
            func.lower(User.name).contains(term, autoescape=True),
            func.lower(func.coalesce(Order.shipping_address["full_name"].as_string(), "")).contains(term, autoescape=True),
            func.coalesce(Order.shipping_address["phone"].as_string(), "").contains(term.replace(" ", ""), autoescape=True),
        ))
    q = q.order_by(Order.created_at.desc(), Order.id.desc())
    page = db.paginate(q, page=page_number(), per_page=PER_PAGE, error_out=False)
    args = {k: v for k, v in request.args.items() if k != "page" and v}
    return render_template("owner/orders.html", page=page, args=args, svc=svc, unpaid=unpaid,
                           next_url=request.full_path.rstrip("?"))


@bp.route("/orders/<int:order_id>")
def order_detail(order_id):
    order = db.session.scalar(select(Order).where(Order.id == order_id).options(
        joinedload(Order.user), selectinload(Order.items), selectinload(Order.payments)))
    if order is None:
        abort(404)
    history = db.session.execute(
        select(OrderStatusHistory, User.name).outerjoin(User, User.id == OrderStatusHistory.changed_by)
        .where(OrderStatusHistory.order_id == order.id).order_by(OrderStatusHistory.created_at, OrderStatusHistory.id)).all()
    return render_template("owner/order_detail.html", order=order, history=history, svc=svc)


@bp.get("/orders/<int:order_id>/invoice.pdf")
def order_invoice(order_id):
    order = db.session.scalar(select(Order).where(Order.id == order_id).options(selectinload(Order.items)))
    if order is None or order.status in invoice_svc.NOT_INVOICEABLE:
        abort(404)
    resp = make_response(invoice_svc.build_invoice(order))
    resp.mimetype = "application/pdf"
    resp.headers["Content-Disposition"] = f'attachment; filename="invoice-{order.order_number}.pdf"'
    return resp


@bp.post("/orders/<int:order_id>/status")
def order_status(order_id):
    to = request.form.get("to", "")
    back = safe_next(request.form.get("next"), url_for("owner.order_detail", order_id=order_id))
    try:
        order = svc.change_status(order_id, to, g.user, reason=request.form.get("reason"), expected_from=request.form.get("from_status") or None,
                                  restock=request.form.get("restock") == "1", mark_paid=request.form.get("paid") == "1")
        db.session.commit()
    except svc.OrderError as e:
        db.session.rollback()
        flash(str(e), "error")
        return redirect(back)
    verb = {"confirmed": "confirmed", "packed": "marked as packed", "shipped": "marked as shipped", "out_for_delivery": "marked as out for delivery", "delivered": "marked as delivered",
            "rejected": "rejected", "returned": "marked as returned", "refunded": "marked as refunded"}[to]
    if to == "delivered" and request.form.get("from_status") == "return_requested":
        verb = "kept as delivered (return declined)"
    note = " The stock was put back." if to == "rejected" else ""
    if to == "confirmed" and order.payment_status == "paid":
        note = " Payment is marked as received."
    flash(f"Order {order.order_number} {verb}. The customer has been notified.{note}", "success")
    return redirect(back)


@bp.post("/orders/<int:order_id>/payment")
def order_payment(order_id):
    """Paid / Not paid toggle. The money itself is received on WhatsApp; this only records it."""
    paid = request.form.get("paid") == "1"
    back = safe_next(request.form.get("next"), url_for("owner.order_detail", order_id=order_id))
    try:
        order, changed = svc.set_payment(order_id, paid, g.user)
        db.session.commit()
    except svc.OrderError as e:
        db.session.rollback()
        flash(str(e), "error")
        return redirect(back)
    if changed:
        flash(f"Order {order.order_number} marked as {'paid. The customer has been told.' if paid else 'not paid.'}", "success")
    else:
        flash(f"Order {order.order_number} was already marked as {'paid' if paid else 'not paid'}.", "info")
    return redirect(back)


@bp.post("/orders/<int:order_id>/tracking")
@limiter.limit("20 per minute")
def order_tracking(order_id):
    order = db.session.get(Order, order_id)
    if order is None:
        abort(404)
    try:
        tracking_svc.update_tracking(order, request.form.get("courier_name"), request.form.get("tracking_id"), request.form.get("tracking_url"), g.user)
        db.session.commit()
    except ValueError as exc:
        db.session.rollback()
        flash(str(exc), "error")
    else:
        flash("Courier tracking details saved.", "success")
    return redirect(url_for("owner.order_detail", order_id=order_id))


@bp.get("/orders/<int:order_id>/packing-slip")
def packing_slip(order_id):
    order = db.session.scalar(select(Order).where(Order.id == order_id).options(selectinload(Order.items)))
    if order is None:
        abort(404)
    return render_template("owner/packing_slip.html", order=order)


@bp.post("/orders/<int:order_id>/whatsapp-update")
@limiter.limit("30 per hour")
def whatsapp_update(order_id):
    """Open a localized wa.me status message; record that the owner initiated the update."""
    from urllib.parse import quote
    from ..models import SiteSetting, AuditLog
    order = db.session.get(Order, order_id)
    if order is None: abort(404)
    stage = (request.form.get("stage") or "").strip()
    if stage not in ("confirmed", "packed", "shipped", "delivered"): abort(400)
    phone = str((order.shipping_address or {}).get("phone") or order.user.phone or "")
    digits = "".join(ch for ch in phone if ch.isdigit())
    if len(digits) == 10: digits = "91" + digits
    if len(digits) < 10: flash("Customer phone number is missing.", "error"); return redirect(url_for("owner.order_detail", order_id=order_id))
    lang = getattr(order.user, "preferred_language", "en") or "en"
    defaults = {"confirmed": {"en":"Your RR Foods order {order} is confirmed.","ta":"உங்கள் RR Foods ஆர்டர் {order} உறுதிப்படுத்தப்பட்டது."}, "packed":{"en":"Your RR Foods order {order} is packed.","ta":"உங்கள் RR Foods ஆர்டர் {order} பேக் செய்யப்பட்டது."}, "shipped":{"en":"Your RR Foods order {order} has been shipped. Courier: {courier}. Track: {tracking}","ta":"உங்கள் RR Foods ஆர்டர் {order} அனுப்பப்பட்டது. கூரியர்: {courier}. கண்காணிப்பு: {tracking}"}, "delivered":{"en":"Your RR Foods order {order} has been delivered. Thank you!","ta":"உங்கள் RR Foods ஆர்டர் {order} டெலிவரி செய்யப்பட்டது. நன்றி!"}}
    setting = db.session.get(SiteSetting, "whatsapp_status_templates")
    custom = (setting.value if setting and isinstance(setting.value, dict) else {}).get(stage, {})
    template = custom.get(lang) or custom.get("en") or defaults[stage].get(lang) or defaults[stage]["en"]
    message = template.replace("{order}", order.order_number).replace("{courier}", order.courier_name or "").replace("{tracking}", order.tracking_url or order.tracking_id or "")
    db.session.add(OrderStatusHistory(order_id=order.id, from_status=order.status, to_status=order.status, changed_by=g.user.id, note=f"WhatsApp {stage} update opened by owner"))
    db.session.add(AuditLog(actor_id=g.user.id, action="order.whatsapp_update_opened", entity_type="order", entity_id=str(order.id), after={"stage": stage, "language": lang}))
    db.session.commit()
    return redirect(f"https://wa.me/{digits}?text={quote(message)}")

@bp.route("/settings/whatsapp-templates", methods=["GET", "POST"])
@limiter.limit("20 per hour")
def whatsapp_templates():
    from ..models import SiteSetting
    if request.method == "POST":
        payload = {}
        for stage in ("confirmed", "packed", "shipped", "delivered"):
            payload[stage] = {lang: (request.form.get(f"{stage}_{lang}") or "")[:1000] for lang in ("en", "ta")}
        setting = db.session.get(SiteSetting, "whatsapp_status_templates")
        if setting is None: setting = SiteSetting(key="whatsapp_status_templates", value=payload); db.session.add(setting)
        else: setting.value = payload
        from ..models import AuditLog
        db.session.add(AuditLog(actor_id=g.user.id, action="whatsapp.templates.update", entity_type="settings", entity_id="whatsapp"))
        db.session.commit(); flash("WhatsApp templates saved.", "success"); return redirect(url_for("owner.whatsapp_templates"))
    setting = db.session.get(SiteSetting, "whatsapp_status_templates")
    return render_template("owner/whatsapp_templates.html", templates=(setting.value if setting and isinstance(setting.value, dict) else {}))
