"""Step 4 performance. 4.1: hashed + minified CSS/JS, immutable caching, gzip/Brotli."""
import gzip
import json
import re
import shutil
from pathlib import Path

import brotli
import pytest

from tests.helpers import make_user, sign_in

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "app" / "static"


@pytest.fixture()
def built(tmp_path, monkeypatch):
    """Run the real build against a copy of the static folder so the repo's own app/static/dist is never touched."""
    import sys
    sys.path.insert(0, str(ROOT / "tools"))
    import build_assets as ba
    static = tmp_path / "static"
    shutil.copytree(STATIC, static, ignore=shutil.ignore_patterns("img", "fonts", "dist"))
    monkeypatch.setattr(ba, "STATIC", static)
    monkeypatch.setattr(ba, "DIST", static / "dist")
    return ba, static, ba.build()


# ---------------------------------------------------------------- 4.1 build
def test_build_writes_hashed_minified_files_and_a_manifest(built):
    ba, static, manifest = built
    css = manifest["css/storefront.css"]
    assert re.fullmatch(r"dist/storefront\.[0-9a-f]{10}\.css", css)
    assert (static / css).stat().st_size < (static / "css/storefront.css").stat().st_size
    assert json.loads((static / "dist" / "manifest.json").read_text()) == manifest
    assert "js/sw.js" not in manifest                      # the service worker keeps its stable URL


def test_bundle_is_the_five_storefront_scripts_joined_in_their_old_order(built):
    import rjsmin
    ba, static, manifest = built
    assert ba.STOREFRONT_JS == ["js/theme.js", "js/shop.js", "js/shell.js", "js/storefront-layout.js", "js/share.js"]
    joined = ";\n".join((static / p).read_text(encoding="utf-8") for p in ba.STOREFRONT_JS)
    assert (static / manifest["js/storefront.bundle.js"]).read_text(encoding="utf-8") == rjsmin.jsmin(joined)
    assert len(rjsmin.jsmin(joined)) < len(joined)


def test_hash_changes_only_when_content_changes(built, monkeypatch):
    ba, static, first = built
    assert ba.build() == first                              # same input -> same names
    (static / "css/auth-page.css").write_text("body{color:red}", encoding="utf-8")
    second = ba.build()
    assert second["css/auth-page.css"] != first["css/auth-page.css"]
    assert second["css/storefront.css"] == first["css/storefront.css"]


def test_production_assets_are_small_enough():
    """Budget from the brief: CSS + JS under 150 KB gzip on the home page."""
    import sys
    sys.path.insert(0, str(ROOT / "tools"))
    import build_assets as ba
    css = (STATIC / "css/storefront.css").read_text()
    js = ";\n".join((STATIC / p).read_text() for p in ba.STOREFRONT_JS)
    import rcssmin, rjsmin
    total = len(gzip.compress(rcssmin.cssmin(css).encode(), 9)) + len(gzip.compress(rjsmin.jsmin(js).encode(), 9))
    assert total < 150 * 1024


# ---------------------------------------------------------------- 4.1 templates use the manifest
def test_pages_fall_back_to_source_files_without_a_manifest(app, session):
    html = app.test_client().get("/login").get_data(as_text=True)
    assert "/static/css/auth-page.css?v=" in html


def test_pages_use_hashed_files_when_a_manifest_exists(app, session, monkeypatch):
    manifest = app.extensions["asset_manifest"]
    monkeypatch.setitem(manifest, "css/storefront.css", "dist/storefront.aaaaaaaaaa.css")
    monkeypatch.setitem(manifest, "js/storefront.bundle.js", "dist/storefront.bbbbbbbbbb.js")
    html = app.test_client().get("/").get_data(as_text=True)
    assert html.count("/static/dist/storefront.aaaaaaaaaa.css") == 1
    assert html.count("/static/dist/storefront.bbbbbbbbbb.js") == 1
    for old in ("js/shop.js", "js/shell.js", "js/theme.js", "js/share.js", "js/storefront-layout.js"):
        assert old not in html


def test_without_a_manifest_the_five_scripts_still_load_in_order(app, session):
    html = app.test_client().get("/").get_data(as_text=True)
    order = [html.index(f"js/{n}.js") for n in ("theme", "shop", "shell", "storefront-layout", "share")]
    assert order == sorted(order)


# ---------------------------------------------------------------- 4.1 caching + compression
def test_dist_files_are_immutable_even_for_signed_in_users(app, session):
    dist = STATIC / "dist"
    made = not dist.exists()
    dist.mkdir(exist_ok=True)
    f = dist / "unit-test.0123456789.js"
    f.write_text("console.log(1)", encoding="utf-8")
    try:
        make_user(session, "user", "buyer@test.com")
        c = app.test_client()
        sign_in(c, "user")
        assert c.get("/account").headers["Cache-Control"] == "no-store"      # pages behind login stay uncached
        r = c.get("/static/dist/unit-test.0123456789.js")
        assert r.status_code == 200
        assert r.headers["Cache-Control"] == "public, max-age=31536000, immutable"
        anon = app.test_client().get("/static/dist/unit-test.0123456789.js")
        assert anon.headers["Cache-Control"] == "public, max-age=31536000, immutable"
    finally:
        f.unlink()
        if made:
            dist.rmdir()


def test_images_and_fonts_get_a_week_not_a_year(app):
    r = app.test_client().get("/static/img/rr-foods-brand-logo.png")
    assert r.headers["Cache-Control"] == "public, max-age=604800"
    assert "immutable" not in r.headers["Cache-Control"]


def test_unhashed_css_is_not_marked_immutable(app):
    r = app.test_client().get("/static/css/storefront.css")
    assert "immutable" not in r.headers.get("Cache-Control", "")


def test_brotli_and_gzip_are_offered(app):
    c = app.test_client()
    raw = c.get("/static/css/storefront.css", headers={"Accept-Encoding": "identity"})
    assert "Content-Encoding" not in raw.headers
    br = c.get("/static/css/storefront.css", headers={"Accept-Encoding": "br, gzip"})
    assert br.headers["Content-Encoding"] == "br" and "Accept-Encoding" in br.headers["Vary"]
    assert brotli.decompress(br.data) == raw.data
    gz = c.get("/static/css/storefront.css", headers={"Accept-Encoding": "gzip"})
    assert gz.headers["Content-Encoding"] == "gzip"
    assert gzip.decompress(gz.data) == raw.data
    assert len(br.data) < len(raw.data) / 4


def test_html_is_compressed_too(app, session):
    r = app.test_client().get("/login", headers={"Accept-Encoding": "gzip"})
    assert r.headers["Content-Encoding"] == "gzip"
    assert b"<html" in gzip.decompress(r.data)


def test_check_config_advises_a_build_when_the_app_started_without_one(app, monkeypatch):
    from app.prodcheck import config_problems
    monkeypatch.setitem(app.extensions, "asset_manifest", {})
    assert any("build_assets" in a for a in config_problems(app)[1])
    monkeypatch.setitem(app.extensions, "asset_manifest", {"css/storefront.css": "dist/storefront.aaaaaaaaaa.css"})
    assert not any("build_assets" in a for a in config_problems(app)[1])


# ---------------------------------------------------------------- 4.2 no database write in before_request
def test_stock_sync_no_longer_runs_inside_requests(app, session, monkeypatch):
    names = [f.__name__ for f in app.before_request_funcs.get(None, [])]
    assert "_periodic_stock_notification_sync" not in names

    def boom():
        raise AssertionError("sync_stock_notifications must only run from the CLI")
    monkeypatch.setattr("app.services.inventory.sync_stock_notifications", boom)
    c = app.test_client()
    for url in ("/", "/shop", "/offers", "/login"):
        assert c.get(url).status_code == 200


def test_get_requests_do_not_write_to_the_database(app, session):
    from sqlalchemy import event
    from app.extensions import db
    writes = []

    def spy(conn, cursor, statement, *a):
        if statement.lstrip().split(None, 1)[0].upper() in {"INSERT", "UPDATE", "DELETE"}:
            writes.append(statement[:80])
    engine = db.engine
    event.listen(engine, "before_cursor_execute", spy)
    try:
        c = app.test_client()
        for url in ("/", "/shop", "/cart"):
            c.get(url)
    finally:
        event.remove(engine, "before_cursor_execute", spy)
    assert writes == []


def test_sync_command_still_works_and_is_scheduled(app, session):
    result = app.test_cli_runner().invoke(args=["sync-stock-notifications"])
    assert result.exit_code == 0 and "Checked" in result.output
    cron = (ROOT / "deploy" / "crontab.txt").read_text()
    assert "flask sync-stock-notifications" in cron


# ---------------------------------------------------------------- 4.3 images
import io as _io
import os as _os
from decimal import Decimal

from PIL import Image
from werkzeug.datastructures import FileStorage

from app import imaging
from app.extensions import db
from app.models import ProductImage
from tests.test_step2_models import make_category, make_product


def photo_like(size):
    """Random colour blobs: over 100 KB as WebP at quality 85 (so the budget bites) yet far below the 5 MB upload cap as PNG."""
    w, h = size
    return Image.frombytes("RGB", (max(w // 16, 1), max(h // 16, 1)), _os.urandom(max(w // 16, 1) * max(h // 16, 1) * 3)).resize(size, Image.BICUBIC)


def noisy(size=(1200, 900)):
    img = photo_like(size)
    buf = _io.BytesIO()
    img.save(buf, "PNG")
    buf.seek(0)
    return FileStorage(buf, filename="photo.png", content_type="image/png")


def test_encode_within_budget_fits_100kb():
    img = Image.frombytes("RGB", (1600, 1200), _os.urandom(1600 * 1200 * 3))   # worst case: pure noise
    data = imaging.encode_within_budget(img)
    assert len(data) <= imaging.BUDGET_BYTES
    assert min(Image.open(_io.BytesIO(data)).size) >= 0.9 * 0.9 * imaging.MIN_SIDE * 0.5  # shrunk, not destroyed


def test_upload_creates_budgeted_main_400_and_800_copies(app, tmp_path):
    from app.uploads import save_image
    app.config["UPLOAD_DIR"] = str(tmp_path)
    with app.app_context():
        url, thumb = save_image(noisy(), "products")
        root = tmp_path / "products"
        main = root / _os.path.basename(url)
        t = root / _os.path.basename(thumb)
        m = root / _os.path.basename(url).replace(".webp", "_m.webp")
        assert main.stat().st_size <= imaging.BUDGET_BYTES
        assert max(Image.open(t).size) == 400 and max(Image.open(m).size) == 800
        assert t.stat().st_size <= imaging.BUDGET_BYTES and m.stat().st_size <= imaging.BUDGET_BYTES


def test_small_upload_gets_no_800_copy(app, tmp_path):
    from app.uploads import save_image
    app.config["UPLOAD_DIR"] = str(tmp_path)
    with app.app_context():
        url, _ = save_image(noisy((500, 500)), "products")
        assert not (tmp_path / "products" / _os.path.basename(url).replace(".webp", "_m.webp")).exists()


def test_deleting_and_copying_an_image_handles_the_800_copy(app, tmp_path):
    from app.uploads import copy_file, delete_files, save_image
    app.config["UPLOAD_DIR"] = str(tmp_path)
    with app.app_context():
        url, thumb = save_image(noisy(), "products")
        stem = _os.path.basename(url)[:-5]
        copy_url = copy_file(url)
        copy_stem = _os.path.basename(copy_url)[:-5]
        assert (tmp_path / "products" / f"{copy_stem}_m.webp").is_file()
        delete_files(url, thumb)
        assert not (tmp_path / "products" / f"{stem}_m.webp").exists()
        assert (tmp_path / "products" / f"{copy_stem}_m.webp").is_file()       # the duplicate keeps its own


def test_banners_keep_full_quality(app, tmp_path):
    from app.uploads import save_image
    app.config["UPLOAD_DIR"] = str(tmp_path)
    with app.app_context():
        url, _ = save_image(noisy(), "banners", thumb_side=None, budget=None)
        assert (tmp_path / "banners" / _os.path.basename(url)).stat().st_size > imaging.BUDGET_BYTES


def test_optimize_file_shrinks_only_when_over_budget(tmp_path):
    big = tmp_path / "big.webp"
    photo_like((1200, 1200)).save(big, "WEBP", quality=90)
    assert big.stat().st_size > imaging.BUDGET_BYTES
    before, after = imaging.optimize_file(big)
    assert after <= imaging.BUDGET_BYTES < before
    again = imaging.optimize_file(big)
    assert again == (after, after)                                            # second run changes nothing


def test_bundled_images_are_under_budget_and_have_responsive_copies():
    photos = sorted((STATIC / "img" / "products").glob("*.webp"))
    mains = [p for p in photos if not imaging.is_variant(p)]
    assert mains
    for p in mains:
        assert p.stat().st_size <= imaging.BUDGET_BYTES, p.name
        assert (p.with_name(p.stem + "_t.webp")).is_file(), p.name
        assert (p.with_name(p.stem + "_m.webp")).is_file(), p.name
    for p in (STATIC / "img").glob("*.jpg"):
        assert p.stat().st_size <= imaging.BUDGET_BYTES, p.name


def test_logo_in_the_header_is_small():
    assert (STATIC / "img" / "rr-foods-logo-144.webp").stat().st_size < 20 * 1024


@pytest.fixture()
def many_products(session):
    cat = make_category(session, "Snacks")
    items = [make_product(session, category=cat, sku=f"S{i}", slug=f"item-{i}", name="Millet Soup Mix" if i % 2 else "Millet Noodles",
                          stock_qty=5, final_price=Decimal("80"), mrp=Decimal("100")) for i in range(1, 11)]
    session.commit()
    return items


PRODUCT_IMG = re.compile(r"<img\b[^>]*data-product-image[^>]*>")


def product_imgs(html):
    return [m.group(0) for m in PRODUCT_IMG.finditer(html)]


def test_first_four_product_images_are_high_priority_rest_lazy(app, session, many_products):
    html = app.test_client().get("/shop").get_data(as_text=True)
    imgs = product_imgs(html)
    assert len(imgs) >= 8
    for tag in imgs[:4]:
        assert 'fetchpriority="high"' in tag and 'loading="lazy"' not in tag
    for tag in imgs[4:]:
        assert 'loading="lazy"' in tag and "fetchpriority" not in tag


def test_priority_resets_on_every_request(app, session, many_products):
    c = app.test_client()
    first = product_imgs(c.get("/shop").get_data(as_text=True))
    second = product_imgs(c.get("/shop").get_data(as_text=True))
    assert [("fetchpriority" in t) for t in first] == [("fetchpriority" in t) for t in second]
    assert sum("fetchpriority" in t for t in second) == 4


def test_every_product_image_has_dimensions_and_alt(app, session, many_products):
    c = app.test_client()
    for url in ("/", "/shop", "/product/item-1"):
        html = c.get(url).get_data(as_text=True)
        for tag in re.findall(r"<img\b[^>]*>", html):
            if 'id="zoom-img"' in tag:
                continue
            assert re.search(r'\bwidth="\d+"', tag) and re.search(r'\bheight="\d+"', tag), (url, tag[:120])
            assert " alt=" in tag, (url, tag[:120])


def test_cards_offer_a_400_and_800_srcset(app, session, many_products):
    # a product whose slug matches a bundled photo gets that photo (and its 400/800 px copies); the neutral placeholder has none
    make_product(session, category=many_products[0].category, sku="PHOTO1", slug="multi-millet-noodles", name="Multi Millet Noodles",
                 stock_qty=5, final_price=Decimal("80"), mrp=Decimal("100"))
    session.commit()
    html = app.test_client().get("/shop").get_data(as_text=True)
    tag = next(t for t in product_imgs(html) if "img/products/multi-millet-noodles" in t)
    m = re.search(r'srcset="([^"]+)"', tag)
    assert m and "sizes=" in tag
    parts = [p.strip().rsplit(" ", 1) for p in m.group(1).split(",")]
    widths = [int(w[:-1]) for _, w in parts]
    assert widths == sorted(widths) and len(set(widths)) == len(widths) >= 2
    for url, _ in parts:
        assert app.test_client().get(url).status_code == 200


def test_remote_images_get_no_srcset(app):
    with app.test_request_context("/"):
        assert app.jinja_env.globals["img_srcset"]("https://cdn.example.com/a.webp") == ""
        assert app.jinja_env.globals["img_srcset"](None) == ""


def test_uploaded_photo_srcset_uses_thumb_and_800_copy(app, session, tmp_path):
    from app.uploads import save_image
    app.config["UPLOAD_DIR"] = str(tmp_path)
    cat = make_category(session, "Snacks")
    p = make_product(session, category=cat, sku="U1", slug="upload-1", name="Upload One", stock_qty=5, final_price=Decimal("50"), mrp=Decimal("60"))
    url, thumb = save_image(noisy(), "products")
    session.add(ProductImage(product_id=p.id, url=url, thumb_url=thumb, is_primary=True))
    session.commit()
    html = app.test_client().get("/product/upload-1").get_data(as_text=True)
    main = re.search(r'<img id="gal-main"[^>]*>', html, re.S).group(0)
    assert 'fetchpriority="high"' in main and 'loading="lazy"' not in main
    ss = re.search(r'srcset="([^"]+)"', main).group(1)
    assert thumb in ss and url.replace(".webp", "_m.webp") in ss and url in ss
    card = product_imgs(app.test_client().get("/shop").get_data(as_text=True))[0]
    assert thumb in card and url.replace(".webp", "_m.webp") in card and f'src="{thumb}"' in card


def test_optimize_images_command_adds_missing_800_copy(app, tmp_path):
    from app.uploads import save_image
    app.config["UPLOAD_DIR"] = str(tmp_path)
    with app.app_context():
        url, _ = save_image(noisy(), "products")
        m = tmp_path / "products" / _os.path.basename(url).replace(".webp", "_m.webp")
        m.unlink()
        r = app.test_cli_runner().invoke(args=["optimize-images"])
        assert r.exit_code == 0 and m.is_file()
        r = app.test_cli_runner().invoke(args=["optimize-images"])
        assert "created 0" in r.output


# ---------------------------------------------------------------- 4.4 fonts
def test_one_display_font_is_preloaded_and_all_faces_swap(app, session):
    css = (STATIC / "css/storefront.css").read_text(encoding="utf-8")
    faces = re.findall(r"@font-face\s*\{[^}]*\}", css)
    assert faces and all("font-display: swap" in f for f in faces)
    html = app.test_client().get("/").get_data(as_text=True)
    preloads = re.findall(r'<link rel="preload"[^>]*as="font"[^>]*>', html)
    assert len(preloads) == 1
    assert "bricolage-latin.woff2" in preloads[0] and "crossorigin" in preloads[0] and 'type="font/woff2"' in preloads[0]
    assert "latin-ext" not in html                                  # the extended subset loads only when a page needs it


def test_no_unused_font_files_and_no_third_party_fonts():
    css = (STATIC / "css/storefront.css").read_text(encoding="utf-8")
    used = set(re.findall(r"fonts/([\w.-]+\.woff2)", css))
    on_disk = {p.name for p in (STATIC / "fonts").iterdir()}
    assert on_disk == used
    assert "fonts.googleapis" not in css and "fonts.gstatic" not in css


# ---------------------------------------------------------------- 4.5 indexes and query counts
HOT_INDEXES = [
    ("products", ["is_active"]), ("products", ["category_id"]), ("products", ["slug"]),
    ("cart_items", ["user_id"]), ("cart_items", ["session_id"]),
    ("orders", ["user_id"]), ("orders", ["user_id", "created_at"]),
]


@pytest.mark.parametrize("table,cols", HOT_INDEXES)
def test_hot_query_columns_are_indexed(app, session, table, cols):
    from sqlalchemy import text
    rows = session.execute(text(
        "select array_agg(a.attname order by k.ord) from pg_index i "
        "join pg_class c on c.oid = i.indrelid "
        "join lateral unnest(i.indkey) with ordinality as k(attnum, ord) on true "
        "join pg_attribute a on a.attrelid = c.oid and a.attnum = k.attnum "
        "where c.relname = :t and k.attnum > 0 group by i.indexrelid"), {"t": table}).scalars().all()
    assert any(r[:len(cols)] == cols for r in rows), f"{table}{cols} has no index starting with those columns"


def seed_catalog(session, n):
    cats = [make_category(session, f"Cat {i}") for i in range(3)]
    for i in range(n):
        p = make_product(session, category=cats[i % 3], sku=f"Q{i}", slug=f"q-{i}", name=f"Millet {i}", stock_qty=5,
                         final_price=Decimal("80"), mrp=Decimal("100"))
        p.is_bestseller = i % 2 == 0
        session.add(ProductImage(product_id=p.id, url=f"/uploads/x{i}.webp", thumb_url=f"/uploads/x{i}_t.webp", is_primary=True))
        session.add(ProductImage(product_id=p.id, url=f"/uploads/y{i}.webp", thumb_url=f"/uploads/y{i}_t.webp"))
    session.commit()


def query_count(app, url):
    from sqlalchemy import event
    n = []
    def spy(*a):
        n.append(1)
    event.listen(db.engine, "before_cursor_execute", spy)
    try:
        assert app.test_client().get(url).status_code == 200
    finally:
        event.remove(db.engine, "before_cursor_execute", spy)
    return len(n)


MAX_QUERIES = {"/": 22, "/shop": 12, "/product/q-1": 22}


def test_query_counts_stay_under_budget_and_do_not_grow_with_products(app, session):
    seed_catalog(session, 6)
    for u in MAX_QUERIES:                         # warm up: the first request also loads settings and banners
        query_count(app, u)
    small = {u: query_count(app, u) for u in MAX_QUERIES}
    from app.models import Product
    cat = session.query(Product).first().category
    for i in range(6, 30):
        p = make_product(session, category=cat, sku=f"Q{i}", slug=f"q-{i}", name=f"Millet {i}", stock_qty=5,
                         final_price=Decimal("80"), mrp=Decimal("100"))
        p.is_bestseller = i % 2 == 0
        session.add(ProductImage(product_id=p.id, url=f"/uploads/x{i}.webp", thumb_url=f"/uploads/x{i}_t.webp", is_primary=True))
    session.commit()
    for u in MAX_QUERIES:
        query_count(app, u)
    big = {u: query_count(app, u) for u in MAX_QUERIES}
    for url, cap in MAX_QUERIES.items():
        assert big[url] <= cap, f"{url}: {big[url]} queries (budget {cap})"
        assert big[url] <= small[url] + 1, f"{url} grew from {small[url]} to {big[url]} queries: an N+1"
