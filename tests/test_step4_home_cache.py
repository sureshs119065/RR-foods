"""Step 4.6: per-worker cache of the home page's categories and New Arrivals, emptied by product/category edits."""
import re
from decimal import Decimal

import pytest
from sqlalchemy import event, inspect, select

from app.extensions import db
from app.models import Category, Product, ProductImage, WishlistItem
from app.services import home_cache, storefront
from tests.helpers import make_user, post, sign_in, token
from tests.test_step2_models import make_category, make_product


@pytest.fixture()
def cache_on(app):
    app.config["HOME_CACHE_SECONDS"] = 60
    home_cache.bust()
    yield
    app.config["HOME_CACHE_SECONDS"] = 0
    home_cache.bust()


@pytest.fixture()
def shop(session):
    cat = make_category(session, "Snacks")
    items = []
    for i in range(1, 4):
        p = make_product(session, category=cat, sku=f"H{i}", slug=f"h-{i}", name=f"Millet Item {i}", stock_qty=5,
                         final_price=Decimal("80"), mrp=Decimal("100"))
        session.add(ProductImage(product_id=p.id, url=f"/uploads/h{i}.webp", thumb_url=f"/uploads/h{i}_t.webp", is_primary=True))
        items.append(p)
    session.commit()
    return cat, items


def count_queries(client, url="/"):
    n = []
    def spy(*a):
        n.append(a[2] if len(a) > 2 else "")
    event.listen(db.engine, "before_cursor_execute", spy)
    try:
        r = client.get(url)
        assert r.status_code == 200
    finally:
        event.remove(db.engine, "before_cursor_execute", spy)
    return len(n), r.get_data(as_text=True)


def strip_tokens(html):
    return re.sub(r'(name="csrf_token" value=|name="csrf-token" content=)"[^"]+"', r'\1"T"', html)


def new_arrival_names(html):
    section = html.split('aria-labelledby="new-h"', 1)[1].split("</section>", 1)[0]
    return re.findall(r'class="rc__name"><a [^>]*>([^<]+)</a>', section)


# ------------------------------------------------------------------ defaults
def test_cache_defaults_to_60_seconds_and_is_off_in_tests(app):
    from app.config import Config
    assert Config.HOME_CACHE_SECONDS == 60
    assert app.config["HOME_CACHE_SECONDS"] == 0


def test_with_the_cache_off_a_direct_change_shows_at_once(app, session, shop):
    c = app.test_client()
    assert "Millet Item 1" in c.get("/").get_data(as_text=True)
    session.execute(Product.__table__.update().values(name="Renamed Direct"))  # a core write: no ORM event, nothing cached
    session.commit()
    assert "Renamed Direct" in c.get("/").get_data(as_text=True)
    assert home_cache.stats()["entries"] == 0


# ------------------------------------------------------------------ it works and is correct
def test_second_home_request_skips_the_cached_queries(app, session, shop, cache_on):
    c = app.test_client()
    count_queries(c)                       # first request also loads settings, banners
    home_cache.bust()
    cold, _ = count_queries(c)
    warm, _ = count_queries(c)
    assert warm <= cold - 4, f"cold {cold}, warm {warm}: categories, counts and new arrivals (2+ queries) should be skipped"
    assert home_cache.stats()["hits"] >= 3


def test_cached_page_is_identical_to_the_uncached_page(app, session, shop, cache_on):
    c = app.test_client()
    app.config["HOME_CACHE_SECONDS"] = 0
    uncached = strip_tokens(c.get("/").get_data(as_text=True))
    app.config["HOME_CACHE_SECONDS"] = 60
    home_cache.bust()
    first = strip_tokens(c.get("/").get_data(as_text=True))    # fills the cache
    second = strip_tokens(c.get("/").get_data(as_text=True))   # served from it
    assert uncached == first == second
    assert len(new_arrival_names(second)) >= 3  # real cards were rendered, not an empty section


def test_cached_objects_are_detached_and_complete(app, session, shop, cache_on):
    app.test_client().get("/")
    new = storefront.home_cache.get("new_arrivals", lambda s: pytest.fail("should be cached"))
    cats = storefront.home_cache.get("categories", lambda s: pytest.fail("should be cached"))
    assert new and cats
    for obj in (*new, *cats):
        assert inspect(obj).detached
    p = new[0]
    assert p.category.name == "Snacks" and p.primary_image.url.startswith("/uploads/h") and p.variants == []  # no lazy load needed


def test_nav_categories_use_the_same_cache_on_every_page(app, session, shop, cache_on):
    c = app.test_client()
    home_cache.bust()
    cold = count_queries(c, "/shop")[0]
    warm = count_queries(c, "/shop")[0]
    assert warm < cold


def test_rows_are_returned_in_the_same_shape_with_or_without_the_cache(app, session, shop):
    with app.test_request_context("/"):
        off = storefront.home_rows()
    app.config["HOME_CACHE_SECONDS"] = 60
    home_cache.bust()
    try:
        with app.test_request_context("/"):
            on = storefront.home_rows()
    finally:
        app.config["HOME_CACHE_SECONDS"] = 0
        home_cache.bust()
    assert off.keys() == on.keys()
    assert [p.id for p in off["new"]] == [p.id for p in on["new"]]
    assert [c.id for c in off["categories"]] == [c.id for c in on["categories"]]
    assert off["counts"] == on["counts"]


# ------------------------------------------------------------------ nothing personal is cached
def test_csrf_tokens_and_wishlist_hearts_are_not_shared_between_visitors(app, session, shop, cache_on):
    _, items = shop
    user = make_user(session, "user")
    session.add(WishlistItem(user_id=user.id, product_id=items[0].id))
    session.commit()
    anon, member = app.test_client(), app.test_client()
    sign_in(member, "user")
    home_cache.bust()
    a1 = anon.get("/").get_data(as_text=True)           # fills the cache
    m1 = member.get("/").get_data(as_text=True)         # served from it
    assert home_cache.stats()["hits"] >= 1
    tok = lambda h: set(re.findall(r'name="csrf_token" value="([^"]+)"', h))
    assert tok(a1) and tok(m1) and tok(a1).isdisjoint(tok(m1))
    hearts = lambda h: len(re.findall(r'class="wish is-on"', h.split('aria-labelledby="new-h"', 1)[1]))
    assert hearts(a1) == 0 and hearts(m1) >= 1  # (the looping row renders each card twice, so 2 for one product)


# ------------------------------------------------------------------ invalidation
def test_ttl_expiry_reloads(app, session, shop, cache_on, monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(home_cache.time, "monotonic", lambda: now[0])
    calls = []
    loader = lambda s: calls.append(1) or "v"
    with app.app_context():
        assert home_cache.get("k", loader) == "v" and home_cache.get("k", loader) == "v"
        assert len(calls) == 1
        now[0] += 59
        home_cache.get("k", loader)
        assert len(calls) == 1
        now[0] += 2
        home_cache.get("k", loader)
        assert len(calls) == 2


def test_orm_commit_of_a_product_change_empties_the_cache(app, session, shop, cache_on):
    _, items = shop
    c = app.test_client()
    assert "Millet Item 1" in new_arrival_names(c.get("/").get_data(as_text=True))
    assert home_cache.stats()["entries"] >= 1
    items[0].name = "Brand New Name"
    session.commit()
    assert home_cache.stats()["entries"] == 0
    assert "Brand New Name" in new_arrival_names(c.get("/").get_data(as_text=True))


def test_rollback_does_not_empty_the_cache(app, session, shop, cache_on):
    _, items = shop
    app.test_client().get("/")
    before = home_cache.stats()
    items[0].name = "Never saved"
    session.flush()
    session.rollback()
    assert home_cache.stats()["busts"] == before["busts"] and home_cache.stats()["entries"] == before["entries"]
    session.commit()  # an empty commit after the rollback must not bust either (the flag was cleared)
    assert home_cache.stats()["busts"] == before["busts"]


def test_unrelated_commits_leave_the_cache_alone(app, session, shop, cache_on):
    app.test_client().get("/")
    busts = home_cache.stats()["busts"]
    make_user(session, "user")
    assert home_cache.stats()["busts"] == busts


def test_a_load_that_raced_an_edit_is_not_stored(app, session, shop, cache_on):
    calls = []
    def slow_loader(sess):
        calls.append(1)
        home_cache.bust()          # an edit is committed while this load is running
        return "stale"
    with app.app_context():
        assert home_cache.get("race", slow_loader) == "stale"
        assert home_cache.get("race", lambda s: calls.append(1) or "fresh") == "fresh"
    assert len(calls) == 2


def admin_client(app, session):
    make_user(session, "admin")
    c = app.test_client()
    sign_in(c, "admin")
    return c


def test_admin_product_edit_shows_on_the_next_home_load(app, session, shop, cache_on):
    cat, items = shop
    admin = admin_client(app, session)
    visitor = app.test_client()
    assert "Millet Item 1" in new_arrival_names(visitor.get("/").get_data(as_text=True))
    r = post(admin, f"/admin/products/{items[0].id}/edit",
             {"name": "Ragi Laddu Edited", "sku": "H1", "category_id": str(cat.id), "mrp": "100", "discount_type": "none",
              "discount_value": "0", "stock_qty": "5", "low_stock_threshold": "3", "is_active": "1"})
    assert r.status_code in (200, 302), r.status_code
    names = new_arrival_names(visitor.get("/").get_data(as_text=True))
    assert "Ragi Laddu Edited" in names and "Millet Item 1" not in names


def test_admin_stock_to_zero_removes_it_from_new_arrivals(app, session, shop, cache_on):
    cat, items = shop
    admin = admin_client(app, session)
    visitor = app.test_client()
    assert "Millet Item 2" in new_arrival_names(visitor.get("/").get_data(as_text=True))
    post(admin, f"/admin/products/{items[1].id}/edit",
         {"name": "Millet Item 2", "sku": "H2", "category_id": str(cat.id), "mrp": "100", "discount_type": "none",
          "discount_value": "0", "stock_qty": "0", "low_stock_threshold": "3", "is_active": "1"})
    assert "Millet Item 2" not in new_arrival_names(visitor.get("/").get_data(as_text=True))


def test_admin_archive_and_category_rename_show_at_once(app, session, shop, cache_on):
    cat, items = shop
    admin = admin_client(app, session)
    visitor = app.test_client()
    html = visitor.get("/").get_data(as_text=True)
    assert "Millet Item 3" in new_arrival_names(html) and "Snacks" in html
    post(admin, f"/admin/products/{items[2].id}/archive")
    assert "Millet Item 3" not in new_arrival_names(visitor.get("/").get_data(as_text=True))
    session.expire_all()
    r = post(admin, f"/admin/categories/{cat.id}/edit", {"name": "Tiffin Treats", "slug": cat.slug, "is_active": "1", "sort_order": "0"})
    assert r.status_code in (200, 302)
    html = visitor.get("/").get_data(as_text=True)
    assert "Tiffin Treats" in html and "Millet Item 1" in new_arrival_names(html)


def test_a_new_product_appears_without_waiting_for_the_ttl(app, session, shop, cache_on):
    cat, _ = shop
    visitor = app.test_client()
    visitor.get("/")
    make_product(session, category=cat, sku="H9", slug="h-9", name="Fresh Arrival", stock_qty=3,
                 final_price=Decimal("50"), mrp=Decimal("50"))
    session.commit()
    assert new_arrival_names(visitor.get("/").get_data(as_text=True))[0] == "Fresh Arrival"


def test_sales_count_updates_do_not_flush_the_cache(app, session, shop, cache_on):
    """Orders bump sales_count with a bulk UPDATE; nothing shown in these fragments depends on it."""
    app.test_client().get("/")
    busts = home_cache.stats()["busts"]
    session.execute(Product.__table__.update().values(sales_count=Product.sales_count + 1))
    session.commit()
    assert home_cache.stats()["busts"] == busts


def test_stock_decrement_through_the_orm_empties_the_cache(app, session, shop, cache_on):
    """checkout.py changes stock_qty on locked ORM rows; that commit must drop the cached 'In stock' labels."""
    _, items = shop
    visitor = app.test_client()
    visitor.get("/")
    locked = session.scalars(select(Product).where(Product.id == items[0].id).with_for_update().execution_options(populate_existing=True)).one()
    locked.stock_qty = 0
    session.commit()
    assert "Millet Item 1" not in new_arrival_names(visitor.get("/").get_data(as_text=True))


def test_two_workers_catch_up_within_the_ttl(app, session, shop, cache_on, monkeypatch):
    """Per worker means another worker's cache (here: simulated by a direct core write) can be stale for up to the TTL."""
    now = [5000.0]
    monkeypatch.setattr(home_cache.time, "monotonic", lambda: now[0])
    c = app.test_client()
    c.get("/")
    session.execute(Product.__table__.update().values(name="Changed Elsewhere"))
    session.commit()
    assert "Changed Elsewhere" not in c.get("/").get_data(as_text=True)
    now[0] += 61
    assert "Changed Elsewhere" in c.get("/").get_data(as_text=True)


# ------------------------------------------------------------------ query budgets with the cache on
WARM_BUDGET = {"/": 12, "/shop": 9}  # measured with 12 products: home 16 -> 11, listing 9 -> 8 once the cache is warm (1 spare)


def test_warm_cache_query_budgets(app, session, cache_on):
    from tests.test_step4_perf import seed_catalog
    seed_catalog(session, 12)
    c = app.test_client()
    for url in WARM_BUDGET:
        count_queries(c, url)
    for url, cap in WARM_BUDGET.items():
        n = count_queries(c, url)[0]
        assert n <= cap, f"{url}: {n} queries with a warm cache (budget {cap})"


def test_a_rating_refresh_empties_the_cache(app, session, shop, cache_on):
    """refresh_rating() writes with a Core update, which skips the ORM events; it must still empty the cache on commit."""
    from app.services.reviews import refresh_rating
    app.test_client().get("/")
    assert home_cache.stats()["entries"] > 0
    before = home_cache.stats()["busts"]
    refresh_rating(Product.query.first().id)
    db.session.rollback()
    assert home_cache.stats()["busts"] == before  # a rollback keeps the cache
    refresh_rating(Product.query.first().id)
    db.session.commit()
    assert home_cache.stats()["busts"] == before + 1
    assert home_cache.stats()["entries"] == 0
