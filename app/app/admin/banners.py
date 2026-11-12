import re

from flask import abort, flash, jsonify, redirect, render_template, request, url_for
from sqlalchemy import func, select

from ..extensions import db
from ..models import Category, Coupon, HeaderBanner, Product, SiteSetting
from ..models import base as _base
from ..services.header_banners import bust_cache, get_settings, status_of
from ..uploads import UploadError, copy_file, delete_files, save_image
from . import bp
from .helpers import checked, clean, local_input, log, parse_local_dt, to_int

COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")
MAX_BANNERS_TOTAL = 50

# One-click starting points. The admin still edits the text, colours and dates.
TEMPLATES = {
    "festival": dict(title="Festival Sale", subtitle="Special festival offers on sweets and snacks", badge_text="FESTIVAL", button_text="Shop festival offers",
                     bg_color="#7a1f3d", link_type="category", countdown_enabled=True),
    "today": dict(title="Today's Special", subtitle="Fresh picks chosen for today", badge_text="TODAY", button_text="See today's special",
                  bg_color="#1b5e3b", link_type="url"),
    "flash": dict(title="Flash Sale", subtitle="Ends soon", badge_text="FLASH SALE", button_text="Grab the deal",
                  bg_color="#b4234f", link_type="url", countdown_enabled=True),
    "coupon": dict(title="Extra savings with a coupon", subtitle="Use the code at checkout", badge_text="COUPON", button_text="Get the offer",
                   bg_color="#0f3d27", link_type="coupon"),
}


def _snap(b: HeaderBanner) -> dict:
    return {"title": b.title, "link_type": b.link_type, "link_target": b.link_target, "is_active": b.is_active,
            "start_at": b.start_at.isoformat() if b.start_at else None, "end_at": b.end_at.isoformat() if b.end_at else None,
            "countdown": b.countdown_enabled, "sort_order": b.sort_order}


def _all():
    return db.session.scalars(select(HeaderBanner).order_by(HeaderBanner.sort_order, HeaderBanner.id)).all()


@bp.route("/header-banners")
def banners():
    now = _base.utcnow()
    rows = [(b, status_of(b, now)) for b in _all()]
    return render_template("admin/banners.html", rows=rows, settings=get_settings(), templates=TEMPLATES)


# ------------------------------------------------------------------ form
def _read_target(link_type: str, errors: dict) -> str | None:
    f = request.form
    if link_type == "category":
        slug = f.get("target_category", "")
        ok = db.session.scalar(select(Category.id).where(Category.slug == slug, Category.is_deleted.is_(False)))
        if not ok:
            errors["link_target"] = "Choose a category."
        return slug
    if link_type == "product":
        slug = f.get("target_product", "")
        ok = db.session.scalar(select(Product.id).where(Product.slug == slug, Product.is_deleted.is_(False)))
        if not ok:
            errors["link_target"] = "Choose a product."
        return slug
    if link_type == "coupon":
        code = f.get("target_coupon", "").upper()
        if not db.session.scalar(select(Coupon.id).where(func.upper(Coupon.code) == code)):
            errors["link_target"] = "Choose a coupon."
        return code
    url = clean(f.get("target_url"), 500)
    # only pages on this site ("/shop") or secure links. Blocks javascript:, data:, //evil and plain http.
    if not re.fullmatch(r"(/(?!/)[^\s\\]*|https://[^\s\\]+)", url):
        errors["link_target"] = "Enter a page on this site starting with / (for example /shop) or a full https:// link."
    return url


def _parse(banner: HeaderBanner | None):
    f = request.form
    errors: dict[str, str] = {}
    title = clean(f.get("title"), 150)
    if len(title) < 2:
        errors["title"] = "Enter a headline (at least 2 characters)."
    link_type = f.get("link_type", "url")
    if link_type not in ("category", "product", "coupon", "url"):
        errors["link_type"] = "Choose where the banner links to."
        link_type = "url"
    target = _read_target(link_type, errors)
    colors = {}
    for key, default in (("bg_color", "#1b5e3b"), ("text_color", "#ffffff")):
        val = f.get(key, default)
        if not COLOR.match(val):
            errors[key] = "Choose a colour."
        colors[key] = val
    start = parse_local_dt(f.get("start_at"), "start_at", errors)
    end = parse_local_dt(f.get("end_at"), "end_at", errors)
    if start and end and end <= start:
        errors["end_at"] = "The end must be after the start."
    countdown = checked("countdown_enabled")
    if countdown and not end and "end_at" not in errors:
        errors["end_at"] = "A countdown needs an end date and time."
    return dict(title=title, subtitle=clean(f.get("subtitle"), 250) or None, badge_text=clean(f.get("badge_text"), 40) or None,
                button_text=clean(f.get("button_text"), 40) or None, link_type=link_type, link_target=target, start_at=start,
                end_at=end, countdown_enabled=countdown, is_active=checked("is_active"), **colors), errors


def _images(banner: HeaderBanner, errors: dict) -> tuple[list[str], list[str]]:
    """Saves new desktop/mobile images. Returns (new urls, replaced urls): the new ones are removed if the save fails,
    the replaced ones are removed once it succeeds."""
    saved: list[str] = []
    old: list[str] = []
    for field, attr, max_side, label in (("desktop_image", "desktop_image", 1920, "Desktop image"), ("mobile_image", "mobile_image", 900, "Mobile image")):
        upload = request.files.get(field)
        if upload and upload.filename:
            try:
                url, _ = save_image(upload, "banners", max_side=max_side, thumb_side=None)
            except UploadError as exc:
                errors[field] = f"{label}: {exc}"
                delete_files(*saved)
                return [], []
            saved.append(url)
            old.append(getattr(banner, attr))
            setattr(banner, attr, url)
        elif checked(f"remove_{field}") and getattr(banner, attr):
            old.append(getattr(banner, attr))
            setattr(banner, attr, None)
    return saved, old


def _form(banner: HeaderBanner | None, prefill: dict | None = None):
    errors: dict[str, str] = {}
    status = 200
    if request.method == "POST":
        data, errors = _parse(banner)
        if not errors:
            is_new = banner is None
            if is_new:
                if db.session.scalar(select(func.count(HeaderBanner.id))) >= MAX_BANNERS_TOTAL:
                    flash(f"You already have {MAX_BANNERS_TOTAL} banners. Delete old ones first.", "error")
                    return redirect(url_for("admin.banners"))
                nxt = (db.session.scalar(select(func.max(HeaderBanner.sort_order))) or 0) + 1
                banner = HeaderBanner(title=data["title"], sort_order=nxt)
                db.session.add(banner)
            before = None if is_new else _snap(banner)
            for k, v in data.items():
                setattr(banner, k, v)
            saved, replaced = _images(banner, errors)
            if not errors:
                db.session.flush()
                log("header_banner.create" if is_new else "header_banner.update", "header_banner", banner.id, before, _snap(banner))
                db.session.commit()
                delete_files(*[u for u in replaced if u])
                bust_cache()
                flash(f"Banner “{banner.title}” saved.", "success")
                return redirect(url_for("admin.banners"))
            db.session.rollback()
            delete_files(*saved)
            if is_new:
                banner = None
        status = 422
        f = {k: request.form.get(k, "") for k in ("title", "subtitle", "badge_text", "button_text", "bg_color", "text_color", "link_type",
                                                  "target_category", "target_product", "target_coupon", "target_url", "start_at", "end_at")}
        f.update(countdown_enabled=checked("countdown_enabled"), is_active=checked("is_active"))
    else:
        src = prefill or {}
        if banner is not None:
            t = banner.link_target or ""
            f = dict(title=banner.title, subtitle=banner.subtitle or "", badge_text=banner.badge_text or "", button_text=banner.button_text or "",
                     bg_color=banner.bg_color, text_color=banner.text_color, link_type=banner.link_type,
                     target_category=t if banner.link_type == "category" else "", target_product=t if banner.link_type == "product" else "",
                     target_coupon=t if banner.link_type == "coupon" else "", target_url=t if banner.link_type == "url" else "",
                     start_at=local_input(banner.start_at), end_at=local_input(banner.end_at),
                     countdown_enabled=banner.countdown_enabled, is_active=banner.is_active)
        else:
            f = dict(title=src.get("title", ""), subtitle=src.get("subtitle", ""), badge_text=src.get("badge_text", ""),
                     button_text=src.get("button_text", ""), bg_color=src.get("bg_color", "#1b5e3b"), text_color="#ffffff",
                     link_type=src.get("link_type", "url"), target_category="", target_product="", target_coupon="", target_url="/shop",
                     start_at="", end_at="", countdown_enabled=src.get("countdown_enabled", False), is_active=True)
    if banner is not None:
        banner = db.session.get(HeaderBanner, banner.id)
    return render_template(
        "admin/banner_form.html", banner=banner, f=f, errors=errors,
        categories=db.session.scalars(select(Category).where(Category.is_deleted.is_(False)).order_by(Category.name)).all(),
        products=db.session.scalars(select(Product).where(Product.is_deleted.is_(False)).order_by(Product.name).limit(500)).all(),
        coupons=db.session.scalars(select(Coupon).order_by(Coupon.code)).all()), status



@bp.route("/header-banners/new", methods=["GET", "POST"])
def banner_new():
    return _form(None, TEMPLATES.get(request.args.get("template", "")))


@bp.route("/header-banners/<int:banner_id>/edit", methods=["GET", "POST"])
def banner_edit(banner_id):
    return _form(db.session.get(HeaderBanner, banner_id) or abort(404))


# ------------------------------------------------------------------ list actions
def _get(banner_id: int) -> HeaderBanner:
    return db.session.get(HeaderBanner, banner_id) or abort(404)


@bp.post("/header-banners/<int:banner_id>/toggle")
def banner_toggle(banner_id):
    b = _get(banner_id)
    b.is_active = not b.is_active
    log("header_banner.toggle", "header_banner", b.id, after={"is_active": b.is_active})
    db.session.commit()
    bust_cache()
    flash(f"“{b.title}” is now {'on' if b.is_active else 'off'}.", "success")
    return redirect(url_for("admin.banners"))


@bp.post("/header-banners/<int:banner_id>/duplicate")
def banner_duplicate(banner_id):
    src = _get(banner_id)
    nxt = (db.session.scalar(select(func.max(HeaderBanner.sort_order))) or 0) + 1
    new = HeaderBanner(
        title=f"{src.title} (Copy)"[:150], subtitle=src.subtitle, badge_text=src.badge_text, bg_color=src.bg_color, text_color=src.text_color,
        button_text=src.button_text, link_type=src.link_type, link_target=src.link_target, start_at=src.start_at, end_at=src.end_at,
        countdown_enabled=src.countdown_enabled, sort_order=nxt, is_active=False,
        desktop_image=copy_file(src.desktop_image), mobile_image=copy_file(src.mobile_image))
    db.session.add(new)
    db.session.flush()
    log("header_banner.duplicate", "header_banner", new.id, before={"source_id": src.id})
    db.session.commit()
    flash("Copy created and switched off. Edit it, then turn it on.", "success")
    return redirect(url_for("admin.banner_edit", banner_id=new.id))


@bp.post("/header-banners/<int:banner_id>/delete")
def banner_delete(banner_id):
    b = _get(banner_id)
    files = [b.desktop_image, b.mobile_image]
    log("header_banner.delete", "header_banner", b.id, before=_snap(b))
    db.session.delete(b)
    db.session.commit()
    delete_files(*files)
    bust_cache()
    flash("Banner deleted.", "success")
    return redirect(url_for("admin.banners"))


@bp.post("/header-banners/<int:banner_id>/move")
def banner_move(banner_id):
    b = _get(banner_id)
    direction = request.form.get("direction")
    if direction not in ("up", "down"):
        abort(400)
    rows = _all()
    for i, r in enumerate(rows):
        r.sort_order = i
    i = rows.index(b)
    j = i - 1 if direction == "up" else i + 1
    if 0 <= j < len(rows):
        rows[i].sort_order, rows[j].sort_order = rows[j].sort_order, rows[i].sort_order
        log("header_banner.reorder", "header_banner", b.id, after={"direction": direction})
    db.session.commit()
    bust_cache()
    return redirect(url_for("admin.banners"))


@bp.post("/header-banners/reorder")
def banner_reorder():
    """Drag-and-drop: receives the full list of banner ids in their new order."""
    body = request.get_json(silent=True) or {}
    ids = body.get("ids")
    existing = {b.id: b for b in _all()}
    if not isinstance(ids, list) or not all(isinstance(i, int) and not isinstance(i, bool) for i in ids) \
            or len(set(ids)) != len(ids) or set(ids) != set(existing):
        return jsonify(error="The list is out of date. Reload the page."), 400
    for pos, i in enumerate(ids):
        existing[i].sort_order = pos
    log("header_banner.reorder", "header_banner", None, after={"ids": ids})
    db.session.commit()
    bust_cache()
    return jsonify(ok=True)


@bp.post("/header-banners/settings")
def banner_settings():
    f = request.form
    errors: dict = {}
    seconds = to_int(f.get("interval_seconds"), "interval", errors, min_=2, max_=30)
    maximum = to_int(f.get("max_banners"), "max", errors, min_=1, max_=10)
    transition = f.get("transition", "")
    if errors or transition not in ("slide", "fade"):
        flash("Interval must be 2 to 30 seconds, maximum 1 to 10 banners, and transition slide or fade. Nothing was saved.", "error")
        return redirect(url_for("admin.banners"))
    new = {"header_carousel_interval_ms": seconds * 1000, "header_carousel_autoplay": checked("autoplay"),
           "header_carousel_transition": transition, "header_carousel_max_banners": maximum}
    before = get_settings()
    for key, value in new.items():
        row = db.session.get(SiteSetting, key)
        if row is None:
            db.session.add(SiteSetting(key=key, value=value))
        else:
            row.value = value
    log("header_banner.settings", "site_settings", None, before, new)
    db.session.commit()
    bust_cache()
    flash("Carousel settings saved.", "success")
    return redirect(url_for("admin.banners"))
