from datetime import datetime, timedelta, timezone

import pytest

from app.models import Bundle
from tests.test_step2_models import make_category, make_product


def _bundle(session, **over):
    cat = make_category(session)
    p1 = make_product(session, category=cat, stock_qty=50)
    p2 = make_product(session, category=cat, name="Second Pack", slug="second", sku="T2", stock_qty=50)
    session.flush()
    b = Bundle(name="Test Combo Pack", slug="kids", bundle_price=100,
               description="Seven favourites in one pack.",
               product_quantities=[{"product_id": p1.id, "quantity": 1}, {"product_id": p2.id, "quantity": 2}],
               is_active=True, **over)
    session.add(b)
    session.commit()
    return b


def test_home_offers_section_is_hidden_when_nothing_is_on_offer(app, session):
    html = app.test_client().get("/").get_data(as_text=True)
    assert "rr-offers-section" not in html and "Coming soon" not in html and "op--combo" not in html
    off = app.test_client().get("/offers").get_data(as_text=True)
    assert "op--combo" in off and "op--offer" in off and "Coming soon" in off  # placeholders live on /offers only


def test_home_points_to_offers_for_a_live_bundle_without_listing_it(app, session):
    _bundle(session)
    html = app.test_client().get("/").get_data(as_text=True)
    assert "op--combo" in html and "1 combo pack available" in html and "Coming soon" not in html
    assert "Test Combo Pack" not in html and "bd__title" not in html
    assert "TRADITIONAL GRAINS" not in html and "rr-combo" not in html and "Combo offer" not in html


def test_upcoming_bundle_is_teased_on_offers_page_only_and_cannot_be_bought(app, session):
    start = datetime.now(timezone.utc) + timedelta(days=1)
    b = _bundle(session, starts_at=start, ends_at=start + timedelta(days=2))
    shop = app.test_client()
    home = shop.get("/").get_data(as_text=True)
    assert "bd--soon" not in home and "Coming soon" not in home and "rr-offers-section" not in home
    offers = shop.get("/offers").get_data(as_text=True)
    assert f'id="bundle-{b.id}"' in offers and "Add bundle to cart" not in offers


def test_offers_page_live_bundle_has_add_button(app, session):
    _bundle(session)
    offers = app.test_client().get("/offers").get_data(as_text=True)
    assert "Add bundle to cart" in offers and "bd__thumb" in offers
