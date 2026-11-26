"""Admin operational screens: inventory alerts, orders, FAQs and notifications."""
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

from flask import abort, flash, g, jsonify, redirect, render_template, request, url_for
from sqlalchemy import func, or_, select
from sqlalchemy.orm import joinedload, selectinload

from ..auth.service import safe_next
from ..extensions import db, limiter
from ..services import order_view
from ..services import tracking as tracking_svc
from ..models import Category, Notification, Order, OrderStatusHistory, Product, User
from ..services import inventory as stock
from ..services.inventory import MAX_QTY, StockError
from ..services.stock_alerts import notify_restocked
from . import bp
from ..services.orders import REVENUE_STATUSES
from .helpers import page_number, shop_tz

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


ORDER_STATUSES = ("placed", "confirmed", "packed", "shipped", "out_for_delivery", "delivered", "rejected", "cancelled",
                  "return_requested", "returned", "refunded")


def _iso_day(raw):
    try:
        return date.fromisoformat((raw or "").strip())
    except ValueError:
        return None


def _local_midnight_utc(day: date) -> datetime:
    return datetime.combine(day, time.min, tzinfo=shop_tz()).astimezone(timezone.utc)


def order_filters():
    """The orders list's search, date range, status chip and revenue tile, as (status, term, d_from, d_to, rev, where).
    Shared by the list and the Excel export, so a download always holds exactly the rows the screen is showing."""
    status = request.args.get("status", "")
    status = status if status in ORDER_STATUSES else ""
    term = (request.args.get("q") or "").strip()
    d_from, d_to = _iso_day(request.args.get("date_from")), _iso_day(request.args.get("date_to"))
    if d_from and d_to and d_to < d_from:
        d_from, d_to = d_to, d_from
    rev = request.args.get("rev") == "1"  # set by the "Revenue today" tile: only orders that count as sales

    base = [Order.status != "pending_whatsapp"]  # unconfirmed WhatsApp requests are not orders yet
    if term:
        base.append(or_(Order.order_number.ilike(f"%{term}%"),
                        Order.shipping_address["full_name"].as_string().ilike(f"%{term}%"),
                        Order.shipping_address["phone"].as_string().ilike(f"%{term}%"),
                        Order.user_id.in_(select(User.id).where(or_(User.name.ilike(f"%{term}%"), User.phone.ilike(f"%{term}%"))))))
    if d_from:
        base.append(Order.created_at >= _local_midnight_utc(d_from))
    if d_to:
        base.append(Order.created_at < _local_midnight_utc(d_to + timedelta(days=1)))
    if rev:
        base.append(Order.status.in_(REVENUE_STATUSES))
    return status, term, d_from, d_to, rev, base


@bp.get("/orders")
def orders():
    """Orders list. Search, date range and status chips all narrow the same query, and every link and the pager carry them along."""
    status, term, d_from, d_to, rev, base = order_filters()

    # chip counts follow search + dates (not the status itself), so each chip says what clicking it would show
    counts = dict(db.session.execute(select(Order.status, func.count()).where(*base).group_by(Order.status)).all())
    counts_all = sum(counts.values())

    conds = [*base, Order.status == status] if status else base
    q = select(Order).options(joinedload(Order.user)).where(*conds)
    page = db.paginate(q.order_by(Order.created_at.desc(), Order.id.desc()), page=page_number(), per_page=PER_PAGE, error_out=False)

    # summary strip (always today / right now, whatever the filters are)
    today = datetime.now(shop_tz()).date()
    t0, t1 = _local_midnight_utc(today), _local_midnight_utc(today + timedelta(days=1))
    live = Order.status != "pending_whatsapp"
    today_rows = db.session.execute(select(Order.status, func.count(), func.coalesce(func.sum(Order.total), 0))
                                    .where(live, Order.created_at >= t0, Order.created_at < t1).group_by(Order.status)).all()
    open_counts = dict(db.session.execute(select(Order.status, func.count()).where(Order.status.in_(("placed", "confirmed"))).group_by(Order.status)).all())
    today_s = today.isoformat()
    plain = not (term or rev)
    summary = [
        {"key": "today", "label": "Today's orders", "value": str(sum(n for _, n, _ in today_rows)),
         "url": url_for("admin.orders", date_from=today_s, date_to=today_s),
         "on": plain and not status and d_from == today and d_to == today},
        {"key": "pending", "label": "Pending confirmation", "value": str(open_counts.get("placed", 0)),
         "url": url_for("admin.orders", status="placed"), "on": plain and status == "placed" and not (d_from or d_to)},
        {"key": "pack", "label": "To pack", "value": str(open_counts.get("confirmed", 0)),
         "url": url_for("admin.orders", status="confirmed"), "on": plain and status == "confirmed" and not (d_from or d_to)},
        {"key": "revenue", "label": "Revenue today", "value": "₹{:,.2f}".format(sum((Decimal(str(t)) for st, _, t in today_rows if st in REVENUE_STATUSES), Decimal("0"))),
         "url": url_for("admin.orders", date_from=today_s, date_to=today_s, rev=1),
         "on": rev and not term and not status and d_from == today and d_to == today},
    ]
    args = {"q": term or None, "date_from": d_from.isoformat() if d_from else None, "date_to": d_to.isoformat() if d_to else None, "rev": "1" if rev else None}
    return render_template("admin/orders.html", page=page, status=status, q=term, prods=order_view.item_products(page.items),
                           summary=summary, pager_args={**args, "status": status or None}, args_norev={**args, "rev": None}, counts=counts, counts_all=counts_all, order_statuses=ORDER_STATUSES, args=args,
                           d_from=args["date_from"] or "", d_to=args["date_to"] or "", rev=rev,
                           filtered=bool(status or term or d_from or d_to or rev))


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
