"""Reviews placement: the product page shows only a small average rating; reviews are written from the delivered order page
("Rate this order", one per product per order); the admin chooses which approved reviews appear in "What our customers say" on the home
page (max 6, newest first, text cut to 150 characters, customer first name, product name)."""
import re
from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.models import AuditLog, Category, Faq, OrderItem, Review
from app.models.base import utcnow
from app.services import home_cache
from tests.helpers import make_user, post
from tests.test_order_lifecycle import _tok, world  # noqa: F401  (fixture)
from tests.test_step2_models import make_product
from tests.test_step5_owner import mk_order

HEADING = "What our customers say"


@pytest.fixture(autouse=True)
def _reviews_go_live_at_once(session):
    """These tests are about placement and counting, not approval: switch the approval step off here (it is on by default and has its own tests)."""
    from app.models import SiteSetting
    session.add(SiteSetting(key="review_moderation", value="0"))
    session.commit()


@pytest.fixture()
def cache_on(app):
    app.config["HOME_CACHE_SECONDS"] = 60
    home_cache.bust()
    yield
    app.config["HOME_CACHE_SECONDS"] = 0
    home_cache.bust()


def another(session, product, n):
    """A second (third, ...) product in the same category (make_product would otherwise create a clashing 'Snacks' category)."""
    return make_product(session, category=session.get(Category, product.category_id), sku=f"X{n}", slug=f"x{n}", name=f"Product {n}")


def add_review(session, user, product, body="Tasty and fresh", rating=5, status="approved", home=True, deleted=False, age=0, title=None):
    r = Review(user_id=user.id, product_id=product.id, rating=rating, body=body, title=title, status=status, show_on_home=home,
               is_deleted=deleted, is_verified_purchase=True, created_at=utcnow() - timedelta(minutes=age))
    session.add(r)
    session.commit()
    return r


def cards(html):
    section = html.split('id="hrev-h"', 1)[1].split("</section>", 1)[0]
    return section.split('<li class="hrev__card">')[1:]


def rate(client, product, order, item=None, **kw):
    url = f"/account/orders/{order.order_number}"
    data = {"rating": "5", "body": "Great stuff", "order_item_id": str((item or order.items[0]).id), "next": url, "csrf_token": _tok(client, url), **kw}
    return client.post(f"/product/{product.slug}/review", data=data, content_type="multipart/form-data")


# ------------------------------------------------------------------ home page section
def test_home_section_hidden_unless_an_approved_flagged_review_exists(world, session):
    customer, other, product, owner, cust, stranger, admin = world
    add_review(session, customer, product, "Not flagged", home=False)
    add_review(session, other, product, "Still pending", status="pending")
    add_review(session, customer, another(session, product, 1), "Hidden one", status="hidden")
    add_review(session, other, another(session, product, 2), "Deleted one", deleted=True)
    html = stranger.get("/").get_data(as_text=True)
    assert HEADING not in html and "hrev__track" not in html


def test_home_cards_show_stars_trimmed_text_first_name_and_product(world, session):
    customer, other, product, owner, cust, stranger, admin = world
    customer.name = "Priya Raman"
    session.commit()
    add_review(session, customer, product, "x" * 300, rating=4)
    html = stranger.get("/").get_data(as_text=True)
    (card,) = cards(html)
    text = re.search(r'hrev__text">&ldquo;(.*?)&rdquo;', card).group(1)
    assert len(text) == 150 and text.endswith("\u2026")                       # cut to 150 characters
    assert ">Priya<" in card and "Raman" not in html and "buyer@x.com" not in card  # first name only
    assert product.name in card and 'aria-label="4 out of 5 stars"' in card
    add_review(session, other, another(session, product, 3), "y" * 150)
    texts = [re.search(r'hrev__text">&ldquo;(.*?)&rdquo;', c).group(1) for c in cards(stranger.get("/").get_data(as_text=True))]
    assert "y" * 150 in texts                                                    # exactly 150 is kept whole


def test_home_shows_at_most_six_newest_first(world, session):
    customer, other, product, owner, cust, stranger, admin = world
    for n in range(8):
        add_review(session, customer, another(session, product, 100 + n), f"Review number {n}", age=100 - n)  # n=7 newest
    found = [re.search(r"Review number (\d)", c).group(1) for c in cards(stranger.get("/").get_data(as_text=True))]
    assert found == ["7", "6", "5", "4", "3", "2"]


def test_home_section_sits_before_the_faq_and_uses_css_scroll_snap_not_js(world, session):
    customer, other, product, owner, cust, stranger, admin = world
    add_review(session, customer, product)
    session.add(Faq(question="How does delivery work?", answer="We deliver.", sort_order=1))
    session.commit()
    html = stranger.get("/").get_data(as_text=True)
    assert 'id="faq"' in html and html.index(HEADING) < html.index('id="faq"')
    assert html.index("New Arrivals") < html.index(HEADING) if "New Arrivals" in html else True
    section = html.split('id="customer-reviews"', 1)[1].split("</section>", 1)[0]
    assert "<script" not in section
    css = open("app/static/css/storefront.css", encoding="utf-8").read()
    phone, desktop = css.split("/* Home: \"What our customers say\"", 1)[1].split("@media (min-width: 768px)", 1)
    assert "scroll-snap-type: x mandatory" in phone and "overflow-x: auto" in phone           # phone: swipe row
    assert "grid-template-columns: repeat(3, minmax(0, 1fr))" in desktop.split("}", 1)[0]       # desktop: three cards per row


# ------------------------------------------------------------------ admin toggle and cache
def test_admin_can_show_and_hide_an_approved_review_on_the_home_page(world, session):
    customer, other, product, owner, cust, stranger, admin = world
    r = add_review(session, customer, product, "Lovely millets", home=False)
    assert HEADING not in stranger.get("/").get_data(as_text=True)
    page = admin.get("/admin/reviews").get_data(as_text=True)
    assert "Show on home page" in page and f"/admin/reviews/{r.id}/home" in page
    assert post(admin, f"/admin/reviews/{r.id}/home", {}, page="/admin/reviews").status_code == 302
    session.expire_all()
    assert session.get(Review, r.id).show_on_home is True
    assert session.scalar(select(AuditLog).where(AuditLog.action == "review.home_on"))
    assert "Lovely millets" in stranger.get("/").get_data(as_text=True)
    assert "Shown on home" in admin.get("/admin/reviews").get_data(as_text=True)
    post(admin, f"/admin/reviews/{r.id}/home", {}, page="/admin/reviews")
    session.expire_all()
    assert session.get(Review, r.id).show_on_home is False and "Lovely millets" not in stranger.get("/").get_data(as_text=True)


def test_only_approved_reviews_can_be_flagged_and_only_by_the_admin(world, session):
    customer, other, product, owner, cust, stranger, admin = world
    pending = add_review(session, customer, product, status="pending", home=False)
    ok = add_review(session, other, product, "Approved one", home=False)
    assert post(admin, f"/admin/reviews/{pending.id}/home", {}, page="/admin/reviews").status_code == 302
    session.expire_all()
    assert session.get(Review, pending.id).show_on_home is False
    for who in (owner, cust, stranger):
        assert post(who, f"/admin/reviews/{ok.id}/home", {}, page="/").status_code in (302, 400, 403)
    session.expire_all()
    assert session.get(Review, ok.id).show_on_home is False


def test_rejecting_a_review_takes_it_off_the_home_page(world, session):
    customer, other, product, owner, cust, stranger, admin = world
    r = add_review(session, customer, product, "Soon rejected")
    assert "Soon rejected" in stranger.get("/").get_data(as_text=True)
    post(admin, f"/admin/reviews/{r.id}/set", {"action": "reject"}, page="/admin/reviews")
    session.expire_all()
    rv = session.get(Review, r.id)
    assert rv.status == "hidden" and rv.show_on_home is False and "Soon rejected" not in stranger.get("/").get_data(as_text=True)


def test_home_cache_is_cleared_when_status_or_home_flag_changes(app, world, session, cache_on):
    customer, other, product, owner, cust, stranger, admin = world
    r = add_review(session, customer, product, "Cached words", home=False)
    assert HEADING not in stranger.get("/").get_data(as_text=True)               # cached as "no reviews"
    post(admin, f"/admin/reviews/{r.id}/home", {}, page="/admin/reviews")         # flag on -> visible at once
    assert "Cached words" in stranger.get("/").get_data(as_text=True)
    post(admin, f"/admin/reviews/{r.id}/toggle", {}, page="/admin/reviews")       # status change (hide) -> gone at once
    assert "Cached words" not in stranger.get("/").get_data(as_text=True)
    post(admin, f"/admin/reviews/{r.id}/set", {"action": "approve"}, page="/admin/reviews")
    post(admin, f"/admin/reviews/{r.id}/home", {}, page="/admin/reviews")
    assert "Cached words" in stranger.get("/").get_data(as_text=True)
    post(admin, f"/admin/reviews/{r.id}/set", {"action": "reject"}, page="/admin/reviews")
    assert "Cached words" not in stranger.get("/").get_data(as_text=True)


def test_editing_a_review_takes_it_off_the_home_page_until_the_admin_flags_it_again(world, session):
    customer, other, product, owner, cust, stranger, admin = world
    order = mk_order(session, customer, product, status="delivered")
    rate(cust, product, order, body="First words")
    r = session.scalar(select(Review))
    r.show_on_home = True
    session.commit()
    assert "First words" in stranger.get("/").get_data(as_text=True)
    rate(cust, product, order, body="Changed words")
    session.expire_all()
    assert session.scalar(select(Review)).show_on_home is False
    assert HEADING not in stranger.get("/").get_data(as_text=True)


# ------------------------------------------------------------------ one review per product per order
def test_one_review_per_product_per_order_but_a_new_order_can_be_reviewed(world, session):
    customer, other, product, owner, cust, stranger, admin = world
    first = mk_order(session, customer, product, status="delivered", number="NK-A1")
    second = mk_order(session, customer, product, status="delivered", number="NK-A2")
    rate(cust, product, first, body="Order one")
    rate(cust, product, first, body="Order one again", rating="3")               # same order: an edit
    assert session.scalar(select(func.count(Review.id))) == 1
    rate(cust, product, second, body="Order two")                                # another order: its own review
    session.expire_all()
    rows = session.scalars(select(Review).order_by(Review.id)).all()
    assert [(x.body, x.rating) for x in rows] == [("Order one again", 3), ("Order two", 5)]
    assert rows[0].order_item_id == first.items[0].id and rows[1].order_item_id == second.items[0].id
    session.refresh(product)
    assert product.review_count == 2 and product.avg_rating == Decimal("4.00")


def test_two_lines_of_the_same_product_in_one_order_share_one_review(world, session):
    customer, other, product, owner, cust, stranger, admin = world
    order = mk_order(session, customer, product, status="delivered")
    session.add(OrderItem(order_id=order.id, product_id=product.id, name=product.name, unit_price=Decimal("100"), mrp=Decimal("100"), quantity=1, line_total=Decimal("100")))
    session.commit()
    session.refresh(order)
    assert len(order.items) == 2
    rate(cust, product, order, item=order.items[0], body="Via first line")
    rate(cust, product, order, item=order.items[1], body="Via second line")
    assert session.scalar(select(func.count(Review.id))) == 1
    page = cust.get(f"/account/orders/{order.order_number}").get_data(as_text=True)
    assert page.count('class="acc orev__item"') + page.count('class="acc orev__item" data-open') == 1  # one entry per product


def test_only_the_buyer_of_the_product_can_review_it(world, session):
    customer, other, product, owner, cust, stranger, admin = world
    order = mk_order(session, customer, product, status="delivered")
    rate(stranger, product, order)                                               # someone else's order line
    stranger_order = mk_order(session, other, another(session, product, 5), status="delivered", number="NK-Z1")
    rate(stranger, product, stranger_order)                                      # own order, but a product they did not buy
    assert session.scalar(select(func.count(Review.id))) == 0
    unpaid = mk_order(session, customer, product, status="shipped", number="NK-S9")
    rate(cust, product, unpaid)                                                  # not delivered yet
    assert session.scalar(select(func.count(Review.id))) == 0


def test_rate_this_order_button_follows_what_is_still_unrated(world, session):
    customer, other, product, owner, cust, stranger, admin = world
    second_product = another(session, product, 6)
    order = mk_order(session, customer, product, status="delivered")
    session.add(OrderItem(order_id=order.id, product_id=second_product.id, name=second_product.name, unit_price=Decimal("50"), mrp=Decimal("50"), quantity=1, line_total=Decimal("50")))
    session.commit()
    url = f"/account/orders/{order.order_number}"
    assert "Rate this order" in cust.get("/account/orders").get_data(as_text=True) and "data-rate-order" in cust.get(url).get_data(as_text=True)
    rate(cust, product, order)
    assert "Rate this order" in cust.get("/account/orders").get_data(as_text=True)     # one product still unrated
    assert "data-rate-order" in cust.get(url).get_data(as_text=True)
    rate(cust, second_product, order, item=order.items[1])
    assert "Rate this order" not in cust.get("/account/orders").get_data(as_text=True)
    assert "data-rate-order" not in cust.get(url).get_data(as_text=True)
    assert "Rate this order" not in stranger.get("/account/orders").get_data(as_text=True)  # not their order


def test_product_page_lists_only_approved_reviews_with_optional_feedback(world, session):
    customer, other, product, owner, cust, stranger, admin = world
    order = mk_order(session, customer, product, status="delivered")
    assert "No reviews yet" in stranger.get(f"/product/{product.slug}").get_data(as_text=True)
    add_review(session, customer, product, "Shown after approval", status="approved", home=False)
    add_review(session, other, product, "Waiting for approval", status="pending", home=False)
    add_review(session, other, product, "Rejected words", status="hidden", home=False)
    add_review(session, customer, another(session, product, 9), "Other product", home=False)
    html = stranger.get(f"/product/{product.slug}").get_data(as_text=True)
    assert 'id="reviews"' in html and "Shown after approval" in html and "Verified purchase" in html
    assert "Waiting for approval" not in html and "Rejected words" not in html and "Other product" not in html
    assert "Questions &amp; answers" not in html and 'id="qa"' not in html


def test_a_rating_without_feedback_text_is_accepted_and_shown_as_stars(world, session):
    customer, other, product, owner, cust, stranger, admin = world
    order = mk_order(session, customer, product, status="delivered")
    rate(cust, product, order, body="")
    session.expire_all()
    r = session.scalar(select(Review))
    assert r.rating == 5 and r.body is None and r.status == "approved"
    html = stranger.get(f"/product/{product.slug}").get_data(as_text=True)
    assert 'id="reviews"' in html and "5 out of 5 stars" in html


def test_new_reviews_wait_for_approval_by_default(world, session):
    from app.models import SiteSetting
    customer, other, product, owner, cust, stranger, admin = world
    session.query(SiteSetting).filter_by(key="review_moderation").delete()
    session.commit()
    order = mk_order(session, customer, product, status="delivered")
    rate(cust, product, order, body="Needs the shop's OK")
    session.expire_all()
    assert session.scalar(select(Review)).status == "pending"
    assert "Needs the shop" not in stranger.get(f"/product/{product.slug}").get_data(as_text=True)
    rid = session.scalar(select(Review.id))
    post(admin, f"/admin/reviews/{rid}/set", {"action": "approve"}, page="/admin/reviews")
    assert "Needs the shop" in stranger.get(f"/product/{product.slug}").get_data(as_text=True)
