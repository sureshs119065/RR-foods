import pytest

PAGES = ["/login", "/register", "/forgot", "/admin/login", "/owner/login"]


@pytest.mark.parametrize("url", PAGES)
def test_auth_pages_have_no_site_header_or_footer(app, session, url):
    r = app.test_client().get(url)
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert 'class="auth-page"' in html and "auth-page.css" in html
    assert "<footer" not in html and 'data-footer' not in html
    assert "Track Orders" not in html and 'class="sf"' not in html


def test_storefront_pages_keep_header_and_footer(app, session):
    html = app.test_client().get("/").get_data(as_text=True)
    assert "data-footer" in html and "Track Orders" in html
