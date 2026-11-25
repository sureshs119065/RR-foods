"""Admin operational screens: inventory alerts, orders, FAQs and notifications."""
from flask import abort, flash, g, jsonify, redirect, render_template, request, url_for
from sqlalchemy import func, or_, select
from sqlalchemy.orm import joinedload, selectinload

from ..auth.service import safe_next
from ..extensions import db, limiter
from ..services import tracking as tracking_svc
from ..models import Category, Notification, Order, OrderStatusHistory, Product, User
from ..services import inventory as stock
from ..services.inventory import MAX_QTY, StockError
from ..services.stock_alerts import notify_restocked
from . import bp
from .helpers import page_number

PER_PAGE = 24
STOCK_LEVELS = ("attention", "out", "low", "in", "all")
STOCK_CHIPS = (("attention", "Needs attention"), ("out", "Out"), ("low", "Low"), ("in", "Healthy"), ("all", "All"))


def _stock_reply(ok: bool, message: str, code: int = 200, **extra):
    """JSON for the inline editor, flash + redirect for a plain form post (works without JavaScript)."""
    if request.accept_mimetypes.best == "application/json":
        return jsonify(ok=ok, message=message, **extra), code
    flash(message, "success" if ok else "error")
    return redirect(safe_next(request.form.get("next"), url_for("admin.stock_alerts")))


@bp.get("/stock-alerts")
def stock_alerts():
    level = request.args.get("level", "attention")
    if level not in STOCK_LEVELS:
        level = "attention"
    term = (request.args.get("q") or "").strip().lower()
    product_id = None
    if term.startswith("stock-id-") and term[9:].isdigit():       # links from notifications open one product
        product_id = int(term[9:])
        term = ""
        level = "all"

    # search and category narrow everything, including the chip counts; the status chip then picks a slice of that
    scope = [Product.is_deleted.is_(False)]
    if product_id is not None:
        scope.append(Product.id == product_id)
    if term:
        scope.append(or_(func.lower(Product.name).contains(term, autoescape=True),
                         func.lower(Product.sku).contains(term, autoescape=True),
                         func.lower(func.coalesce(Product.brand, "")).contains(term, autoescape=True)))
    cat = request.args.get("category", "")
    if cat.isdigit():
        scope.append(or_(Product.category_id == int(cat), Product.subcategory_id == int(cat)))

    out, low, ok, total = db.session.execute(select(
        func.count(Product.id).filter(stock.level_clause("out")),
        func.count(Product.id).filter(stock.level_clause("low")),
        func.count(Product.id).filter(stock.level_clause("in")),
        func.count(Product.id)).where(*scope)).one()
    counts = {"attention": out + low, "out": out, "low": low, "in": ok, "all": total}

    q = select(Product).where(*scope).options(joinedload(Product.category))
    clause = stock.level_clause(level)
    if clause is not None:
        q = q.where(clause)
    sort = request.args.get("sort", "stock_asc")
    q = q.order_by(*stock.STOCK_SORTS.get(sort, stock.STOCK_SORTS["stock_asc"]), Product.id)
    page = db.paginate(q, page=page_number(), per_page=PER_PAGE, error_out=False)

    cats = db.session.scalars(select(Category).where(Category.is_deleted.is_(False), Category.parent_id.is_(None))
                              .order_by(Category.sort_order, Category.name)).all()
    keep = {k: v for k, v in (("q", request.args.get("q", "").strip()), ("category", cat), ("sort", sort if sort != "stock_asc" else "")) if v}
    return render_template("admin/stock_alerts.html", page=page, level=level, counts=counts, chips=STOCK_CHIPS, cats=cats,
                           sort=sort, keep=keep, args={**keep, "level": level}, next_url=request.full_path.rstrip("?"))


@bp.post("/stock-alerts/<int:product_id>/update")
def stock_alert_update(product_id):
    raw = (request.form.get("qty") or "").strip()
    try:
        qty = int(raw)
        if str(qty) != raw or qty < 0 or qty > MAX_QTY:
            raise ValueError
    except ValueError:
        return _stock_reply(False, f"Enter a whole number from 0 to {MAX_QTY:,}.", 422)
    product = stock.lock_product(product_id)
    if product is None:
        return _stock_reply(False, "That product no longer exists. Reload the page.", 404)
    old = product.stock_qty
    expected_raw = (request.form.get("expected") or str(old)).strip()
    if not expected_raw.isdigit():
        db.session.rollback()
        return _stock_reply(False, "Reload the page and try the stock update again.", 422)
    try:
        stock.set_quantity(product, qty, "admin stock alert update", g.user.id, expected=int(expected_raw))
        db.session.commit()
    except stock.StaleStock as exc:
        db.session.rollback()
        return _stock_reply(False, str(exc), 409, current=exc.current)
    except StockError as exc:
        db.session.rollback()
        return _stock_reply(False, str(exc), 422)
    notify_restocked()
    state = stock.stock_state(qty, product.low_stock_threshold)
    return _stock_reply(True, f"Stock updated successfully — {product.name}: {old} → {qty}.",
                        qty=qty, state=state, label={"out": "Out", "low": "Low", "ok": "Healthy"}[state])


@bp.get("/orders")
def orders():
    status = request.args.get("status", "")
    term = (request.args.get("q") or "").strip()
    q = select(Order).options(joinedload(Order.user)).where(Order.status != "pending_whatsapp")  # unconfirmed WhatsApp requests are not orders yet
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
    from ..services.notification_view import clean_filter, decorate, notification_page

    filt = clean_filter(request.args.get("f"))
    page, counts = notification_page(g.user.id, filt, page_number())
    return render_template("admin/notifications.html", page=page, items=decorate(page.items), filt=filt, counts=counts)


@bp.get("/notifications/<int:notification_id>/go")
def notification_go(notification_id):
    """Open a notification: marks it read, then goes to its link (same-site links only)."""
    row = db.session.scalar(select(Notification).where(
        Notification.id == notification_id, Notification.user_id == g.user.id, Notification.channel == "in_app"))
    if row is None:
        abort(404)
    if not row.is_read:
        row.is_read = True
        db.session.commit()
    return redirect(safe_next(row.link, url_for("admin.notifications")))


@bp.post("/notifications/<int:notification_id>/read")
def notification_read(notification_id):
    row = db.session.scalar(select(Notification).where(
        Notification.id == notification_id, Notification.user_id == g.user.id, Notification.channel == "in_app"))
    if row is None:
        abort(404)
    row.is_read = True
    db.session.commit()
    flash("Notification marked as read.", "success")
    return redirect(safe_next(request.form.get("next"), url_for("admin.notifications")))


@bp.post("/notifications/read-all")
def notifications_read_all():
    from ..services.notification_view import mark_all_read

    mark_all_read(g.user.id)
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
    return redirect(url_for("admin.order_detail", order_id=order_id))
