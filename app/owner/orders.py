from flask import abort, flash, g, make_response, redirect, render_template, request, url_for
from sqlalchemy import func, or_, select
from sqlalchemy.orm import joinedload, selectinload

from ..admin.helpers import page_number
from ..auth.service import safe_next
from ..extensions import db
from ..models import Order, OrderStatusHistory, User
from ..services import invoice as invoice_svc
from ..services import orders as svc
from . import bp

PER_PAGE = 20
# (tab key, label, statuses it shows). The first tab is what the owner needs to act on right now.
TABS = (
    ("new", "New", ("placed",)),
    ("pack", "To pack", ("confirmed",)),
    ("ship", "To ship", ("packed",)),
    ("transit", "On the way", ("shipped",)),
    ("done", "Delivered", ("delivered",)),
    ("returns", "Returns", ("return_requested", "returned", "refunded")),
    ("closed", "Rejected / cancelled", ("rejected", "cancelled")),
    ("all", "All", None),
)


@bp.route("/orders")
def orders():
    tab = request.args.get("tab", "new")
    tabs = {k: statuses for k, _, statuses in TABS}
    if tab not in tabs:
        tab = "new"

    counts = dict(db.session.execute(select(Order.status, func.count(Order.id)).group_by(Order.status)).all())
    tab_counts = {k: (sum(counts.values()) if s is None else sum(counts.get(x, 0) for x in s)) for k, _, s in TABS}

    q = select(Order).join(User, User.id == Order.user_id).options(joinedload(Order.user), selectinload(Order.items))
    if tabs[tab] is not None:
        q = q.where(Order.status.in_(tabs[tab]))
    term = (request.args.get("q") or "").strip().lower()
    if term:
        q = q.where(or_(
            func.lower(Order.order_number).contains(term, autoescape=True),
            func.lower(User.name).contains(term, autoescape=True),
            func.lower(func.coalesce(Order.shipping_address["full_name"].as_string(), "")).contains(term, autoescape=True),
            func.coalesce(Order.shipping_address["phone"].as_string(), "").contains(term.replace(" ", ""), autoescape=True),
        ))
    # oldest first where the owner has to act (so nothing waits), newest first everywhere else
    q = q.order_by(Order.created_at.asc() if tab in ("new", "pack", "ship") else Order.created_at.desc(), Order.id.desc())
    page = db.paginate(q, page=page_number(), per_page=PER_PAGE, error_out=False)
    args = {k: v for k, v in request.args.items() if k != "page" and v}
    return render_template("owner/orders.html", page=page, args=args, tab=tab, tabs=TABS, tab_counts=tab_counts, svc=svc,
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
                                  restock=request.form.get("restock") == "1")
        db.session.commit()
    except svc.OrderError as e:
        db.session.rollback()
        flash(str(e), "error")
        return redirect(back)
    verb = {"confirmed": "confirmed", "packed": "marked as packed", "shipped": "marked as shipped", "delivered": "marked as delivered",
            "rejected": "rejected", "returned": "marked as returned", "refunded": "marked as refunded"}[to]
    if to == "delivered" and request.form.get("from_status") == "return_requested":
        verb = "kept as delivered (return declined)"
    note = " The stock was put back." if to == "rejected" else ""
    flash(f"Order {order.order_number} {verb}. The customer has been notified.{note}", "success")
    return redirect(back)
