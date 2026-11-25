from pathlib import Path
from flask import abort, flash, g, redirect, render_template, request, url_for
from sqlalchemy import select
from ..extensions import db
from ..models import Product, Reel, Order, OrderStatusHistory, Notification
from ..uploads import save_image, save_video, UploadError, delete_files
from . import bp

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
