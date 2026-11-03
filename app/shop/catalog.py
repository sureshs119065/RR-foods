import re
from decimal import Decimal
from datetime import timezone

from flask import abort, jsonify, make_response, render_template, request, url_for
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from ..extensions import db, limiter
from flask import g
from ..models import Category, Coupon, DeliveryZone, Product, ProductQuestion, Review, ReviewVote
from ..services import reviews as review_svc
from ..models.base import utcnow
from ..services import header_banners, storefront
from ..services.storefront import Filters, active_variants, available_qty, in_stock_sql
from . import bp

HEX = re.compile(r"^#[0-9a-fA-F]{3,8}$")


@bp.get("/")
def home():
    from ..models import Reel, SiteSetting
    setting = db.session.get(SiteSetting, "home_reels")
    cfg = setting.value if setting and isinstance(setting.value, dict) else {}
    selected = cfg.get("selected_ids") or []
    stmt = select(Reel).where(Reel.is_active.is_(True)).order_by(Reel.sort_order, Reel.id)
    if selected: stmt = stmt.where(Reel.id.in_(selected))
    reels = db.session.scalars(stmt.limit(max(1, min(20, int(cfg.get("max_count", 8)))))).all()
    return render_template("shop/home.html", rows=storefront.home_rows(), carousel=header_banners.cached_payload(),
                           recent=storefront.recently_viewed(), now=utcnow(), home_reels=reels,
                           reels_enabled=cfg.get("enabled", True))


@bp.get("/banner-colors.css")
def banner_colors():
    """Per-banner colours as real CSS rules. The site's CSP forbids style="" attributes, and this keeps the first paint correct without JavaScript."""
    rules = []
    for b in header_banners.cached_payload()["banners"]:
        bg = b["bg_color"] if b.get("bg_color") and HEX.match(b["bg_color"]) else "#1b5e3b"
        fg = b["text_color"] if b.get("text_color") and HEX.match(b["text_color"]) else "#ffffff"
        rules.append(f".hb-{int(b['id'])}{{--hb-bg:{bg};--hb-fg:{fg}}}")
    resp = make_response("\n".join(rules) or "/* no banners */")
    resp.mimetype = "text/css"
    resp.headers["Cache-Control"] = "public, max-age=60"
    return resp


def _render_listing(*, slug=None, bestseller_only=False):
    f = Filters.from_args(request.args)
    if slug:
        f.category = slug
    page, cat, brands = storefront.listing(f, bestseller_only=bestseller_only)
    if f.category and cat is None:
        abort(404)

    # Keep all active filters in links and pagination; never carry a page number
    # into a newly submitted filter form.
    query_args = {k: v for k, v in request.args.lists()
                  if k not in ("page", "bestsellers", "category") and any(v)}
    if cat:
        if slug:
            query_args["slug"] = cat.slug
        else:
            query_args["category"] = cat.slug

    if bestseller_only:
        title = "Our Bestsellers"
        crumbs = [("Home", "/"), ("Bestsellers", None)]
        endpoint = "shop.bestsellers"
        canonical = url_for("shop.bestsellers", _external=True)
    elif cat:
        title = cat.name
        crumbs = storefront.breadcrumb_for(cat)
        endpoint = "shop.category_listing"
        canonical = url_for("shop.category_listing", slug=cat.slug, _external=True)
    elif f.q:
        title = f"Search results for “{f.q}”"
        crumbs = [("Home", "/"), ("Search results", None)]
        endpoint = "shop.listing"
        canonical = url_for("shop.listing", _external=True)
    else:
        title = "Shop All Products"
        crumbs = [("Home", "/"), ("Shop All", None)]
        endpoint = "shop.listing"
        canonical = url_for("shop.listing", _external=True)

    clear_args = {"q": f.q} if f.q else {}
    clean = not (f.q or f.active_count() or request.args.get("sort"))
    subcats = (db.session.scalars(
        select(Category).where(Category.parent_id == cat.id, Category.is_deleted.is_(False),
                               Category.is_active.is_(True)).order_by(Category.sort_order, Category.name)
    ).all() if cat else [])
    return render_template(
        "shop/listing.html", f=f, page=page, cat=cat, brands=brands,
        sorts=storefront.SORTS, crumbs=crumbs, title=title, listing_endpoint=endpoint,
        listing_args=query_args, canonical=canonical, clear_args=clear_args,
        listing_url=(url_for(endpoint, slug=cat.slug) if cat and endpoint == "shop.category_listing"
                     else url_for(endpoint)),
        clear_url=(url_for(endpoint, slug=cat.slug, **clear_args) if cat and endpoint == "shop.category_listing"
                   else url_for(endpoint, category=cat.slug, **clear_args) if cat
                   else url_for(endpoint, **clear_args)),
        index_ok=clean and f.page == 1, subcats=subcats,
        bestseller_only=bestseller_only,
    )


@bp.get("/shop")
@limiter.limit("120 per minute")
def listing():
    return _render_listing()


@bp.get("/bestsellers")
@limiter.limit("120 per minute")
def bestsellers():
    return _render_listing(bestseller_only=True)


@bp.get("/category/<slug>")
@limiter.limit("120 per minute")
def category_listing(slug):
    return _render_listing(slug=slug)


@bp.get("/product/<slug>")
def product(slug):
    p = storefront.get_product(slug)
    if p is None:
        abort(404)
    storefront.remember_view(p.id)
    now = utcnow()
    offers = [o for o in p.offers if o.is_active and (not o.starts_at or o.starts_at <= now) and (not o.ends_at or o.ends_at > now)]
    coupons = db.session.scalars(select(Coupon).where(Coupon.is_active.is_(True), (Coupon.expires_at.is_(None)) | (Coupon.expires_at > now)).order_by(Coupon.id).limit(3)).all()
    reviews = db.session.scalars(select(Review).where(Review.product_id == p.id, Review.status == "approved", Review.is_deleted.is_(False))
                                 .options(joinedload(Review.user)).order_by(Review.helpful_count.desc(), Review.created_at.desc()).limit(10)).all()
    questions = db.session.scalars(select(ProductQuestion).where(ProductQuestion.product_id == p.id, ProductQuestion.is_deleted.is_(False), ProductQuestion.answer.is_not(None))
                                   .order_by(ProductQuestion.created_at.desc()).limit(10)).all()
    shopper = g.get("user") is not None and g.user.role == "user"
    can_review = bool(shopper and review_svc.purchase_for(g.user.id, p.id))
    my_review = db.session.scalar(select(Review).where(Review.user_id == g.user.id, Review.product_id == p.id, Review.is_deleted.is_(False))) if shopper else None
    voted = set(db.session.scalars(select(ReviewVote.review_id).where(ReviewVote.user_id == g.user.id, ReviewVote.review_id.in_([r.id for r in reviews] or [0])))) if shopper else set()
    cat = db.session.get(Category, p.category_id) if p.category_id else None
    crumbs = storefront.breadcrumb_for(cat)
    if cat:
        crumbs[-1] = (cat.name, f"/shop?category={cat.slug}")
    crumbs.append((p.name, None))
    variants = active_variants(p)
    together = storefront.bought_together(p)
    from ..models import Bundle
    bundles = db.session.scalars(select(Bundle).where(Bundle.is_active.is_(True))).all()
    product_bundles = [b for b in bundles if any(int(x.get("product_id", 0)) == p.id for x in (b.product_quantities or []))]
    return render_template("shop/product.html", p=p, variants=variants, stock=available_qty(p), offers=offers, coupons=coupons, reviews=reviews,
                           questions=questions, crumbs=crumbs, together=together, together_ids=[t.id for t in together if not active_variants(t)],
                           similar=storefront.you_may_like(p), shopper=shopper, can_review=can_review, my_review=my_review, voted=voted, recent=storefront.recently_viewed(exclude=p.id), now=now, product_bundles=product_bundles)


@bp.get("/offers")
def offers():
    now = utcnow()
    coupons = db.session.scalars(select(Coupon).where(Coupon.is_active.is_(True), (Coupon.expires_at.is_(None)) | (Coupon.expires_at > now)).order_by(Coupon.id)).all()
    from ..models import Bundle, Combo, Offer, SiteSetting
    active_offers = db.session.scalars(select(Offer).where(Offer.is_active.is_(True),
        (Offer.starts_at.is_(None)) | (Offer.starts_at <= now),
        (Offer.ends_at.is_(None)) | (Offer.ends_at > now)).order_by(Offer.name)).all()
    bundles = db.session.scalars(select(Bundle).where(Bundle.is_active.is_(True),
        (Bundle.starts_at.is_(None)) | (Bundle.starts_at <= now),
        (Bundle.ends_at.is_(None)) | (Bundle.ends_at > now)).order_by(Bundle.created_at.desc())).all()
    products = {p.id: p for p in db.session.scalars(select(Product).where(Product.is_deleted.is_(False))).all()}
    originals = {b.id: sum((Decimal(str(products[int(line.get("product_id", 0))].final_price)) * int(line.get("quantity", 1))
        for line in (b.product_quantities or []) if int(line.get("product_id", 0)) in products), Decimal("0")) for b in bundles}
    combos = db.session.scalars(select(Combo).where(Combo.is_active.is_(True), Combo.festival_tag == "diwali").order_by(Combo.created_at.desc())).all()
    combo_products = {p.id: p for p in db.session.scalars(select(Product).where(Product.is_deleted.is_(False))).all()}
    end_setting = db.session.get(SiteSetting, "diwali_end_at")
    diwali_end_at = end_setting.value if end_setting and isinstance(end_setting.value, str) else "2026-11-12T23:59:00+05:30"
    return render_template("shop/offers.html", coupons=coupons, highlight=(request.args.get("coupon") or "").upper()[:40],
        rows=storefront.home_rows(), active_offers=active_offers, bundles=bundles, products=products, originals=originals,
        diwali_combos=combos, combo_products=combo_products, diwali_end_at=diwali_end_at)


# ---------------------------------------------------------------- JSON helpers for the page scripts
@bp.get("/api/suggest")
@limiter.limit("90 per minute")
def api_suggest():
    resp = jsonify(storefront.suggest(request.args.get("q", "")))
    resp.headers["Cache-Control"] = "public, max-age=30"
    return resp


@bp.get("/api/pincode/<pin>")
@limiter.limit("60 per minute")
def api_pincode(pin):
    if not re.fullmatch(r"\d{6}", pin):
        return jsonify(ok=False, message="Enter a 6 digit pincode."), 422
    zone = db.session.get(DeliveryZone, pin)
    if zone is None or not zone.is_serviceable:
        return jsonify(ok=True, deliverable=False, message=f"Sorry, we do not deliver to {pin} yet.")
    days = zone.eta_days or 3
    fee = float(zone.delivery_fee or 0)
    return jsonify(ok=True, deliverable=True, eta_days=days, fee=fee,
                   message=f"Delivery to {pin} in about {days} day{'s' if days != 1 else ''}" + (" (free delivery)." if fee == 0 else f" (delivery ₹{fee:,.0f})."))


# ---------------------------------------------------------------- SEO
@bp.get("/robots.txt")
def robots():
    body = "User-agent: *\nDisallow: /admin\nDisallow: /owner\nDisallow: /account\nDisallow: /cart\nDisallow: /checkout\nDisallow: /api\nAllow: /\n" \
           f"Sitemap: {url_for('shop.sitemap', _external=True)}\n"
    resp = make_response(body)
    resp.mimetype = "text/plain"
    return resp


@bp.get("/sitemap.xml")
def sitemap():
    urls = [url_for("shop.home", _external=True), url_for("shop.listing", _external=True),
            url_for("shop.bestsellers", _external=True)]
    urls += [url_for("shop.category_listing", slug=s, _external=True) for s in db.session.scalars(select(Category.slug).where(Category.is_deleted.is_(False), Category.is_active.is_(True)))]
    for slug in db.session.scalars(select(Product.slug).where(storefront.LIVE).order_by(Product.id).limit(20000)):
        urls.append(url_for("shop.product", slug=slug, _external=True))
    from markupsafe import escape
    xml = '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' + "".join(f"<url><loc>{escape(u)}</loc></url>\n" for u in urls) + "</urlset>\n"
    resp = make_response(xml)
    resp.mimetype = "application/xml"
    return resp
