from flask import abort, flash, redirect, render_template, request, url_for
from sqlalchemy import func, select

from ..extensions import db
from ..models import Category, Product
from ..uploads import UploadError, delete_files, save_image
from . import bp
from .helpers import checked, clean, clean_multiline, log, to_int, unique_slug


def _live_product_count(cat_id: int) -> int:
    return db.session.scalar(
        select(func.count(Product.id)).where(
            (Product.category_id == cat_id) | (Product.subcategory_id == cat_id), Product.is_deleted.is_(False))
    ) or 0


def _roots(include_archived: bool):
    q = select(Category).where(Category.parent_id.is_(None)).order_by(Category.sort_order, Category.name)
    if not include_archived:
        q = q.where(Category.is_deleted.is_(False))
    return db.session.scalars(q).all()


def _children(parent_id: int, include_archived: bool):
    q = select(Category).where(Category.parent_id == parent_id).order_by(Category.sort_order, Category.name)
    if not include_archived:
        q = q.where(Category.is_deleted.is_(False))
    return db.session.scalars(q).all()


def _snapshot(c: Category) -> dict:
    return {"name": c.name, "slug": c.slug, "parent_id": c.parent_id, "sort_order": c.sort_order,
            "is_active": c.is_active, "image": c.image, "is_deleted": c.is_deleted}


@bp.route("/categories")
def categories():
    show_archived = request.args.get("archived") == "1"
    rows = []
    for root in _roots(show_archived):
        rows.append((root, 0))
        rows.extend((child, 1) for child in _children(root.id, show_archived))
    counts = {c.id: _live_product_count(c.id) for c, _ in rows}
    return render_template("admin/categories.html", rows=rows, counts=counts, show_archived=show_archived)


def _parse(category: Category | None):
    errors: dict[str, str] = {}
    name = clean(request.form.get("name"), 120)
    if len(name) < 2:
        errors["name"] = "Enter a name (at least 2 characters)."
    parent_raw = request.form.get("parent_id", "")
    parent = None
    if parent_raw:
        parent = db.session.get(Category, int(parent_raw)) if parent_raw.isdigit() else None
        if parent is None or parent.is_deleted:
            errors["parent_id"] = "Choose a valid parent category."
        elif parent.parent_id is not None:
            errors["parent_id"] = "Only two levels are allowed: a subcategory cannot have its own subcategories."
        elif category is not None and parent.id == category.id:
            errors["parent_id"] = "A category cannot be its own parent."
        elif category is not None and db.session.scalar(select(func.count(Category.id)).where(Category.parent_id == category.id)):
            errors["parent_id"] = "This category has subcategories, so it must stay at the top level."
    if "name" not in errors:
        dupe = select(Category.id).where(
            func.lower(Category.name) == name.lower(),
            Category.parent_id.is_(None) if parent is None else Category.parent_id == parent.id,
            Category.is_deleted.is_(False))
        if category is not None:
            dupe = dupe.where(Category.id != category.id)
        if db.session.scalar(dupe):
            errors["name"] = "A category with this name already exists here."
    sort_order = to_int(request.form.get("sort_order"), "sort_order", errors, min_=0, max_=9999, required=False, default=0)
    return {
        "name": name, "parent": parent, "description": clean_multiline(request.form.get("description"), 1000) or None,
        "sort_order": sort_order, "is_active": checked("is_active"),
    }, errors


def _apply_image(cat: Category, errors: dict) -> None:
    upload = request.files.get("image")
    if checked("remove_image") and cat.image:
        delete_files(cat.image)
        cat.image = None
    if upload and upload.filename:
        try:
            url, _ = save_image(upload, "categories", max_side=1000, thumb_side=None)
        except UploadError as exc:
            errors["image"] = str(exc)
            return
        delete_files(cat.image)
        cat.image = url


@bp.route("/categories/new", methods=["GET", "POST"])
def category_new():
    return _form(None)


@bp.route("/categories/<int:cat_id>/edit", methods=["GET", "POST"])
def category_edit(cat_id):
    cat = db.session.get(Category, cat_id) or abort(404)
    return _form(cat)


def _form(cat: Category | None):
    errors: dict[str, str] = {}
    data = {}
    if request.method == "POST":
        data, errors = _parse(cat)
        if not errors:
            is_new = cat is None
            before = None if is_new else _snapshot(cat)
            if is_new:
                cat = Category(name=data["name"], slug=unique_slug(Category, data["name"]))
                db.session.add(cat)
            elif cat.name != data["name"]:
                cat.slug = unique_slug(Category, data["name"], exclude_id=cat.id)
            cat.name = data["name"]
            cat.parent_id = data["parent"].id if data["parent"] else None
            cat.description = data["description"]
            cat.sort_order = data["sort_order"]
            cat.is_active = data["is_active"]
            _apply_image(cat, errors)
            if not errors:
                db.session.flush()
                log("category.create" if is_new else "category.update", "category", cat.id, before, _snapshot(cat))
                db.session.commit()
                flash(f"Category “{cat.name}” saved.", "success")
                return redirect(url_for("admin.categories"))
            db.session.rollback()
        status = 422
    else:
        status = 200
    roots = [c for c in _roots(False) if cat is None or c.id != cat.id]
    form = data or ({} if cat is None else {
        "name": cat.name, "parent": cat.parent, "description": cat.description, "sort_order": cat.sort_order, "is_active": cat.is_active})
    if cat is None and not data:
        form = {"name": "", "parent": None, "description": "", "sort_order": 0, "is_active": True}
    if request.method == "POST" and errors:
        form = {"name": request.form.get("name", ""), "parent": data.get("parent"), "description": request.form.get("description", ""),
                "sort_order": request.form.get("sort_order", "0"), "is_active": checked("is_active")}
    return render_template("admin/category_form.html", cat=cat, form=form, errors=errors, roots=roots), status


@bp.post("/categories/<int:cat_id>/move")
def category_move(cat_id):
    """Moves a category up or down among its siblings."""
    cat = db.session.get(Category, cat_id) or abort(404)
    direction = request.form.get("direction")
    if direction not in ("up", "down"):
        abort(400)
    siblings = db.session.scalars(select(Category).where(
        Category.parent_id.is_(None) if cat.parent_id is None else Category.parent_id == cat.parent_id,
        Category.is_deleted.is_(False)).order_by(Category.sort_order, Category.name, Category.id)).all()
    for i, s in enumerate(siblings):  # make the order explicit first (ties are common)
        s.sort_order = i
    i = siblings.index(cat)
    j = i - 1 if direction == "up" else i + 1
    if 0 <= j < len(siblings):
        siblings[i].sort_order, siblings[j].sort_order = siblings[j].sort_order, siblings[i].sort_order
        log("category.reorder", "category", cat.id, after={"direction": direction})
    db.session.commit()
    return redirect(url_for("admin.categories"))


@bp.post("/categories/<int:cat_id>/archive")
def category_archive(cat_id):
    cat = db.session.get(Category, cat_id) or abort(404)
    n = _live_product_count(cat.id)
    kids = db.session.scalar(select(func.count(Category.id)).where(Category.parent_id == cat.id, Category.is_deleted.is_(False)))
    if n:
        flash(f"“{cat.name}” still has {n} product(s). Move or archive them first.", "error")
    elif kids:
        flash(f"“{cat.name}” still has {kids} subcategor{'y' if kids == 1 else 'ies'}. Archive those first.", "error")
    else:
        cat.archive()
        log("category.archive", "category", cat.id)
        db.session.commit()
        flash(f"Category “{cat.name}” archived.", "success")
    return redirect(url_for("admin.categories"))


@bp.post("/categories/<int:cat_id>/restore")
def category_restore(cat_id):
    cat = db.session.get(Category, cat_id) or abort(404)
    if cat.parent_id and db.session.get(Category, cat.parent_id).is_deleted:
        flash("Restore the parent category first.", "error")
    else:
        cat.restore()
        log("category.restore", "category", cat.id)
        db.session.commit()
        flash(f"Category “{cat.name}” restored.", "success")
    return redirect(url_for("admin.categories", archived="1"))


@bp.post("/categories/<int:cat_id>/delete")
def category_delete(cat_id):
    """Permanent delete. Only for categories with nothing inside, and only after an explicit confirmation."""
    cat = db.session.get(Category, cat_id) or abort(404)
    if not checked("confirm"):
        flash("Tick the confirmation box to delete permanently.", "error")
        return redirect(url_for("admin.categories", archived="1"))
    products = db.session.scalar(select(func.count(Product.id)).where((Product.category_id == cat.id) | (Product.subcategory_id == cat.id)))
    kids = db.session.scalar(select(func.count(Category.id)).where(Category.parent_id == cat.id))
    if products or kids:
        flash("This category still has products or subcategories (including archived ones), so it cannot be deleted.", "error")
        return redirect(url_for("admin.categories", archived="1"))
    name, image = cat.name, cat.image
    log("category.delete", "category", cat.id, before=_snapshot(cat))
    db.session.delete(cat)
    db.session.commit()
    delete_files(image)
    flash(f"Category “{name}” deleted permanently.", "success")
    return redirect(url_for("admin.categories", archived="1"))
