"""Buy now orders only the chosen product. Whatever is already in the cart stays in the cart and is not ordered;
the cart's own checkout still orders everything in it."""
from sqlalchemy import select

from app.models import CartItem, Order
from tests.helpers import post
from tests.test_step2_models import make_product  # noqa: F401
from tests.test_step6_shop import add, catalog, checkout, cust  # noqa: F401  (fixtures)


def _second_product(session, catalog):
    _, p = catalog
    return make_product(session, category=p.category, name="Second snack", slug="second-snack", sku="SKU-2", stock_qty=10)


def test_buy_now_orders_only_that_product_and_keeps_the_cart(cust, session, catalog):
    _, p = catalog
    other = _second_product(session, catalog)
    add(cust, other, 3)                                                   # earlier cart content
    post(cust, "/buy-now", {"product_id": p.id, "qty": 2}, page=f"/product/{p.slug}")
    html = cust.get("/checkout?buy_now=1").get_data(as_text=True)
    assert p.name in html and other.name not in html                      # the checkout shows only the chosen product
    r = checkout(cust, session, cust.user, buy_now=1)
    assert r.headers["Location"].startswith("/order-placed/NK")
    session.expire_all()
    order = session.scalar(select(Order))
    assert [(i.product_id, i.quantity) for i in order.items] == [(p.id, 2)]
    cart = {c.product_id: c.quantity for c in session.scalars(select(CartItem))}
    assert cart == {other.id: 3}                                          # cart untouched, nothing added to it


def test_buy_now_on_a_product_already_in_the_cart_does_not_change_the_cart_quantity(cust, session, catalog):
    _, p = catalog
    add(cust, p, 4)
    post(cust, "/buy-now", {"product_id": p.id, "qty": 1}, page=f"/product/{p.slug}")
    checkout(cust, session, cust.user, buy_now=1)
    session.expire_all()
    assert [(i.product_id, i.quantity) for i in session.scalar(select(Order)).items] == [(p.id, 1)]
    assert session.scalar(select(CartItem.quantity)) == 4


def test_cart_checkout_still_orders_everything_in_the_cart(cust, session, catalog):
    _, p = catalog
    other = _second_product(session, catalog)
    add(cust, p, 1)
    add(cust, other, 2)
    checkout(cust, session, cust.user)
    session.expire_all()
    assert sorted((i.product_id, i.quantity) for i in session.scalar(select(Order)).items) == sorted([(p.id, 1), (other.id, 2)])


def test_a_leftover_buy_now_choice_never_mixes_into_the_cart_checkout(cust, session, catalog):
    _, p = catalog
    other = _second_product(session, catalog)
    add(cust, other, 2)
    post(cust, "/buy-now", {"product_id": p.id, "qty": 1}, page=f"/product/{p.slug}")   # clicked Buy now, then left
    html = cust.get("/checkout").get_data(as_text=True)                                  # later: normal cart checkout
    assert other.name in html and p.name not in html
    assert cust.get("/checkout?buy_now=1").status_code == 302                            # the old choice was dropped
