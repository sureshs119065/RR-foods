import io
import json
import os
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.extensions import db
from app.models import AuditLog, Category, Coupon, HeaderBanner, Offer, Product, SiteSetting, User
from app.models import base as base_mod
from app.models.base import utcnow
from app.security import verify_password
from app.services import header_banners as svc
from tests.helpers import PW, img, make_user, post, sign_in, token
from tests.test_step2_models import make_category, make_product


@pytest.fixture()
def admin(app, session):
    make_user(session, "admin")
    svc.bust_cache()
    c = app.test_client()
    sign_in(c, "admin")
    return c


def bdata(**over):
    d = {"title": "Diwali Sale", "link_type": "url", "target_url": "/shop", "bg_color": "#7a1f3d", "text_color": "#ffffff", "is_active": "1"}
    d.update(over)
    return d


def fake_now(monkeypatch, when):
    monkeypatch.setattr(base_mod, "utcnow", lambda: when)


# ---------------- header banners: admin CRUD ----------------
def test_create_edit_banner_with_images_and_audit(admin, session, app):
    r = post(admin, "/admin/header-banners/new", bdata(subtitle="Big offers", badge_text="FESTIVAL", button_text="Shop",
                                                       start_at="2030-10-25T09:00", end_at="2030-11-05T23:59", countdown_enabled="1"),
             files={"desktop_image": img("d.png", size=(2400, 900)), "mobile_image": img("m.png", size=(1200, 900))})
    assert r.status_code == 302
    b = session.scalar(select(HeaderBanner))
    assert b.desktop_image.startswith("/uploads/banners/") and b.mobile_image and b.countdown_enabled
    assert b.start_at == datetime(2030, 10, 25, 3, 30, tzinfo=timezone.utc)  # 09:00 India time stored as UTC
    from PIL import Image
    path = os.path.join(app.config["UPLOAD_DIR"], b.desktop_image[len("/uploads/"):])
    assert Image.open(path).size[0] <= 1920
    old = b.desktop_image
    r = post(admin, f"/admin/header-banners/{b.id}/edit", bdata(title="Diwali Sale 2", end_at="2030-11-06T23:59", countdown_enabled="1",
                                                                  start_at="2030-10-25T09:00"), files={"desktop_image": img("new.png")})
    assert r.status_code == 302
    session.expire_all()
    b = session.scalar(select(HeaderBanner))
    assert b.title == "Diwali Sale 2" and b.desktop_image != old
    assert not os.path.exists(os.path.join(app.config["UPLOAD_DIR"], old[len("/uploads/"):]))  # replaced file is cleaned up
    assert {"header_banner.create", "header_banner.update"} <= {a.action for a in session.scalars(select(AuditLog))}


@pytest.mark.parametrize("over,field", [
    ({"title": ""}, "title"),
    ({"link_type": "url", "target_url": "javascript:alert(1)"}, "link_target"),
    ({"link_type": "url", "target_url": "//evil.example"}, "link_target"),
    ({"link_type": "url", "target_url": "http://plain.example"}, "link_target"),
    ({"link_type": "url", "target_url": "data:text/html,x"}, "link_target"),
    ({"link_type": "category", "target_category": "nope"}, "link_target"),
    ({"link_type": "product", "target_product": "nope"}, "link_target"),
    ({"link_type": "coupon", "target_coupon": "NOPE"}, "link_target"),
    ({"bg_color": "red"}, "bg_color"),
    ({"text_color": "#12"}, "text_color"),
    ({"start_at": "2030-02-01T10:00", "end_at": "2030-01-01T10:00"}, "end_at"),
    ({"countdown_enabled": "1"}, "end_at"),
    ({"start_at": "garbage"}, "start_at"),
])
def test_banner_validation(admin, session, over, field):
    r = post(admin, "/admin/header-banners/new", bdata(**over))
    assert r.status_code == 422
    assert session.scalar(select(HeaderBanner)) is None
    assert "Nothing was saved" in r.get_data(as_text=True)


def test_banner_links_to_real_category_product_coupon(admin, session):
    cat = make_category(session, "Sweets")
    make_product(session, category=cat, sku="Q1", slug="laddu", name="Laddu")
    session.add(Coupon(code="SAVE5", discount_type="flat", discount_value=5))
    session.commit()
    for data in (bdata(title="Cat", link_type="category", target_category="sweets"), bdata(title="Prod", link_type="product", target_product="laddu"),
                 bdata(title="Coup", link_type="coupon", target_coupon="save5"), bdata(title="Link", link_type="url", target_url="https://example.com/x")):
        assert post(admin, "/admin/header-banners/new", data).status_code == 302
    hrefs = {b["title"]: b["href"] for b in svc.cached_payload()["banners"]}
    assert hrefs == {"Cat": "/shop?category=sweets", "Prod": "/product/laddu", "Coup": "/offers?coupon=SAVE5", "Link": "https://example.com/x"}


def test_bad_image_rolls_back_the_banner(admin, session, app):
    r = post(admin, "/admin/header-banners/new", bdata(), files={"desktop_image": (io.BytesIO(b"<script>"), "x.png")})
    assert r.status_code == 422 and session.scalar(select(HeaderBanner)) is None


def test_toggle_duplicate_delete_and_move(admin, session):
    ids = []
    for t in ("One", "Two", "Three"):
        post(admin, "/admin/header-banners/new", bdata(title=t), files={"desktop_image": img()} if t == "One" else None)
    one, two, three = (session.scalar(select(HeaderBanner).where(HeaderBanner.title == t)) for t in ("One", "Two", "Three"))
    assert [one.sort_order, two.sort_order, three.sort_order] == sorted([one.sort_order, two.sort_order, three.sort_order])
    page = "/admin/header-banners"
    post(admin, f"/admin/header-banners/{one.id}/toggle", page=page)
    session.expire_all()
    assert not session.get(HeaderBanner, one.id).is_active
    post(admin, f"/admin/header-banners/{one.id}/duplicate", page=page)
    session.expire_all()
    copy = session.scalar(select(HeaderBanner).where(HeaderBanner.title == "One (Copy)"))
    assert not copy.is_active and copy.desktop_image != session.get(HeaderBanner, one.id).desktop_image
    post(admin, f"/admin/header-banners/{three.id}/move", {"direction": "up"}, page=page)
    order = [b.title for b in session.scalars(select(HeaderBanner).order_by(HeaderBanner.sort_order))]
    assert order.index("Three") < order.index("Two")
    post(admin, f"/admin/header-banners/{one.id}/delete", page=page)
    session.expire_all()
    assert session.get(HeaderBanner, one.id) is None and admin.get(copy.desktop_image).status_code == 200  # copy keeps its own file


def test_reorder_endpoint_with_csrf_header(admin, session):
    for t in ("A1", "B2", "C3"):
        post(admin, "/admin/header-banners/new", bdata(title=t))
    ids = [b.id for b in session.scalars(select(HeaderBanner).order_by(HeaderBanner.id))]
    tok = token(admin, "/admin/header-banners")
    ok = admin.post("/admin/header-banners/reorder", json={"ids": ids[::-1]}, headers={"X-CSRFToken": tok})
    assert ok.status_code == 200
    session.expire_all()
    assert [b.id for b in session.scalars(select(HeaderBanner).order_by(HeaderBanner.sort_order))] == ids[::-1]
    for body in ({"ids": ids[:2]}, {"ids": ids + [99999]}, {"ids": ids + ids}, {"ids": ["1", "2", "3"]}, {"ids": [True, False]}, {}, {"ids": "x"}):
        assert admin.post("/admin/header-banners/reorder", json=body, headers={"X-CSRFToken": tok}).status_code == 400
    assert admin.post("/admin/header-banners/reorder", json={"ids": ids}).status_code == 400  # no CSRF token


def test_settings_validation_and_save(admin, session):
    page = "/admin/header-banners"
    post(admin, "/admin/header-banners/settings", {"interval_seconds": "8", "max_banners": "4", "transition": "fade", "autoplay": "1"}, page=page)
    assert session.get(SiteSetting, "header_carousel_interval_ms").value == 8000
    assert session.get(SiteSetting, "header_carousel_transition").value == "fade"
    for bad in ({"interval_seconds": "1"}, {"interval_seconds": "31"}, {"max_banners": "0"}, {"max_banners": "11"}, {"transition": "spin"}):
        data = {"interval_seconds": "5", "max_banners": "5", "transition": "slide", **bad}
        post(admin, "/admin/header-banners/settings", data, page=page)
    session.expire_all()
    assert session.get(SiteSetting, "header_carousel_interval_ms").value == 8000  # bad submissions changed nothing


def test_quick_templates_prefill_the_form(admin):
    html = admin.get("/admin/header-banners/new?template=flash").get_data(as_text=True)
    assert 'value="Flash Sale"' in html and "FLASH SALE" in html
    assert admin.get("/admin/header-banners/new?template=bogus").status_code == 200


# ---------------- public API: schedule, order, cache ----------------
def add_banner(session, title, **kw):
    b = HeaderBanner(title=title, link_type="url", link_target="/shop", **kw)
    session.add(b)
    session.commit()
    return b


def test_api_returns_only_live_banners_in_order_and_hides_when_empty(app, session, monkeypatch):
    client = app.test_client()
    svc.bust_cache()
    assert client.get("/api/header-banners").get_json()["banners"] == []
    now = datetime(2030, 6, 1, 12, 0, tzinfo=timezone.utc)
    fake_now(monkeypatch, now)
    add_banner(session, "Third", sort_order=3)
    add_banner(session, "First", sort_order=1)
    add_banner(session, "Off", sort_order=0, is_active=False)
    add_banner(session, "Future", sort_order=2, start_at=now + timedelta(hours=1))
    add_banner(session, "Expired", sort_order=2, end_at=now - timedelta(seconds=1))
    add_banner(session, "Window", sort_order=2, start_at=now - timedelta(days=1), end_at=now + timedelta(days=1), countdown_enabled=True)
    svc.bust_cache()
    r = client.get("/api/header-banners")
    data = r.get_json()
    assert [b["title"] for b in data["banners"]] == ["First", "Window", "Third"]
    assert r.headers["Cache-Control"] == "public, max-age=60"
    assert data["banners"][1]["ends_at"] and data["banners"][0]["ends_at"] is None
    assert data["settings"] == {"interval_ms": 5000, "autoplay": True, "transition": "slide", "arrows": True}


def test_expired_banner_disappears_and_scheduled_one_appears_on_time(app, session, monkeypatch):
    client = app.test_client()
    t0 = datetime(2030, 6, 1, 12, 0, tzinfo=timezone.utc)
    fake_now(monkeypatch, t0)
    add_banner(session, "Ends", sort_order=1, end_at=t0 + timedelta(seconds=20))
    add_banner(session, "Starts", sort_order=2, start_at=t0 + timedelta(seconds=30))
    svc.bust_cache()
    assert [b["title"] for b in client.get("/api/header-banners").get_json()["banners"]] == ["Ends"]
    fake_now(monkeypatch, t0 + timedelta(seconds=21))   # inside the 60 s cache window, but a schedule boundary passed
    assert [b["title"] for b in client.get("/api/header-banners").get_json()["banners"]] == []
    fake_now(monkeypatch, t0 + timedelta(seconds=31))
    assert [b["title"] for b in client.get("/api/header-banners").get_json()["banners"]] == ["Starts"]


def test_single_banner_disables_autoplay_and_arrows_and_max_limit_applies(app, session, monkeypatch):
    client = app.test_client()
    svc.bust_cache()
    add_banner(session, "Only")
    s = client.get("/api/header-banners").get_json()["settings"]
    assert s["autoplay"] is False and s["arrows"] is False
    session.add(SiteSetting(key="header_carousel_max_banners", value=2))
    for i in range(4):
        add_banner(session, f"B{i}", sort_order=i + 1)
    svc.bust_cache()
    assert len(client.get("/api/header-banners").get_json()["banners"]) == 2


def test_cache_is_used_then_cleared_by_admin_changes(admin, session):
    client = admin
    post(admin, "/admin/header-banners/new", bdata(title="Cached"))
    assert [b["title"] for b in client.get("/api/header-banners").get_json()["banners"]] == ["Cached"]
    session.execute(db.text("update header_banners set title='Changed behind the cache'"))
    session.commit()
    assert client.get("/api/header-banners").get_json()["banners"][0]["title"] == "Cached"  # served from cache
    b = session.scalar(select(HeaderBanner))
    post(admin, f"/admin/header-banners/{b.id}/toggle", page="/admin/header-banners")        # admin action busts the cache
    assert client.get("/api/header-banners").get_json()["banners"] == []


def test_api_is_public_but_admin_pages_are_not(app, session):
    c = app.test_client()
    assert c.get("/api/header-banners").status_code == 200
    assert c.get("/admin/header-banners").status_code == 302


# ---------------- offers ----------------
def test_offers_crud_and_validation(admin, session):
    assert post(admin, "/admin/offers/new", {"name": "x", "tag": "y"}).status_code == 422
    assert post(admin, "/admin/offers/new", {"name": "Daily", "tag": "Deal of the Day", "is_active": "1",
                                              "starts_at": "2030-01-02T10:00", "ends_at": "2030-01-01T10:00"}).status_code == 422
    assert post(admin, "/admin/offers/new", {"name": "Daily", "tag": "Deal of the Day", "is_active": "1"}).status_code == 302
    o = session.scalar(select(Offer))
    cat = make_category(session, "X1")
    p = make_product(session, category=cat)
    p.offers.append(o)
    session.commit()
    post(admin, f"/admin/offers/{o.id}/delete", page="/admin/offers")
    session.expire_all()
    assert session.scalar(select(Offer)) is None and session.get(Product, p.id).offers == []


# ---------------- coupons ----------------
def cdata(**over):
    d = {"code": "welcome10", "discount_type": "percent", "discount_value": "10", "min_cart_value": "299", "per_user_limit": "1", "is_active": "1"}
    d.update(over)
    return d


def test_coupon_create_and_rules(admin, session):
    assert post(admin, "/admin/coupons/new", cdata(expires_at="2030-12-31T23:59", usage_limit="100", max_discount="50")).status_code == 302
    c = session.scalar(select(Coupon))
    assert c.code == "WELCOME10" and c.max_discount == 50 and c.usage_limit == 100 and c.expires_at.tzinfo is not None
    for over, field in [({"code": "WELCOME10"}, "code"), ({"code": "ab"}, "code"), ({"code": "has space"}, "code"),
                        ({"code": "NEW1", "discount_value": "101"}, "discount_value"), ({"code": "NEW1", "discount_value": "0"}, "discount_value"),
                        ({"code": "NEW1", "discount_type": "bogus"}, "discount_type"), ({"code": "NEW1", "min_cart_value": "-1"}, "min_cart_value"),
                        ({"code": "NEW1", "usage_limit": "0"}, "usage_limit"), ({"code": "NEW1", "per_user_limit": "0"}, "per_user_limit")]:
        r = post(admin, "/admin/coupons/new", cdata(**over))
        assert r.status_code == 422, over
    assert session.scalar(select(db.func.count(Coupon.id))) == 1


def test_coupon_flat_ignores_max_discount_toggle_and_delete_rules(admin, session):
    post(admin, "/admin/coupons/new", cdata(code="FLAT50", discount_type="flat", discount_value="50", max_discount="10"))
    c = session.scalar(select(Coupon).where(Coupon.code == "FLAT50"))
    assert c.max_discount is None
    post(admin, f"/admin/coupons/{c.id}/toggle", page="/admin/coupons")
    session.expire_all()
    assert not session.get(Coupon, c.id).is_active
    c.used_count = 3
    session.commit()
    assert post(admin, f"/admin/coupons/{c.id}/edit", cdata(code="FLAT50", discount_type="flat", discount_value="50", usage_limit="2")).status_code == 422
    post(admin, f"/admin/coupons/{c.id}/delete", page="/admin/coupons")
    assert session.get(Coupon, c.id) is not None      # used coupons cannot be deleted
    c.used_count = 0
    session.commit()
    post(admin, f"/admin/coupons/{c.id}/delete", page="/admin/coupons")
    session.expire_all()
    assert session.get(Coupon, c.id) is None


# ---------------- users ----------------
def test_block_unblock_and_self_block_protection(app, admin, session):
    cust = make_user(session, "user")
    cc = app.test_client()
    sign_in(cc, "user")
    assert cc.get("/account").status_code == 200
    post(admin, f"/admin/users/{cust.id}/block", page="/admin/users")
    assert cc.get("/account").status_code == 302          # signed out on their next request
    assert sign_in(app.test_client(), "user").status_code == 401
    post(admin, f"/admin/users/{cust.id}/unblock", page="/admin/users")
    assert sign_in(app.test_client(), "user").status_code == 302
    me = session.scalar(select(User).where(User.role == "admin"))
    post(admin, f"/admin/users/{me.id}/block", page="/admin/users")
    session.expire_all()
    assert not session.get(User, me.id).is_blocked
    assert {"user.block", "user.unblock"} <= {a.action for a in session.scalars(select(AuditLog))}


def test_admin_reset_password_shows_it_once_and_signs_out_the_user(app, admin, session):
    cust = make_user(session, "user")
    cc = app.test_client()
    sign_in(cc, "user")
    r = post(admin, f"/admin/users/{cust.id}/reset-password", page="/admin/users")
    assert r.status_code == 200 and r.headers["Cache-Control"] == "no-store"
    import re
    new_pw = re.search(r'class="pw-box">([^<]+)<', r.get_data(as_text=True)).group(1)
    session.expire_all()
    u = session.get(User, cust.id)
    assert verify_password(u.password_hash, new_pw) and not verify_password(u.password_hash, PW)
    assert cc.get("/account").status_code == 302
    assert new_pw not in "".join(a.after and json.dumps(a.after) or "" for a in session.scalars(select(AuditLog)))  # never logged
    assert admin.get("/admin/users").get_data(as_text=True).count(new_pw) == 0
    me = session.scalar(select(User).where(User.role == "admin"))
    r = post(admin, f"/admin/users/{me.id}/reset-password", page="/admin/users")
    assert r.status_code == 302                              # cannot reset yourself this way


def test_create_owner_account(app, admin, session):
    r = post(admin, "/admin/users/new-owner", {"name": "Shop Owner", "email": "Boss@Shop.com"})
    assert r.status_code == 200
    import re
    pw = re.search(r'class="pw-box">([^<]+)<', r.get_data(as_text=True)).group(1)
    oc = app.test_client()
    assert oc.post("/owner/login", data={"email": "boss@shop.com", "password": pw, "csrf_token": token(oc, "/owner/login")}).status_code == 302
    assert post(admin, "/admin/users/new-owner", {"name": "Dup", "email": "boss@shop.com"}).status_code == 422
    assert post(admin, "/admin/users/new-owner", {"name": "", "email": "bad"}).status_code == 422


def test_users_list_filters(admin, session):
    make_user(session, "owner")
    make_user(session, "user")
    html = admin.get("/admin/users?role=owner").get_data(as_text=True)
    assert "owner@test.com" in html and "user@test.com" not in html
    assert "user@test.com" in admin.get("/admin/users?q=USER@").get_data(as_text=True)
    assert admin.get("/admin/users?state=blocked").status_code == 200


# ---------------- audit viewer + access ----------------
def test_audit_log_viewer_filters(admin, session):
    post(admin, "/admin/header-banners/new", bdata())
    html = admin.get("/admin/audit?action=header_banner").get_data(as_text=True)
    assert "header_banner.create" in html
    assert "auth.login" not in html
    assert admin.get("/admin/audit?entity=nothing").status_code == 200


def test_owner_and_customer_blocked_from_new_admin_pages(app, session):
    make_user(session, "owner")
    make_user(session, "user")
    for role in ("owner", "user"):
        c = app.test_client()
        sign_in(c, role)
        for url in ("/admin/offers", "/admin/coupons", "/admin/users", "/admin/audit", "/admin/header-banners", "/admin/header-banners/new"):
            assert c.get(url).status_code == 403, (role, url)
        assert c.post("/admin/header-banners/reorder", json={"ids": []}).status_code in (400, 403)
