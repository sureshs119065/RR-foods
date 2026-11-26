import re
from decimal import Decimal
from datetime import timedelta, timezone

from flask import abort, current_app, jsonify, make_response, redirect, render_template, request, url_for
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from .. import ratelimits as limits
from .. import validation as v
from ..extensions import db, limiter
from flask import g
from ..models import Category, Coupon, DeliveryZone, Product, ProductQuestion, User
from ..services import reviews as review_svc
from ..models.base import utcnow
from ..services import header_banners, storefront
from ..services import stock_alerts
from ..services.cart import free_delivery_threshold
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
    # "What our customers say": approved reviews the admin flagged for the home page (max 6, newest first, cached with the other home fragments).
    # Answered product questions stay managed by the Shop Owner > Questions workflow.
    featured_questions = db.session.execute(
        select(ProductQuestion, Product.name, User.name)
        .join(Product, Product.id == ProductQuestion.product_id)
        .join(User, User.id == ProductQuestion.user_id)
        .where(ProductQuestion.answer.is_not(None), ProductQuestion.is_deleted.is_(False), Product.is_deleted.is_(False))
        .order_by(ProductQuestion.answered_at.desc(), ProductQuestion.created_at.desc()).limit(4)
    ).all()
    return render_template("shop/home.html", rows=storefront.home_rows(), carousel=header_banners.cached_payload(),
                           recent=storefront.recently_viewed(), now=utcnow(), home_reels=reels,
                           reels_enabled=cfg.get("enabled", True), home_reviews=review_svc.home_reviews(),
                           featured_questions=featured_questions)


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


def _money(d: Decimal) -> str:
    d = Decimal(d)
    return f"₹{d:,.0f}" if d == d.to_integral_value() else f"₹{d:,.2f}"


def filter_chips(f: Filters, endpoint: str, cat, query_args: dict) -> list[dict]:
    """One removable chip per active filter. Each chip's url is the current listing without that one filter
    (page number dropped), so removing works without JavaScript and the result is shareable."""
    args = {k: v for k, v in query_args.items() if k != "slug"}

    def without(*keys, brand=None, **extra):
        out = {}
        for k, vals in args.items():
            if k in keys:
                continue
            if k == "brand" and brand is not None:
                vals = [v for v in vals if v != brand]
                if not vals:
                    continue
            out[k] = vals
        out.update(extra)
        if endpoint == "shop.category_listing" and cat is not None:
            return url_for(endpoint, slug=cat.slug, **out)
        return url_for(endpoint, **out)

    chips = []
    if f.q:
        # "relevance" only exists while searching, so leave it out of the URL once the search is removed
        keep_sort = args.get("sort") and args["sort"] != ["relevance"]
        chips.append({"label": f"Search: {f.q}", "url": without("q", *(() if keep_sort else ("sort",)))})
    for b in f.brands:
        chips.append({"label": b, "url": without(brand=b)})
    if f.min_price is not None or f.max_price is not None:
        if f.min_price is not None and f.max_price is not None:
            label = f"{_money(f.min_price)} – {_money(f.max_price)}"
        elif f.min_price is not None:
            label = f"Over {_money(f.min_price)}"
        else:
            label = f"Under {_money(f.max_price)}"
        chips.append({"label": label, "url": without("min_price", "max_price")})
    if f.rating:
        chips.append({"label": f"{f.rating}★ & up", "url": without("rating")})
    if f.discount:
        chips.append({"label": f"{f.discount}% off or more", "url": without("discount")})
    if f.avail:
        chips.append({"label": "In stock", "url": without("avail")})
    for d in f.diets:
        chips.append({"label": storefront.DIETS[d][0], "url": without("diet", **({"diet": [x for x in f.diets if x != d]} if len(f.diets) > 1 else {}))})
    return chips


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

    counts = storefront.shop_counts()
    top = cat if cat is None or cat.parent_id is None else db.session.get(Category, cat.parent_id)  # a sub-category page lights up its parent chip
    active_chip = "bestsellers" if bestseller_only else (top.id if top else "all")
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
        filter_chips=filter_chips(f, endpoint, cat, query_args),
        bestseller_only=bestseller_only,
        shop_counts=counts, active_chip=active_chip, diet_opts=storefront.diet_options(),
        free_delivery_min=free_delivery_threshold() or None,   # the free_delivery_above setting; None = no offer, so no strip item
    )


@bp.get("/shop")
@limiter.limit("120 per minute")
def listing():
    # An empty search (no text, no other filter) must not take the customer anywhere: send them back to the page they were on.
    if "q" in request.args and not request.args.get("q", "").strip() and set(request.args) == {"q"}:
        from urllib.parse import urlsplit
        ref = urlsplit(request.referrer or "")
        same_site = ref.netloc == request.host and ref.path and ref.path != request.path
        return redirect(ref.path + (f"?{ref.query}" if ref.query else "") if same_site else url_for("shop.home"))
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
    from sqlalchemy.orm import joinedload
    from ..models import Review
    # Only reviews the shop approved are shown; the customer's feedback text is optional, the star rating is not.
    reviews = db.session.scalars(select(Review).options(joinedload(Review.user)).where(Review.product_id == p.id, Review.status == "approved", Review.is_deleted.is_(False))
                                 .order_by(Review.created_at.desc(), Review.id.desc()).limit(30)).all()
    shopper = g.get("user") is not None and g.user.role == "user"
    cat = db.session.get(Category, p.category_id) if p.category_id else None
    crumbs = storefront.breadcrumb_for(cat)
    if cat:
        crumbs[-1] = (cat.name, f"/shop?category={cat.slug}")
    crumbs.append((p.name, None))
    variants = active_variants(p)
    alert_on = bool(shopper and stock_alerts.has_alert(g.user.id, p.id))
    together = [item for item in storefront.bought_together(p) if not active_variants(item)]
    from ..models import Bundle
    bundles = db.session.scalars(select(Bundle).where(Bundle.is_active.is_(True))).all()
    product_bundles = [b for b in bundles if any(int(x.get("product_id", 0)) == p.id for x in (b.product_quantities or []))]
    from ..services.product_catalogue import catalogue_for_product
    catalogue_content = catalogue_for_product(p)
    return render_template("shop/product.html", p=p, variants=variants, stock=available_qty(p), offers=offers, coupons=coupons,
                           reviews=reviews, crumbs=crumbs, together=together, together_ids=[t.id for t in together if not active_variants(t)],
                           similar=storefront.you_may_like(p), shopper=shopper, alert_on=alert_on, now=now, product_bundles=product_bundles,
                           catalogue_content=catalogue_content)


COMBO_BUNDLE_SLUG = "rr-foods-traditional-grains-combo"


def _combo_lines(combo):
    """Resolve each catalogue combo item to its live product by exact SKU. Missing -> product None."""
    skus = [item["sku"].upper() for item in combo["items"]]
    found = {(pr.sku or "").upper(): pr for pr in db.session.scalars(select(Product).where(
        Product.sku.in_(skus), Product.is_active.is_(True), Product.is_deleted.is_(False))).all()}
    return [{"name": item["name"], "pack": item["pack"], "product": found.get(item["sku"].upper())}
            for item in combo["items"]]


def _combo_price(combo):
    digits = re.sub(r"[^0-9.]", "", combo["price"])
    return Decimal(digits or "0")


def ensure_catalogue_combo_bundle():
    """Make sure the catalogue combo exists as a Bundle so the admin can see and edit it (price, products, active, dates).
    Created once if missing and never overwritten afterwards. If some products cannot be matched it is created as
    Hidden with the products that were found, so the admin can complete it. Returns the Bundle or None."""
    from flask import current_app
    from ..models import Bundle
    from ..models import SiteSetting
    from ..services.product_catalogue import CATALOGUE_COMBO_OFFER
    bundle = db.session.scalar(select(Bundle).where(Bundle.slug == COMBO_BUNDLE_SLUG))
    if bundle is not None:
        return bundle
    flag = db.session.get(SiteSetting, "catalogue_combo_deleted")
    if flag is not None and flag.value:
        return None  # an admin deleted this bundle on purpose: never silently re-create it
    lines = _combo_lines(CATALOGUE_COMBO_OFFER)
    matched = [l for l in lines if l["product"] is not None]
    if not matched:
        current_app.logger.warning("Combo bundle not created: no combo products matched store products.")
        return None
    missing = [l["name"] for l in lines if l["product"] is None]
    if missing:
        current_app.logger.warning("Combo bundle created Hidden; unmatched products: %s", "; ".join(missing))
    bundle = Bundle(name=CATALOGUE_COMBO_OFFER["title"], slug=COMBO_BUNDLE_SLUG,
                    description=CATALOGUE_COMBO_OFFER["strapline"] + " " + CATALOGUE_COMBO_OFFER["description"],
                    product_quantities=[{"product_id": l["product"].id, "quantity": 1} for l in matched],
                    bundle_price=float(_combo_price(CATALOGUE_COMBO_OFFER)), is_active=not missing)
    db.session.add(bundle)
    db.session.commit()
    return bundle


def catalogue_combo_removed():
    """True when an admin deliberately deleted the catalogue combo bundle (so it is hidden, not re-created)."""
    from ..models import SiteSetting
    flag = db.session.get(SiteSetting, "catalogue_combo_deleted")
    return bool(flag is not None and flag.value)


def restore_catalogue_combo_bundle():
    """Admin action: clear the 'deleted' flag and re-create the catalogue combo bundle."""
    from ..models import SiteSetting
    flag = db.session.get(SiteSetting, "catalogue_combo_deleted")
    if flag is not None:
        flag.value = False
        db.session.commit()
    return ensure_catalogue_combo_bundle()


@bp.get("/offers")
def offers():
    """Everything here comes from the admin panel: coupons and bundles. Nothing is built into the code."""
    now = utcnow()
    coupons = db.session.scalars(select(Coupon).where(Coupon.is_active.is_(True), (Coupon.expires_at.is_(None)) | (Coupon.expires_at > now)).order_by(Coupon.id)).all()
    return render_template("shop/offers.html", coupons=coupons,
        highlight=(lambda c: c if v.COUPON_RE.fullmatch(c) else "")("".join(v.strip_controls(request.args.get("coupon")).upper().split())[:40]),
        bundle_cards=storefront.bundle_cards(), deal_products=storefront.deal_products())


# ---------------------------------------------------------------- JSON helpers for the page scripts
@bp.get("/api/suggest")
@limiter.limit("90 per minute")
def api_suggest():
    resp = jsonify(storefront.suggest(v.search_query(request.args.get("q"), 60)))
    resp.headers["Cache-Control"] = "public, max-age=30"
    return resp


@bp.get("/api/pincode/<pin>")
@limiter.limit(limits.limit("pincode"))
def api_pincode(pin):
    if not v.is_pincode(pin):
        return jsonify(ok=False, message="Enter a 6 digit pincode."), 422
    from ..services.delivery import zone_for, is_tamil_nadu_pincode
    zone = zone_for(pin)
    if zone is None:
        return jsonify(ok=True, deliverable=False, message=f"Sorry, we do not deliver to {pin} yet.")
    days = zone.eta_days or 3
    fee = float(zone.delivery_fee or 0)
    city = zone.city or ""
    state = zone.state or ("Tamil Nadu" if is_tamil_nadu_pincode(pin) else "")
    return jsonify(ok=True, deliverable=True, eta_days=days, fee=fee, city=city, state=state,
                   message=f"Delivery to {pin} in about {days} day{'s' if days != 1 else ''}" + (f" (delivery fee ₹{fee:,.0f})."))


# ---------------------------------------------------------------- SEO
@bp.get("/favicon.ico")
def favicon():
    return redirect(url_for("static", filename="img/rr-foods-icon-192.png"), 301)


@bp.get("/robots.txt")
def robots():
    body = "User-agent: *\nDisallow: /admin\nDisallow: /owner\nDisallow: /account\nDisallow: /cart\nDisallow: /checkout\nDisallow: /api\nAllow: /\n" \
           f"Sitemap: {url_for('shop.sitemap', _external=True)}\n"
    resp = make_response(body)
    resp.mimetype = "text/plain"
    return resp


@bp.get("/.well-known/security.txt")
def security_txt():
    """RFC 9116 contact file for people who find a vulnerability. Shown only when SECURITY_CONTACT is configured,
    so the site never publishes a made-up address. Expires is rolling (now + 180 days) unless SECURITY_TXT_EXPIRES pins it."""
    contact = (current_app.config.get("SECURITY_CONTACT") or "").strip()
    if not contact or any(c in contact for c in "\r\n "):
        abort(404)
    if "@" in contact and not contact.lower().startswith(("mailto:", "https://", "tel:")):
        contact = "mailto:" + contact
    if not contact.lower().startswith(("mailto:", "https://", "tel:")):
        abort(404)
    expires = (current_app.config.get("SECURITY_TXT_EXPIRES") or "").strip()
    if not expires:
        expires = (utcnow().astimezone(timezone.utc) + timedelta(days=180)).strftime("%Y-%m-%dT%H:%M:%SZ")
    canonical = current_app.config["SITE_URL"] + "/.well-known/security.txt"
    body = (f"Contact: {contact}\nExpires: {expires}\nPreferred-Languages: en, ta\nCanonical: {canonical}\n"
            "Policy: Please report privately and give us reasonable time to fix before sharing details. "
            "Do not access other customers' data or disrupt the shop.\n")
    resp = make_response(body)
    resp.mimetype = "text/plain"
    resp.charset = "utf-8"
    resp.headers["Cache-Control"] = "public, max-age=3600"
    return resp


@bp.get("/security.txt")
def security_txt_legacy():
    return redirect(url_for("shop.security_txt"), 301)


@bp.get("/sitemap.xml")
def sitemap():
    from markupsafe import escape
    entries = [(url_for(e, _external=True), None) for e in ("shop.home", "shop.listing", "shop.bestsellers", "shop.about", "shop.bundles", "shop.recipes")]
    entries += [(url_for("shop.category_listing", slug=s, _external=True), None) for s in db.session.scalars(select(Category.slug).where(Category.is_deleted.is_(False), Category.is_active.is_(True)))]
    for slug, changed in db.session.execute(select(Product.slug, Product.updated_at).where(storefront.LIVE).order_by(Product.id).limit(20000)):
        entries.append((url_for("shop.product", slug=slug, _external=True), changed))
    rows = "".join(f"<url><loc>{escape(u)}</loc>" + (f"<lastmod>{d:%Y-%m-%d}</lastmod>" if d else "") + "</url>\n" for u, d in entries)
    xml = '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' + rows + "</urlset>\n"
    resp = make_response(xml)
    resp.mimetype = "application/xml"
    return resp
