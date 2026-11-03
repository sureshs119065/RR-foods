from decimal import ROUND_HALF_UP, Decimal

from flask import Response, abort, flash, redirect, render_template, request, url_for
from sqlalchemy import select

from ..extensions import db
from ..models import Category, Product
from . import bp
from .csvio import MAX_BYTES, export_csv, import_csv
from .helpers import checked, log, to_decimal, to_int
from .products import _list_query, permanently_delete, snapshot


def _ids() -> list[int]:
    ids = sorted({int(v) for v in request.form.getlist("ids") if v.isdigit()})
    if len(ids) > 500:
        abort(400)
    return ids


@bp.post("/products/bulk")
def products_bulk():
    ids = _ids()
    action = request.form.get("action", "")
    back = url_for("admin.products")
    if not ids:
        flash("Select at least one product first.", "error")
        return redirect(back)
    products = db.session.scalars(select(Product).where(Product.id.in_(ids))).all()
    if len(products) != len(ids):
        flash("Some selected products no longer exist. Reload the list and try again.", "error")
        return redirect(back)
    n = len(products)
    noun = f"{n} product{'' if n == 1 else 's'}"

    if action in ("hide", "show"):
        for p in products:
            p.is_active = action == "show"
        msg = f"{noun} {'shown in the shop' if action == 'show' else 'hidden from the shop'}."
    elif action == "archive":
        for p in products:
            p.archive()
        log("product.bulk_archive", "product", None, after={"ids": ids})
        db.session.commit()
        return redirect(url_for("admin.products", undo=",".join(map(str, ids))))
    elif action == "restore":
        for p in products:
            p.restore()
        msg = f"{noun} restored."
    elif action == "discount":
        dtype = request.form.get("discount_type", "")
        errs: dict = {}
        if dtype not in ("none", "percent", "flat"):
            flash("Choose a discount type.", "error")
            return redirect(back)
        value = Decimal(0)
        if dtype != "none":
            value = to_decimal(request.form.get("value"), "value", errs, min_=Decimal(0), max_=Decimal(100) if dtype == "percent" else Decimal(1_000_000))
            if errs:
                flash("Enter a valid discount: " + ("0 to 100 for a percentage." if dtype == "percent" else "a rupee amount."), "error")
                return redirect(back)
            if dtype == "flat":
                too_big = next((p for p in products if value > p.mrp), None)
                if too_big:
                    flash(f"₹{value} is more than the MRP of “{too_big.name}”. Nothing was changed.", "error")
                    return redirect(back)
        for p in products:
            p.discount_type, p.discount_value = dtype, value
            p.apply_pricing()
        msg = f"Discount updated on {noun}."
    elif action == "price_percent":
        errs = {}
        pct = to_decimal(request.form.get("value"), "value", errs, min_=Decimal(-90), max_=Decimal(500))
        if errs or pct == 0:
            flash("Enter a percentage between -90 and 500 (not zero). Use a minus sign to lower prices.", "error")
            return redirect(back)
        updates = []
        for p in products:
            new_mrp = (p.mrp * (Decimal(100) + pct) / 100).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            if new_mrp < Decimal("0.01") or (p.discount_type == "flat" and p.discount_value > new_mrp):
                flash(f"The new price of “{p.name}” would be too low for its discount. Nothing was changed.", "error")
                return redirect(back)
            updates.append((p, new_mrp))
        for p, new_mrp in updates:
            p.mrp = new_mrp
            p.apply_pricing()
        msg = f"Prices changed by {pct}% on {noun}."
    elif action == "move_category":
        raw = request.form.get("category_id", "")
        cat = db.session.get(Category, int(raw)) if raw.isdigit() else None
        if cat is None or cat.is_deleted or cat.parent_id is not None:
            flash("Choose the category to move them to.", "error")
            return redirect(back)
        for p in products:
            p.category_id, p.subcategory_id = cat.id, None
        msg = f"{noun} moved to “{cat.name}”."
    elif action == "delete":
        if not checked("confirm"):
            flash("Tick “I understand” to delete permanently.", "error")
            return redirect(back)
        live = [p for p in products if not p.is_deleted]
        if live:
            flash("Only archived products can be deleted permanently. Archive them first (you can undo that).", "error")
            return redirect(back)
        for p in products:
            permanently_delete(p)
        db.session.commit()
        flash(f"{noun} deleted permanently.", "success")
        return redirect(url_for("admin.products", status="archived"))
    else:
        flash("Choose an action first.", "error")
        return redirect(back)

    log(f"product.bulk_{action}", "product", None, after={"ids": ids})
    db.session.commit()
    flash(msg, "success")
    return redirect(back)


@bp.get("/products/export.csv")
def products_export():
    rows = db.session.scalars(_list_query()).all()
    log("product.export", "product", None, after={"count": len(rows)})
    db.session.commit()
    return Response(export_csv(rows), mimetype="text/csv", headers={
        "Content-Disposition": "attachment; filename=products.csv", "Cache-Control": "no-store"})


@bp.route("/products/import", methods=["GET", "POST"])
def products_import():
    result = None
    if request.method == "POST":
        upload = request.files.get("file")
        errs: dict = {}
        stock = to_int(request.form.get("default_stock"), "s", errs, min_=0, max_=100000, required=False, default=0)
        if not upload or not upload.filename:
            flash("Choose a CSV file first.", "error")
        elif errs:
            flash("Starting stock must be a whole number.", "error")
        else:
            result = import_csv(upload.read(MAX_BYTES + 1), create_categories=checked("create_categories"), default_stock=stock)
            if result.errors:
                db.session.rollback()
                flash("Nothing was imported. Fix the problems below and upload again.", "error")
            else:
                log("product.import", "product", None, after={"created": result.created, "updated": result.updated})
                db.session.commit()
                flash(f"Import finished: {result.created} added, {result.updated} updated.", "success")
                return redirect(url_for("admin.products"))
    return render_template("admin/import.html", result=result), (422 if result and result.errors else 200)
