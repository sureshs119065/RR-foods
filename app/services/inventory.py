"""Stock changes. Every change is locked, validated and written to inventory_logs (who, when, old, new).

Rules
- A product row (or variant row) is locked with SELECT ... FOR UPDATE before it is read, so two people (or the owner and a
  customer checking out) can never overwrite each other's quantity.
- `expected` lets a screen say "I saw 10 on my page". If the real number is no longer 10, nothing is saved and the caller
  is told the current number (StaleStock), so a stale page cannot wipe out an order's deduction.
- The functions here never commit. The caller commits, so a whole bulk update is all-or-nothing.
"""
from sqlalchemy import select

from ..extensions import db
from ..models import InventoryLog, Product, ProductVariant

MAX_QTY = 1_000_000


class StockError(Exception):
    """A problem the owner can fix. The message is safe to show."""


class StaleStock(StockError):
    def __init__(self, current: int):
        super().__init__(f"The stock changed while you were looking at it. It is now {current}. Check it and try again.")
        self.current = current


def lock_product(product_id: int, include_archived: bool = False) -> Product | None:
    q = select(Product).where(Product.id == product_id)
    if not include_archived:
        q = q.where(Product.is_deleted.is_(False))
    return db.session.scalar(q.with_for_update().execution_options(populate_existing=True))


def lock_variant(variant_id: int, include_archived: bool = False) -> ProductVariant | None:
    q = select(ProductVariant).where(ProductVariant.id == variant_id)
    if not include_archived:
        q = q.where(ProductVariant.is_deleted.is_(False))
    return db.session.scalar(q.with_for_update().execution_options(populate_existing=True))


def _log(product_id: int, variant_id: int | None, old: int, new: int, reason: str, actor_id: int | None) -> None:
    db.session.add(InventoryLog(product_id=product_id, variant_id=variant_id, changed_by=actor_id,
                                old_qty=old, new_qty=new, reason=(reason or "")[:200] or None))


def set_quantity(row: Product | ProductVariant, new_qty: int, reason: str, actor_id: int | None, expected: int | None = None) -> int:
    """Set a locked product/variant row to `new_qty`. Returns the old quantity. No log row if nothing changed."""
    if not isinstance(new_qty, int) or new_qty < 0 or new_qty > MAX_QTY:
        raise StockError(f"Enter a whole number from 0 to {MAX_QTY:,}.")
    old = row.stock_qty
    if expected is not None and expected != old:
        raise StaleStock(old)
    if new_qty == old:
        return old
    row.stock_qty = new_qty
    is_variant = isinstance(row, ProductVariant)
    _log(row.product_id if is_variant else row.id, row.id if is_variant else None, old, new_qty, reason, actor_id)
    return old


def add_quantity(row: Product | ProductVariant, delta: int, reason: str, actor_id: int | None) -> int:
    """Add (or subtract, when negative) from a locked row. Refuses to go below zero."""
    new = row.stock_qty + delta
    if new < 0:
        raise StockError("That would take the stock below zero.")
    return set_quantity(row, new, reason, actor_id)


def stock_state(qty: int, threshold: int) -> str:
    """'out' (0), 'low' (1..threshold) or 'ok'. Used for badges and the dashboard alerts."""
    if qty <= 0:
        return "out"
    return "low" if qty <= threshold else "ok"


def restore_order_stock(order, reason: str, actor_id: int | None) -> int:
    """Give the quantities of a rejected/cancelled order back to the shelf. Returns the number of lines restored.

    Rows are locked in a fixed order (products, then variants, by id) so two simultaneous restores cannot deadlock.
    Lines whose product was permanently deleted (product_id is NULL) are skipped.
    """
    lines = [i for i in order.items if i.product_id is not None]
    restored = 0
    for item in sorted(lines, key=lambda i: (i.product_id, i.variant_id or 0)):
        # archived products/variants still get their stock back, so the number is right if they are restored later
        row = lock_variant(item.variant_id, include_archived=True) if item.variant_id else lock_product(item.product_id, include_archived=True)
        if row is None:
            continue
        add_quantity(row, item.quantity, reason, actor_id)
        restored += 1
    return restored
