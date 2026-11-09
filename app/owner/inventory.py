import re

from flask import flash, g, jsonify, redirect, render_template, request, url_for
from sqlalchemy import func, or_, select
from sqlalchemy.orm import joinedload, selectinload

from ..auth.service import audit, safe_next
from ..extensions import db
from ..services.stock_alerts import notify_restocked
from ..models import Category, InventoryLog, Product, ProductVariant
from ..services import inventory as stock
from ..services.inventory import MAX_QTY, StockError
from . import bp
from ..admin.helpers import clean, page_number, to_int

PER_PAGE = 30
MAX_BULK = 200
MAX_THRESHOLD = 100_000
SORTS = {
    "stock_asc": (Product.stock_qty.asc(), Product.name.asc()),
    "stock_desc": (Product.stock_qty.desc(), Product.name.asc()),
    "name": (func.lower(Product.name).asc(),),
    "updated": (Product.updated_at.desc(),),
}


def _wants_json() -> bool:
    return request.accept_mimetypes.best == "application/json"


def _reply(ok: bool, message: str, code: int = 200, **extra):
    """JSON for the in-page editor, flash + redirect for a plain form post (works without JavaScript)."""
    if _wants_json():
        return jsonify(ok=ok, message=message, **extra), code
    flash(message, "success" if ok else "error")
    return redirect(safe_next(request.form.get("next"), url_for("owner.inventory")))


def _state_payload(qty: int, threshold: int) -> dict:
    state = stock.stock_state(qty, threshold)
    return {"qty": qty, "state": state, "label": {"out": "Out of stock", "low": "Low stock", "ok": "In stock"}[state]}


# ---------------------------------------------------------------- list
@bp.route("/inventory")
def inventory():
    q = (select(Product).where(Product.is_deleted.is_(False))
         .options(selectinload(Product.variants), joinedload(Product.category)))

    term = (request.args.get("q") or "").strip().lower()
    if term:
        q = q.where(or_(func.lower(Product.name).contains(term, autoescape=True),
                        func.lower(Product.sku).contains(term, autoescape=True),
                        func.lower(func.coalesce(Product.brand, "")).contains(term, autoescape=True)))
    cat = request.args.get("category", "")
    if cat.isdigit():
        q = q.where(or_(Product.category_id == int(cat), Product.subcategory_id == int(cat)))
    level = request.args.get("stock", "")
    if level == "out":
        q = q.where(Product.stock_qty == 0)
    elif level == "low":
        q = q.where(Product.stock_qty > 0, Product.stock_qty <= Product.low_stock_threshold)
    elif level == "attention":
        q = q.where(Product.stock_qty <= Product.low_stock_threshold)
    elif level == "in":
        q = q.where(Product.stock_qty > Product.low_stock_threshold)
    sort = request.args.get("sort", "stock_asc")
    q = q.order_by(*SORTS.get(sort, SORTS["stock_asc"]), Product.id)

    page = db.paginate(q, page=page_number(), per_page=PER_PAGE, error_out=False)
    cats = db.session.scalars(select(Category).where(Category.is_deleted.is_(False), Category.parent_id.is_(None)).order_by(Category.sort_order, Category.name)).all()
    args = {k: v for k, v in request.args.items() if k != "page" and v}
    return render_template("owner/inventory.html", page=page, args=args, cats=cats, sort=sort, state_of=stock.stock_state,
                           next_url=request.full_path.rstrip("?"))


# ---------------------------------------------------------------- one quantity (inline edit)
@bp.post("/inventory/<kind>/<int:row_id>/stock")
def inventory_stock(kind, row_id):
    if kind not in ("product", "variant"):
        return _reply(False, "Unknown item.", 404)
    errs: dict = {}
    qty = to_int(request.form.get("qty"), "qty", errs, min_=0, max_=MAX_QTY)
    expected = to_int(request.form.get("expected"), "expected", errs, min_=0, max_=MAX_QTY, required=False, default=None)
    if errs:
        return _reply(False, errs.get("qty") or "Enter a whole number from 0 to 1,000,000.", 422)

    row = stock.lock_variant(row_id) if kind == "variant" else stock.lock_product(row_id)
    if row is None:
        return _reply(False, "That item no longer exists. Reload the page.", 404)
    product = row.product if kind == "variant" else row
    try:
        old = stock.set_quantity(row, qty, "owner edit", g.user.id, expected=expected)
    except stock.StaleStock as e:
        db.session.rollback()
        return _reply(False, str(e), 409, current=e.current)
    except StockError as e:
        db.session.rollback()
        return _reply(False, str(e), 422)
    if old != qty:
        audit("stock.set", entity_type="product", entity_id=product.id, actor_id=g.user.id,
              before={"qty": old}, after={"qty": qty, **({"variant_id": row_id} if kind == "variant" else {})})
    db.session.commit()
    notify_restocked()  # tell customers waiting for a product that is back
    msg = f"Saved: {product.name}{' (' + row.option_value + ')' if kind == 'variant' else ''} is now {qty}." if old != qty else "No change."
    return _reply(True, msg, **_state_payload(qty, product.low_stock_threshold))


# ---------------------------------------------------------------- alert level
@bp.post("/inventory/product/<int:product_id>/threshold")
def inventory_threshold(product_id):
    errs: dict = {}
    value = to_int(request.form.get("threshold"), "threshold", errs, min_=0, max_=MAX_THRESHOLD)
    if errs:
        return _reply(False, f"Enter a whole number from 0 to {MAX_THRESHOLD:,}.", 422)
    product = stock.lock_product(product_id)
    if product is None:
        return _reply(False, "That product no longer exists. Reload the page.", 404)
    old = product.low_stock_threshold
    if old != value:
        product.low_stock_threshold = value
        audit("stock.threshold", entity_type="product", entity_id=product.id, actor_id=g.user.id, before={"threshold": old}, after={"threshold": value})
    db.session.commit()
    notify_restocked()  # tell customers waiting for a product that is back
    return _reply(True, f"You will be warned when {product.name} reaches {value} or fewer.", **_state_payload(product.stock_qty, value), threshold=value)


# ---------------------------------------------------------------- bulk
_ID = re.compile(r"^([pv])(\d{1,9})$")


@bp.post("/inventory/bulk")
def inventory_bulk():
    back = safe_next(request.form.get("next"), url_for("owner.inventory"))
    refs = [m.groups() for m in (_ID.match(v) for v in request.form.getlist("ids")) if m]
    refs = sorted(set(refs))
    if not refs:
        flash("Select at least one item first.", "error")
        return redirect(back)
    if len(refs) > MAX_BULK:
        flash(f"Select at most {MAX_BULK} items at a time.", "error")
        return redirect(back)

    action = request.form.get("action", "")
    errs: dict = {}
    if action == "set":
        value = to_int(request.form.get("value"), "value", errs, min_=0, max_=MAX_QTY)
    elif action in ("add", "subtract"):
        value = to_int(request.form.get("value"), "value", errs, min_=1, max_=MAX_QTY)
    elif action == "threshold":
        value = to_int(request.form.get("value"), "value", errs, min_=0, max_=MAX_THRESHOLD)
    else:
        flash("Choose what to do first.", "error")
        return redirect(back)
    if errs:
        flash("Enter a whole number for the value" + (" (at least 1)." if action in ("add", "subtract") else "."), "error")
        return redirect(back)

    note = clean(request.form.get("reason"), 120)
    reason = f"bulk {action}" + (f": {note}" if note else "")

    pids = sorted(int(i) for k, i in refs if k == "p")
    vids = sorted(int(i) for k, i in refs if k == "v")
    # lock in a fixed order (products by id, then variants by id) so two bulk updates cannot deadlock each other
    products = db.session.scalars(select(Product).where(Product.id.in_(pids), Product.is_deleted.is_(False)).order_by(Product.id)
                                  .with_for_update().execution_options(populate_existing=True)).all() if pids else []
    variants = db.session.scalars(select(ProductVariant).where(ProductVariant.id.in_(vids), ProductVariant.is_deleted.is_(False)).order_by(ProductVariant.id)
                                  .with_for_update().execution_options(populate_existing=True)).all() if vids else []
    if len(products) != len(pids) or len(variants) != len(vids):
        db.session.rollback()
        flash("Some selected items no longer exist. Reload the list and try again.", "error")
        return redirect(back)

    if action == "threshold":
        if not products:
            db.session.rollback()
            flash("The alert level belongs to a product. Select a product row, not only variants.", "error")
            return redirect(back)
        for p in products:
            p.low_stock_threshold = value
        audit("stock.bulk_threshold", entity_type="product", actor_id=g.user.id, after={"ids": pids, "threshold": value})
        db.session.commit()
        notify_restocked()  # tell customers waiting for a product that is back
        flash(f"Alert level set to {value} on {len(products)} product{'s' if len(products) != 1 else ''}.", "success")
        return redirect(back)

    # work out every new quantity first; if any would go below zero nothing at all is changed
    plan = []
    for row in [*products, *variants]:
        new = value if action == "set" else row.stock_qty + value if action == "add" else row.stock_qty - value
        if new < 0:
            db.session.rollback()
            name = row.name if isinstance(row, Product) else f"{row.product.name} ({row.option_value})"
            flash(f"“{name}” has only {row.stock_qty}, so it cannot go down by {value}. Nothing was changed.", "error")
            return redirect(back)
        if new > MAX_QTY:
            db.session.rollback()
            flash(f"That would take an item above {MAX_QTY:,}. Nothing was changed.", "error")
            return redirect(back)
        plan.append((row, new))
    changed = 0
    for row, new in plan:
        if stock.set_quantity(row, new, reason, g.user.id) != new:
            changed += 1
    audit(f"stock.bulk_{action}", entity_type="product", actor_id=g.user.id, after={"products": pids, "variants": vids, "value": value, "changed": changed})
    db.session.commit()
    notify_restocked()  # tell customers waiting for a product that is back
    flash(f"Stock updated on {changed} of {len(plan)} item{'s' if len(plan) != 1 else ''}." if changed != len(plan) else f"Stock updated on {changed} item{'s' if changed != 1 else ''}.", "success")
    return redirect(back)


# ---------------------------------------------------------------- history
@bp.route("/stock-history")
def stock_history():
    q = select(InventoryLog).options(joinedload(InventoryLog.product), joinedload(InventoryLog.variant), joinedload(InventoryLog.actor))
    product = None
    pid = request.args.get("product", "")
    if pid.isdigit():
        product = db.session.get(Product, int(pid))
        q = q.where(InventoryLog.product_id == int(pid))
    term = (request.args.get("q") or "").strip().lower()
    if term and not product:
        q = q.join(Product, Product.id == InventoryLog.product_id).where(or_(
            func.lower(Product.name).contains(term, autoescape=True), func.lower(Product.sku).contains(term, autoescape=True)))
    page = db.paginate(q.order_by(InventoryLog.id.desc()), page=page_number(), per_page=50, error_out=False)
    args = {k: v for k, v in request.args.items() if k != "page" and v}
    return render_template("owner/stock_history.html", page=page, args=args, product=product)
