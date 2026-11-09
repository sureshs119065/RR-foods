"""Range-aware sales analytics shared by the Admin and Shop Owner dashboards.

Revenue follows the same accepted-order definition as the existing owner dashboard:
confirmed, packed, shipped, out for delivery and delivered orders only.
All date boundaries are interpreted in the configured shop timezone and converted
into UTC before querying the database.
"""
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func, select

from ..extensions import db
from ..models import Category, Order, OrderItem, Product
from .orders import REVENUE_STATUSES


def _month_after(value: date) -> date:
    return date(value.year + (value.month == 12), 1 if value.month == 12 else value.month + 1, 1)


def resolve_range(range_key: str | None, start_raw: str | None, end_raw: str | None, tz, today: date):
    """Return (key, start_date, end_date_inclusive, start_utc, end_utc, label)."""
    key = range_key if range_key in {"month", "year", "custom"} else "month"
    if key == "year":
        start_day = date(today.year, 1, 1)
        end_day = date(today.year, 12, 31)
        label = f"This year ({today.year})"
    elif key == "custom":
        try:
            start_day = date.fromisoformat(start_raw or "")
            end_day = date.fromisoformat(end_raw or "")
            if end_day < start_day or (end_day - start_day).days > 3660:
                raise ValueError
        except (TypeError, ValueError):
            key = "month"
            start_day = today.replace(day=1)
            end_day = today
            label = "This month"
        else:
            label = f"{start_day:%d %b %Y} – {end_day:%d %b %Y}"
    else:
        key = "month"
        start_day = today.replace(day=1)
        end_day = today
        label = "This month"

    start_local = datetime.combine(start_day, time.min, tzinfo=tz)
    end_local = datetime.combine(end_day + timedelta(days=1), time.min, tzinfo=tz)
    return (key, start_day, end_day, start_local.astimezone(timezone.utc),
            end_local.astimezone(timezone.utc), label)


def build_sales_analytics(range_key: str | None, start_raw: str | None, end_raw: str | None, tz):
    now_local = datetime.now(timezone.utc).astimezone(tz)
    today = now_local.date()
    key, start_day, end_day, start_utc, end_utc, label = resolve_range(
        range_key, start_raw, end_raw, tz, today
    )
    base_filter = (
        Order.status.in_(REVENUE_STATUSES),
        Order.created_at >= start_utc,
        Order.created_at < end_utc,
    )

    order_rows = db.session.execute(
        select(Order.created_at, Order.total).where(*base_filter)
    ).all()
    total_sales = sum((Decimal(str(amount or 0)) for _, amount in order_rows), Decimal("0.00"))
    accepted_order_count = len(order_rows)
    total_order_count = db.session.scalar(
        select(func.count(Order.id)).where(Order.created_at >= start_utc, Order.created_at < end_utc)
    ) or 0
    average_order_value = total_sales / accepted_order_count if accepted_order_count else Decimal("0.00")

    # Build chart buckets in shop-local time. This avoids database-specific date
    # truncation behaviour and keeps the displayed day/month boundaries correct.
    daily_totals: dict[date, Decimal] = {}
    monthly_totals: dict[tuple[int, int], Decimal] = {}
    for created_at, amount in order_rows:
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        local_day = created_at.astimezone(tz).date()
        value = Decimal(str(amount or 0))
        daily_totals[local_day] = daily_totals.get(local_day, Decimal("0.00")) + value
        month_key = (local_day.year, local_day.month)
        monthly_totals[month_key] = monthly_totals.get(month_key, Decimal("0.00")) + value

    monthly_chart = []
    cursor = date(start_day.year, start_day.month, 1)
    while cursor <= end_day:
        monthly_chart.append({
            "label": cursor.strftime("%b %Y"),
            "value": float(monthly_totals.get((cursor.year, cursor.month), Decimal("0.00"))),
        })
        cursor = _month_after(cursor)

    span_days = (end_day - start_day).days + 1
    if span_days <= 62:
        daily_chart = [
            {"label": (start_day + timedelta(days=i)).strftime("%d %b"),
             "value": float(daily_totals.get(start_day + timedelta(days=i), Decimal("0.00")))}
            for i in range(span_days)
        ]
        daily_granularity = "daily"
        daily_title = "Daily sales"
    else:
        # Weekly buckets keep long custom/year ranges readable on small screens.
        daily_chart = []
        offset = 0
        while offset < span_days:
            bucket_start = start_day + timedelta(days=offset)
            bucket_end = min(bucket_start + timedelta(days=6), end_day)
            value = sum((daily_totals.get(bucket_start + timedelta(days=i), Decimal("0.00"))
                         for i in range((bucket_end - bucket_start).days + 1)), Decimal("0.00"))
            daily_chart.append({
                "label": f"{bucket_start:%d %b}–{bucket_end:%d %b}",
                "value": float(value),
            })
            offset += 7
        daily_granularity = "weekly"
        daily_title = "Weekly sales trend"

    item_rows = db.session.execute(
        select(
            OrderItem.product_id,
            OrderItem.name,
            Category.name,
            func.coalesce(func.sum(OrderItem.line_total), 0),
            func.coalesce(func.sum(OrderItem.quantity), 0),
        )
        .select_from(OrderItem)
        .join(Order, Order.id == OrderItem.order_id)
        .outerjoin(Product, Product.id == OrderItem.product_id)
        .outerjoin(Category, Category.id == Product.category_id)
        .where(*base_filter)
        .group_by(OrderItem.product_id, OrderItem.name, Category.name)
    ).all()

    product_totals: dict[tuple[int | None, str], Decimal] = {}
    category_totals: dict[str, Decimal] = {}
    for product_id, product_name, category_name, line_total, quantity in item_rows:
        product_key = (product_id, product_name)
        product_totals[product_key] = product_totals.get(product_key, Decimal("0.00")) + Decimal(str(line_total or 0))
        category = category_name or "Uncategorised"
        category_totals[category] = category_totals.get(category, Decimal("0.00")) + Decimal(str(line_total or 0))

    top_products = [
        {"label": name, "value": float(amount)}
        for (_, name), amount in sorted(product_totals.items(), key=lambda pair: pair[1], reverse=True)[:8]
    ]
    categories = [
        {"label": name, "value": float(amount)}
        for name, amount in sorted(category_totals.items(), key=lambda pair: pair[1], reverse=True)
    ]

    return {
        "range_key": key,
        "start_date": start_day.isoformat(),
        "end_date": end_day.isoformat(),
        "range_label": label,
        "sales_label": {"month": "Sales This Month", "year": "Sales This Year", "custom": "Sales in Selected Range"}.get(key, "Sales This Month"),
        "total_sales": float(total_sales),
        "total_orders": int(total_order_count),
        "accepted_orders": accepted_order_count,
        "average_order_value": float(average_order_value),
        "products_sold": sum(int(row[4] or 0) for row in item_rows),
        "monthly_sales": monthly_chart,
        "daily_sales": daily_chart,
        "daily_granularity": daily_granularity,
        "daily_title": daily_title,
        "top_products": top_products,
        "categories": categories,
    }
