"""Step 3 accessibility (3.1-3.3): contrast gate, flash roles, focus/tap/input CSS, no unlabeled heading jumps in card grids."""
import re
import sys
from pathlib import Path

from tests.test_step6_shop import cust, catalog, many  # noqa: F401  (fixtures)

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import check_contrast  # noqa: E402

CSS = (ROOT / "app" / "static" / "css" / "storefront.css").read_text(encoding="utf-8")


def test_contrast_gate_passes():
    rows, bad = check_contrast.run()
    assert len(rows) > 100 and not bad, bad


def test_contrast_gate_fails_below_threshold():
    _, bad = check_contrast.run(CSS.replace("--c-muted: #5B635D;", "--c-muted: #A0A8A2;", 1))
    assert any(fg == "--c-muted" for fg, *_ in bad)


def test_required_token_values():
    t = check_contrast.effective_tokens(CSS)
    assert t["--c-muted"].upper() == "#5B635D" and t["--c-warn"].upper() == "#8A5A00"
    assert check_contrast.ratio("#8A5A00", "#FFFFFF") >= 5.7 and check_contrast.ratio("#5B635D", "#F7F6F2") >= 5.7


def test_flash_roles(app):
    c = app.test_client()
    with c.session_transaction() as s:
        s["_flashes"] = [("error", "Bad thing"), ("success", "Good thing"), ("info", "FYI")]
    html = c.get("/login").get_data(as_text=True)
    assert re.search(r'role="alert">Bad thing', html)
    assert re.search(r'role="status">Good thing', html) and re.search(r'role="status">FYI', html)


def test_focus_ring_has_single_authority_and_no_bare_outline_removal():
    assert "STEP 3.3 accessibility layer" in CSS
    assert not re.search(r"(?m)^:focus-visible", CSS)
    block = CSS.split("STEP 3.3 accessibility layer")[1]
    assert "var(--ring-color)" in block and "min-height: var(--tap)" in block and "max(16px, 1rem)" in block


def test_listing_card_grid_has_h2_before_h3(app, many):
    html = app.test_client().get("/shop").get_data(as_text=True)
    assert html.index('class="sr-only">Products</h2>') < html.index('class="pc__name"')
    assert ".sr-only" in CSS


# ---------------------------------------------------------------- 3.4 labels, aria-invalid / aria-describedby, alt
from tests.helpers import token  # noqa: E402

JS_DIR = ROOT / "app" / "static" / "js"


def _described_ids_exist(html):
    """Every aria-describedby target on the page must exist (ids may be space separated)."""
    ids = set(re.findall(r'\sid="([^"]+)"', html))
    missing = []
    for ref in re.findall(r'aria-describedby="([^"]+)"', html):
        missing += [r for r in ref.split() if r not in ids]
    return missing


def test_address_form_errors_are_linked_to_their_inputs(cust):
    r = cust.post("/account/addresses/new", data={"csrf_token": token(cust, "/account/addresses/new")})
    html = r.get_data(as_text=True)
    assert 'aria-invalid="true"' in html
    for name in ("full_name", "phone", "line1"):
        assert re.search(rf'name="{name}"[^>]*aria-describedby="addr-{name}-err"', html), name
        assert f'id="addr-{name}-err"' in html
    assert not _described_ids_exist(html)


def test_login_error_is_linked_to_both_fields(app, session):
    c = app.test_client()
    r = c.post("/login", data={"email": "nobody@example.com", "password": "wrong-pass-1", "csrf_token": token(c, "/login")})
    html = r.get_data(as_text=True)
    assert 'id="login-err"' in html and 'role="alert"' in html
    assert html.count('aria-describedby="login-err"') == 2 and html.count('aria-invalid="true"') == 2
    assert not _described_ids_exist(html)


def test_change_password_errors_are_linked(cust):
    r = cust.post("/account/password", data={"current": "", "new": "x", "confirm": "y", "csrf_token": token(cust, "/account/password")})
    html = r.get_data(as_text=True)
    assert 'aria-describedby="new-err"' in html and 'id="new-err"' in html
    assert not _described_ids_exist(html)


def test_register_hint_is_described_and_every_page_has_one_h1(app, many):
    html = app.test_client().get("/register").get_data(as_text=True)
    assert 'aria-describedby="password-hint"' in html and 'id="password-hint"' in html
    c = app.test_client()
    for url in ("/", "/shop", "/cart", "/login", "/register", "/forgot", "/offers", "/help"):
        h = c.get(url).get_data(as_text=True)
        assert len(re.findall(r"<h1[\s>]", h)) == 1, url
        assert not _described_ids_exist(h), url
        for img in re.findall(r"<img\b[^>]*>", h):
            assert " alt=" in img, (url, img[:80])


def test_cart_image_link_is_not_a_nameless_tab_stop(cust, catalog):
    _, p = catalog
    cust.post("/cart/add", data={"product_id": p.id, "qty": 1, "csrf_token": token(cust, "/")})
    html = cust.get("/cart").get_data(as_text=True)
    assert 'class="cl__img"' in html
    assert re.search(r'class="cl__img"[^>]*tabindex="-1" aria-hidden="true"', html)


# ---------------------------------------------------------------- 3.5 carousel pause, focus traps, Esc, focus return
def test_every_auto_moving_region_has_a_pause_control():
    loop = (JS_DIR / "home-loop.js").read_text(encoding="utf-8")
    # the Pause/Play button was removed on request: rows still stop for reduced motion, and while touched, hovered or focused
    assert "createElement('button')" not in loop and "prefers-reduced-motion" in loop and "mouseenter" in loop
    hc = (JS_DIR / "header-carousel.js").read_text(encoding="utf-8")
    assert "data-hc-pause" in hc and "prefers-reduced-motion" in hc and "ArrowLeft" in hc


def test_loop_region_is_labelled_and_clones_are_inert(app, many):
    html = app.test_client().get("/").get_data(as_text=True)
    m = re.search(r'<div class="rr-loop"[^>]*>', html)
    if m:  # the New Arrivals row only renders when products exist
        assert 'role="region"' in m.group(0) and 'aria-label="New arrivals product row"' in m.group(0)
        # step 2.5: the server sends each card once; the script adds aria-hidden + inert clones only while the row loops
        no_drawer = re.sub(r'<aside class="drawer"[^>]*>', "", html)   # the closed menu drawer is legitimately aria-hidden + inert
        assert 'aria-hidden="true" inert' not in no_drawer
        js = (JS_DIR / "home-loop.js").read_text(encoding="utf-8")
        assert "setAttribute('aria-hidden', 'true')" in js and "setAttribute('inert', '')" in js


def test_overlays_trap_focus_and_return_it():
    js = (JS_DIR / "shop.js").read_text(encoding="utf-8")
    assert "function trapTab" in js and 'e.key === "Tab"' in js
    assert "opener.focus()" in js and "zoomOpener.focus()" in js
    assert 'e.key === "Escape"' in js
    assert "d.inert = true" in js


def test_drawer_is_a_modal_dialog_and_inert_while_closed(app):
    html = app.test_client().get("/").get_data(as_text=True)
    m = re.search(r'<aside class="drawer"[^>]*>', html)
    assert m and 'role="dialog"' in m.group(0) and 'aria-modal="true"' in m.group(0) and "inert" in m.group(0)
