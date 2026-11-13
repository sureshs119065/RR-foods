from datetime import datetime, timezone
import re
import uuid

from flask import abort, flash, redirect, render_template, request, url_for
from sqlalchemy import select

from ..extensions import db
from ..models import Bundle, Combo, Product
from ..uploads import save_image, UploadError, delete_files
from . import bp


def _slug(value):
    return re.sub(r"[^a-z0-9]+", "-", (value or "").lower()).strip("-")[:180] or "bundle"


def _products():
    return db.session.scalars(select(Product).where(Product.is_deleted.is_(False)).order_by(Product.name)).all()


@bp.get("/bundles")
def bundles():
    try:
        from ..shop.catalog import ensure_catalogue_combo_bundle
        ensure_catalogue_combo_bundle()  # makes the catalogue combo visible/editable here
    except Exception:  # never block the admin list, but record why
        db.session.rollback()
        from flask import current_app
        current_app.logger.exception("Could not create the catalogue combo bundle")
    try:
        from ..shop.catalog import catalogue_combo_removed
        combo_removed = catalogue_combo_removed()
    except Exception:
        combo_removed = False
    return render_template("admin/content_list.html", title="Bundles", kind="bundles", combo_removed=combo_removed,
        items=db.session.scalars(select(Bundle).order_by(Bundle.created_at.desc())).all())

@bp.post("/bundles/restore-catalogue-combo")
def bundle_restore_catalogue_combo():
    from ..shop.catalog import restore_catalogue_combo_bundle
    try:
        bundle = restore_catalogue_combo_bundle()
        flash("Catalogue combo restored." if bundle else "Could not restore the combo: none of its products were found.", "success" if bundle else "error")
    except Exception:
        db.session.rollback()
        flash("Could not restore the catalogue combo.", "error")
    return redirect(url_for("admin.bundles"))

def _form_item(original):
    """What to show again after a failed save: the values just typed (a rollback would otherwise reload the old ones)."""
    from types import SimpleNamespace
    def dt(value):
        try: return datetime.fromisoformat(value) if value else None
        except ValueError: return None
    lines = []
    for pid, qty in list(zip(request.form.getlist("product_id"), request.form.getlist("quantity")))[:30]:
        if pid.isdigit(): lines.append({"product_id": int(pid), "quantity": int(qty) if qty.isdigit() else 1})
    return SimpleNamespace(id=original.id, name=request.form.get("name", ""), description=request.form.get("description", ""),
        bundle_price=request.form.get("bundle_price", ""), image_url=original.image_url,
        starts_at=dt(request.form.get("starts_at", "")), ends_at=dt(request.form.get("ends_at", "")),
        is_active=request.form.get("is_active") == "1", product_quantities=lines)


@bp.route("/bundles/new", methods=["GET", "POST"])
@bp.route("/bundles/<int:item_id>/edit", methods=["GET", "POST"])
def bundle_form(item_id=None):
    item = db.session.get(Bundle, item_id) if item_id else Bundle(product_quantities=[])
    if item_id and item is None: abort(404)
    if request.method == "POST":
        try:
            name = request.form.get("name", "").strip()
            if not name: raise ValueError("Enter a bundle name.")
            item.name = name[:180]
            # Keep an existing bundle's slug stable on edit (the storefront looks bundles up by slug, and renaming
            # must never collide with another bundle). Only generate a slug for a brand-new bundle.
            if not item.slug:
                base_slug = _slug(name)
                with db.session.no_autoflush:  # don't flush half-edited rows while checking for a collision
                    taken = db.session.scalar(select(Bundle.id).where(Bundle.slug == base_slug))
                item.slug = f"{base_slug}-{uuid.uuid4().hex[:6]}" if taken else base_slug
            item.description = request.form.get("description", "").strip()
            item.bundle_price = float(request.form.get("bundle_price") or 0)
            if item.bundle_price < 0: raise ValueError("Bundle price cannot be negative.")
            items = []
            seen_products = set()
            for pid, qty in list(zip(request.form.getlist("product_id"), request.form.getlist("quantity")))[:30]:
                if pid.isdigit() and qty.isdigit() and int(qty) > 0 and db.session.get(Product, int(pid)):
                    if int(pid) in seen_products: raise ValueError("Choose each product only once in a bundle.")
                    seen_products.add(int(pid))
                    items.append({"product_id": int(pid), "quantity": min(int(qty), 50)})
            if not items: raise ValueError("Choose at least one product.")
            regular_total = sum((db.session.get(Product, line["product_id"]).final_price * line["quantity"] for line in items), 0)
            if item.bundle_price <= 0 or item.bundle_price >= float(regular_total):
                raise ValueError("Bundle price must be positive and lower than the combined product price.")
            item.product_quantities = items
            image = request.files.get("image")
            if image and image.filename: item.image_url = save_image(image, "bundles")[0]
            item.is_active = request.form.get("is_active") == "1"
            def parse_dt(value):
                if not value: return None
                parsed = datetime.fromisoformat(value)
                return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed
            item.starts_at = parse_dt(request.form.get("starts_at", ""))
            item.ends_at = parse_dt(request.form.get("ends_at", ""))
            if item.starts_at and item.ends_at and item.ends_at <= item.starts_at:
                raise ValueError("Bundle end date must be after its start date.")
            db.session.add(item); db.session.flush()
            combo = db.session.scalar(select(Combo).where(Combo.bundle_id == item.id)) if item.id else None
            if combo is not None:  # a festival combo shows its own copy of these fields on the storefront: keep it in step
                from decimal import Decimal
                combo.name, combo.description, combo.items = item.name, item.description, items
                combo.price, combo.is_active = Decimal(str(item.bundle_price)), item.is_active
                if item.image_url: combo.image = item.image_url
            db.session.commit()
            flash("Bundle saved.", "success"); return redirect(url_for("admin.bundles"))
        except (ValueError, UploadError) as exc:
            db.session.rollback(); flash(str(exc), "error")
            item = _form_item(item)
    return render_template("admin/content_form.html", title="Bundle", kind="bundles", item=item, products=_products())

@bp.post("/bundles/<int:item_id>/delete")
def bundle_delete(item_id):
    item = db.session.get(Bundle, item_id)
    if item:
        from ..shop.catalog import COMBO_BUNDLE_SLUG
        from ..models import SiteSetting
        if item.slug == COMBO_BUNDLE_SLUG:  # remember it so the storefront does not re-create it on the next page load
            flag = db.session.get(SiteSetting, "catalogue_combo_deleted")
            if flag is None: db.session.add(SiteSetting(key="catalogue_combo_deleted", value=True))
            else: flag.value = True
        delete_files(item.image_url); db.session.delete(item); db.session.commit()
        flash("Bundle deleted.", "success")
    return redirect(url_for("admin.bundles"))

