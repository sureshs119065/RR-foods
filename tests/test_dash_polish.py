import pytest

from tests.helpers import make_user, sign_in


def _client(app, session, role):
    make_user(session, role)
    c = app.test_client()
    sign_in(c, role)
    return c


def test_admin_dashboard_has_attention_strip_and_polish_assets(app, session):
    html = _client(app, session, "admin").get("/admin/").get_data(as_text=True)
    assert "dp-attn" in html and "data-dp-greet" in html and "dash-polish.css" in html and "dash-polish.js" in html
    assert "All clear" in html  # empty store: nothing needs attention


def test_owner_dashboard_has_attention_strip(app, session):
    html = _client(app, session, "owner").get("/owner/").get_data(as_text=True)
    assert "dp-attn" in html and "data-dp-refresh" in html and "dash-polish.js" in html
    assert "All caught up" in html
