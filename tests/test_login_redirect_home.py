"""Customer sign-in lands on the Home Page; a safe ?next= still works; the welcome flash shows on the landing page."""
import pytest

from tests.test_step3_auth import PW, client, post, token, users  # noqa: F401  (fixtures)


def _login(c, next_value=None, via="query"):
    data = {"email": "user@test.com", "password": PW}
    url = "/login"
    if next_value is not None:
        if via == "query":
            url = f"/login?next={next_value}"
        else:
            data["next"] = next_value
    data["csrf_token"] = token(c, "/login")
    return c.post(url, data=data)


def test_default_redirect_is_the_home_page(client, users):
    r = _login(client)
    assert r.status_code == 302 and r.headers["Location"] == "/"


def test_welcome_flash_shows_once_on_the_home_page(client, users):
    r = _login(client)
    page = client.get(r.headers["Location"])
    html = page.get_data(as_text=True)
    assert page.status_code == 200
    assert 'class="alert alert--success"' in html and "Welcome back, User!" in html
    assert "Welcome back" not in client.get("/").get_data(as_text=True)   # consumed, not repeated


@pytest.mark.parametrize("nxt", ["/checkout", "/cart", "/account/orders"])
def test_safe_next_is_honoured(client, users, nxt):
    assert _login(client, nxt).headers["Location"] == nxt


def test_safe_next_in_form_field_is_honoured(client, users):
    assert _login(client, "/checkout", via="form").headers["Location"] == "/checkout"


@pytest.mark.parametrize("nxt", ["https://evil.com", "//evil.com", "/\\evil.com", "javascript:alert(1)", "evil.com", "/admin/", "/owner/orders"])
def test_unsafe_next_falls_back_to_home(client, users, nxt):
    assert _login(client, nxt).headers["Location"] == "/"


def test_staff_redirects_are_unchanged(client, users):
    r = client.post("/owner/login", data={"email": "owner@test.com", "password": PW, "csrf_token": token(client, "/owner/login")})
    assert r.headers["Location"] == "/owner/"
