"""Admin operational screens: inventory alerts, orders, FAQs and notifications."""
from flask import abort, flash, g, redirect, render_template, request, url_for
from sqlalchemy import func, or_, select
from sqlalchemy.orm import joinedload, selectinload

from ..extensions import db
from ..models import Notification, Order, OrderStatusHistory, Product, User
from ..services import inventory as stock
from ..services.inventory import MAX_QTY, StockError
from ..services.stock_alerts import notify_restocked
from . import bp
from .helpers import page_number

PER_PAGE = 24


@bp.get("/stock-alerts")
def stock_alerts():
    level = request.args.get("level", "attention")
    term = (request.args.get("q") or "").strip().lower()
    q = select(Product).where(Product.is_deleted.is_(False))
    if level == "out":
        q = q.where(Product.stock_qty == 0)
    elif level == "low":
        q = q.where(Product.stock_qty > 0, Product.stock_qty <= Product.low_stock_threshold)
    else:
        q = q.where(Product.stock_qty <= Product.low_stock_threshold)
    if term:
        q = q.where(or_(func.lower(Product.name).contains(term, autoescape=True),
                        func.lower(Product.sku).contains(term, autoescape=True)))
    page = db.paginate(q.order_by(Product.stock_qty.asc(), Product.name.asc()), page=page_number(), per_page=PER_PAGE, error_out=False)
    return render_template("admin/stock_alerts.html", page=page, level=level)


@bp.post("/stock-alerts/<int:product_id>/update")
def stock_alert_update(product_id):
    raw = (request.form.get("qty") or "").strip()
    try:
        qty = int(raw)
        if str(qty) != raw or qty < 0 or qty > MAX_QTY:
            raise ValueError
    except ValueError:
        flash(f"Enter a whole number from 0 to {MAX_QTY:,}.", "error")
        return redirect(url_for("admin.stock_alerts"))
    product = stock.lock_product(product_id)
    if product is None:
        abort(404)
    old = product.stock_qty
    expected_raw = (request.form.get("expected") or str(old)).strip()
    if not expected_raw.isdigit():
        flash("Reload the page and try the stock update again.", "error")
        return redirect(url_for("admin.stock_alerts"))
    try:
        stock.set_quantity(product, qty, "admin stock alert update", g.user.id, expected=int(expected_raw))
        db.session.commit()
    except stock.StaleStock as exc:
        db.session.rollback()
        flash(str(exc), "error")
        return redirect(url_for("admin.stock_alerts"))
    except StockError as exc:
        db.session.rollback()
        flash(str(exc), "error")
        return redirect(url_for("admin.stock_alerts"))
    notify_restocked()
    flash(f"Stock updated successfully — {product.name}: {old} → {qty}.", "success")
    return redirect(url_for("admin.stock_alerts", level=request.form.get("level", "attention")))


@bp.get("/orders")
def orders():
    status = request.args.get("status", "")
    term = (request.args.get("q") or "").strip()
    q = select(Order).options(joinedload(Order.user))
    if status:
        q = q.where(Order.status == status)
    if term:
        q = q.where(or_(Order.order_number.ilike(f"%{term}%"), Order.user_id.in_(
            select(User.id).where(or_(User.name.ilike(f"%{term}%"), User.phone.ilike(f"%{term}%")))
        )))
    page = db.paginate(q.order_by(Order.created_at.desc(), Order.id.desc()), page=page_number(), per_page=PER_PAGE, error_out=False)
    return render_template("admin/orders.html", page=page, status=status, q=term)


@bp.get("/orders/<int:order_id>")
def order_detail(order_id):
    order = db.session.scalar(select(Order).where(Order.id == order_id).options(
        joinedload(Order.user), selectinload(Order.items), selectinload(Order.payments)))
    if order is None:
        abort(404)
    history = db.session.execute(select(OrderStatusHistory, User.name).outerjoin(
        User, User.id == OrderStatusHistory.changed_by).where(
        OrderStatusHistory.order_id == order.id).order_by(OrderStatusHistory.created_at, OrderStatusHistory.id)).all()
    return render_template("admin/order_detail.html", order=order, history=history)


@bp.get("/notifications")
def notifications():
    unread = db.session.scalar(select(func.count(Notification.id)).where(
        Notification.user_id == g.user.id, Notification.channel == "in_app", Notification.is_read.is_(False))) or 0
    rows = db.session.scalars(select(Notification).where(
        Notification.user_id == g.user.id, Notification.channel == "in_app").order_by(
        Notification.created_at.desc(), Notification.id.desc()).limit(100)).all()
    return render_template("admin/notifications.html", rows=rows, unread=unread)


@bp.post("/notifications/<int:notification_id>/read")
def notification_read(notification_id):
    row = db.session.scalar(select(Notification).where(
        Notification.id == notification_id, Notification.user_id == g.user.id, Notification.channel == "in_app"))
    if row is None:
        abort(404)
    row.is_read = True
    db.session.commit()
    flash("Notification marked as read.", "success")
    return redirect(url_for("admin.notifications"))


@bp.post("/notifications/read-all")
def notifications_read_all():
    db.session.query(Notification).filter_by(user_id=g.user.id, channel="in_app", is_read=False).update(
        {"is_read": True}, synchronize_session=False)
    db.session.commit()
    flash("All notifications marked as read.", "success")
    return redirect(url_for("admin.notifications"))


@bp.get("/help")
def help_center():
    import json
    from pathlib import Path
    source = Path(__file__).resolve().parents[1] / "data" / "admin_faqs.json"
    with source.open(encoding="utf-8") as handle:
        faqs = json.load(handle)
    return render_template("admin/help.html", faqs=faqs)
