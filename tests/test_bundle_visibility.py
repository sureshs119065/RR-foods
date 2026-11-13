import pytest

from app.models import Bundle
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


def test_nothing_is_hardcoded_and_nothing_is_auto_created(app, session, admin):
    shop = app.test_client()
    for url in ("/", "/offers"):
        assert "TRADITIONAL GRAINS" not in shop.get(url).get_data(as_text=True)
    admin.get("/admin/bundles")
    session.expire_all()
    assert session.query(Bundle).count() == 0


def test_hiding_a_bundle_in_admin_removes_it_from_home_and_offers(app, session, admin):
    p1, p2 = _two_products(session)
    post(admin, "/admin/bundles/new", _data(p1, p2, name="Festival Special"), page="/admin/bundles/new")
    shop = app.test_client()
    assert "Festival Special" in shop.get("/").get_data(as_text=True)
    b = session.query(Bundle).one()
    b.is_active = False
    session.commit()
    assert "Festival Special" not in shop.get("/").get_data(as_text=True)
    assert "Festival Special" not in shop.get("/offers").get_data(as_text=True)
