"""Customer-facing issues list (RR Foods): one check per point."""
import re
from datetime import date

from sqlalchemy import select

from app.models import HeaderBanner, Order, Product
from app.seed import seed_header_banners
from app.services import header_banners
from tests.helpers import post
from tests.test_step2_models import make_product  # noqa: F401
from tests.test_step6_shop import add, catalog, checkout, cust  # noqa: F401  (fixtures)
from tests.test_step5_owner import ADDR  # noqa: F401


def test_1_nav_says_products_and_about_us(cust):
    html = cust.get("/").get_data(as_text=True)
    nav = re.search(r'<nav class="sh__links.*?</nav>', html, re.S).group(0)
    assert ">Products<" in nav and ">About Us<" in nav
    assert ">Shop<" not in nav and ">Story<" not in nav
    assert "<summary>Shop</summary>" not in html


def test_2_empty_search_stays_on_the_same_page(cust):
    r = cust.get("/shop?q=", headers={"Referer": "http://localhost/"})
    assert r.status_code == 302 and r.headers["Location"] == "/"
    r = cust.get("/shop?q=%20%20")
    assert r.status_code == 302 and r.headers["Location"] == "/"
    assert cust.get("/shop?q=soup").status_code == 200
    assert cust.get("/shop").status_code == 200


def test_3_festival_and_combo_links_go_to_their_own_pages(cust, session):
    seed_header_banners()
    session.commit()
    festival = session.scalar(select(HeaderBanner).where(HeaderBanner.badge_text == "FESTIVAL"))
    assert header_banners.resolve_href(festival) == "/offers"
    assert cust.get("/offers").status_code == 200 and cust.get("/bundles").status_code == 200
    html = cust.get("/offers").get_data(as_text=True)
    assert 'id="combo-bundles"' in html and 'id="product-offers"' in html


def test_4_8_buy_now_only_records_a_request_not_an_order(cust, session, catalog):
    _, p = catalog
    r = post(cust, "/buy-now", {"product_id": p.id, "qty": 2}, page=f"/product/{p.slug}")
    assert r.status_code == 302 and r.headers["Location"].endswith("/checkout")
    html = cust.get("/checkout").get_data(as_text=True)
    assert 'type="date"' not in html and "preferred delivery" not in html.lower()   # 9: no customer-chosen delivery date
    r = checkout(cust, session, cust.user)
    session.expire_all()
    o = session.scalar(select(Order))
    assert o.status == "pending_whatsapp"
    assert session.get(Product, p.id).stock_qty == 10          # nothing taken just because WhatsApp was offered
    page = cust.get(f"/account/orders/{o.order_number}").get_data(as_text=True)
    assert "not placed yet" in page.lower()
    assert o.delivery_date is None


def test_5_6_7_cancel_rules_and_no_shipment_after_cancel(cust, session, catalog):
    from app.services import orders as svc
    from tests.test_step5_owner import mk_order
    _, p = catalog
    # confirmed by the owner -> customer cannot cancel, and the cancel button is not shown
    o = mk_order(session, cust.user, p, status="confirmed", number="NK-C1")
    page = cust.get(f"/account/orders/{o.order_number}").get_data(as_text=True)
    assert "Cancel order" not in page and "can no longer be cancelled" in page
    r = post(cust, f"/account/orders/{o.order_number}/cancel", {}, page=f"/account/orders/{o.order_number}")
    session.expire_all()
    assert session.get(Order, o.id).status == "confirmed"
    # placed but not yet confirmed -> still cancellable; cancelling wipes courier + delivery date
    o2 = mk_order(session, cust.user, p, status="placed", number="NK-C2", courier_name="DTDC", tracking_id="T1", delivery_date=date(2026, 12, 1))
    assert "Cancel order" in cust.get(f"/account/orders/{o2.order_number}").get_data(as_text=True)
    post(cust, f"/account/orders/{o2.order_number}/cancel", {}, page=f"/account/orders/{o2.order_number}")
    session.expire_all()
    o2 = session.get(Order, o2.id)
    assert o2.status == "cancelled" and o2.delivery_date is None and o2.courier_name is None and o2.tracking_id is None
    page = cust.get(f"/account/orders/{o2.order_number}").get_data(as_text=True)
    assert "Shipment details" not in page and "Expected delivery" not in page and "Cancel order</button>" not in page
    js = cust.get(f"/account/orders/{o2.order_number}/status.json").get_json()
    assert js["delivery_date"] is None and js["courier_name"] is None and js["tracking_id"] is None
    # a cancelled order that somehow still carries a date never shows it
    o3 = mk_order(session, cust.user, p, status="cancelled", number="NK-C3", delivery_date=date(2026, 12, 1), courier_name="DTDC")
    page = cust.get(f"/account/orders/{o3.order_number}").get_data(as_text=True)
    assert "Expected delivery" not in page and "DTDC" not in page and "Shipment details" not in page


def test_8_no_easy_returns_anywhere(cust, session, catalog):
    _, p = catalog
    for url in ("/", "/shop", f"/product/{p.slug}", "/offers", "/bundles", "/about", "/help", "/cart", "/login"):
        text = cust.get(url).get_data(as_text=True).lower()
        assert "easy return" not in text and "free return" not in text and "hassle-free return" not in text, url
