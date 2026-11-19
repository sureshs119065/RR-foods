from types import SimpleNamespace

import pytest

from app.services import tracking


def test_tracking_rejects_non_https_urls_before_mutating_order():
    order = SimpleNamespace(id=10, courier_name=None, tracking_id=None, tracking_url=None)
    actor = SimpleNamespace(id=2)
    with pytest.raises(ValueError, match="HTTPS"):
        tracking.update_tracking(order, "Courier", "ABC123", "http://example.com/track/ABC123", actor)
    assert order.tracking_url is None


def test_tracking_rejects_credentials_in_tracking_url():
    order = SimpleNamespace(id=10, courier_name=None, tracking_id=None, tracking_url=None)
    actor = SimpleNamespace(id=2)
    with pytest.raises(ValueError, match="HTTPS"):
        tracking.update_tracking(order, "Courier", "ABC123", "https://user:pass@example.com/track", actor)


def test_pincode_api_returns_saved_city_and_state(app, session):
    from app.models import DeliveryZone
    session.add(DeliveryZone(pincode="636001", is_serviceable=True, eta_days=2, delivery_fee=35, city="Salem", state="Tamil Nadu"))
    session.commit()
    data = app.test_client().get("/api/pincode/636001").get_json()
    assert data["deliverable"] is True
    assert data["city"] == "Salem" and data["state"] == "Tamil Nadu"


def test_cart_recommendations_are_empty_without_cart():
    from app.services.recommendations import cart_suggestions
    assert cart_suggestions([]) == []


def test_frequently_bought_together_uses_order_item_history(app, session):
    from decimal import Decimal
    from app.models import Order, OrderItem
    from app.services import recommendations
    from tests.test_step2_models import make_category, make_product
    from tests.helpers import make_user

    recommendations._CACHE.clear()
    category = make_category(session, "Pairings")
    first = make_product(session, category=category, name="First snack", slug="first-snack", sku="PAIR1", stock_qty=10)
    second = make_product(session, category=category, name="Second snack", slug="second-snack", sku="PAIR2", stock_qty=10)
    third = make_product(session, category=category, name="Third snack", slug="third-snack", sku="PAIR3", stock_qty=10)
    user = make_user(session, "user")
    for suffix in ("01", "02"):
        order = Order(order_number="NK261112100" + suffix, user_id=user.id, status="delivered", shipping_address={},
                      subtotal=Decimal("20"), total=Decimal("20"), payment_method="upi_manual", payment_status="pending")
        order.items.extend([
            OrderItem(product_id=first.id, name=first.name, unit_price=Decimal("10"), mrp=Decimal("10"), quantity=1, line_total=Decimal("10")),
            OrderItem(product_id=second.id, name=second.name, unit_price=Decimal("10"), mrp=Decimal("10"), quantity=1, line_total=Decimal("10")),
        ])
        session.add(order)
    session.commit()
    suggestions = recommendations.frequently_bought_together(first)
    assert second.id in [product.id for product in suggestions]
    cart_picks = recommendations.cart_suggestions([first.id, second.id])
    assert all(product.id not in {first.id, second.id} for product in cart_picks)
    assert third.id in [product.id for product in cart_picks]


def test_tracking_update_is_audited(app, session):
    from app.models import AuditLog, Order
    from tests.helpers import make_user
    from app.services.tracking import update_tracking

    owner = make_user(session, "owner")
    order = Order(order_number="NK26111220001", user_id=owner.id, status="placed", shipping_address={},
                  subtotal=100, total=100, payment_method="upi_manual", payment_status="pending")
    session.add(order)
    session.flush()
    with app.test_request_context("/"):
        update_tracking(order, "India Post", "EA123456789IN", "https://www.indiapost.gov.in/", owner)
        session.commit()
    assert order.courier_name == "India Post"
    assert order.tracking_id == "EA123456789IN"
    assert session.query(AuditLog).filter_by(action="order.tracking.update", entity_id=str(order.id)).count() == 1


def test_tracking_sets_courier_expected_delivery_date(app, session):
    from datetime import date
    from app.models import Order
    from tests.helpers import make_user
    from app.services.tracking import update_tracking

    owner = make_user(session, "owner")
    order = Order(order_number="NK26111220002", user_id=owner.id, status="packed", shipping_address={},
                  subtotal=100, total=100, payment_method="upi_manual", payment_status="pending")
    session.add(order)
    session.flush()
    with app.test_request_context("/"):
        update_tracking(order, "India Post", "EA1", "", owner, "2026-11-25")
        session.commit()
    assert order.delivery_date == date(2026, 11, 25) and order.delivery_slot is None
    with app.test_request_context("/"), pytest.raises(ValueError, match="expected delivery"):
        update_tracking(order, "India Post", "EA1", "", owner, "not-a-date")
