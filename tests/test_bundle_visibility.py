import pytest

from app.models import Bundle
from app.services.product_catalogue import CATALOGUE_COMBO_OFFER
from app.shop.catalog import COMBO_BUNDLE_SLUG
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
    d = {"name": "Childrens Combo", "bundle_price": "150", "product_id": [str(p1.id), str(p2.id)],
         "quantity": ["1", "1"], "is_active": "1"}
    d.update(over)
    return d


def test_edit_form_is_prefilled(app, session, admin):
    p1, p2 = _two_products(session)
    post(admin, "/admin/bundles/new", _data(p1, p2, description="Fun pack"), page="/admin/bundles/new")
    b = session.query(Bundle).one()
    html = admin.get(f"/admin/bundles/{b.id}/edit").get_data(as_text=True)
    assert 'value="Childrens Combo"' in html and "Fun pack" in html and 'value="150.0"' in html
    assert "Edit Bundle" in html


def test_saving_bundle_with_colliding_name_does_not_crash(app, session, admin):
    p1, p2 = _two_products(session)
    post(admin, "/admin/bundles/new", _data(p1, p2), page="/admin/bundles/new")
    post(admin, "/admin/bundles/new", _data(p1, p2, name="Other"), page="/admin/bundles/new")
    other = session.query(Bundle).filter_by(name="Other").one()
    slug = other.slug
    url = f"/admin/bundles/{other.id}/edit"
    r = post(admin, url, _data(p1, p2, name="Childrens Combo"), page=url)  # same name as the first bundle
    assert r.status_code == 302
    session.expire_all()
    assert session.get(Bundle, other.id).slug == slug


def test_admin_bundle_shows_on_customer_offers_page(app, session, admin):
    p1, p2 = _two_products(session)
    post(admin, "/admin/bundles/new", _data(p1, p2, name="Festival Special"), page="/admin/bundles/new")
    html = app.test_client().get("/offers").get_data(as_text=True)
    assert "Festival Special" in html and "Add bundle to cart" in html


def test_deleted_catalogue_combo_is_gone_everywhere(app, session, admin):
    p1, p2 = _two_products(session)
    session.add(Bundle(name=CATALOGUE_COMBO_OFFER["title"], slug=COMBO_BUNDLE_SLUG, bundle_price=100,
                       product_quantities=[{"product_id": p1.id, "quantity": 1}], is_active=True))
    session.commit()
    shop = app.test_client()
    assert "TRADITIONAL GRAINS" in shop.get("/offers").get_data(as_text=True)
    bid = session.query(Bundle).one().id
    post(admin, f"/admin/bundles/{bid}/delete", page="/admin/bundles")
    admin.get("/admin/bundles")  # the list used to silently re-create the combo here
    session.expire_all()
    assert session.query(Bundle).count() == 0
    assert "TRADITIONAL GRAINS" not in shop.get("/offers").get_data(as_text=True)
    shop.get("/offers")
    session.expire_all()
    assert session.query(Bundle).count() == 0
