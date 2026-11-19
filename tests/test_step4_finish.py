"""Step 4 finish: static requests skip the user load, home images do not fight the LCP, no oversized rasters."""
import re
from decimal import Decimal
from pathlib import Path

import pytest
from PIL import Image
from sqlalchemy import event

from app import imaging
from app.extensions import db
from tests.helpers import make_user, sign_in
from tests.test_step2_models import make_category, make_product

STATIC = Path(__file__).resolve().parent.parent / "app" / "static"
RASTER = {".png", ".jpg", ".jpeg", ".webp", ".gif"}


# ---------------------------------------------------------------- static files cost nothing for signed-in customers
@pytest.fixture()
def signed_in(app, session):
    make_user(session, "user")  # sign_in() logs in as <role>@test.com
    c = app.test_client()
    sign_in(c, "user")
    assert c.get("/account").status_code == 200, "fixture must really be signed in, or the tests below prove nothing"
    return c


def _queries_during(fn):
    seen = []
    def spy(*a):
        seen.append(a[2] if len(a) > 2 else "")
    event.listen(db.engine, "before_cursor_execute", spy)
    try:
        return fn(), seen
    finally:
        event.remove(db.engine, "before_cursor_execute", spy)


def test_static_file_for_a_signed_in_customer_runs_no_query_and_sets_no_cookie(app, signed_in):
    r, queries = _queries_during(lambda: signed_in.get("/static/img/rr-foods-logo-144.webp"))
    assert r.status_code == 200
    assert queries == [], queries
    assert "Set-Cookie" not in r.headers
    assert "Cookie" not in (r.headers.get("Vary") or "")


def test_static_css_is_cacheable_by_shared_caches(app, signed_in):
    r = signed_in.get("/static/css/storefront.css")
    assert r.status_code == 200 and "Set-Cookie" not in r.headers
    assert "cookie" not in (r.headers.get("Vary") or "").lower()


def test_pages_still_load_the_signed_in_user(app, signed_in):
    html = signed_in.get("/account").get_data(as_text=True)
    assert "user@test.com" in html
    assert signed_in.get("/static/img/rr-foods-logo-144.webp").status_code == 200
    assert signed_in.get("/account").status_code == 200  # the session survived the static request in between


def test_a_blocked_customer_is_still_signed_out_on_pages(app, session, signed_in):
    from app.models import User
    u = session.query(User).filter_by(email="user@test.com").one()
    u.is_blocked = True
    session.commit()
    assert signed_in.get("/account").status_code in (302, 401, 403)


# ---------------------------------------------------------------- home page image priority
@pytest.fixture()
def catalogue(session):
    cat = make_category(session, "Snacks")
    for i in range(1, 9):
        make_product(session, category=cat, sku=f"F{i}", slug=f"f-{i}", name=f"Millet {i}", stock_qty=5,
                     final_price=Decimal("80"), mrp=Decimal("100"))
    session.commit()


def _product_imgs(html):
    return re.findall(r"<img\b[^>]*data-product-image[^>]*>", html)


def test_home_product_images_are_lazy_so_they_do_not_compete_with_the_lcp(app, session, catalogue):
    imgs = _product_imgs(app.test_client().get("/").get_data(as_text=True))
    assert imgs
    for tag in imgs:
        assert 'loading="lazy"' in tag and "fetchpriority" not in tag, tag[:140]


def test_listing_still_gives_its_first_four_images_priority(app, session, catalogue):
    imgs = _product_imgs(app.test_client().get("/shop").get_data(as_text=True))
    assert sum("fetchpriority" in t for t in imgs) == 4


# ---------------------------------------------------------------- decorative backgrounds
def test_storefront_css_uses_webp_backgrounds_that_exist_and_are_small():
    css = (STATIC / "css" / "storefront.css").read_text(encoding="utf-8")
    assert ".jpg" not in css and ".jpeg" not in css
    refs = set(re.findall(r'url\(["\']?\.\./img/([\w.-]+\.webp)', css))
    assert {"new-arrivals-bg.webp", "bestsellers-bg.webp"} <= refs
    for name in ("new-arrivals-bg.webp", "bestsellers-bg.webp"):
        f = STATIC / "img" / name
        assert f.is_file() and f.stat().st_size <= 30 * 1024, name
        assert Image.open(f).format == "WEBP"


def test_every_image_the_storefront_css_names_exists():
    css = (STATIC / "css" / "storefront.css").read_text(encoding="utf-8")
    missing = [m for m in set(re.findall(r'url\(["\']?\.\./img/([\w./-]+?\.(?:webp|png|jpg|svg))', css))
               if not (STATIC / "img" / m).is_file()]
    assert missing == []


# ---------------------------------------------------------------- nothing in static/img is over the 100 KB budget
def test_no_bundled_raster_image_is_over_100_kb():
    big = [(p.relative_to(STATIC).as_posix(), p.stat().st_size) for p in (STATIC / "img").rglob("*")
           if p.suffix.lower() in RASTER and p.stat().st_size > imaging.BUDGET_BYTES]
    assert big == [], f"over {imaging.BUDGET_BYTES} B: {big}"


@pytest.mark.parametrize("name,size", [("rr-foods-icon-192.png", (192, 192)), ("rr-foods-icon-512.png", (512, 512)),
                                       ("rr-foods-brand-logo.png", (512, 512))])
def test_app_icons_keep_their_size_and_transparency(name, size):
    im = Image.open(STATIC / "img" / name)
    assert im.size == size and im.format == "PNG"
    assert im.convert("RGBA").getpixel((0, 0))[3] == 0  # the corner is still transparent


def test_pwa_manifest_icons_resolve(app):
    c = app.test_client()
    for icon in c.get("/manifest.webmanifest").get_json()["icons"]:
        assert c.get(icon["src"]).status_code == 200

