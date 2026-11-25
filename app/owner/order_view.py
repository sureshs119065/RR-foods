"""Read-only helpers that feed the order timeline (owner cards and the customer tracker)."""
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from ..extensions import db
from ..models import OrderStatusHistory, Product


def item_products(orders) -> dict:
    """{product_id: Product} for every line of the given orders, loaded in one query (for thumbnails)."""
    ids = {it.product_id for o in orders for it in o.items if it.product_id}
    if not ids:
        return {}
    rows = db.session.scalars(select(Product).where(Product.id.in_(ids)).options(selectinload(Product.images))).all()
    return {p.id: p for p in rows}


def step_times(orders) -> dict:
    """{order_id: {step: datetime}} so each timeline step can show when it happened."""
    out = {o.id: {"placed": o.created_at} for o in orders}
    if not out:
        return out
    rows = db.session.scalars(select(OrderStatusHistory).where(OrderStatusHistory.order_id.in_(list(out)))
                              .order_by(OrderStatusHistory.created_at, OrderStatusHistory.id)).all()
    for h in rows:
        if h.from_status != h.to_status:  # payment notes are not stage changes
            out[h.order_id].setdefault(h.to_status, h.created_at)
    for when in out.values():  # shipped straight to delivered: earlier stages still count as done
        if "delivered" in when:
            when.setdefault("shipped", when["delivered"])
            when.setdefault("confirmed", when.get("placed", when["delivered"]))
            when.setdefault("packed", when.get("confirmed", when["delivered"]))
    return out
