import re

import pytest

from app.models import Bundle, Combo, DeliveryZone
from app.services.delivery import is_tamil_nadu_pincode, zone_for
from tests.helpers import make_user, post, sign_in
from tests.test_step2_models import make_category, make_product


@pytest.fixture()
def admin(app, session):
    make_user(session, "admin")
    c = app.test_client()
    sign_in(c, "admin")
    return c


def _two_products(session):
    cat = make_category(session)
    p1 = make_product(session, category=cat, stock_qty=50)
    p2 = make_product(session, category=cat, name="Second", slug="second", sku="T2", stock_qty=50)
    session.commit()
    return p1, p2


def _data(p1, p2, **over):
    d = {"name": "Combo A", "bundle_price": "150", "product_id": [str(p1.id), str(p2.id)], "quantity": ["1", "1"], "is_active": "1"}
    d.update(over)
    return d


def test_bundle_edit_saves(app, session, admin):
    p1, p2 = _two_products(session)
    post(admin, "/admin/bundles/new", _data(p1, p2), page="/admin/bundles/new")
    b = session.query(Bundle).one()
    slug = b.slug
    url = f"/admin/bundles/{b.id}/edit"
    r = post(admin, url, _data(p1, p2, name="Renamed", bundle_price="160"), page=url)
    assert r.status_code == 302
    session.expire_all()
    b = session.query(Bundle).one()
    assert (b.name, b.bundle_price, b.slug) == ("Renamed", 160.0, slug)  # slug stays stable


def test_failed_bundle_edit_keeps_what_was_typed(app, session, admin):
    p1, p2 = _two_products(session)
    post(admin, "/admin/bundles/new", _data(p1, p2), page="/admin/bundles/new")
    b = session.query(Bundle).one()
    url = f"/admin/bundles/{b.id}/edit"
    r = post(admin, url, _data(p1, p2, name="Typed name", bundle_price="500"), page=url)
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert 'value="Typed name"' in html and 'value="500"' in html and "lower than the combined" in html
    assert html.count("selected") >= 2  # both products still chosen
    session.expire_all()
    assert session.query(Bundle).one().bundle_price == 150.0  # nothing was saved


def test_editing_a_combo_bundle_updates_the_combo(app, session, admin):
    p1, p2 = _two_products(session)
    post(admin, "/admin/combos/new", {"name": "Diwali Box", "price": "150", "original_price": "200",
         "product_ids": [str(p1.id), str(p2.id)], "is_active": "1", "festival_tag": "diwali"}, page="/admin/combos/new")
    combo = session.query(Combo).one()
    url = f"/admin/bundles/{combo.bundle_id}/edit"
    r = post(admin, url, _data(p1, p2, name="Diwali Box 2", bundle_price="140"), page=url)
    assert r.status_code == 302
    session.expire_all()
    combo = session.query(Combo).one()
    assert float(combo.price) == 140.0 and combo.name == "Diwali Box 2"


# ------------------------------------------------------------------ delivery: all Tamil Nadu pincodes
@pytest.mark.parametrize("pin", ["600001", "605602", "620001", "625001", "627001", "630001", "636001", "641001", "643253", "629001"])
def test_every_tamil_nadu_pincode_is_deliverable(app, session, pin):
    assert is_tamil_nadu_pincode(pin)
    z = zone_for(pin)
    assert z is not None and z.is_serviceable and z.eta_days == 3
    assert session.get(DeliveryZone, pin) is None  # nothing written to the database


@pytest.mark.parametrize("pin", ["560001", "682001", "110001", "500001", "12345", "abcdef", ""])
def test_pincodes_outside_tamil_nadu_are_not_deliverable(app, session, pin):
    assert zone_for(pin) is None


def test_saved_row_overrides_default(app, session):
    session.add(DeliveryZone(pincode="600002", is_serviceable=False, eta_days=1, delivery_fee=0))
    session.add(DeliveryZone(pincode="600003", is_serviceable=True, eta_days=1, delivery_fee=40))
    session.commit()
    assert zone_for("600002") is None
    z = zone_for("600003")
    assert z.eta_days == 1 and float(z.delivery_fee) == 40


def test_pincode_api(app, session):
    c = app.test_client()
    ok = c.get("/api/pincode/625001").get_json()
    assert ok["deliverable"] is True
    no = c.get("/api/pincode/560001").get_json()
    assert no["deliverable"] is False


def test_bundle_edit_page_shows_saved_values(app, session, admin):
    """Regression: the layout's nav macro used to be called `item`, which hid the bundle passed to the form."""
    p1, p2 = _two_products(session)
    post(admin, "/admin/bundles/new", _data(p1, p2, name="Saved Combo", bundle_price="175"), page="/admin/bundles/new")
    b = session.query(Bundle).one()
    html = admin.get(f"/admin/bundles/{b.id}/edit").get_data(as_text=True)
    assert 'value="Saved Combo"' in html and 'value="175.0"' in html and html.count(" selected") == 2

