from decimal import Decimal
from sqlalchemy import select

from app.extensions import db
from app.models import Bundle, Combo, Product, SiteSetting


def test_about_page_renders_quality_journey(app):
    response = app.test_client().get("/about")
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    for stage in ("Sourcing", "Cleaning and Sorting", "Traditional Processing",
                  "Quality Testing", "Hygienic Packaging", "Delivery"):
        assert stage in html
    assert "100% Quality Assured" in html


def test_diwali_combo_is_rendered_from_database(app, session):
    from app.models import Category
    category = Category(name="Test foods", slug="test-foods", is_active=True)
    session.add(category)
    session.flush()
    product = Product(sku="DIWALI-TEST-1", slug="diwali-test-product", name="Test Laddu",
                      category_id=category.id, mrp=Decimal("100"), final_price=Decimal("100"),
                      stock_qty=10, is_active=True)
    session.add(product)
    session.flush()
    bundle = Bundle(name="Test Diwali", slug="test-diwali-cart", description="Test",
                    product_quantities=[{"product_id": product.id, "quantity": 1}],
                    bundle_price=80, is_active=True)
    session.add(bundle)
    session.flush()
    combo = Combo(name="Test Diwali Combo", slug="test-diwali-combo", description="Festive test",
                  items=[{"product_id": product.id, "quantity": 1}], price=Decimal("80"),
                  original_price=Decimal("100"), festival_tag="diwali", is_active=True, bundle=bundle)
    session.add(combo)
    session.add(SiteSetting(key="diwali_end_at", value="2026-11-12T23:59"))
    session.commit()
    response = app.test_client().get("/offers")
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "Diwali Special Combos" in html
    assert "Test Diwali Combo" in html
    assert "Test Laddu" in html
    assert "80.00" in html and "100.00" in html
