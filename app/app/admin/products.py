from flask import abort, flash, redirect, render_template, request, url_for
from sqlalchemy import func, or_, select

from ..extensions import db
from ..models import Category, InventoryLog, Offer, Product, ProductImage, ProductVariant
from ..uploads import MAX_FILE_BYTES, UploadError, copy_file, delete_files, save_image
from ..services.inventory import notify_admin_stock_transition
from . import bp
from .helpers import log, page_number, unique_slug
from .product_forms import (DISCOUNT_CHOICES, MAX_IMAGES, NUTRITION_FIELDS, parse_product, values_from_product,
                            values_from_request)

PER_PAGE = 20


def snapshot(p: Product) -> dict:
    return {"sku": p.sku, "name": p.name, "category_id": p.category_id, "mrp": str(p.mrp), "discount_type": p.discount_type,
            "discount_value": str(p.discount_value), "final_price": str(p.final_price), "stock_qty": p.stock_qty,
            "is_active": p.is_active, "is_deleted": p.is_deleted, "is_bestseller": p.is_bestseller}


def inventory_log(product_id, variant_id, old, new, reason):
    from flask import g
    if old != new:
        db.session.add(InventoryLog(product_id=product_id, variant_id=variant_id, changed_by=g.user.id, old_qty=old, new_qty=new, reason=reason))


def _list_query():
    status = request.args.get("status", "")
    q = select(Product).options()
    if status == "archived":
        q = q.where(Product.is_deleted.is_(True))
    else:
        q = q.where(Product.is_deleted.is_(False))
        if status == "active":
            q = q.where(Product.is_active.is_(True))
        elif status == "hidden":
            q = q.where(Product.is_active.is_(False))
    term = (request.args.get("q") or "").strip()
    if term:
        like = f"%{term.lower()}%"
        q = q.where(or_(func.lower(Product.name).like(like), func.lower(Product.sku).like(like), func.lower(func.coalesce(Product.brand, "")).like(like)))
    cat = request.args.get("category", "")
    if cat.isdigit():
        q = q.where((Product.category_id == int(cat)) | (Product.subcategory_id == int(cat)))
    stock = request.args.get("stock", "")
    if stock == "low":
        q = q.where(Product.stock_qty > 0, Product.stock_qty <= Product.low_stock_threshold)
    elif stock == "out":
        q = q.where(Product.stock_qty == 0)
    elif stock == "in":
        q = q.where(Product.stock_qty > 0)
    order = {"name": Product.name, "price_asc": Product.final_price, "stock": Product.stock_qty}.get(request.args.get("sort", ""))
    if request.args.get("sort") == "price_desc":
        return q.order_by(Product.final_price.desc(), Product.id)
    return q.order_by(order if order is not None else Product.id.desc(), Product.id)


def _categories():
    roots = db.session.scalars(select(Category).where(Category.parent_id.is_(None), Category.is_deleted.is_(False)).order_by(Category.sort_order, Category.name)).all()
    out = []
    for r in roots:
        out.append((r, [c for c in db.session.scalars(select(Category).where(Category.parent_id == r.id, Category.is_deleted.is_(False)).order_by(Category.sort_order, Category.name))]))
    return out


@bp.route("/products")
def products():
    page = db.paginate(_list_query(), page=page_number(), per_page=PER_PAGE, error_out=False)
    args = {k: v for k, v in request.args.items() if k not in ("page", "undo") and v}
    undo = [int(x) for x in request.args.get("undo", "").split(",") if x.isdigit()][:200]
    return render_template("admin/products.html", page=page, args=args, cats=_categories(), undo=undo,
                           status=request.args.get("status", ""))


# ---------------------------------------------------------------- create / edit
def _apply(product: Product, data: dict, is_new: bool) -> None:
    old_stock = 0 if is_new else product.stock_qty
    product.name, product.sku = data["name"], data["sku"]
    product.brand, product.pack_size = data["brand"], data["pack_size"]
    product.category_id = data["category"].id
    product.subcategory_id = data["subcategory"].id if data["subcategory"] else None
    for key in ("short_description", "description", "ingredients", "how_to_use", "fssai", "video_id", "tags",
                "specifications", "nutrition", "is_active", "is_bestseller", "low_stock_threshold"):
        setattr(product, key, data[key])
    product.mrp, product.discount_type, product.discount_value = data["mrp"], data["discount_type"], data["discount_value"]
    product.apply_pricing()
    product.stock_qty = data["stock_qty"]
    if is_new:
        db.session.add(product)
    db.session.flush()
    inventory_log(product.id, None, old_stock, product.stock_qty, "initial stock" if is_new else "admin edit")
    notify_admin_stock_transition(product, old_stock, product.stock_qty)

    product.offers = [db.session.get(Offer, i) for i in data["offer_ids"]]
    product.related = [db.session.get(Product, i) for i in data["related_ids"]]

    keep = {v["id"] for v in data["variants"] if v["id"]}
    for existing in list(product.variants):
        if existing.id not in keep:
            db.session.delete(existing)
    by_id = {v.id: v for v in product.variants}
    for row in data["variants"]:
        variant = by_id.get(row["id"]) if row["id"] else None
        old_qty = variant.stock_qty if variant else 0
        if variant is None:
            variant = ProductVariant(product_id=product.id)
            product.variants.append(variant)
        variant.option_name, variant.option_value, variant.sku = row["option_name"], row["option_value"], row["sku"]
        variant.mrp, variant.price, variant.stock_qty = row["mrp"], row["price"], row["stock"]
        db.session.flush()
        inventory_log(product.id, variant.id, old_qty, variant.stock_qty, "initial stock" if row["id"] is None else "admin edit")
        notify_admin_stock_transition(product, old_qty, variant.stock_qty)


def _store_images(product: Product, files, errors: dict) -> list[str]:
    """Saves uploaded images. Returns the saved URLs so the caller can delete them again if something later fails."""
    saved: list[str] = []
    files = [f for f in files if f and f.filename]
    if not files:
        return saved
    room = MAX_IMAGES - len(product.images)
    if len(files) > room:
        errors["images"] = f"A product can have at most {MAX_IMAGES} images ({max(room, 0)} more can be added)."
        return saved
    for f in files:
        try:
            url, thumb = save_image(f, "products")
        except UploadError as exc:
            errors["images"] = str(exc)
            delete_files(*saved)
            return []
        saved += [url, thumb]
        product.images.append(ProductImage(url=url, thumb_url=thumb, alt=product.name, sort_order=len(product.images),
                                           is_primary=not product.images))
    return saved


def _form(product: Product | None):
    is_new = product is None
    errors: dict[str, str] = {}
    if request.method == "POST":
        data, errors = parse_product(product)
        before = None if is_new else snapshot(product)
        if not errors:
            saved_files: list[str] = []
            try:
                if is_new:
                    product = Product(slug=unique_slug(Product, data["name"]), category_id=data["category"].id,
                                      mrp=data["mrp"], final_price=data["mrp"])
                _apply(product, data, is_new)
                saved_files = _store_images(product, request.files.getlist("images"), errors)
                if not errors:
                    log("product.create" if is_new else "product.update", "product", product.id, before, snapshot(product))
                    db.session.commit()
                    flash(f"“{product.name}” saved.", "success")
                    return redirect(url_for("admin.product_edit", product_id=product.id))
            except Exception:
                db.session.rollback()
                delete_files(*saved_files)
                raise
            db.session.rollback()
            delete_files(*saved_files)
            if is_new:
                product = None
        values, status = values_from_request(), 422
    else:
        values, status = values_from_product(product), 200
    if product is not None:
        product = db.session.get(Product, product.id)
    pad = max(0, 2 - len([v for v in values["variants"] if not v.get("id")]))
    return render_template(
        "admin/product_form.html", product=product, f=values, errors=errors, cats=_categories(),
        offers=db.session.scalars(select(Offer).where(Offer.is_active.is_(True)).order_by(Offer.name)).all(),
        others=db.session.scalars(select(Product).where(Product.is_deleted.is_(False), *( [Product.id != product.id] if product else [])).order_by(Product.name).limit(300)).all(),
        discount_choices=DISCOUNT_CHOICES, nutrition_fields=NUTRITION_FIELDS, blank_variants=pad, max_images=MAX_IMAGES,
        max_mb=MAX_FILE_BYTES // (1024 * 1024)), status


@bp.route("/products/new", methods=["GET", "POST"])
def product_new():
    return _form(None)


@bp.route("/products/<int:product_id>/edit", methods=["GET", "POST"])
def product_edit(product_id):
    return _form(db.session.get(Product, product_id) or abort(404))


# ---------------------------------------------------------------- images
def _image(product_id: int, image_id: int) -> tuple[Product, ProductImage]:
    product = db.session.get(Product, product_id) or abort(404)
    image = db.session.get(ProductImage, image_id)
    if image is None or image.product_id != product.id:
        abort(404)
    return product, image


@bp.post("/products/<int:product_id>/images/<int:image_id>/primary")
def image_primary(product_id, image_id):
    product, image = _image(product_id, image_id)
    for img in product.images:
        img.is_primary = img.id == image.id
    log("product.image_primary", "product", product.id, after={"image_id": image.id})
    db.session.commit()
    flash("Main image changed.", "success")
    return redirect(url_for("admin.product_edit", product_id=product.id))


@bp.post("/products/<int:product_id>/images/<int:image_id>/move")
def image_move(product_id, image_id):
    product, image = _image(product_id, image_id)
    direction = request.form.get("direction")
    if direction not in ("up", "down"):
        abort(400)
    imgs = sorted(product.images, key=lambda i: (i.sort_order, i.id))
    for n, i in enumerate(imgs):
        i.sort_order = n
    idx = imgs.index(image)
    j = idx - 1 if direction == "up" else idx + 1
    if 0 <= j < len(imgs):
        imgs[idx].sort_order, imgs[j].sort_order = imgs[j].sort_order, imgs[idx].sort_order
    db.session.commit()
    return redirect(url_for("admin.product_edit", product_id=product.id))


@bp.post("/products/<int:product_id>/images/<int:image_id>/delete")
def image_delete(product_id, image_id):
    product, image = _image(product_id, image_id)
    was_primary, urls = image.is_primary, (image.url, image.thumb_url)
    product.images.remove(image)
    db.session.flush()
    if was_primary and product.images:
        sorted(product.images, key=lambda i: (i.sort_order, i.id))[0].is_primary = True
    log("product.image_delete", "product", product.id, before={"url": image.url})
    db.session.commit()
    delete_files(*urls)
    flash("Image removed.", "success")
    return redirect(url_for("admin.product_edit", product_id=product.id))


# ---------------------------------------------------------------- archive / restore / delete / duplicate
@bp.post("/products/<int:product_id>/archive")
def product_archive(product_id):
    product = db.session.get(Product, product_id) or abort(404)
    product.archive()
    log("product.archive", "product", product.id, after={"is_deleted": True})
    db.session.commit()
    return redirect(url_for("admin.products", undo=product.id))


@bp.post("/products/<int:product_id>/restore")
def product_restore(product_id):
    product = db.session.get(Product, product_id) or abort(404)
    product.restore()
    log("product.restore", "product", product.id, after={"is_deleted": False})
    db.session.commit()
    flash(f"“{product.name}” is back in your product list.", "success")
    return redirect(url_for("admin.products"))


def permanently_delete(product: Product) -> None:
    urls = [u for img in product.images for u in (img.url, img.thumb_url)]
    log("product.delete", "product", product.id, before=snapshot(product))
    db.session.delete(product)
    db.session.flush()
    delete_files(*urls)


@bp.post("/products/<int:product_id>/delete")
def product_delete(product_id):
    from .helpers import checked
    product = db.session.get(Product, product_id) or abort(404)
    if not checked("confirm"):
        flash("Tick “I understand” to delete permanently.", "error")
        return redirect(url_for("admin.products", status="archived"))
    name = product.name
    permanently_delete(product)
    db.session.commit()
    flash(f"“{name}” was deleted permanently.", "success")
    return redirect(url_for("admin.products", status="archived"))


def _unique_sku(base: str) -> str:
    n = 1
    while True:
        sku = f"{base}-COPY" if n == 1 else f"{base}-COPY{n}"
        if not db.session.scalar(select(Product.id).where(func.upper(Product.sku) == sku.upper())) \
                and not db.session.scalar(select(ProductVariant.id).where(func.upper(ProductVariant.sku).like(f"{sku.upper()}%"))):
            return sku[:60]
        n += 1


def duplicate_product(src: Product) -> Product:
    sku = _unique_sku(src.sku)
    new = Product(sku=sku, slug=unique_slug(Product, f"{src.name} copy"), name=f"{src.name} (Copy)", brand=src.brand,
                  short_description=src.short_description, description=src.description, category_id=src.category_id,
                  subcategory_id=src.subcategory_id, pack_size=src.pack_size, mrp=src.mrp, discount_type=src.discount_type,
                  discount_value=src.discount_value, final_price=src.final_price, stock_qty=0, low_stock_threshold=src.low_stock_threshold,
                  tags=list(src.tags or []), specifications=dict(src.specifications or {}), ingredients=src.ingredients,
                  nutrition=dict(src.nutrition or {}), how_to_use=src.how_to_use, fssai=src.fssai, video_id=src.video_id,
                  is_active=False)  # hidden until the admin checks it
    db.session.add(new)
    db.session.flush()
    for img in src.images:
        new.images.append(ProductImage(url=copy_file(img.url), thumb_url=copy_file(img.thumb_url), alt=new.name,
                                       sort_order=img.sort_order, is_primary=img.is_primary))
    for n, v in enumerate(src.variants, 1):
        new.variants.append(ProductVariant(option_name=v.option_name, option_value=v.option_value, sku=f"{sku}-{n}",
                                           mrp=v.mrp, price=v.price, stock_qty=0))
    new.offers = list(src.offers)
    new.related = list(src.related)
    return new


@bp.post("/products/<int:product_id>/duplicate")
def product_duplicate(product_id):
    src = db.session.get(Product, product_id) or abort(404)
    new = duplicate_product(src)
    log("product.duplicate", "product", new.id, before={"source_id": src.id}, after=snapshot(new))
    db.session.commit()
    flash("Copy created. It is hidden and has no stock yet. Check it and switch it on when ready.", "success")
    return redirect(url_for("admin.product_edit", product_id=new.id))
