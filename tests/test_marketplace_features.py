"""Marketplace-style storefront additions: rating bars, share button, trust strip, free-delivery progress bar,
card quick-add, and a richer empty search result."""
import pytest
from sqlalchemy import select

from app.extensions import limiter
from app.models import Review, SiteSetting
from tests.test_step6_shop import add, catalog, cust, mk, pj  # noqa: F401  (fixtures)
from tests.test_step7_engage import delivered, review


@pytest.fixture(autouse=True)
def _fresh_limits():
    limiter.reset()


def test_product_page_has_share_trust_and_rating_bars(cust, session, catalog):
    _, p = catalog
    delivered(session, cust, p)
    review(cust, p.slug, rating="4")
    r = session.scalar(select(Review).where(Review.product_id == p.id))
    r.status = "approved"
    session.commit()
    html = cust.get(f"/product/{p.slug}").get_data(as_text=True)
    assert "data-share" in html and 'class="pdp-trust"' in html
    assert 'class="rbars"' in html and html.count('class="rbars__bar"') == 5
    assert '<progress class="rbars__bar" max="1" value="1" aria-label="4 star: 1 of 1 reviews">' in html
    assert " style=" not in html


def test_cart_shows_free_delivery_progress_bar(cust, session, catalog):
    _, p = catalog
    add(cust, p, 2)
    assert 'class="fship"' not in cust.get("/cart").get_data(as_text=True)  # no threshold set, nothing to show
    session.add(SiteSetting(key="free_delivery_min_cart", value=500))
    session.commit()
    html = cust.get("/cart").get_data(as_text=True)
    assert 'class="fship__bar"' in html and 'value="32"' in html and "Add ₹340.00 more for free delivery" in html
    assert " style=" not in html


def test_listing_cards_have_quick_add_and_empty_search_helps(app, cust, session, catalog):
    _, p = catalog
    html = cust.get("/shop").get_data(as_text=True)
    assert "data-quickadd" in html and f'name="product_id" value="{p.id}"' in html
    empty = cust.get("/shop?q=zzzqqxx").get_data(as_text=True)
    assert "Or browse a category" in empty and "Snacks" in empty
    app.config["WHATSAPP_NUMBER"] = "919876543210"
    try:
        empty = cust.get("/shop?q=zzzqqxx").get_data(as_text=True)
        assert "https://wa.me/919876543210?text=" in empty and "zzzqqxx" in empty
    finally:
        app.config["WHATSAPP_NUMBER"] = ""


def test_quick_add_posts_to_the_normal_cart_endpoint(cust, session, catalog):
    _, p = catalog
    r = pj(cust, "/cart/add", {"product_id": p.id, "qty": 1}, page="/shop")
    assert r.status_code == 200 and r.get_json()["count"] == 1


# ---------------------------------------------------------------- back-in-stock alerts
def _sold_out(session, p):
    p.stock_qty = 0
    session.commit()


def test_notify_box_shows_only_when_out_of_stock(cust, session, catalog):
    _, p = catalog
    assert "data-notify" not in cust.get(f"/product/{p.slug}").get_data(as_text=True)
    _sold_out(session, p)
    html = cust.get(f"/product/{p.slug}").get_data(as_text=True)
    assert "data-notify" in html and "Notify me when available" in html
    assert "Notify me" in cust.get("/shop").get_data(as_text=True)  # the card links to the product's alert box


def test_alert_toggle_and_restock_notifies_once(cust, session, catalog):
    from app.models import Notification, StockAlert
    from app.services.stock_alerts import notify_restocked
    _, p = catalog
    _sold_out(session, p)
    r = pj(cust, f"/product/{p.slug}/notify", page=f"/product/{p.slug}")
    assert r.status_code == 200 and r.get_json()["on"] is True
    assert "Alert on" in cust.get(f"/product/{p.slug}").get_data(as_text=True)
    assert notify_restocked() == 0  # still out of stock, nothing sent
    p.stock_qty = 5
    session.commit()
    assert notify_restocked() == 1 and notify_restocked() == 0  # told exactly once
    n = session.scalar(select(Notification).where(Notification.kind == "back_in_stock"))
    assert n is not None and n.link == f"/product/{p.slug}" and "back in stock" in n.title
    assert session.scalar(select(StockAlert)).notified_at is not None
    # asking again later turns it back on; asking twice turns it off
    _sold_out(session, p)
    assert pj(cust, f"/product/{p.slug}/notify", page=f"/product/{p.slug}").get_json()["on"] is True
    assert pj(cust, f"/product/{p.slug}/notify", page=f"/product/{p.slug}").get_json()["on"] is False


def test_alert_refused_when_in_stock_and_needs_sign_in(app, cust, session, catalog):
    _, p = catalog
    r = pj(cust, f"/product/{p.slug}/notify", page=f"/product/{p.slug}")
    assert r.status_code == 409 and r.get_json()["ok"] is False
    _sold_out(session, p)
    guest = app.test_client()
    from tests.helpers import token
    r = guest.post(f"/product/{p.slug}/notify", data={"csrf_token": token(guest, f"/product/{p.slug}")}, headers={"Accept": "application/json"})
    assert r.status_code == 401


def test_cli_command_is_registered(app):
    assert app.cli.commands.get("send-stock-alerts") is not None
