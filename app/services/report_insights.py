"""The "Insights" sheet of every Excel report: native charts plus short, rule-based suggestions.

One shared module, so the Admin and the Owner get the same workbook with the same wording. The rules are plain thresholds applied to
numbers that are really in the file (or read from the database for the same period). Nothing is estimated, nothing is invented: when
there is too little data a box says "Not enough data yet for suggestions." and when the data is fine but no rule fires it says so.

Every `*_suggestions` function returns a list of (title, text). The `*_insights` functions return an `InsightsSheet` (drawn by
xlsx_export, which also runs every text through the formula guard).
"""
from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import func, select

from ..extensions import db
from ..models import Order, OrderItem, Product
from . import report_export as rx
from .inventory import stock_state
from .orders import REVENUE_STATUSES
from .storefront import LIVE
from .xlsx_export import INT, MONEY, PERCENT, TEXT, ChartBlock, InsightsSheet

NOT_ENOUGH = "Not enough data yet for suggestions."
ALL_CLEAR = ("All clear", "The automatic checks found nothing to flag in this data. Check again as new orders come in.")

# Thresholds (percent unless noted). Ratios are only judged once there are at least MIN_ORDERS orders / MIN_CUSTOMERS customers behind them.
MIN_ORDERS = 5
MIN_CUSTOMERS = 5
TOP_SHARE_PCT = 30          # one product above this share of product sales = too dependent on it
DROP_PCT = 10               # revenue down by at least this much versus the comparison period
MIN_PREVIOUS_ORDERS = 3     # the comparison period needs a few orders, otherwise a "drop" is just noise
CANCEL_PCT = 15             # cancelled + rejected share of all orders
REPEAT_PCT = 20             # repeat customer rate below this
PINCODE_SHARE_PCT = 50      # one pincode above this share of orders
SIGNUP_DROP_PCT = 25
MIN_SIGNUPS = 5
SALES_WINDOW_DAYS = 30      # "selling fast" / "no sales" on the stock reports look at the last 30 days
MAX_NAMES = 3

STATUS_COLORS = {
    "delivered": "183D2B", "out_for_delivery": "2E5E3C", "shipped": "47764F", "packed": "78A982", "confirmed": "9CC4A8",
    "placed": "C9A227", "pending_whatsapp": "E0CD8A", "cancelled": "B5483A", "rejected": "8E2F25",
    "return_requested": "D98F4E", "returned": "C06A3B", "refunded": "9A6B4F",
}
CLOSED = ("cancelled", "rejected")
STOCK_CHIPS = {"out": ("Out of stock", "F8D7DA", "7A1F2B"), "low": ("Low stock", "FFF1C2", "7A5A00"), "ok": ("Healthy", "DCEBDF", "183D2B")}
STOCK_COLORS = {"out": "B5483A", "low": "C9A227", "ok": "47764F"}


# ------------------------------------------------------------------ small helpers
def _shop_tz() -> ZoneInfo:
    from flask import current_app
    return ZoneInfo(current_app.config["SHOP_TIMEZONE"])


def _name(value, limit: int = 60) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _names(items) -> str:
    items = [_name(i) for i in items]
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def _pct(part, whole) -> float:
    return float(part) / float(whole) * 100 if whole else 0.0


def _finish(found: list[tuple[str, str]], enough: bool) -> list[tuple[str, str]]:
    """The suggestions for one box: what fired, else "not enough data", else "all clear"."""
    if found:
        return found
    return [("No suggestions yet", NOT_ENOUGH)] if not enough else [ALL_CLEAR]


def _local_window(start: date, end: date, tz):
    """[start, end] as UTC datetimes (end is inclusive), the same way the sales dashboard does it."""
    lo = datetime.combine(start, datetime.min.time(), tzinfo=tz).astimezone(timezone.utc)
    hi = datetime.combine(end + timedelta(days=1), datetime.min.time(), tzinfo=tz).astimezone(timezone.utc)
    return lo, hi


# ------------------------------------------------------------------ rules (pure functions of numbers)
def rule_top_product_share(name, share_pct, orders):
    if name and orders >= MIN_ORDERS and share_pct > TOP_SHARE_PCT:
        return [("One product carries your sales",
                 f"{_name(name)} brings in {share_pct:.0f}% of product sales. Stock up on {_name(name)} and promote the next best sellers "
                 "to reduce dependence on one product.")]
    return []


def rule_fast_but_low(items):
    """items: (name, state) for top sellers; only 'out' and 'low' fire."""
    out = []
    for name, state in items:
        if state in ("out", "low"):
            how = "out of stock" if state == "out" else "almost out of stock"
            out.append((f"Restock {_name(name, 40)}", f"{_name(name)} is selling fast but is {how}. Restock now."))
    return out[:MAX_NAMES]


def rule_no_sales(names, total, when="in this period"):
    if not names:
        return []
    more = f" ({total - len(names)} more had no sales too)" if total > len(names) else ""
    return [("Slow products", f"{_names(names)} had no sales {when}{more}. Consider a discount or a combo for {_names(names)}.")]


def rule_revenue_drop(now_amount, before_amount, before_orders, what="the previous period"):
    if before_orders >= MIN_PREVIOUS_ORDERS and before_amount > 0 and now_amount < before_amount:
        drop = (before_amount - now_amount) / before_amount * 100
        if drop >= DROP_PCT:
            return [("Revenue is down",
                     f"Revenue is down {drop:.0f}% versus {what} ({rx.inr(now_amount)} now, {rx.inr(before_amount)} before). "
                     "Try a coupon or a homepage banner to bring customers back.")]
    return []


def rule_cancelled(closed, total):
    if total >= MIN_ORDERS and _pct(closed, total) >= CANCEL_PCT:
        return [("Many cancelled or rejected orders",
                 f"{closed} of {total} orders ({_pct(closed, total):.0f}%) were cancelled or rejected. Review delivery pincodes and stock accuracy.")]
    return []


def rule_repeat_rate(rate_pct, customers):
    if customers >= MIN_CUSTOMERS and rate_pct < REPEAT_PCT:
        return [("Few repeat customers",
                 f"Only {rate_pct:.0f}% of customers ordered more than once. Offer a coupon on the second order to bring them back.")]
    return []


def rule_pincode(counter: Counter, orders):
    known = Counter({k: v for k, v in counter.items() if k and k != "Unknown"})
    if not known or orders < MIN_ORDERS:
        return []
    pin, n = known.most_common(1)[0]
    if _pct(n, orders) >= PINCODE_SHARE_PCT:
        return [("One pincode dominates", f"Pincode {pin} accounts for {_pct(n, orders):.0f}% of orders. Plan delivery slots for this pincode.")]
    return []


# ------------------------------------------------------------------ database lookups (read only)
def revenue_between(start: date, end: date, tz) -> tuple[Decimal, int]:
    """Revenue and accepted-order count in [start, end], with the same definition as the sales dashboard."""
    lo, hi = _local_window(start, end, tz)
    amount, count = db.session.execute(select(func.coalesce(func.sum(Order.total), 0), func.count(Order.id))
                                       .where(Order.status.in_(REVENUE_STATUSES), Order.created_at >= lo, Order.created_at < hi)).one()
    return Decimal(str(amount or 0)), int(count or 0)


def unsold_products(start: date, end: date, tz, limit: int = MAX_NAMES) -> tuple[list[str], int]:
    """Live products that still have stock but sold nothing in the period: (the biggest piles of stock first, how many in all)."""
    lo, hi = _local_window(start, end, tz)
    sold = (select(OrderItem.product_id).join(Order, Order.id == OrderItem.order_id)
            .where(Order.status.in_(REVENUE_STATUSES), Order.created_at >= lo, Order.created_at < hi, OrderItem.product_id.is_not(None)))
    where = (LIVE, Product.stock_qty > 0, Product.id.not_in(sold))
    total = db.session.scalar(select(func.count(Product.id)).where(*where)) or 0
    names = db.session.scalars(select(Product.name).where(*where).order_by(Product.stock_qty.desc(), Product.name).limit(limit)).all()
    return list(names), int(total)


def units_sold_by_product(days: int = SALES_WINDOW_DAYS) -> dict[int, int]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    rows = db.session.execute(select(OrderItem.product_id, func.sum(OrderItem.quantity)).join(Order, Order.id == OrderItem.order_id)
                              .where(Order.status.in_(REVENUE_STATUSES), Order.created_at >= cutoff, OrderItem.product_id.is_not(None))
                              .group_by(OrderItem.product_id)).all()
    return {int(pid): int(units or 0) for pid, units in rows}


# ------------------------------------------------------------------ sales report
def _month_starts(start: date, count: int) -> list[date]:
    out, y, m = [], start.year, start.month
    for _ in range(count):
        out.append(date(y, m, 1))
        y, m = y + (m == 12), 1 if m == 12 else m + 1
    return out


def _periods(data, today: date):
    """(rows, x title, chart title) for revenue by period, without the periods that have not started yet."""
    start = date.fromisoformat(data["start_date"])
    monthly = data["monthly_sales"]
    if len(monthly) > 1:
        starts, items, word = _month_starts(start, len(monthly)), monthly, "Month"
        keep = [i for i, s in enumerate(starts) if s <= today]
    else:
        items, word = data["daily_sales"], "Week" if data["daily_granularity"] == "weekly" else "Day"
        step = 7 if word == "Week" else 1
        keep = [i for i in range(len(items)) if start + timedelta(days=i * step) <= today]
    rows = [[rx.clean_text(items[i]["label"]), items[i]["value"], items[i]["orders"]] for i in keep]
    return rows, word, f"Revenue by {word.lower()}"


def sales_insights(data, tz=None) -> InsightsSheet:
    """Revenue by period, top products and order status, plus customer / delivery suggestions, for the sales report."""
    tz = tz or _shop_tz()
    today = datetime.now(tz).date()
    start, end = date.fromisoformat(data["start_date"]), date.fromisoformat(data["end_date"])
    accepted = int(data["accepted_orders"])
    revenue = float(data["total_sales"])

    # 1. revenue by period, compared with the window of the same length just before it (only the days that have happened)
    rows, word, title = _periods(data, today)
    drop = []
    days = (min(end, today) - start).days + 1
    if days >= 1 and revenue > 0:
        before, before_orders = revenue_between(start - timedelta(days=days), start - timedelta(days=1), tz)
        drop = rule_revenue_drop(Decimal(str(revenue)), before, before_orders, f"the previous {days} day{'s' if days != 1 else ''}")
    revenue_block = ChartBlock(title, "bar", [word, "Revenue (₹)", "Orders"], [TEXT, MONEY, INT], rows, [1], word, "Revenue (₹)",
                               suggestions=_finish(drop, accepted >= MIN_ORDERS))

    # 2. top products: concentration, best sellers that are nearly out of stock, products with no sales
    item_total = sum(c["value"] for c in data["categories"])
    top = data["top_products"]
    rows = [[rx.clean_text(p["label"]), p["value"], _pct(p["value"], item_total)] for p in top]
    found = rule_top_product_share(top[0]["label"] if top else None, _pct(top[0]["value"], item_total) if top else 0, accepted)
    watch = []
    for p in top[:5]:
        product = db.session.get(Product, p["product_id"]) if p.get("product_id") else None
        if product is not None:
            watch.append((p["label"], stock_state(product.stock_qty, product.low_stock_threshold)))
    found += rule_fast_but_low(watch)
    if accepted >= MIN_ORDERS:
        found += rule_no_sales(*unsold_products(start, end, tz))
    products_block = ChartBlock("Top products by sales", "hbar", ["Product", "Sales (₹)", "Share of sales (%)"], [TEXT, MONEY, PERCENT],
                                rows, [1], "Product", "Sales (₹)", suggestions=_finish(found, accepted >= MIN_ORDERS))

    # 3. order status
    status = data["status_breakdown"]
    total_orders = sum(s["value"] for s in status)
    closed = sum(s["value"] for s in status if s["key"] in CLOSED)
    status_block = ChartBlock("Orders by status", "doughnut", ["Status", "Orders"], [TEXT, INT],
                              [[s["label"], s["value"]] for s in status], [1], colors=[STATUS_COLORS.get(s["key"], "B7C4BB") for s in status],
                              suggestions=_finish(rule_cancelled(closed, total_orders), total_orders >= MIN_ORDERS))

    # 4. customers and delivery (no chart of its own)
    pins = Counter({p["label"]: p.get("orders", 0) for p in data["orders_by_pincode"]})
    more = rule_repeat_rate(float(data["repeat_customer_rate"]), int(data["unique_customers"])) + rule_pincode(pins, accepted)
    people_block = ChartBlock("Customers and delivery", "text",
                              suggestions=_finish(more, accepted >= MIN_ORDERS and data["unique_customers"] >= MIN_CUSTOMERS))

    notes = [f"Period: {data['range_label']} ({start:%d %b %Y} to {end:%d %b %Y}). Charts read the small tables beside them.",
             "Revenue counts accepted orders only (confirmed, packed, shipped, out for delivery, delivered)."]
    return InsightsSheet(notes=notes, blocks=[revenue_block, products_block, status_block, people_block])


# ------------------------------------------------------------------ orders report
def _pincode(order) -> str | None:
    addr = order.shipping_address or {}
    pin = addr.get("pincode") or addr.get("postal_code")
    return str(pin).strip() if pin else None


def orders_insights(orders, tz) -> InsightsSheet:
    """Orders by status and revenue by day, from the orders that are in this very file."""
    orders = list(orders)
    status = Counter(o.status for o in orders)
    sales = [(rx.to_local(o.created_at, tz), Decimal(str(o.total or 0)), o) for o in orders if o.status in REVENUE_STATUSES]
    sales = [(when.date(), amount, o) for when, amount, o in sales if when is not None]

    by_day: dict[date, list] = {}
    for day, amount, _ in sales:
        cell = by_day.setdefault(day, [Decimal(0), 0])
        cell[0] += amount
        cell[1] += 1
    rows, word, first_half, second_half = [], "Day", Decimal(0), Decimal(0)
    if by_day:
        lo, hi = min(by_day), max(by_day)
        span = (hi - lo).days + 1
        if span <= 62:
            for i in range(span):
                d = lo + timedelta(days=i)
                rows.append([f"{d:%d %b}", *by_day.get(d, [Decimal(0), 0])])
        else:
            word = "Month"
            months: dict[tuple, list] = {}
            for d, (amount, n) in sorted(by_day.items()):
                cell = months.setdefault((d.year, d.month), [Decimal(0), 0])
                cell[0] += amount
                cell[1] += n
            rows = [[f"{date(y, m, 1):%b %Y}", *v] for (y, m), v in months.items()]
        mid = lo + timedelta(days=span // 2)
        first_half = sum((a for d, (a, _) in by_day.items() if d < mid), Decimal(0))
        second_half = sum((a for d, (a, _) in by_day.items() if d >= mid), Decimal(0))
        first_orders = sum(n for d, (_, n) in by_day.items() if d < mid)

    drop = []
    if by_day and span >= 6:
        drop = rule_revenue_drop(second_half, first_half, first_orders, f"the earlier half of these orders ({lo:%d %b} to {(mid - timedelta(days=1)):%d %b})")
    buyers = Counter(o.user_id for _, _, o in sales)
    repeat = sum(1 for n in buyers.values() if n >= 2)
    found = drop + rule_repeat_rate(_pct(repeat, len(buyers)), len(buyers))
    revenue_block = ChartBlock(f"Revenue by {word.lower()}", "bar", [word, "Revenue (₹)", "Orders"], [TEXT, MONEY, INT], rows, [1], word, "Revenue (₹)",
                               suggestions=_finish(found, len(sales) >= MIN_ORDERS))

    ordered = status.most_common()
    closed = sum(status[k] for k in CLOSED)
    pins = Counter(p for p in (_pincode(o) for o in orders) if p)
    found = rule_cancelled(closed, len(orders)) + rule_pincode(pins, len(orders))
    status_block = ChartBlock("Orders by status", "doughnut", ["Status", "Orders"], [TEXT, INT], [[rx.status_label(k), n] for k, n in ordered], [1],
                              colors=[STATUS_COLORS.get(k, "B7C4BB") for k, _ in ordered], suggestions=_finish(found, len(orders) >= MIN_ORDERS))
    notes = ["Built from the orders in this file. Revenue counts accepted orders only (confirmed, packed, shipped, out for delivery, delivered)."]
    return InsightsSheet(notes=notes, blocks=[status_block, revenue_block])


# ------------------------------------------------------------------ users report
def users_insights(accounts, today: date) -> InsightsSheet:
    """accounts: dicts with role, joined (a local datetime or None) and orders (placed by that account)."""
    accounts = list(accounts)
    by_month = Counter((a["joined"].year, a["joined"].month) for a in accounts if a["joined"])
    rows = []
    if by_month:
        lo, hi = min(by_month), max(by_month)
        y, m = lo
        while (y, m) <= hi:
            rows.append([f"{date(y, m, 1):%b %Y}", by_month.get((y, m), 0)])
            y, m = y + (m == 12), 1 if m == 12 else m + 1
        rows = rows[-12:]                                                  # the latest twelve months keep the chart readable
    found = []
    prev = date(today.year - (today.month == 1), 12 if today.month == 1 else today.month - 1, 1)       # last full month
    before = date(prev.year - (prev.month == 1), 12 if prev.month == 1 else prev.month - 1, 1)
    if by_month and min(by_month) <= (before.year, before.month):
        a, b = by_month.get((prev.year, prev.month), 0), by_month.get((before.year, before.month), 0)
        if b >= MIN_SIGNUPS and a < b and (b - a) / b * 100 >= SIGNUP_DROP_PCT:
            found.append(("New accounts are down",
                          f"New accounts fell {(b - a) / b * 100:.0f}% in {prev:%b %Y} ({a}) versus {before:%b %Y} ({b}). "
                          "Promote a welcome coupon or a homepage banner to bring new customers in."))
    month_block = ChartBlock("New accounts per month", "bar", ["Month", "New accounts"], [TEXT, INT], rows, [1], "Month", "New accounts",
                             suggestions=_finish(found, bool(by_month) and min(by_month) <= (before.year, before.month)))

    roles = Counter(a["role"] for a in accounts)
    order = [r for r in ("user", "owner", "admin") if roles.get(r)]
    customers = [a for a in accounts if a["role"] == "user"]
    ordered = [a for a in customers if a["orders"] >= 1]
    repeat = sum(1 for a in ordered if a["orders"] >= 2)
    found = rule_repeat_rate(_pct(repeat, len(ordered)), len(ordered))
    idle = len(customers) - len(ordered)
    if len(customers) >= MIN_CUSTOMERS and _pct(idle, len(customers)) >= 50:
        found.append(("Customers who never ordered",
                      f"{idle} of {len(customers)} customers have not placed an order yet. Send them a first-order coupon."))
    role_block = ChartBlock("Role split", "doughnut", ["Role", "Accounts"], [TEXT, INT], [[rx.label(rx.ROLE_LABELS, r), roles[r]] for r in order], [1],
                            colors=["183D2B", "C9A227", "47764F"][: len(order)] or None, suggestions=_finish(found, len(customers) >= MIN_CUSTOMERS))
    return InsightsSheet(notes=["Built from the accounts in this file. Order counts come from the same file."], blocks=[month_block, role_block])


# ------------------------------------------------------------------ stock / products
def stock_insights(products) -> InsightsSheet:
    """Stock level chips, a stock level chart, the low-stock products, and slow movers, for the stock and products reports."""
    products = list(products)
    sold = units_sold_by_product()
    shop_units = sum(sold.values())
    state = {p.id: stock_state(p.stock_qty, p.low_stock_threshold) for p in products}
    counts = Counter(state.values())
    chips = [(STOCK_CHIPS[k][0], counts.get(k, 0), STOCK_CHIPS[k][1], STOCK_CHIPS[k][2]) for k in ("out", "low", "ok")]

    attention = sorted((p for p in products if state[p.id] in ("out", "low")), key=lambda p: (p.stock_qty, p.name or ""))
    found = []
    if attention:
        first = [f"{_name(p.name)} ({max(p.stock_qty, 0)} left)" for p in attention[:5]]
        found.append(("Restock soon", f"{counts.get('out', 0)} out of stock and {counts.get('low', 0)} low. Restock {_names(first)} first."))
    levels = [k for k in ("out", "low", "ok") if counts.get(k)]
    level_block = ChartBlock("Stock levels", "doughnut", ["Stock level", "Products"], [TEXT, INT],
                             [[STOCK_CHIPS[k][0], counts[k]] for k in levels], [1], colors=[STOCK_COLORS[k] for k in levels],
                             suggestions=_finish(found, bool(products)))

    top5 = [pid for pid, _ in sorted(sold.items(), key=lambda kv: -kv[1])[:5]]
    by_id = {p.id: p for p in products}
    fast = rule_fast_but_low([(by_id[pid].name, state[pid]) for pid in top5 if pid in by_id])
    low_rows = [[rx.clean_text(p.name), max(p.stock_qty, 0), p.low_stock_threshold] for p in attention[:10]]
    low_block = ChartBlock("Low-stock products (lowest first, up to 10)", "hbar", ["Product", "Stock qty", "Alert level"], [TEXT, INT, INT], low_rows,
                           [1, 2], "Product", "Units", empty_note="No product is low or out of stock, so there is no chart.",
                           suggestions=_finish(fast, bool(products) and shop_units > 0))

    idle = sorted((p for p in products if p.is_active and not p.is_deleted and p.stock_qty > 0 and not sold.get(p.id)), key=lambda p: (-p.stock_qty, p.name or ""))
    slow = rule_no_sales([p.name for p in idle[:MAX_NAMES]], len(idle), f"in the last {SALES_WINDOW_DAYS} days") if shop_units >= MIN_ORDERS else []
    slow_block = ChartBlock("Slow movers", "text", suggestions=_finish(slow, bool(products) and shop_units >= MIN_ORDERS))

    notes = ["Built from the products in this file.",
             f"Selling fast and slow movers look at units sold in the last {SALES_WINDOW_DAYS} days (accepted orders only)."]
    return InsightsSheet(notes=notes, chips=chips, blocks=[level_block, low_block, slow_block])
