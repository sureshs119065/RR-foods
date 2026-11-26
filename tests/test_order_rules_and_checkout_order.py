"""Buy Now goes straight to checkout, shipped orders cannot be cancelled (with a caution), cancelled orders hide
the delivery tracker and address, and checkout reads: product details, delivery address, payment details."""
import pytest
from sqlalchemy import select

from app.models import Order
from tests.helpers import post
from tests.test_step2_models import make_product  # noqa: F401
from tests.test_step6_shop import add, catalog, checkout, cust  # noqa: F401  (fixtures)


def test_buy_now_goes_straight_to_checkout_not_the_cart(cust, catalog):
    _, p = catalog
    r = post(cust, "/buy-now", {"product_id": p.id, "qty": 1}, page=f"/product/{p.slug}")
    assert r.status_code == 302 and r.headers["Location"].endswith("/checkout")
    assert "/cart" not in r.headers["Location"]
    assert cust.get("/checkout").status_code == 200   # the checkout page opens at once, no cart step in between


def test_checkout_sections_are_product_then_address_then_payment(cust, catalog):
    _, p = catalog
    post(cust, "/buy-now", {"product_id": p.id, "qty": 2}, page=f"/product/{p.slug}")
    html = cust.get("/checkout").get_data(as_text=True)
    a, b, c = html.index("1. Product details"), html.index("2. Delivery address"), html.index("3. Payment details")
    assert a < b < c


@pytest.mark.parametrize("status", ["shipped", "out_for_delivery"])
def test_shipped_order_shows_a_caution_and_cannot_be_cancelled(cust, session, catalog, status):
    from tests.test_step5_owner import mk_order
    _, p = catalog
    o = mk_order(session, cust.user, p, status=status, number=f"NK-S-{status[:3]}")
    page = cust.get(f"/account/orders/{o.order_number}").get_data(as_text=True)
    assert "Caution: this order has already been shipped" in page
    assert "Cancel order" not in page and "/cancel" not in page
    r = post(cust, f"/account/orders/{o.order_number}/cancel", {}, page="/", follow=True)
    assert "Caution: this order has already been shipped" in r.get_data(as_text=True)
    session.expire_all()
    assert session.get(Order, o.id).status == status


def test_confirmed_order_has_no_shipped_caution(cust, session, catalog):
    from tests.test_step5_owner import mk_order
    _, p = catalog
    o = mk_order(session, cust.user, p, status="confirmed", number="NK-S-CONF")
    page = cust.get(f"/account/orders/{o.order_number}").get_data(as_text=True)
    assert "has already been shipped" not in page and "Cancel order" not in page


def test_cancelled_order_hides_the_delivery_bar_and_delivery_address(cust, session, catalog):
    from tests.test_step5_owner import mk_order
    _, p = catalog
    live = mk_order(session, cust.user, p, status="placed", number="NK-D1")
    page = cust.get(f"/account/orders/{live.order_number}").get_data(as_text=True)
    assert "Delivering to" in page and 'aria-label="Order progress"' in page      # still shown for a live order
    post(cust, f"/account/orders/{live.order_number}/cancel", {}, page=f"/account/orders/{live.order_number}")
    session.expire_all()
    assert session.get(Order, live.id).status == "cancelled"
    page = cust.get(f"/account/orders/{live.order_number}").get_data(as_text=True)
    assert "Order cancelled" in page                                                # the cancelled notice stays
    assert "Delivering to" not in page and "Delivery to" not in page
    assert 'aria-label="Order progress"' not in page and 'aria-label="Order final status"' not in page and "data-track" not in page
