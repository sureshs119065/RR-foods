"""Step 5.4: every customer input is validated (names, phone, pincode, notes, coupon, search) and nothing user-written is marked safe."""
import re
from pathlib import Path

import pytest
from sqlalchemy import select

from app import validation as v
from app.extensions import limiter
from app.models import Address, Order, User
from tests.helpers import make_user, post, signup, token
from tests.test_step6_shop import JSON, add, address_id, catalog, checkout, cust, pj  # noqa: F401  (fixtures)

ROOT = Path(__file__).resolve().parent.parent
XSS = '"><script>alert(1)</script>'


@pytest.fixture(autouse=True)
def _fresh():
    limiter.reset()


def run(fn, *args, **kw):
    errors: dict = {}
    return fn(*args, errors=errors, **kw) if "field" in fn.__code__.co_varnames[:1] else fn(args[0], "f", errors, **kw), errors


# ---------------------------------------------------------------- unit: the checkers
@pytest.mark.parametrize("name", ["Asha Rao", "அருண் குமார்", "Renée O'Brien-Smith", "Dr. K. Rao", "रमेश कुमार", "Li"])
def test_person_name_accepts_real_names(name):
    errors: dict = {}
    assert v.person_name(name, "n", errors) == name and not errors


@pytest.mark.parametrize("name", ["<script>", "Asha <b>", "A", "", "R2D2", "a@b.com", "x" * 121, "Asha;DROP TABLE"])
def test_person_name_rejects_the_rest(name):
    errors: dict = {}
    v.person_name(name, "n", errors)
    assert "n" in errors


def test_person_name_collapses_spaces_and_drops_control_characters():
    errors: dict = {}
    assert v.person_name("  Asha \t  Rao\x00 ", "n", errors) == "Asha Rao" and not errors
    assert v.person_name("Asha\u202eRao", "n", errors) == "AshaRao" and not errors   # direction override removed, not kept


@pytest.mark.parametrize("raw, want", [("9876543210", "9876543210"), ("+91 98765-43210", "9876543210"), ("919876543210", "9876543210"),
                                       ("09876543210", "9876543210"), ("(98765) 43210", "9876543210")])
def test_phone_accepts_indian_mobiles(raw, want):
    errors: dict = {}
    assert v.phone(raw, "p", errors) == want and not errors


@pytest.mark.parametrize("raw", ["5876543210", "98765", "abcdefghij", "98765432101", "9876543210; DROP", "<9876543210>", "9" * 40, ""])
def test_phone_rejects_the_rest(raw):
    errors: dict = {}
    v.phone(raw, "p", errors)
    assert "p" in errors


def test_phone_can_be_optional():
    errors: dict = {}
    assert v.phone("", "p", errors, required=False) == "" and not errors
    v.phone("12", "p", errors, required=False)
    assert "p" in errors


@pytest.mark.parametrize("pin, ok", [("641001", True), (" 641 001 ", True), ("012345", False), ("64100", False), ("6410011", False),
                                     ("64100a", False), ("", False), ("٦٤١٠٠١", False), ("641001\n", True)])
def test_pincode(pin, ok):
    errors: dict = {}
    v.pincode(pin, "pin", errors)
    assert (not errors) is ok


def test_is_pincode_rejects_non_strings_and_unicode_digits():
    assert v.is_pincode("641001") and not v.is_pincode("٦٤١٠٠١") and not v.is_pincode(None) and not v.is_pincode("641001\n")


@pytest.mark.parametrize("raw, want", [("save10", "SAVE10"), (" diwali 25 ", "DIWALI25"), ("new-user_5", "NEW-USER_5")])
def test_coupon_code_normalises(raw, want):
    errors: dict = {}
    assert v.coupon_code(raw, "c", errors) == want and not errors


@pytest.mark.parametrize("raw", ["", "   ", "SAVE%10", "A'B", "<b>", "-SAVE", "SAVE10;--", "X" * 41])
def test_coupon_code_rejects_the_rest(raw):
    errors: dict = {}
    v.coupon_code(raw, "c", errors)
    assert "c" in errors


def test_search_query_never_errors_but_cleans():
    assert v.search_query("  ragi \x00 flour\n\t ") == "ragi flour"
    assert len(v.search_query("a" * 500)) == 80 and v.search_query(None) == "" and v.search_query(123) == ""
    assert v.search_query("x" * 200, 60) == "x" * 60


def test_notes_keep_line_breaks_but_not_control_characters_and_have_a_cap():
    errors: dict = {}
    assert v.multiline("leave at gate\r\n\x00call me", "n", errors, max_=500) == "leave at gate\ncall me" and not errors
    v.multiline("x" * 501, "n", errors, max_=500)
    assert "500" in errors["n"]


def test_text_line_rejects_angle_brackets_and_overlong():
    errors: dict = {}
    v.text_line("12 <b>Lake</b>", "l", errors, label="Line")
    assert "l" in errors
    errors.clear()
    v.text_line("x" * 201, "l", errors, label="Line", max_=200)
    assert "l" in errors
    errors.clear()
    assert v.text_line("12/3, Lake Road #4", "l", errors, label="Line") == "12/3, Lake Road #4" and not errors


def test_strip_controls_handles_non_strings():
    assert v.strip_controls(None) == "" and v.strip_controls("a\x00b\u202e") == "ab" and v.strip_controls("a\nb\tc") == "a\nb\tc"


# ---------------------------------------------------------------- register
def _reg_data(**over):
    return {"name": "Asha Rao", "email": "asha@example.com", "phone": "9876543210", "password": "Sup3rSecret!", "confirm": "Sup3rSecret!", **over}


def reg(c, **over):
    return post(c, "/register", _reg_data(**over), page="/register")


def test_register_accepts_a_tamil_name_and_formats_the_phone(app, session, monkeypatch):
    c = app.test_client()
    assert signup(c, monkeypatch, _reg_data(name="அருண் குமார்", phone="+91 98765 43210")).status_code == 302
    u = session.scalar(select(User).where(User.email == "asha@example.com"))
    assert u.name == "அருண் குமார்" and u.phone == "9876543210"


@pytest.mark.parametrize("over, field", [({"name": "<script>alert(1)</script>"}, "name"), ({"name": "A"}, "name"), ({"name": "x" * 121}, "name"),
                                         ({"phone": "98 AB 12"}, "phone"), ({"phone": "12345"}, "phone"), ({"email": "a" * 300 + "@x.com"}, "email")])
def test_register_rejects_bad_input(app, session, over, field):
    r = reg(app.test_client(), **over)
    assert r.status_code == 422 and session.scalar(select(User).where(User.email == "asha@example.com")) is None


def test_register_without_phone_is_fine_and_control_characters_are_dropped(app, session, monkeypatch):
    c = app.test_client()
    assert signup(c, monkeypatch, _reg_data(phone="", name="As\x07ha Rao")).status_code == 302
    assert session.scalar(select(User).where(User.email == "asha@example.com")).name == "Asha Rao"


# ---------------------------------------------------------------- login
def test_login_with_huge_password_or_email_is_refused_cheaply(app, session):
    c = app.test_client()
    r = post(c, "/login", {"email": "a@x.com", "password": "p" * 100000}, page="/login")
    assert r.status_code == 401 and "Incorrect email or password" in r.get_data(as_text=True)
    r = post(c, "/login", {"email": "a" * 400 + "@x.com", "password": "Sup3rSecret!"}, page="/login")
    assert r.status_code == 401
    r = post(c, "/login", {"email": "a\x07@x.com", "password": "Sup3rSecret!"}, page="/login")
    assert r.status_code == 401


# ---------------------------------------------------------------- address
ADDR = {"label": "Home", "full_name": "Asha Rao", "phone": "9876543210", "line1": "12 Lake Road", "line2": "", "city": "Coimbatore",
        "state": "Tamil Nadu", "pincode": "641001"}


def save_addr(c, **over):
    return post(c, "/account/addresses/new", {**ADDR, **over}, page="/account/addresses/new")


def test_address_saved_when_valid(cust, session):
    assert save_addr(cust, line1="12/3, Lake Road #4", label="Office").status_code == 302
    assert session.scalar(select(Address).where(Address.label == "Office")).line1 == "12/3, Lake Road #4"


@pytest.mark.parametrize("over", [{"full_name": "<script>alert(1)</script>"}, {"full_name": "Asha 123"}, {"phone": "abc"}, {"phone": "1234567890"},
                                  {"line1": "<img src=x onerror=alert(1)>"}, {"line2": "a<b"}, {"city": "Coimbatore<br>"}, {"state": "TN1"},
                                  {"pincode": "012345"}, {"pincode": "64100"}, {"pincode": "64100x"}, {"label": "<b>"}, {"line1": "x" * 201},
                                  {"full_name": "x" * 121}, {"city": "x" * 81}, {"line1": "ab"}])
def test_address_rejects_bad_fields(cust, session, over):
    before = session.scalar(select(__import__("sqlalchemy").func.count(Address.id)))
    r = save_addr(cust, **over)
    assert r.status_code == 422
    assert session.scalar(select(__import__("sqlalchemy").func.count(Address.id))) == before


def test_address_error_messages_keep_their_wording(cust):
    body = save_addr(cust, full_name="", line1="", city="", state="", pincode="").get_data(as_text=True)
    for text in ("Enter the name of the person receiving the order.", "Enter house number and street.", "Enter the city.",
                 "Enter the state.", "Enter a 6 digit pincode."):
        assert text in body


def test_address_edit_is_validated_too(cust, session):
    aid = address_id(session, cust.user)
    r = post(cust, f"/account/addresses/{aid}/edit", {**ADDR, "full_name": "<b>x</b>"}, page=f"/account/addresses/{aid}/edit")
    assert r.status_code == 422 and session.get(Address, aid).full_name == "Asha Rao"


def test_address_echo_is_escaped(cust):
    body = save_addr(cust, full_name=XSS).get_data(as_text=True)
    assert "<script>alert(1)" not in body and "&lt;script&gt;" in body


# ---------------------------------------------------------------- checkout notes
def test_checkout_notes_over_500_are_an_error_not_a_silent_cut(cust, session, catalog):
    _, p = catalog
    add(cust, p)
    r = checkout(cust, session, cust.user, notes="x" * 501)
    assert r.status_code == 302 and "/checkout" in r.headers["Location"]
    assert session.scalar(select(Order.id)) is None
    assert "500 characters" in cust.get("/checkout").get_data(as_text=True)


def test_checkout_notes_lose_control_characters(cust, session, catalog):
    _, p = catalog
    add(cust, p)
    r = checkout(cust, session, cust.user, notes="Leave at gate\x07\x1b\r\nCall me")
    assert r.status_code == 302 and "order-placed" in r.headers["Location"]
    assert session.scalar(select(Order)).customer_notes == "Leave at gate\nCall me"


def test_checkout_notes_of_exactly_500_are_kept(cust, session, catalog):
    _, p = catalog
    add(cust, p)
    checkout(cust, session, cust.user, notes="n" * 500)
    assert len(session.scalar(select(Order)).customer_notes) == 500


# ---------------------------------------------------------------- coupon
@pytest.mark.parametrize("code", ["bad code!", "SAVE%", "<script>", "X" * 41, "   "])
def test_coupon_with_bad_characters_is_rejected_before_any_lookup(app, catalog, code):
    c = app.test_client()
    r = pj(c, "/cart/coupon", {"code": code})
    assert r.status_code == 422 and r.get_json()["ok"] is False


def test_coupon_error_message_names_the_rule(app, catalog):
    assert "letters, numbers" in pj(app.test_client(), "/cart/coupon", {"code": "A%B"}).get_json()["message"]


def test_offers_page_does_not_echo_a_bad_coupon_parameter(app):
    body = app.test_client().get("/offers?coupon=" + XSS).get_data(as_text=True)
    assert "<script>alert(1)" not in body


# ---------------------------------------------------------------- search and query strings
@pytest.mark.parametrize("url", ["/shop?q=a%07b", "/shop?q=" + "z" * 5000, "/shop?q=%25_%25", "/shop?q=" + XSS, "/shop?category=%07&brand=%07",
                                 "/api/suggest?q=%07%07", "/api/suggest?q=" + "y" * 5000, "/recipes?q=%07", "/recipes?q=%25", "/recipes?category=%07"])
def test_odd_query_strings_never_cause_a_server_error(app, catalog, url):
    assert app.test_client().get(url).status_code in (200, 404)   # 404 = unknown category, as before; never a 5xx


def test_search_term_is_escaped_in_the_page(app, catalog):
    body = app.test_client().get("/shop?q=" + XSS).get_data(as_text=True)
    assert "<script>alert(1)" not in body


def test_recipe_search_treats_percent_literally(app, session):
    from app.models import RecipeVideo
    from datetime import datetime, timezone
    for i, title in enumerate(["Ragi dosa", "100% millet bowl"]):
        session.add(RecipeVideo(title=title, slug=f"r{i}", is_published=True, published_at=datetime.now(timezone.utc)))
    session.commit()
    body = app.test_client().get("/recipes?q=%25").get_data(as_text=True)
    assert "100% millet bowl" in body and "Ragi dosa" not in body


# ---------------------------------------------------------------- pincode API
@pytest.mark.parametrize("pin, code", [("641001", 200), ("012345", 422), ("64100", 422), ("64100a", 422), ("٦٤١٠٠١", 422)])
def test_pincode_api_validates(app, catalog, pin, code):
    assert app.test_client().get(f"/api/pincode/{pin}").status_code == code


# ---------------------------------------------------------------- contact form
def help_post(c, **over):
    data = {"name": "Asha Rao", "email": "asha@example.com", "phone": "9876543210", "subject": "Bulk order", "message": "Do you ship 20 kg of ragi flour?", **over}
    return post(c, "/help", data, page="/help")


def test_help_form_hands_off_to_whatsapp_when_valid(app, monkeypatch):
    monkeypatch.setitem(app.config, "ADMIN_WHATSAPP_NUMBER", "919876543210")
    r = help_post(app.test_client())
    assert r.status_code == 302 and r.headers["Location"].startswith("https://wa.me/919876543210?text=")


@pytest.mark.parametrize("over", [{"name": "<b>"}, {"name": "A"}, {"email": "not-an-email"}, {"email": "a" * 300 + "@x.com"}, {"phone": "12"},
                                  {"subject": ""}, {"subject": "<script>"}, {"subject": "s" * 141}, {"message": "short"}, {"message": "m" * 4001}])
def test_help_form_rejects_bad_input_without_redirecting(app, monkeypatch, over):
    monkeypatch.setitem(app.config, "ADMIN_WHATSAPP_NUMBER", "919876543210")
    r = help_post(app.test_client(), **over)
    assert r.status_code == 200 and "wa.me" not in r.headers.get("Location", "")


def test_help_form_email_and_phone_are_optional(app, monkeypatch):
    monkeypatch.setitem(app.config, "ADMIN_WHATSAPP_NUMBER", "919876543210")
    assert help_post(app.test_client(), email="", phone="").status_code == 302


def test_help_form_cannot_inject_extra_lines_into_the_whatsapp_text(app, monkeypatch):
    monkeypatch.setitem(app.config, "ADMIN_WHATSAPP_NUMBER", "919876543210")
    r = help_post(app.test_client(), subject="Hi\r\nName: Admin")
    from urllib.parse import unquote_plus
    text = unquote_plus(r.headers["Location"])
    assert "Subject: Hi Name: Admin" in text and "\r" not in text


# ---------------------------------------------------------------- password lengths
def test_change_password_with_a_huge_current_password_is_refused(cust):
    r = post(cust, "/account/password", {"current": "p" * 100000, "new": "Another-Pass1", "confirm": "Another-Pass1"}, page="/account/password")
    assert r.status_code == 422


# ---------------------------------------------------------------- output escaping
def python_files():
    return [p for p in (ROOT / "app").rglob("*.py")]


def template_files():
    return [p for p in (ROOT / "app" / "templates").rglob("*") if p.is_file()]


def test_no_template_marks_anything_safe():
    bad = []
    for p in template_files():
        text = p.read_text(encoding="utf-8", errors="ignore")
        for pattern in (r"\|\s*safe\b", r"\{%-?\s*autoescape\s+(false|off)", r"\|\s*forceescape\b.*\|\s*safe", r"\bMarkup\("):
            if re.search(pattern, text):
                bad.append(f"{p.relative_to(ROOT)}: {pattern}")
    assert not bad, "\n".join(bad)


def test_no_python_code_marks_text_safe():
    bad = []
    for p in python_files():
        text = p.read_text(encoding="utf-8", errors="ignore")
        if re.search(r"\bMarkup\(|render_template_string\(", text) and p.name != "validation.py":
            bad.append(str(p.relative_to(ROOT)))
    assert not bad, bad


def test_autoescape_is_on_for_html_templates(app):
    assert app.jinja_env.autoescape("page.html") and app.jinja_env.autoescape("x.htm") and app.jinja_env.autoescape("x.xml")


def test_json_in_templates_goes_through_tojson():
    """`|tojson` is the only safe way to put data in a script or attribute; a raw `{{ x }}` inside <script> is not."""
    bad = []
    for p in template_files():
        text = p.read_text(encoding="utf-8", errors="ignore")
        for m in re.finditer(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", text, re.S):
            body = m.group(1)
            if "application/ld+json" in m.group(0):
                continue
            if re.search(r"\{\{(?![^}]*tojson)", body):
                bad.append(str(p.relative_to(ROOT)))
    assert not bad, bad


# ---------------------------------------------------------------- NUL bytes (PostgreSQL cannot store them)
@pytest.mark.parametrize("url", ["/shop?category=%00", "/shop?q=a%00b", "/category/%00", "/product/%00", "/api/pincode/%00", "/recipes/%00", "/shop?brand=x%00"])
def test_nul_in_a_url_is_a_400_not_a_500(app, catalog, url):
    assert app.test_client().get(url).status_code == 400


def test_nul_in_a_form_field_is_a_400(app, catalog):
    c = app.test_client()
    assert post(c, "/help", {"name": "A\x00b", "message": "x" * 20, "subject": "s"}, page="/help").status_code == 400
    assert pj(c, "/cart/coupon", {"code": "A\x00B"}).status_code == 400


def test_nul_in_a_json_body_is_a_400(cust):
    r = cust.post("/account/push/subscribe", json={"subscription": {"endpoint": "https://p.example/a\u0000b", "keys": {"p256dh": "a", "auth": "b"}}},
                  headers={"X-CSRFToken": token(cust, "/account")})
    assert r.status_code == 400


def test_everyday_requests_are_untouched_by_the_nul_guard(app, catalog):
    c = app.test_client()
    assert c.get("/shop?q=ragi&category=snacks").status_code == 200 and c.get("/").status_code == 200
