from decimal import Decimal
from flask import abort, flash, redirect, render_template, request, url_for
from sqlalchemy import select

from ..extensions import db
from ..models import Bundle, Combo, Product, SiteSetting
from ..services.storefront import active_variants
from . import bp
from .helpers import checked, clean, log, to_decimal, unique_slug


def _products():
    rows = db.session.scalars(select(Product).where(Product.is_deleted.is_(False), Product.is_active.is_(True), Product.stock_qty > 0).order_by(Product.name)).all()
    return [p for p in rows if not active_variants(p)]


def _save(combo=None):
    errors = {}
    products = _products()
    if request.method == "POST":
        name = clean(request.form.get("name"), 180)
        description = clean(request.form.get("description"), 1000) or None
        image = clean(request.form.get("image"), 500) or None
        festival = clean(request.form.get("festival_tag"), 40).lower() or "diwali"
        price = to_decimal(request.form.get("price"), "price", errors, min_=Decimal("0.01"), max_=Decimal("1000000"))
        original = to_decimal(request.form.get("original_price"), "original_price", errors, min_=Decimal("0.01"), max_=Decimal("1000000"))
        ids = []
        for raw in request.form.getlist("product_ids")[:12]:
            if raw.isdigit() and int(raw) not in ids:
                ids.append(int(raw))
        selected = [p for p in products if p.id in ids]
        if len(name) < 3: errors["name"] = "Enter a combo name."
        if not selected: errors["items"] = "Choose at least one active product."
        if price and original and price >= original: errors["price"] = "Combo price must be lower than original price."
        end_date = clean(request.form.get("diwali_end_at"), 30)
        if end_date:
            from datetime import datetime
            try: datetime.fromisoformat(end_date)
            except ValueError: errors["diwali_end_at"] = "Enter a valid date and time."
        if not errors:
            is_new = combo is None
            if is_new:
                slug = unique_slug(Combo, name)
                bundle = Bundle(name=name, slug=unique_slug(Bundle, f"{slug}-cart"), description=description,
                                product_quantities=[{"product_id": p.id, "quantity": 1} for p in selected],
                                bundle_price=float(price), is_active=checked("is_active"))
                db.session.add(bundle)
                db.session.flush()
                combo = Combo(name=name, slug=slug, bundle=bundle)
                db.session.add(combo)
            else:
                bundle = combo.bundle
                bundle.name, bundle.description = name, description
                bundle.product_quantities = [{"product_id": p.id, "quantity": 1} for p in selected]
                bundle.bundle_price = float(price)
                bundle.is_active = checked("is_active")
            combo.name, combo.description, combo.items = name, description, [{"product_id": p.id, "quantity": 1} for p in selected]
            combo.price, combo.original_price = price, original
            combo.image, combo.festival_tag, combo.is_active = image, festival, checked("is_active")
            if end_date:
                setting = db.session.get(SiteSetting, "diwali_end_at") or SiteSetting(key="diwali_end_at", value=end_date)
                setting.value = end_date
                db.session.add(setting)
            elif is_new and db.session.get(SiteSetting, "diwali_end_at") is None:
                db.session.add(SiteSetting(key="diwali_end_at", value="2026-11-12T23:59"))
            db.session.flush()
            log("combo.create" if is_new else "combo.update", "combo", combo.id,
                after={"name": name, "price": str(price), "is_active": combo.is_active})
            db.session.commit()
            flash(f"{name} saved.", "success")
            return redirect(url_for("admin.combos"))
        f = {"name": name, "description": description or "", "image": image or "", "festival_tag": festival,
             "price": request.form.get("price", ""), "original_price": request.form.get("original_price", ""),
             "is_active": checked("is_active"), "selected_ids": ids, "diwali_end_at": end_date}
        return render_template("admin/combo_form.html", combo=combo, f=f, products=products, errors=errors), 422

    setting = db.session.get(SiteSetting, "diwali_end_at")
    if combo:
        selected_ids = [int(x.get("product_id")) for x in (combo.items or []) if str(x.get("product_id", "")).isdigit()]
        f = {"name": combo.name, "description": combo.description or "", "image": combo.image or "",
             "festival_tag": combo.festival_tag, "price": str(combo.price), "original_price": str(combo.original_price),
             "is_active": combo.is_active, "selected_ids": selected_ids,
             "diwali_end_at": setting.value if setting and isinstance(setting.value, str) else ""}
    else:
        f = {"name": "", "description": "", "image": "", "festival_tag": "diwali", "price": "",
             "original_price": "", "is_active": True, "selected_ids": [],
             "diwali_end_at": setting.value if setting and isinstance(setting.value, str) else "2026-11-12T23:59"}
    return render_template("admin/combo_form.html", combo=combo, f=f, products=products, errors=errors)


@bp.get("/combos")
def combos():
    rows = db.session.scalars(select(Combo).order_by(Combo.created_at.desc())).all()
    return render_template("admin/combos.html", rows=rows)


@bp.route("/combos/new", methods=["GET", "POST"])
def combo_new():
    return _save()


@bp.route("/combos/<int:combo_id>/edit", methods=["GET", "POST"])
def combo_edit(combo_id):
    return _save(db.session.get(Combo, combo_id) or abort(404))


@bp.post("/combos/<int:combo_id>/delete")
def combo_delete(combo_id):
    combo = db.session.get(Combo, combo_id) or abort(404)
    log("combo.delete", "combo", combo.id, before={"name": combo.name})
    db.session.delete(combo)
    db.session.commit()
    flash("Combo deleted.", "success")
    return redirect(url_for("admin.combos"))
