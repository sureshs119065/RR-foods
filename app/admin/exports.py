"""Admin downloads: orders, users and the sales report (Excel only).

Every route here sits on the admin blueprint, so the admin-only guard in admin/__init__.py covers it. Orders and users use the SAME
filters as their on-screen lists, so a download holds exactly what the screen shows. Each export is written to the audit log.
"""
from datetime import datetime

from flask import Response, g, request
from sqlalchemy import case, func, select
from sqlalchemy.orm import joinedload, selectinload

from ..extensions import db
from ..models import Order, User
from ..models.orders import DRAFT_STATUS
from ..services import order_report, report_export as rx, report_insights, sales_report
from ..services.analytics import build_sales_analytics
from ..services.orders import REVENUE_STATUSES
from ..services.xlsx_export import DATETIME, INT, MONEY, TEXT, XLSX_MIMETYPE
from . import bp
from .helpers import log, shop_tz
from .operations import order_filters
from .users import user_query


def _stamp() -> str:
    return datetime.now(shop_tz()).strftime("%Y-%m-%d")


def _deliver(report: rx.Report):
    return rx.xlsx_response(report, _stamp())


# ------------------------------------------------------------------ orders
def _orders_report():
    status, term, d_from, d_to, rev, where = order_filters()
    conds = [*where, Order.status == status] if status else where
    total = db.session.scalar(select(func.count(Order.id)).where(*conds)) or 0
    rows = db.session.scalars(select(Order).where(*conds).options(joinedload(Order.user), selectinload(Order.items))
                              .order_by(Order.created_at.desc(), Order.id.desc()).limit(rx.MAX_EXPORT_ROWS)).all()
    bits = [f"dates {rx.day_range_text(d_from, d_to)}", f"status {rx.status_label(status)}" if status else "all statuses"]
    if term:
        bits.append(f"search “{term}”")
    if rev:
        bits.append("sales orders only")
    return order_report.build_orders_report(rows, tz=shop_tz(), include_email=True, filters_text=", ".join(bits),
                                            truncated_from=total if total > len(rows) else None, who=g.user.name), total


@bp.get("/orders/export.<fmt>")
def orders_export(fmt):
    if fmt != "xlsx":
        return Response(status=404)
    report, total = _orders_report()
    log("order.export", "order", None, after={"count": min(total, rx.MAX_EXPORT_ROWS), "format": fmt, "filters": dict(request.args)})
    db.session.commit()
    return _deliver(report)


# ------------------------------------------------------------------ users
ROLE_ORDER = {"user": "Customers", "owner": "Owners", "admin": "Admins"}


def _account_state(u: User, now) -> str:
    if u.is_blocked:
        return "Blocked"
    if u.locked_until and u.locked_until > now:
        return "Locked"
    return "Active"


def _users_report():
    users = db.session.scalars(user_query().limit(rx.MAX_EXPORT_ROWS)).all()
    total = db.session.scalar(select(func.count()).select_from(user_query().order_by(None).subquery())) or 0
    spend = {uid: (n, amount) for uid, n, amount in db.session.execute(
        select(Order.user_id, func.count(Order.id), func.coalesce(func.sum(case((Order.status.in_(REVENUE_STATUSES), Order.total), else_=0)), 0))
        .where(Order.status != DRAFT_STATUS).group_by(Order.user_id)).all()}
    tz, now = shop_tz(), datetime.now(shop_tz())
    headers = ["Name", "Email", "Phone", "Role", "Account Status", "Email Verified", "Orders Placed", "Total Spent (₹)", "Wallet Points",
               "Joined On", "Last Sign-in"]
    kinds = [TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, INT, MONEY, INT, DATETIME, DATETIME]
    rows, by_role, blocked, spent_all, accounts = [], {}, 0, 0, []
    for u in users:
        n, amount = spend.get(u.id, (0, 0))
        state = _account_state(u, now)
        blocked += state == "Blocked"
        by_role[u.role] = by_role.get(u.role, 0) + 1
        spent_all += amount or 0
        accounts.append({"role": u.role, "joined": rx.to_local(u.created_at, tz), "orders": n})
        rows.append([u.name, u.email, u.phone, rx.label(rx.ROLE_LABELS, u.role), state, "Yes" if u.email_verified_at else "No", n, amount,
                     u.wallet_points, rx.to_local(u.created_at, tz), rx.to_local(u.last_login_at, tz)])
    notes = [f"Filters: role {rx.label(rx.ROLE_LABELS, request.args.get('role')) if request.args.get('role') else 'all'}"
             f"{', blocked only' if request.args.get('state') == 'blocked' else ''}"
             f"{', search “' + request.args['q'].strip() + '”' if (request.args.get('q') or '').strip() else ''}",
             f"Generated: {rx.dt_text(now.replace(tzinfo=None))} ({tz.key}) by {g.user.name}",
             "Contains customer contact details. Share only with people who need them."]
    if total > len(rows):
        notes.append(f"Only the newest {rx.MAX_EXPORT_ROWS:,} of {total:,} matching accounts are included.")
    summary = [("Accounts in this report", len(rows), INT)] + [(ROLE_ORDER[r], by_role.get(r, 0), INT) for r in ROLE_ORDER] + [
        ("Blocked accounts", blocked, INT), ("Total spent by listed accounts (₹)", spent_all, MONEY)]
    return rx.Report(title="RR FOODS — Users report", filename="rr-foods-users", sheet_name="Users", headers=headers, kinds=kinds, rows=rows,
                     notes=notes, summary=summary, insights=report_insights.users_insights(accounts, now.date())), len(rows)


@bp.get("/users/export.<fmt>")
def users_export(fmt):
    if fmt != "xlsx":
        return Response(status=404)
    report, count = _users_report()
    log("user.export", "user", None, after={"count": count, "format": fmt, "filters": dict(request.args)})
    db.session.commit()
    return _deliver(report)


# ------------------------------------------------------------------ sales report (same files the owner gets)
def _sales_data():
    return build_sales_analytics(request.args.get("range"), request.args.get("start_date"), request.args.get("end_date"), shop_tz())


@bp.get("/analytics.xlsx")
def analytics_xlsx():
    return Response(sales_report.build_xlsx(_sales_data()), mimetype=XLSX_MIMETYPE, headers={
        "Content-Disposition": "attachment; filename=rr-foods-sales-report.xlsx", "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})
