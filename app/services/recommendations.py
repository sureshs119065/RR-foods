"""Lightweight recommendations using order history with a six-hour process cache."""
import time
from threading import RLock

from sqlalchemy import and_, func, select
from sqlalchemy.orm import aliased, selectinload

from ..extensions import db
from ..models import Order, OrderItem, Product
from .storefront import LIVE, in_stock_sql

_CACHE_TTL = 6 * 60 * 60
_CACHE = {}
_LOCK = RLock()


def _related_ids(product_id: int, limit: int):
    now = time.monotonic()
    with _LOCK:
        cached = _CACHE.get(product_id)
        if cached and now - cached[0] < _CACHE_TTL:
            return cached[1][:limit]
    a, b = aliased(OrderItem), aliased(OrderItem)
    rows = db.session.execute(select(b.product_id, func.count(func.distinct(b.order_id)).label("orders"))
        .join(a, and_(a.order_id == b.order_id, a.product_id == product_id, b.product_id != product_id))
        .join(Order, Order.id == a.order_id)
        .where(Order.status.not_in(("rejected", "cancelled", "returned", "refunded")), b.product_id.is_not(None))
        .group_by(b.product_id).order_by(func.count(func.distinct(b.order_id)).desc(), b.product_id).limit(30)).all()
    ids = [int(row[0]) for row in rows]
    with _LOCK:
        _CACHE[product_id] = (now, ids)
    return ids[:limit]


def _available(ids, exclude=(), limit=4):
    skip = set(exclude)
    if not ids:
        return []
    rows = db.session.scalars(select(Product).where(Product.id.in_(ids), Product.id.not_in(skip or {0}), LIVE, in_stock_sql())
        .options(selectinload(Product.images), selectinload(Product.variants))).all()
    by_id = {p.id: p for p in rows}
    return [by_id[i] for i in ids if i in by_id][:limit]


def frequently_bought_together(product, limit=3):
    picked = _available(_related_ids(product.id, max(limit * 4, 12)), exclude={product.id}, limit=limit)
    if len(picked) >= limit:
        return picked
    have = {product.id, *(p.id for p in picked)}
    fallback = db.session.scalars(select(Product).where(LIVE, in_stock_sql(), Product.id.not_in(have), Product.category_id == product.category_id)
        .options(selectinload(Product.images), selectinload(Product.variants))
        .order_by(Product.is_bestseller.desc(), Product.sales_count.desc(), Product.id).limit(limit - len(picked))).all()
    return picked + list(fallback)


def cart_suggestions(cart_product_ids, limit=6):
    cart_ids = {int(x) for x in cart_product_ids if x}
    if not cart_ids:
        return []
    # Aggregate co-purchases from every product currently in the cart.
    scores = {}
    for pid in sorted(cart_ids):
        for rank, other in enumerate(_related_ids(pid, 30)):
            if other not in cart_ids:
                scores[other] = scores.get(other, 0) + (30 - rank)
    ids = [pid for pid, _ in sorted(scores.items(), key=lambda item: (-item[1], item[0]))]
    picked = _available(ids, exclude=cart_ids, limit=limit)
    if len(picked) < limit:
        categories = db.session.scalars(select(Product.category_id).where(Product.id.in_(cart_ids))).all()
        category_ids = {x for x in categories if x is not None}
        have = cart_ids | {p.id for p in picked}
        if category_ids:
            fallback = db.session.scalars(select(Product).where(LIVE, in_stock_sql(), Product.category_id.in_(category_ids), Product.id.not_in(have))
                .options(selectinload(Product.images), selectinload(Product.variants))
                .order_by(Product.is_bestseller.desc(), Product.sales_count.desc(), Product.id).limit(limit-len(picked))).all()
            picked.extend(fallback)
    return picked[:limit]
