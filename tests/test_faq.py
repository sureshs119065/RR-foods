"""Part 5: customer FAQ (model, admin, home accordion, /faq, JSON-LD, cache) and the removal of the admin recipe routes."""
import importlib.util
import json
import re
from pathlib import Path

import pytest
from sqlalchemy import delete, select

from app.extensions import db
from app.models import Faq
from app.services import faqs as faq_svc
from app.services import home_cache
from tests.helpers import make_user, post, sign_in


@pytest.fixture()
def admin(app, session):
    make_user(session, "admin")
    c = app.test_client()
    sign_in(c, "admin")
    return c


@pytest.fixture(autouse=True)
def _no_seeded_faqs(session):
    """The first test of a run still sees the migration's starter questions (later tests find the tables truncated)."""
    session.execute(delete(Faq))
    session.commit()


def add(session, n, active=True):
    rows = [Faq(question=f"Question {i}?", answer=f"Answer {i}.", sort_order=i * 10, is_active=active) for i in range(1, n + 1)]
    session.add_all(rows)
    session.commit()
    return rows


def ld_blocks(html):
    return [json.loads(b) for b in re.findall(r'<script type="application/ld\+json">(.*?)</script>', html, re.S)]


def test_migration_seeds_six_to_eight_questions():
    path = next(Path("migrations/versions").glob("c8f2a6d4e913_*.py"))
    spec = importlib.util.spec_from_file_location("faq_mig", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert 6 <= len(mod.SEED) <= 8
    assert mod.down_revision == "b9e4d2a6c715"
    text = " ".join(q.lower() for q, _ in mod.SEED)
    for topic in ("deliver", "pay", "return", "track", "quality", "whatsapp"):
        assert topic in text


def test_admin_recipe_routes_are_gone_but_customer_recipes_stay(admin, app):
    for url in ("/admin/recipes", "/admin/recipes/new"):
        assert admin.get(url).status_code == 404
    html = admin.get("/admin/").get_data(as_text=True)
    assert "admin/recipes" not in html and 'href="/admin/faq"' in html
    assert app.test_client().get("/recipes").status_code == 200


def test_admin_faq_crud_toggle_move(admin, session):
    r = post(admin, "/admin/faq/new", {"question": "  Do you deliver?  ", "answer": "Yes.\r\n\r\nSee checkout.", "is_active": "1"}, page="/admin/faq/new")
    assert r.status_code == 302
    r = post(admin, "/admin/faq/new", {"question": "Second?", "answer": "Two.", "is_active": "1"}, page="/admin/faq/new")
    first, second = session.scalars(select(Faq).order_by(Faq.sort_order, Faq.id)).all()
    assert first.question == "Do you deliver?" and first.answer == "Yes.\n\nSee checkout." and first.sort_order < second.sort_order

    assert post(admin, "/admin/faq/new", {"question": "", "answer": ""}, page="/admin/faq/new").status_code == 200
    assert session.scalar(select(Faq).where(Faq.question == "")) is None

    post(admin, f"/admin/faq/{second.id}/move", {"direction": "up"}, page="/admin/faq")
    session.expire_all()
    assert [f.id for f in session.scalars(select(Faq).order_by(Faq.sort_order, Faq.id))] == [second.id, first.id]
    post(admin, f"/admin/faq/{second.id}/move", {"direction": "up"}, page="/admin/faq")  # already first: harmless
    assert post(admin, f"/admin/faq/{second.id}/move", {"direction": "sideways"}, page="/admin/faq").status_code == 400

    post(admin, f"/admin/faq/{first.id}/toggle", page="/admin/faq")
    session.expire_all()
    assert session.get(Faq, first.id).is_active is False

    post(admin, f"/admin/faq/{first.id}/edit", {"question": "Edited?", "answer": "New."}, page=f"/admin/faq/{first.id}/edit")
    session.expire_all()
    edited = session.get(Faq, first.id)
    assert (edited.question, edited.is_active) == ("Edited?", False)  # unticked box means hidden

    post(admin, f"/admin/faq/{first.id}/delete", page="/admin/faq")
    session.expire_all()
    assert session.get(Faq, first.id) is None
    assert admin.get("/admin/faq").status_code == 200


def test_admin_faq_requires_admin(app, session):
    c = app.test_client()
    assert c.get("/admin/faq").status_code in (302, 401, 403)


def test_settings_validate_range_and_save(admin, session):
    for bad in ("2", "11", "", "abc"):
        post(admin, "/admin/faq/settings", {"enabled": "1", "max_count": bad}, page="/admin/faq")
    assert faq_svc.get_settings() == {"enabled": True, "max_count": faq_svc.DEFAULT_COUNT}
    post(admin, "/admin/faq/settings", {"max_count": "7"}, page="/admin/faq")
    assert faq_svc.get_settings() == {"enabled": False, "max_count": 7}


def test_home_shows_limited_accordion_with_jsonld(app, session):
    add(session, 8)
    session.add(Faq(question="Hidden one?", answer="Secret.", sort_order=5, is_active=False))
    session.commit()
    html = app.test_client().get("/").get_data(as_text=True)
    assert html.count('class="faq__btn"') == faq_svc.DEFAULT_COUNT
    assert 'aria-expanded' in html and 'href="/faq"' in html and "View all FAQs" in html
    assert "Hidden one?" not in html
    assert html.index('id="faq"') < html.index('id="customer-message"') < html.index("<footer")
    page = next(b for b in ld_blocks(html) if isinstance(b, dict) and b.get("@type") == "FAQPage")
    assert [q["name"] for q in page["mainEntity"]] == [f"Question {i}?" for i in range(1, 6)]
    assert "<script>" not in html.split('application/ld+json')[-1].split("</script>")[0]


def test_home_count_setting_and_off_switch(app, session):
    add(session, 10)
    faq_svc.save_settings(True, 3); session.commit()
    c = app.test_client()
    assert c.get("/").get_data(as_text=True).count('class="faq__btn"') == 3
    faq_svc.save_settings(False, 3); session.commit()
    html = c.get("/").get_data(as_text=True)
    assert 'class="faq__btn"' not in html and "FAQPage" not in html
    assert c.get("/faq").get_data(as_text=True).count('class="faq__btn"') == 10  # the full page ignores the home setting


def test_faq_page_lists_all_active_and_escapes_jsonld(app, session):
    session.add(Faq(question='Is it </script><b>safe</b>?', answer="Yes & <i>no</i>", sort_order=1))
    session.commit()
    r = app.test_client().get("/faq")
    html = r.get_data(as_text=True)
    assert r.status_code == 200 and "&lt;/script&gt;" in html
    assert ld_blocks(html)[0]["mainEntity"][0]["name"] == 'Is it </script><b>safe</b>?'  # parses back intact: nothing broke out of the tag


def test_home_cache_is_cleared_when_faqs_change(app, session):
    app.config["HOME_CACHE_SECONDS"] = 60
    home_cache.bust()
    try:
        rows = add(session, 4)
        c = app.test_client()
        assert "Question 1?" in c.get("/").get_data(as_text=True)
        rows[0].question = "Renamed question?"
        session.commit()
        html = c.get("/").get_data(as_text=True)
        assert "Renamed question?" in html and "Question 1?" not in html
        session.delete(rows[1]); session.commit()
        assert "Question 2?" not in c.get("/").get_data(as_text=True)
    finally:
        app.config["HOME_CACHE_SECONDS"] = 0
        home_cache.bust()
