from datetime import datetime, timedelta, timezone

import pytest

from app.models import Bundle
from tests.test_step2_models import make_category, make_product


def _bundle(session, **over):
    cat = make_category(session)
    p1 = make_product(session, category=cat, stock_qty=50)
    p2 = make_product(session, category=cat, name="Second Pack", slug="second", sku="T2", stock_qty=50)
    session.flush()
    b = Bundle(name="RR FOODS – Children's Day Special Combo | ₹999", slug="kids", bundle_price=100,
               description="Seven favourites in one pack.",
               product_quantities=[{"product_id": p1.id, "quantity": 1}, {"product_id": p2.id, "quantity": 2}],
               is_active=True, **over)
    session.add(b)
    session.commit()
    return b


def test_home_shows_new_bundle_with_thumbnails_and_not_old_combo(app, session):
    _bundle(session)
    html = app.test_client().get("/").get_data(as_text=True)
    assert "bd__title" in html and "Children&#39;s Day Special Combo" in html
    assert "| ₹999" not in html          # price lives in the price panel, not the title
    assert "bd--link" in html and "bd__thumb" not in html and "bd__item" not in html  # home is only a link
    assert "Seven favourites" not in html
    assert "TRADITIONAL GRAINS" not in html and "rr-combo" not in html and "Combo offer" not in html


def test_upcoming_bundle_is_teased_and_cannot_be_bought(app, session):
    start = datetime.now(timezone.utc) + timedelta(days=1)
    b = _bundle(session, starts_at=start, ends_at=start + timedelta(days=2))
    shop = app.test_client()
    home = shop.get("/").get_data(as_text=True)
    assert "bd--soon" in home and "Opens" in home
    offers = shop.get("/offers").get_data(as_text=True)
    assert f'id="bundle-{b.id}"' in offers and "Add bundle to cart" not in offers


def test_offers_page_live_bundle_has_add_button(app, session):
    _bundle(session)
    offers = app.test_client().get("/offers").get_data(as_text=True)
    assert "Add bundle to cart" in offers and "bd__thumb" in offers
