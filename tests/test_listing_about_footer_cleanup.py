"""Products page strip removed, About page "Care at every step" section removed, footer has one Explore list without Bundles,
and the Availability filter checkbox really filters."""
import re
from decimal import Decimal

from tests.test_step6_shop import catalog, cust, mk  # noqa: F401  (fixtures)


def test_products_page_has_no_organic_diabetic_line(cust):
    html = cust.get("/shop").get_data(as_text=True)
    assert "100% Organic" not in html and "Diabetic Friendly" not in html


def test_about_page_has_no_care_at_every_step_section(cust):
    r = cust.get("/about")
    html = r.get_data(as_text=True)
    assert r.status_code == 200
    assert "Care at every step" not in html and "Quality Journey" not in html and "data-nurse-guide" not in html
    assert "Discover RR FOODS" in html          # the rest of the page is intact


def test_footer_has_one_explore_list_and_no_bundles_or_products_column(cust):
    html = cust.get("/").get_data(as_text=True)
    footer = re.search(r"<footer class=\"sf\".*?</footer>", html, re.S).group(0)
    heads = re.findall(r"<summary>(.*?)</summary>", footer)
    assert heads == ["Explore", "My account"]
    assert "Bundles" not in footer and "Offers &amp; combo" not in footer and "Shop all categories" not in footer
    assert footer.count("Offers &amp; coupons") == 1 and footer.count(">Recipes<") == 1


def test_availability_filter_hides_out_of_stock(cust, session, catalog):
    cat, _ = catalog
    mk(session, cat, 2, name="Sold Out Thing", stock_qty=0, final_price=Decimal("50"), mrp=Decimal("50"))
    session.commit()
    everything = cust.get("/shop").get_data(as_text=True)
    in_stock = cust.get("/shop?avail=1").get_data(as_text=True)
    assert "Sold Out Thing" in everything
    assert "Sold Out Thing" not in in_stock and "Millet Soup Mix" in in_stock


def test_filter_accordion_checkbox_is_not_swallowed_by_the_drawer_click_handler():
    js = open("app/static/js/shop.js", encoding="utf-8").read()
    # the drawer/search opener must not match a bare [data-open] (filter accordions use that attribute to start expanded)
    assert 'closest("[data-open]")' not in js and '[data-open="drawer"]' in js
