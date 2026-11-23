"""Step 2.4 (exact-slug image fallback, flask check-images), 2.5 (6 New Arrivals cards, inert clones), 2.6 (dark-mode toggle removed)."""
import re
import xml.etree.ElementTree as ET
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from app.models import Product, ProductImage
from tests.test_step2_models import make_category, make_product
from tests.test_step6_shop import catalog, many  # noqa: F401  (fixtures)

STATIC = Path(__file__).resolve().parent.parent / "app" / "static"
PLACEHOLDER = "img/placeholder-product.svg"


def fallback(app, **kw):
    with app.test_request_context("/"):
        return app.jinja_env.globals["product_image_fallback"](SimpleNamespace(**kw))


# ---------------------------------------------------------------- 2.4 image fallback
def test_placeholder_svg_is_a_plain_drawing_without_scripts():
    path = STATIC / PLACEHOLDER
    assert path.is_file() and path.stat().st_size < 4096
    root = ET.fromstring(path.read_text(encoding="utf-8"))
    assert root.tag.endswith("svg")
    text = path.read_text(encoding="utf-8").lower()
    assert "<script" not in text and "onload" not in text and "http://www.w3.org/2000/svg" in text and "href=" not in text


def test_exact_slug_match_uses_the_bundled_photo(app):
    assert fallback(app, slug="moringa-soup-mix", name="Anything").endswith("/img/products/moringa-soup-mix.webp")
    assert fallback(app, slug="Moringa Soup Mix!", name="Anything").endswith("/img/products/moringa-soup-mix.webp")  # slug is normalised


def test_no_keyword_guessing_any_more(app):
    # these names used to be matched to a different product's photo by keyword
    for name in ("Moringa Soup Mix", "Ragi flour", "Millet noodles", "Idli podi", "Pasta"):
        assert fallback(app, slug="no-such-bundled-file", name=name).endswith(PLACEHOLDER), name
    assert fallback(app, slug="", name="Millet soup").endswith(PLACEHOLDER)
    assert fallback(app, slug=None, name="x").endswith(PLACEHOLDER)


def test_no_product_means_no_fallback(app):
    with app.test_request_context("/"):
        assert app.jinja_env.globals["product_image_fallback"](None) is None
        assert app.jinja_env.globals["product_image_src"](None, None) is None


def test_keyword_map_is_gone_from_the_source():
    src = (Path(__file__).resolve().parent.parent / "app" / "__init__.py").read_text(encoding="utf-8")
    assert "keyword_map" not in src and "multi-millet-muesli.webp" not in src


def test_product_without_photo_shows_the_placeholder_with_alt(app, catalog):  # noqa: F811
    cat, p = catalog
    c = app.test_client()
    for url in ("/", "/shop", f"/product/{p.slug}"):
        html = c.get(url).get_data(as_text=True)
        assert PLACEHOLDER in html, url
        assert "soup-base-mix" not in html, url   # the old guess for a product called "Millet Soup Mix"
    page = c.get(f"/product/{p.slug}").get_data(as_text=True)
    assert re.search(r'<img[^>]+placeholder-product\.svg[^>]+alt="Millet Soup Mix"', page) or \
        re.search(r'<img[^>]+alt="Millet Soup Mix"[^>]+placeholder-product\.svg', page)


def test_placeholder_is_served_with_the_static_image_headers(app):
    r = app.test_client().get(f"/static/{PLACEHOLDER}")
    assert r.status_code == 200 and r.mimetype == "image/svg+xml"


def test_check_images_lists_only_products_without_a_real_photo(app, session):
    cat = make_category(session, "Snacks")
    make_product(session, category=cat, sku="A1", slug="no-photo-at-all", name="No Photo")
    bundled = make_product(session, category=cat, sku="A2", slug="moringa-soup-mix", name="Bundled Photo")
    uploaded = make_product(session, category=cat, sku="A3", slug="has-remote-image", name="Remote Photo")
    session.add(ProductImage(product_id=uploaded.id, url="https://cdn.example.com/p.webp", is_primary=True))
    broken = make_product(session, category=cat, sku="A4", slug="broken-upload", name="Broken Upload")
    session.add(ProductImage(product_id=broken.id, url="/uploads/does-not-exist.webp", is_primary=True))
    off = make_product(session, category=cat, sku="A5", slug="switched-off", name="Switched Off", is_active=False)
    session.commit()
    run = app.test_cli_runner().invoke(args=["check-images"])
    assert run.exit_code == 0, run.output
    assert "no-photo-at-all" in run.output and "broken-upload" in run.output
    assert "moringa-soup-mix" not in run.output and "has-remote-image" not in run.output
    assert "switched-off" not in run.output
    assert "2 of 4 product(s) have no real photo" in run.output
    run_all = app.test_cli_runner().invoke(args=["check-images", "--all"])
    assert "switched-off" in run_all.output and "[inactive]" in run_all.output


def test_check_images_strict_fails_only_when_something_is_missing(app, session):
    cat = make_category(session, "Snacks")
    make_product(session, category=cat, sku="B1", slug="moringa-soup-mix", name="Bundled Photo")
    session.commit()
    assert app.test_cli_runner().invoke(args=["check-images", "--strict"]).exit_code == 0
    make_product(session, category=cat, sku="B2", slug="needs-a-photo", name="Needs Photo")
    session.commit()
    bad = app.test_cli_runner().invoke(args=["check-images", "--strict"])
    assert bad.exit_code == 1 and "needs-a-photo" in bad.output


def test_check_images_makes_no_database_changes(app, session):
    cat = make_category(session, "Snacks")
    make_product(session, category=cat, sku="C1", slug="x-one", name="One")
    session.commit()
    before = session.query(Product).count(), session.query(ProductImage).count()
    app.test_cli_runner().invoke(args=["check-images", "--all"])
    assert (session.query(Product).count(), session.query(ProductImage).count()) == before


# ---------------------------------------------------------------- 2.5 six New Arrivals cards
def _new_section(html):
    return html.split('aria-labelledby="new-h"', 1)[1].split("</section>", 1)[0]


def test_new_arrivals_renders_six_cards_each_once(app, session):
    cat = make_category(session, "Snacks")
    for n in range(10):
        make_product(session, category=cat, sku=f"N{n}", slug=f"new-item-{n}", name=f"New Item {n}", stock_qty=5,
                     final_price=Decimal("50"), mrp=Decimal("50"))
    session.commit()
    section = _new_section(app.test_client().get("/").get_data(as_text=True))
    names = re.findall(r'class="rc__name"><a [^>]*>([^<]+)</a>', section)
    assert len(names) == 6 and len(set(names)) == 6
    assert section.count('<li class="rc"') == 6


def test_server_html_has_no_clone_cards(app, many):  # noqa: F811
    section = _new_section(app.test_client().get("/").get_data(as_text=True))
    assert 'aria-hidden="true" inert' not in section
    assert "<li" in section and section.count('class="rc__name"') == section.count('<li class="rc"')


def test_loop_script_makes_inert_hidden_clones_only_when_it_loops():
    js = (STATIC / "js" / "home-loop.js").read_text(encoding="utf-8")
    assert "cloneNode(true)" in js
    assert "setAttribute('aria-hidden', 'true')" in js and "setAttribute('inert', '')" in js and "c.inert = true" in js
    # no clones for reduced motion, and none when the row already fits
    assert js.index("if (reduce) return;") < js.index("cloneNode(true)")
    assert js.index("track.scrollWidth <= box.clientWidth") < js.index("cloneNode(true)")
    assert "removeAttribute('id')" in js          # no duplicate ids from clones
    assert "createElement('button')" not in js and "prefers-reduced-motion" in js  # Pause/Play button removed on request; reduced motion still respected


def test_home_new_limit_is_six():
    from app.services.storefront import HOME_NEW_LIMIT
    assert HOME_NEW_LIMIT == 6


# ---------------------------------------------------------------- 2.6 dark mode toggle removed
def test_no_dark_mode_button_on_storefront_pages(app, catalog):  # noqa: F811
    c = app.test_client()
    for url in ("/", "/shop", "/cart", "/login"):
        html = c.get(url).get_data(as_text=True)
        assert "data-theme-toggle" not in html and "Dark mode" not in html, url


def test_no_theme_code_left_in_assets():
    css = (STATIC / "css" / "storefront.css").read_text(encoding="utf-8")
    assert "data-theme" not in css and not re.search(r"prefers-color-scheme\s*:\s*dark", css)
    shop = (STATIC / "js" / "shop.js").read_text(encoding="utf-8")
    assert "data-theme" not in shop and "nk-theme" not in shop and "prefers-color-scheme" not in shop
    theme = (STATIC / "js" / "theme.js").read_text(encoding="utf-8")
    assert "setAttribute(\"data-theme\"" not in theme and 'classList.add("js")' in theme   # the `js` class is still set
    assert 'removeItem("nk-theme")' in theme


def test_other_stylesheets_do_not_mention_the_toggle():
    for css in (STATIC / "css").glob("*.css"):
        assert "[data-theme-toggle]" not in css.read_text(encoding="utf-8"), css.name
