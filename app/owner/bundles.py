from datetime import datetime, timezone
import re
import uuid

from flask import abort, flash, redirect, render_template, request, url_for
from sqlalchemy import select

from ..extensions import db
from ..models import Bundle, Product
from ..uploads import save_image, UploadError, delete_files
from ..owner import bp


def _slug(value):
    return re.sub(r"[^a-z0-9]+", "-", (value or "").lower()).strip("-")[:180] or "bundle"


def _products():
    return db.session.scalars(select(Product).where(Product.is_deleted.is_(False)).order_by(Product.name)).all()


@bp.get("/bundles")
def bundles():
    return render_template("owner/content_list.html", title="Bundles", kind="bundles",
        items=db.session.scalars(select(Bundle).order_by(Bundle.created_at.desc())).all())

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
            db.session.add(item); db.session.commit()
            flash("Bundle saved.", "success"); return redirect(url_for("owner.bundles"))
        except (ValueError, UploadError) as exc:
            db.session.rollback(); flash(str(exc), "error")
    return render_template("owner/content_form.html", title="Bundle", kind="bundles", item=item, products=_products())

@bp.post("/bundles/<int:item_id>/delete")
def bundle_delete(item_id):
    item = db.session.get(Bundle, item_id)
    if item:
        delete_files(item.image_url); db.session.delete(item); db.session.commit()
        flash("Bundle deleted.", "success")
    return redirect(url_for("owner.bundles"))

