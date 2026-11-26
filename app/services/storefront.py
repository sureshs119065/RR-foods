"""Everything the shop pages read: listing/search/filters, suggestions, recently viewed, related and bought-together."""
import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from flask import session
from sqlalchemy import Text, and_, case, cast, exists, func, or_, select
from sqlalchemy.orm import aliased, joinedload, selectinload

from ..extensions import db
from . import home_cache
from ..models import Bundle, Category, Order, OrderItem, Product, ProductVariant, SiteSetting

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


# ------------------------------------------------------------------ diet (read from the product tags the admin already edits)
DIETS = {
    "vegetarian": ("Vegetarian", ("vegetarian", "veg")),
    "vegan": ("Vegan", ("vegan",)),
    "gluten-free": ("Gluten-free", ("gluten-free", "gluten free", "glutenfree")),
}


def diet_clause(key: str):
    """True when one of the product's tags is this diet (tags are a JSON list; compared case-insensitively)."""
    tags = func.lower(cast(Product.tags, Text))
    return or_(*[tags.contains(f'"{t}"', autoescape=True) for t in DIETS[key][1]])


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
    diets: list = field(default_factory=list)
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
        from ..validation import search_query
        q = search_query(args.get("q"))
        rating = num("rating", 4)
        rating = rating if rating in (2, 3, 4) else 0
        return cls(q=q, category=(args.get("category") or "").strip()[:150], brands=[b[:120] for b in args.getlist("brand")[:20] if b.strip()],
                   min_price=dec("min_price"), max_price=dec("max_price"), rating=rating, discount=num("discount", 90),
                   avail=args.get("avail") in ("1", "on", "true"), diets=[d for d in dict.fromkeys(args.getlist("diet")) if d in DIETS],
                   sort=sort if sort in SORTS else ("relevance" if q else "popular"),
                   page=max(1, num("page", 100000) or 1))

    def active_count(self) -> int:
        return sum([bool(self.brands), self.min_price is not None or self.max_price is not None, bool(self.rating), bool(self.discount), self.avail, bool(self.diets)])


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
    for d in f.diets:  # several diets narrow the list (vegan AND gluten-free)
        c.append(diet_clause(d))
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
    from .recommendations import frequently_bought_together
    return frequently_bought_together(p, limit=limit)


def deal_products(limit: int = 12) -> list:
    """In-stock products that are priced below MRP, biggest discount first (Offers page)."""
    opts = (selectinload(Product.images), selectinload(Product.variants))
    pct = case((Product.mrp > 0, (Product.mrp - Product.final_price) * 100 / Product.mrp), else_=0)
    return db.session.scalars(select(Product).where(LIVE, in_stock_sql(), Product.final_price < Product.mrp)
                              .options(*opts).order_by(pct.desc(), Product.id).limit(limit)).all()


NAV_CATEGORY_LIMIT = 14  # the header menu shows up to this many; the home tiles use the first 8 of the same list
HOME_NEW_LIMIT = 6   # step 2.5: six New Arrivals cards, each rendered once


def _load_top_categories(sess) -> tuple:
    return tuple(sess.scalars(select(Category).where(Category.parent_id.is_(None), Category.is_deleted.is_(False), Category.is_active.is_(True))
                              .order_by(Category.sort_order, Category.name).limit(NAV_CATEGORY_LIMIT)).all())


def _load_category_counts(sess) -> dict:
    return dict(sess.execute(select(Product.category_id, func.count()).where(LIVE).group_by(Product.category_id)).all())


def _load_shop_counts(sess) -> dict:
    """Catalogue-wide counts for the listing's category chips: all, bestsellers, and one per top-level category.
    A top-level count includes its sub-categories, matching what the category page lists."""
    all_n = sess.scalar(select(func.count()).select_from(Product).where(LIVE)) or 0
    best_n = sess.scalar(select(func.count()).select_from(Product).where(LIVE, Product.is_bestseller.is_(True))) or 0
    cats = sess.execute(select(Category.id, Category.parent_id).where(Category.is_deleted.is_(False), Category.is_active.is_(True))).all()
    kids: dict[int, set] = {}
    for cid, parent in cats:
        if parent is not None:
            kids.setdefault(parent, set()).add(cid)
    rows = sess.execute(select(Product.category_id, Product.subcategory_id, func.count()).where(LIVE).group_by(Product.category_id, Product.subcategory_id)).all()
    per_cat = {}
    for cid, parent in cats:
        if parent is None:
            ids = {cid, *kids.get(cid, ())}
            per_cat[cid] = sum(n for c, sub, n in rows if c in ids or sub in ids)
    return {"all": all_n, "bestsellers": best_n, "cats": per_cat}


def shop_counts() -> dict:
    return home_cache.get("shop_counts", _load_shop_counts)


def _load_diet_counts(sess) -> list:
    cols = [func.sum(case((diet_clause(k), 1), else_=0)) for k in DIETS]
    row = sess.execute(select(*cols).where(LIVE)).one()
    return [(k, DIETS[k][0], int(n or 0)) for k, n in zip(DIETS, row) if n]


def diet_options() -> list:
    """[(key, label, product count)] for diets that at least one live product is tagged with; empty hides the filter."""
    return home_cache.get("diet_counts", _load_diet_counts)


def new_arrival_clause():
    """True when the product carries the 'New Arrival' tag (tags are a JSON list; compared case-insensitively)."""
    return func.lower(cast(Product.tags, Text)).contains('"new arrival"', autoescape=True)


def _load_new_arrivals(sess) -> tuple:
    # category is joined in the same query: cards print its name, and a detached product cannot lazy-load it later
    opts = (selectinload(Product.images), selectinload(Product.variants), joinedload(Product.category))
    return tuple(sess.scalars(select(Product).where(LIVE, in_stock_sql()).options(*opts)
                              .order_by(new_arrival_clause().desc(), Product.created_at.desc(), Product.id.desc()).limit(HOME_NEW_LIMIT)).all())


def top_categories() -> tuple:
    """Top-level categories for the header menu and the home tiles (cached per worker, see services/home_cache.py)."""
    return home_cache.get("categories", _load_top_categories)


def home_rows() -> dict:
    opts = (selectinload(Product.images), selectinload(Product.variants))
    top = top_categories()
    pct = case((Product.mrp > 0, (Product.mrp - Product.final_price) * 100 / Product.mrp), else_=0)
    deals = db.session.scalars(select(Product).where(LIVE, in_stock_sql(), Product.final_price < Product.mrp).options(*opts).order_by(pct.desc(), Product.id).limit(8)).all()
    best = db.session.scalars(select(Product).where(LIVE, in_stock_sql(), Product.is_bestseller.is_(True))
                              .options(*opts).order_by(Product.sales_count.desc(), Product.id).limit(8)).all()
    new = home_cache.get("new_arrivals", _load_new_arrivals)
    counts = home_cache.get("category_counts", _load_category_counts)
    top_deal = max((round((p.mrp - p.final_price) * 100 / p.mrp) for p in deals if p.mrp and p.mrp > p.final_price), default=0)
    offers = deals
    return {"categories": top, "deals": deals, "offers": offers,
            "bundles": bundle_cards(),
            "best": best, "new": new, "counts": counts, "top_deal": int(top_deal)}


def _aware(dt):
    from datetime import timezone
    return dt if dt is None or dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _bundle_title(name: str) -> str:
    """Bundle names often end with the price ('... | ₹999'); the price has its own spot on the card."""
    return re.sub(r"\s*[|\-–]\s*(?:Rs\.?|₹)\s*[\d,]+\s*$", "", name or "").strip()


def bundle_cards(*, include_upcoming: bool = True) -> list[dict]:
    """Admin-managed bundles shaped for the storefront cards (home 'Offers & Combo' and the Offers page).

    Live bundles come first; a bundle that starts within the next 7 days is included as 'upcoming' so the
    banner is not empty the day before a festival combo opens. Every bundle is managed in admin."""
    from datetime import datetime, timedelta, timezone
    from zoneinfo import ZoneInfo

    now = datetime.now(timezone.utc)
    ist = ZoneInfo("Asia/Kolkata")
    rows = db.session.scalars(select(Bundle).where(Bundle.is_active.is_(True))
                              .order_by(Bundle.created_at.desc())).all()
    ids = {int(l.get("product_id", 0)) for b in rows for l in (b.product_quantities or [])}
    products = {p.id: p for p in db.session.scalars(
        select(Product).where(Product.id.in_(ids), Product.is_deleted.is_(False))
        .options(selectinload(Product.images), selectinload(Product.variants))).all()} if ids else {}
    cards = []
    for b in rows:
        starts, ends = _aware(b.starts_at), _aware(b.ends_at)
        if ends and ends <= now:
            continue
        upcoming = bool(starts and starts > now)
        if upcoming and (not include_upcoming or starts - now > timedelta(days=7)):
            continue
        items, regular, ok, sold_out = [], Decimal("0"), True, None
        for line in (b.product_quantities or []):
            pr, qty = products.get(int(line.get("product_id", 0))), max(1, int(line.get("quantity", 1)))
            if pr is None:
                ok = False
                continue
            regular += Decimal(str(pr.final_price)) * qty
            if not pr.is_active or active_variants(pr) or available_qty(pr) < qty:
                ok = False
            if sold_out is None and pr.is_active and available_qty(pr) <= 0:
                sold_out = pr  # the combo shows "Out of stock" and a "Notify me" link to this product
            items.append({"product": pr, "qty": qty})
        if not items:
            continue
        price = Decimal(str(b.bundle_price)).quantize(Decimal("0.01"))
        saving = regular - price if regular > price else Decimal("0")
        if starts and ends:
            window = f"{starts.astimezone(ist):%-d} – {ends.astimezone(ist):%-d %b}" if starts.astimezone(ist).month == ends.astimezone(ist).month else f"{starts.astimezone(ist):%-d %b} – {ends.astimezone(ist):%-d %b}"
        elif ends:
            window = f"Until {ends.astimezone(ist):%-d %b}"
        else:
            window = ""
        cards.append({"id": b.id, "title": _bundle_title(b.name), "description": (b.description or "").strip(),
                      "price": price, "regular": regular, "saving": saving,
                      "pct": int(round(saving * 100 / regular)) if regular > 0 and saving else 0,
                      "items": items, "count": sum(i["qty"] for i in items), "available": ok and not upcoming,
                      "upcoming": upcoming, "window": window, "sold_out": sold_out,
                      "starts_label": f"{starts.astimezone(ist):%-d %b}" if starts else ""})
    cards.sort(key=lambda c: c["upcoming"])
    return cards


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
