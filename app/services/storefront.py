"""Everything the shop pages read: listing/search/filters, suggestions, recently viewed, related and bought-together."""
import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from flask import session
from sqlalchemy import and_, case, exists, func, or_, select
from sqlalchemy.orm import aliased, selectinload

from ..extensions import db
from ..models import Category, Order, OrderItem, Product, ProductVariant, SiteSetting

PER_PAGE = 12
SORTS = {
    "relevance": "Relevance", "popular": "Popularity", "newest": "Newest first", "price-asc": "Price: low to high",
    "price-desc": "Price: high to low", "rating": "Customer rating", "discount": "Biggest discount",
}
LIVE = and_(Product.is_deleted.is_(False), Product.is_active.is_(True))


# ------------------------------------------------------------------ settings
def setting(key: str, default=None):
    row = db.session.get(SiteSetting, key)
    return default if row is None or row.value is None else row.value


def money_setting(key: str, default: str = "0") -> Decimal:
    try:
        return Decimal(str(setting(key, default))).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        return Decimal(default)


# ------------------------------------------------------------------ stock helpers
def active_variants(p: Product) -> list[ProductVariant]:
    return [v for v in p.variants if v.is_active and not v.is_deleted]


def available_qty(p: Product) -> int:
    """What a customer can buy: the variants' stock when the product has options, otherwise the product's own stock."""
    vs = active_variants(p)
    return sum(v.stock_qty for v in vs) if vs else p.stock_qty


def in_stock_sql():
    has_var = select(ProductVariant.id).where(ProductVariant.product_id == Product.id, ProductVariant.is_active.is_(True), ProductVariant.is_deleted.is_(False)).exists()
    var_stock = select(ProductVariant.id).where(ProductVariant.product_id == Product.id, ProductVariant.is_active.is_(True),
                                                ProductVariant.is_deleted.is_(False), ProductVariant.stock_qty > 0).exists()
    return case((has_var, var_stock), else_=Product.stock_qty > 0)


# ------------------------------------------------------------------ filters
@dataclass
class Filters:
    q: str = ""
    category: str = ""
    brands: list = field(default_factory=list)
    min_price: Decimal | None = None
    max_price: Decimal | None = None
    rating: int = 0
    discount: int = 0
    avail: bool = False
    sort: str = "relevance"
    page: int = 1

    @classmethod
    def from_args(cls, args) -> "Filters":
        def dec(name):
            try:
                v = Decimal((args.get(name) or "").strip())
                return v if v.is_finite() and 0 <= v <= 10_000_000 else None
            except InvalidOperation:
                return None

        def num(name, hi):
            raw = (args.get(name) or "").strip()
            return min(int(raw), hi) if raw.isdigit() else 0

        sort = args.get("sort", "")
        q = " ".join((args.get("q") or "").split())[:80]
        rating = num("rating", 4)
        rating = rating if rating in (2, 3, 4) else 0
        return cls(q=q, category=(args.get("category") or "").strip()[:150], brands=[b[:120] for b in args.getlist("brand")[:20] if b.strip()],
                   min_price=dec("min_price"), max_price=dec("max_price"), rating=rating, discount=num("discount", 90),
                   avail=args.get("avail") in ("1", "on", "true"), sort=sort if sort in SORTS else ("relevance" if q else "popular"),
                   page=max(1, num("page", 100000) or 1))

    def active_count(self) -> int:
        return sum([bool(self.brands), self.min_price is not None or self.max_price is not None, bool(self.rating), bool(self.discount), self.avail])


def category_ids(slug: str) -> tuple[Category | None, list[int]]:
    cat = db.session.scalar(select(Category).where(Category.slug == slug, Category.is_deleted.is_(False), Category.is_active.is_(True))) if slug else None
    if cat is None:
        return None, []
    kids = db.session.scalars(select(Category.id).where(Category.parent_id == cat.id, Category.is_deleted.is_(False), Category.is_active.is_(True))).all()
    return cat, [cat.id, *kids]


def _search_clause(q: str):
    term = q.lower()
    like = or_(func.lower(Product.name).contains(term, autoescape=True),
               func.lower(func.coalesce(Product.brand, "")).contains(term, autoescape=True),
               func.lower(func.coalesce(Product.short_description, "")).contains(term, autoescape=True),
               func.lower(Product.sku) == term)
    if len(term) >= 4:  # typo tolerance: trigram similarity (pg_trgm), only for words long enough to be meaningful
        like = or_(like, func.similarity(Product.name, q) > 0.3, func.word_similarity(q, Product.name) > 0.5)
    return like


def conditions(f: Filters, cat_ids: list[int], skip: tuple = ()) -> list:
    c = [LIVE]
    if f.q:
        c.append(_search_clause(f.q))
    if f.category:
        c.append(or_(Product.category_id.in_(cat_ids or [0]), Product.subcategory_id.in_(cat_ids or [0])))
    if f.brands and "brand" not in skip:
        c.append(Product.brand.in_(f.brands))
    valid_price_range = not (f.min_price is not None and f.max_price is not None and f.max_price < f.min_price)
    if valid_price_range and f.min_price is not None:
        c.append(Product.final_price >= f.min_price)
    if valid_price_range and f.max_price is not None:
        c.append(Product.final_price <= f.max_price)
    if f.rating:
        # Products without approved reviews are excluded from rated filters.
        c.append(and_(Product.review_count > 0, Product.avg_rating >= f.rating))
    if f.discount:
        c.append(and_(Product.mrp > 0, (Product.mrp - Product.final_price) * 100 >= f.discount * Product.mrp))
    if f.avail:
        c.append(in_stock_sql())
    return c


def listing(f: Filters, bestseller_only: bool = False):
    """Returns a paginated product listing and facets. Bestseller selection is admin-controlled."""

    cat, ids = category_ids(f.category)
    conds = conditions(f, ids)
    if bestseller_only:
        conds.append(Product.is_bestseller.is_(True))
    q = select(Product).where(*conds).options(selectinload(Product.images), selectinload(Product.variants))
    pct = case((Product.mrp > 0, (Product.mrp - Product.final_price) * 100 / Product.mrp), else_=0)
    if f.sort == "price-asc":
        order = [Product.final_price.asc()]
    elif f.sort == "price-desc":
        order = [Product.final_price.desc()]
    elif f.sort == "newest":
        order = [Product.created_at.desc()]
    elif f.sort == "rating":
        order = [Product.avg_rating.desc(), Product.review_count.desc()]
    elif f.sort == "discount":
        order = [pct.desc()]
    elif f.sort == "relevance" and f.q:
        score = func.greatest(func.similarity(Product.name, f.q), case((func.lower(Product.name).contains(f.q.lower(), autoescape=True), 0.9), else_=0.0))
        order = [score.desc(), Product.sales_count.desc()]
    else:
        order = [Product.sales_count.desc(), Product.is_bestseller.desc()]
    page = db.paginate(q.order_by(*order, Product.id), page=f.page, per_page=PER_PAGE, error_out=False)
    facet_conditions = conditions(f, ids, skip=("brand",))
    if bestseller_only:
        facet_conditions.append(Product.is_bestseller.is_(True))
    facet_q = (select(Product.brand, func.count(Product.id)).where(*facet_conditions, Product.brand.is_not(None))
               .group_by(Product.brand).order_by(func.count(Product.id).desc(), Product.brand).limit(30))
    brands = [(b, n) for b, n in db.session.execute(facet_q).all() if b]
    return page, cat, brands


def _popular() -> dict:
    """Shown when the search box is tapped and empty (like the big shopping sites): what people buy most, plus categories."""
    prods = db.session.scalars(select(Product).where(LIVE).order_by(Product.sales_count.desc(), Product.name).limit(6)).all()
    cats = db.session.scalars(select(Category).where(Category.is_deleted.is_(False), Category.is_active.is_(True))
                              .order_by(Category.sort_order, Category.name).limit(4)).all()
    return {"popular": True, "terms": [p.name for p in prods], "products": [], "bundles": [],
            "categories": [{"name": c.name, "url": f"/category/{c.slug}"} for c in cats]}


def suggest(q: str) -> dict:
    from datetime import datetime, timezone
    from ..models import Bundle
    q = " ".join(q.split())[:60]
    if len(q) < 2:
        return _popular()
    f = Filters(q=q)
    score = func.greatest(func.similarity(Product.name, q), case((func.lower(Product.name).startswith(q.lower(), autoescape=True), 1.0), else_=0.0))
    prods = db.session.scalars(select(Product).where(*conditions(f, [])).options(selectinload(Product.images))
                               .order_by(score.desc(), Product.sales_count.desc()).limit(6)).all()
    cats = db.session.scalars(select(Category).where(Category.is_deleted.is_(False), Category.is_active.is_(True),
                                                      func.lower(Category.name).contains(q.lower(), autoescape=True)).order_by(Category.name).limit(3)).all()
    now = datetime.now(timezone.utc)
    bundles = db.session.scalars(select(Bundle).where(
        Bundle.is_active.is_(True), func.lower(Bundle.name).contains(q.lower(), autoescape=True),
        (Bundle.starts_at.is_(None)) | (Bundle.starts_at <= now), (Bundle.ends_at.is_(None)) | (Bundle.ends_at > now)).limit(2)).all()
    return {
        "popular": False,
        "terms": [p.name for p in prods[:5]],
        "bundles": [{"name": b.name, "url": "/bundles", "price": f"{float(b.bundle_price):,.0f}"} for b in bundles],
        "products": [{"name": p.name, "url": f"/product/{p.slug}", "price": f"{p.final_price:,.2f}",
                      "image": (p.primary_image.thumb_url or p.primary_image.url) if p.primary_image else None} for p in prods],
        "categories": [{"name": c.name, "url": f"/category/{c.slug}"} for c in cats],
    }


# ------------------------------------------------------------------ product page helpers
def get_product(slug: str) -> Product | None:
    return db.session.scalar(select(Product).where(Product.slug == slug, LIVE).options(
        selectinload(Product.images), selectinload(Product.variants), selectinload(Product.offers), selectinload(Product.related)))


def remember_view(product_id: int) -> None:
    rv = [i for i in session.get("rv", []) if i != product_id]
    session["rv"] = ([product_id] + rv)[:12]


def recently_viewed(exclude: int | None = None, limit: int = 8) -> list[Product]:
    ids = [i for i in session.get("rv", []) if isinstance(i, int) and i != exclude][:limit]
    if not ids:
        return []
    rows = {p.id: p for p in db.session.scalars(select(Product).where(Product.id.in_(ids), LIVE).options(selectinload(Product.images), selectinload(Product.variants)))}
    return [rows[i] for i in ids if i in rows]


def you_may_like(p: Product, limit: int = 8) -> list[Product]:
    picked = [r for r in p.related if r.is_active and not r.is_deleted][:limit]
    if len(picked) < limit:
        have = {p.id, *[r.id for r in picked]}
        more = db.session.scalars(select(Product).where(LIVE, Product.category_id == p.category_id, Product.id.not_in(have))
                                  .options(selectinload(Product.images), selectinload(Product.variants))
                                  .order_by(Product.sales_count.desc(), Product.id).limit(limit - len(picked))).all()
        picked += list(more)
    return picked


def bought_together(p: Product, limit: int = 3) -> list[Product]:
    """Products that appear in the same (not rejected/cancelled) orders as this one, most often first."""
    a, b = aliased(OrderItem), aliased(OrderItem)
    rows = db.session.execute(
        select(b.product_id, func.count(func.distinct(b.order_id)).label("n"))
        .join(a, and_(a.order_id == b.order_id, a.product_id == p.id, b.product_id != p.id))
        .join(Order, Order.id == a.order_id).where(Order.status.not_in(("rejected", "cancelled")), b.product_id.is_not(None))
        .group_by(b.product_id).order_by(func.count(func.distinct(b.order_id)).desc()).limit(limit * 3)).all()
    ids = [r[0] for r in rows]
    if not ids:
        return []
    prods = {x.id: x for x in db.session.scalars(select(Product).where(Product.id.in_(ids), LIVE, in_stock_sql()).options(selectinload(Product.images), selectinload(Product.variants)))}
    return [prods[i] for i in ids if i in prods][:limit]


def home_rows() -> dict:
    opts = (selectinload(Product.images), selectinload(Product.variants))
    top = db.session.scalars(select(Category).where(Category.parent_id.is_(None), Category.is_deleted.is_(False), Category.is_active.is_(True)).order_by(Category.sort_order, Category.name).limit(12)).all()
    pct = case((Product.mrp > 0, (Product.mrp - Product.final_price) * 100 / Product.mrp), else_=0)
    deals = db.session.scalars(select(Product).where(LIVE, in_stock_sql(), Product.final_price < Product.mrp).options(*opts).order_by(pct.desc(), Product.id).limit(8)).all()
    best = db.session.scalars(select(Product).where(LIVE, in_stock_sql(), Product.is_bestseller.is_(True))
                              .options(*opts).order_by(Product.sales_count.desc(), Product.id).limit(8)).all()
    new = db.session.scalars(select(Product).where(LIVE, in_stock_sql()).options(*opts).order_by(Product.created_at.desc(), Product.id.desc()).limit(8)).all()
    counts = dict(db.session.execute(select(Product.category_id, func.count()).where(LIVE).group_by(Product.category_id)).all())
    top_deal = max((round((p.mrp - p.final_price) * 100 / p.mrp) for p in deals if p.mrp and p.mrp > p.final_price), default=0)
    return {"categories": top, "deals": deals, "best": best, "new": new, "counts": counts, "top_deal": int(top_deal)}


def breadcrumb_for(cat: Category | None) -> list[tuple[str, str | None]]:
    trail: list[tuple[str, str | None]] = [("Home", "/")]
    if cat is None:
        return trail
    if cat.parent_id:
        parent = db.session.get(Category, cat.parent_id)
        if parent:
            trail.append((parent.name, f"/category/{parent.slug}"))
    trail.append((cat.name, None))
    return trail
