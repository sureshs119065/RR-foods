from datetime import datetime, timezone
from urllib.parse import quote_plus
from decimal import Decimal, ROUND_HALF_UP
from flask import abort, current_app, flash, g, redirect, render_template, request, url_for
from sqlalchemy import select
from ..extensions import db
from ..models import Bundle, CartItem, Product, RecipeVideo
from ..services.storefront import active_variants
from . import bp

@bp.get("/about")
def about():
    quality_stages = [
        {"number": 1, "title": "Sourcing", "pose": "sourcing", "prop": "wheat", "description": "We handpick millets, grains and nuts from trusted farmers.\nEvery ingredient is chosen with care, right from the source.", "stat_value": None, "stat_suffix": "", "stat_label": ""},
        {"number": 2, "title": "Cleaning and Sorting", "pose": "cleaning", "prop": "sieve", "description": "Stone, dust and visible impurities are carefully removed.\nOnly clean ingredients move to the next step.", "stat_value": None, "stat_suffix": "", "stat_label": ""},
        {"number": 3, "title": "Traditional Processing", "pose": "processing", "prop": "grinder", "description": "Ingredients are stone-ground or slow-roasted, as suited to the product.\nOur recipes are made with 0 preservatives added.", "stat_value": 0, "stat_suffix": "", "stat_label": "preservatives added"},
        {"number": 4, "title": "Quality Testing", "pose": "testing", "prop": "magnifier", "description": "We check moisture, purity and freshness before packing.\nEach batch gets attention before it moves forward.", "stat_value": None, "stat_suffix": "", "stat_label": ""},
        {"number": 5, "title": "Hygienic Packaging", "pose": "packaging", "prop": "pack", "description": "Products are sealed in food-grade packaging.\nBatch identification supports careful handling and traceability.", "stat_value": None, "stat_suffix": "", "stat_label": ""},
        {"number": 6, "title": "Delivery", "pose": "delivery", "prop": "truck", "description": "Your order is prepared and sent on its way.\nWe want every pack to reach your doorstep fresh and safely.", "stat_value": 6, "stat_suffix": "/6", "stat_label": "quality journey stages"},
    ]
    return render_template("shop/about.html", quality_stages=quality_stages)

@bp.get("/recipes")
def recipes():
    q = request.args.get("q", "").strip()[:100]
    category = request.args.get("category", "").strip()[:100]
    stmt = select(RecipeVideo).where(RecipeVideo.is_published.is_(True))
    if q: stmt = stmt.where(RecipeVideo.title.ilike(f"%{q}%"))
    if category: stmt = stmt.where(RecipeVideo.category == category)
    items = db.session.scalars(stmt.order_by(RecipeVideo.published_at.desc(), RecipeVideo.id.desc())).all()
    categories = db.session.scalars(select(RecipeVideo.category).where(RecipeVideo.is_published.is_(True), RecipeVideo.category.is_not(None)).distinct()).all()
    return render_template("shop/recipes.html", items=items, categories=categories, q=q, category=category)

@bp.get("/recipes/<slug>")
def recipe_detail(slug):
    item = db.session.scalar(select(RecipeVideo).where(RecipeVideo.slug == slug, RecipeVideo.is_published.is_(True)))
    if not item: abort(404)
    products = [db.session.get(Product, int(pid)) for pid in (item.linked_product_ids or [])]
    products = [p for p in products if p and p.is_active and not p.is_deleted]
    embed_url = None
    if item.youtube_url:
        from urllib.parse import urlparse, parse_qs
        parsed = urlparse(item.youtube_url)
        video_id = (parsed.path.strip("/").split("/")[-1] if parsed.netloc.endswith("youtu.be")
                    else parse_qs(parsed.query).get("v", [""])[0])
        if video_id and all(ch.isalnum() or ch in "_-" for ch in video_id):
            embed_url = f"https://www.youtube-nocookie.com/embed/{video_id}"
    return render_template("shop/recipe_detail.html", item=item, products=products, embed_url=embed_url)

@bp.get("/bundles")
def bundles():
    now = datetime.now(timezone.utc)
    items = db.session.scalars(select(Bundle).where(Bundle.is_active.is_(True),
        (Bundle.starts_at.is_(None)) | (Bundle.starts_at <= now),
        (Bundle.ends_at.is_(None)) | (Bundle.ends_at > now)).order_by(Bundle.created_at.desc())).all()
    products = {p.id: p for p in db.session.scalars(select(Product).where(Product.is_deleted.is_(False))).all()}
    originals = {}
    bundle_prices = {}
    for bundle in items:
        originals[bundle.id] = sum((Decimal(str(products[int(line.get("product_id", 0))].final_price)) * int(line.get("quantity", 1))
            for line in (bundle.product_quantities or []) if int(line.get("product_id", 0)) in products), Decimal("0"))
        # Normalize database numeric values before template comparisons/subtraction.
        bundle_prices[bundle.id] = Decimal(str(bundle.bundle_price)).quantize(Decimal("0.01"))
    return render_template("shop/bundles.html", items=items, products=products, originals=originals, bundle_prices=bundle_prices)

@bp.post("/bundles/<int:bundle_id>/add")
def add_bundle(bundle_id):
    if not g.get("user") or g.user.role != "user":
        return redirect(url_for("auth.login", next=url_for("shop.bundles")))
    now = datetime.now(timezone.utc)
    bundle = db.session.get(Bundle, bundle_id)
    if not bundle or not bundle.is_active or (bundle.starts_at and bundle.starts_at > now) or (bundle.ends_at and bundle.ends_at <= now):
        abort(404)
    lines = []
    for entry in bundle.product_quantities or []:
        product = db.session.get(Product, int(entry.get("product_id", 0)))
        qty = int(entry.get("quantity", 1))
        if not product or not product.is_active or product.is_deleted or active_variants(product) or qty < 1 or product.stock_qty < qty:
            flash("A bundle product is unavailable or has insufficient stock.", "error")
            return redirect(url_for("shop.bundles"))
        lines.append((product, qty))
    regular_total = sum((Decimal(product.final_price) * qty for product, qty in lines), Decimal("0"))
    bundle_total = Decimal(str(bundle.bundle_price)).quantize(Decimal("0.01"))
    if not lines or regular_total <= 0 or bundle_total <= 0 or bundle_total > regular_total:
        flash("This bundle price is not configured correctly. Please contact the shop.", "error")
        return redirect(url_for("shop.bundles"))
    allocated = Decimal("0")
    for index, (product, qty) in enumerate(lines):
        line_total = (bundle_total - allocated) if index == len(lines)-1 else (bundle_total * (Decimal(product.final_price) * qty / regular_total)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        allocated += line_total
        unit_price = (line_total / qty).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        item = db.session.scalar(select(CartItem).where(CartItem.user_id == g.user.id, CartItem.product_id == product.id,
            CartItem.variant_id.is_(None), CartItem.bundle_id == bundle.id, CartItem.saved_for_later.is_(False)))
        if item:
            if item.quantity + qty > product.stock_qty:
                db.session.rollback()
                flash(f"Not enough stock to add another {bundle.name}.", "error")
                return redirect(url_for("shop.bundles"))
            item.quantity += qty
            item.line_total_override = (item.unit_price_override or unit_price) * item.quantity
        else:
            db.session.add(CartItem(user_id=g.user.id, product_id=product.id, variant_id=None, bundle_id=bundle.id,
                unit_price_override=unit_price, line_total_override=line_total, quantity=qty))
    db.session.commit()
    flash(f"Added {bundle.name} to your cart at its bundle price.", "success")
    return redirect(url_for("shop.cart"))

@bp.post("/recipes/<int:recipe_id>/add-ingredients")
def add_recipe_ingredients(recipe_id):
    if not g.get("user") or g.user.role != "user":
        return redirect(url_for("auth.login", next=url_for("shop.recipes")))
    recipe = db.session.get(RecipeVideo, recipe_id)
    if not recipe or not recipe.is_published: abort(404)
    from .cart import _add_one
    added = 0
    for pid in recipe.linked_product_ids or []:
        product = db.session.get(Product, int(pid))
        if product and product.is_active and not product.is_deleted:
            _, ok = _add_one(g.user, product.id, None, 1)
            added += int(ok)
    flash(f"Added {added} linked ingredient product(s) to your cart." if added else "No linked products could be added.", "success" if added else "error")
    return redirect(url_for("shop.cart"))

@bp.route("/help", methods=["GET", "POST"])
def help_page():
    """Public contact page with a validated WhatsApp/email message handoff."""
    import re

    whatsapp_raw = str(current_app.config.get("WHATSAPP_NUMBER") or "")
    whatsapp_number = re.sub(r"\D", "", whatsapp_raw)
    support_email = (current_app.config.get("SUPPORT_EMAIL") or "").strip()

    if request.method == "POST":
        name = " ".join((request.form.get("name") or "").split())[:100]
        email = " ".join((request.form.get("email") or "").split())[:160]
        phone = " ".join((request.form.get("phone") or "").split())[:30]
        subject = " ".join((request.form.get("subject") or "").split())[:140]
        message = (request.form.get("message") or "").strip()[:4000]

        if len(name) < 2 or not subject or len(message) < 10:
            flash("Please enter your name, a subject and a message of at least 10 characters.", "error")
        elif not whatsapp_number and not support_email:
            flash("Contact messaging is not configured yet. Please contact the store team through your account.", "error")
        else:
            body = (
                "RR FOODS website enquiry\n"
                f"Name: {name}\nEmail: {email or 'Not provided'}\n"
                f"Phone: {phone or 'Not provided'}\nSubject: {subject}\n\n{message}"
            )
            if whatsapp_number:
                return redirect(f"https://wa.me/{whatsapp_number}?text={quote_plus(body)}")
            return redirect(f"mailto:{support_email}?subject={quote_plus('RR FOODS enquiry: ' + subject)}&body={quote_plus(body)}")

    return render_template("shop/help.html", whatsapp_number=whatsapp_number, support_email=support_email)
