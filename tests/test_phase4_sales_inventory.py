from datetime import date, timedelta
from decimal import Decimal

from app.extensions import db
from app.models import Category, InventoryBatch, Product


def make_product(session):
    category = Category(name="Batch Test", slug="batch-test")
    session.add(category)
    session.flush()
    product = Product(sku="BATCH-T", slug="batch-test-product", name="Batch test product",
                      category_id=category.id, mrp=Decimal("100"), final_price=Decimal("100"))
    session.add(product)
    session.flush()
    return product


def test_inventory_batch_model_and_reorder_level_default(session):
    product = make_product(session)
    assert product.reorder_level == 5
    batch = InventoryBatch(product_id=product.id, batch_number="BATCH-TEST",
                           expiry_date=date.today() + timedelta(days=20), quantity=12)
    session.add(batch)
    session.flush()
    assert batch.quantity == 12
    assert batch.product_id == product.id
