from datetime import datetime, timezone
from pathlib import Path
import re
from flask import abort, flash, g, redirect, render_template, request, url_for
from sqlalchemy import select
from ..extensions import db
from ..models import Product, Reel, RecipeVideo, Order, OrderStatusHistory, Notification
from ..uploads import save_image, save_video, UploadError, delete_files
from . import bp

def _slug(value):
    value = re.sub(r"[^a-z0-9]+", "-", (value or "").lower()).strip("-")
    return value[:180] or "content"

def _products():
    return db.session.scalars(select(Product).where(Product.is_deleted.is_(False)).order_by(Product.name)).all()

@bp.get("/reels")
def reels():
    from ..models import SiteSetting
    setting = db.session.get(SiteSetting, "home_reels")
    cfg = setting.value if setting and isinstance(setting.value, dict) else {"enabled": True, "max_count": 8, "selected_ids": []}
    return render_template("admin/content_list.html", title="Reels", kind="reels",
        items=db.session.scalars(select(Reel).order_by(Reel.sort_order, Reel.id)).all(), reels_cfg=cfg)

@bp.route("/reels/new", methods=["GET", "POST"])
@bp.route("/reels/<int:item_id>/edit", methods=["GET", "POST"])
def reel_form(item_id=None):
    item = db.session.get(Reel, item_id) if item_id else Reel()
    if item_id and item is None: abort(404)
    if request.method == "POST":
        try:
            item.title = request.form.get("title", "").strip()[:160]
            if not item.title: raise ValueError("Enter a reel title.")
            video = save_video(request.files.get("video"), "reels")
            if video: item.video_url = video
            thumb = request.files.get("thumbnail")
            if thumb and thumb.filename: item.thumbnail_url = save_image(thumb, "reels-thumbs")[0]
            pid = request.form.get("linked_product_id", "")
            item.linked_product_id = int(pid) if pid.isdigit() else None
            item.sort_order = int(request.form.get("sort_order") or 0)
            item.is_active = request.form.get("is_active") == "1"
            if not item.video_url: raise ValueError("Upload a video file.")
            db.session.add(item); db.session.commit()
            flash("Reel saved.", "success")
            return redirect(url_for("admin.reels"))
        except (ValueError, UploadError) as exc:
            db.session.rollback(); flash(str(exc), "error")
    return render_template("admin/content_form.html", title="Reel", kind="reels", item=item, products=_products())

@bp.post("/reels/<int:item_id>/delete")
def reel_delete(item_id):
    item = db.session.get(Reel, item_id)
    if item:
        delete_files(item.video_url, item.thumbnail_url); db.session.delete(item); db.session.commit()
        flash("Reel deleted.", "success")
    return redirect(url_for("admin.reels"))

@bp.post("/reels/reorder")
def reels_reorder():
    ids = [int(x) for x in request.form.getlist("ids") if x.isdigit()]
    for pos, ident in enumerate(ids):
        item = db.session.get(Reel, ident)
        if item: item.sort_order = pos
    db.session.commit(); flash("Reel order updated.", "success")
    return redirect(url_for("admin.reels"))

@bp.post("/reels/settings")
def reels_settings():
    from ..models import SiteSetting
    setting = db.session.get(SiteSetting, "home_reels") or SiteSetting(key="home_reels", value={})
    setting.value = {"enabled": request.form.get("enabled") == "1",
                     "max_count": max(1, min(20, int(request.form.get("max_count") or 8))),
                     "selected_ids": [int(x) for x in request.form.getlist("selected_ids") if x.isdigit()]}
    db.session.add(setting); db.session.commit()
    flash("Home reels settings saved.", "success")
    return redirect(url_for("admin.reels"))

@bp.get("/recipes")
def recipes():
    return render_template("admin/content_list.html", title="Recipes", kind="recipes",
        items=db.session.scalars(select(RecipeVideo).order_by(RecipeVideo.created_at.desc())).all())

@bp.route("/recipes/new", methods=["GET", "POST"])
@bp.route("/recipes/<int:item_id>/edit", methods=["GET", "POST"])
def recipe_form(item_id=None):
    item = db.session.get(RecipeVideo, item_id) if item_id else RecipeVideo(ingredients=[], linked_product_ids=[])
    if item_id and item is None: abort(404)
    if request.method == "POST":
        try:
            title = request.form.get("title", "").strip()
            if not title: raise ValueError("Enter a recipe title.")
            item.title = title[:180]; item.slug = _slug(title)
            collision = db.session.scalar(select(RecipeVideo).where(RecipeVideo.slug == item.slug, RecipeVideo.id != (item.id or 0)))
            if collision: item.slug = f"{item.slug}-{uuid.uuid4().hex[:6]}"
            item.description = request.form.get("description", "").strip()
            item.category = request.form.get("category", "").strip()[:100]
            item.ingredients = [x.strip() for x in request.form.get("ingredients", "").splitlines() if x.strip()]
            item.linked_product_ids = [int(x) for x in request.form.getlist("product_ids") if x.isdigit()]
            item.youtube_url = request.form.get("youtube_url", "").strip() or None
            video = save_video(request.files.get("video"), "recipes")
            if video: item.video_url = video
            thumb = request.files.get("thumbnail")
            if thumb and thumb.filename: item.thumbnail_url = save_image(thumb, "recipe-thumbs")[0]
            if item.youtube_url and not re.match(r"^https://(www\.)?(youtube\.com|youtu\.be)/", item.youtube_url):
                raise ValueError("Enter a valid YouTube URL.")
            if not item.video_url and not item.youtube_url: raise ValueError("Upload a video or enter a YouTube URL.")
            item.is_published = request.form.get("is_published") == "1"
            item.published_at = datetime.now(timezone.utc) if item.is_published else None
            db.session.add(item); db.session.commit()
            flash("Recipe saved.", "success"); return redirect(url_for("admin.recipes"))
        except (ValueError, UploadError) as exc:
            db.session.rollback(); flash(str(exc), "error")
    return render_template("admin/content_form.html", title="Recipe", kind="recipes", item=item, products=_products())

@bp.post("/recipes/<int:item_id>/delete")
def recipe_delete(item_id):
    item = db.session.get(RecipeVideo, item_id)
    if item:
        delete_files(item.video_url, item.thumbnail_url); db.session.delete(item); db.session.commit()
        flash("Recipe deleted.", "success")
    return redirect(url_for("admin.recipes"))
