"""Step 2 UI (2.1-2.3): one storefront stylesheet, one token set, shared empty/error/skeleton states, toast roles."""
import re
from pathlib import Path

from tests.test_step6_shop import cust, catalog, many  # noqa: F401  (fixtures)

STATIC = Path(__file__).resolve().parent.parent / "app" / "static"
CSS = (STATIC / "css" / "storefront.css").read_text(encoding="utf-8")
MERGED = ("shop", "rr-foods-overrides", "rr-storefront-layout", "rr-home-final", "rr-frontend-fix", "rr-bundle-deal",
          "rr-customer-final", "rr-ux-polish")


# ---------------------------------------------------------------- 2.1 one stylesheet
def test_storefront_pages_load_one_stylesheet(app, catalog):
    html = app.test_client().get("/").get_data(as_text=True)
    assert html.count("css/storefront.css") == 1
    for name in MERGED + ("base", "rr-foods-design"):
        assert f"css/{name}.css" not in html
    for name in MERGED:
        assert not (STATIC / "css" / f"{name}.css").exists()


def test_admin_and_owner_keep_their_own_stylesheets(app, session):
    from tests.helpers import make_user, sign_in
    make_user(session, "admin")
    c = app.test_client()
    sign_in(c, "admin")
    html = c.get("/admin/").get_data(as_text=True)
    assert "css/admin.css" in html and "storefront.css" not in html


def test_no_forced_light_or_dark_hacks_left():
    assert "[data-theme" not in CSS.replace("[data-theme-toggle]", "")
    assert not re.search(r"prefers-color-scheme\s*:\s*dark", CSS)
    assert not re.search(r"color-scheme\s*:[^;{}]*!important", CSS)


def test_no_important_on_custom_properties():
    assert not re.search(r"--[\w-]+\s*:[^;{}]*!important", CSS)


# ---------------------------------------------------------------- 2.2 one token set
def test_one_root_token_block_defines_the_core_tokens():
    roots = re.findall(r"(?m)^:root\s*\{([^}]*)\}", CSS)
    assert len(roots) >= 1
    block = roots[0]
    for token in ("--c-bg", "--c-surface", "--c-ink", "--c-muted", "--c-line", "--c-brand", "--c-brand-dark", "--c-focus", "--c-bad",
                  "--fs-sm", "--fs-md", "--fs-lg", "--fs-xl", "--fs-2xl", "--fs-3xl", "--sp-1", "--sp-4", "--sp-8",
                  "--radius", "--radius-lg", "--shadow", "--shadow-pop", "--ring", "--ring-color"):
        assert re.search(rf"{re.escape(token)}\s*:", block), token


def test_core_colour_tokens_are_defined_once():
    for token in ("--c-bg", "--c-ink", "--c-muted", "--c-brand", "--c-line", "--c-surface"):
        assert len(re.findall(rf"{re.escape(token)}\s*:", CSS)) == 1, token


def test_type_scale_is_a_1_2_ratio():
    block = re.findall(r"(?m)^:root\s*\{([^}]*)\}", CSS)[0]
    sizes = {k: float(v) for k, v in re.findall(r"--fs-(sm|md|lg|xl|2xl|3xl):\s*([\d.]+)rem", block)}
    order = ["sm", "md", "lg", "xl", "2xl", "3xl"]
    for a, b in zip(order, order[1:]):
        assert abs(sizes[b] / sizes[a] - 1.2) < 0.01, (a, b)


def test_spacing_tokens_are_multiples_of_4px():
    block = re.findall(r"(?m)^:root\s*\{([^}]*)\}", CSS)[0]
    for name, val in re.findall(r"--sp-(\d):\s*([\d.]+)rem", block):
        assert (float(val) * 16) % 4 == 0, name


def test_component_layer_uses_tokens_only():
    layer = CSS[CSS.index("/* ===== components: tokens only ===== */"):]
    layer = layer[:layer.index("/* skeleton layouts")]
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", layer)        # no hard-coded colours
    for cls in (".btn", ".input", ".card", ".alert", ".badge", ".toast", ".skel", ".empty"):
        assert cls in layer, cls


# ---------------------------------------------------------------- 2.3 shared states
def test_empty_states_use_the_shared_macro(cust):
    html = cust.get("/account/orders").get_data(as_text=True)
    assert 'class="empty"' in html and "No orders yet" in html and 'class="empty__art"' in html
    html = cust.get("/account/wishlist").get_data(as_text=True)
    assert "Your wishlist is empty" in html and 'class="empty__art"' in html


def test_listing_has_skeleton_templates_and_an_aria_busy_target(app, many):
    html = app.test_client().get("/shop").get_data(as_text=True)
    assert 'data-skel-container="listing"' in html and "js/ui-states.js" in html
    for tpl in ("skel-listing", "skel-product", "skel-cart"):
        assert f'<template id="{tpl}">' in html
    assert 'class="skel-grid" aria-hidden="true"' in html


def test_empty_listing_result_uses_empty_state_with_a_clear_link(app, many):
    html = app.test_client().get("/shop?min_price=99999").get_data(as_text=True)
    assert "No products match your filters" in html and 'class="empty__act"' in html and "Clear all filters" in html


def test_cart_page_has_its_skeleton_hooks(cust, catalog):
    from tests.test_step6_shop import add
    _, p = catalog
    add(cust, p, 1)
    html = cust.get("/cart").get_data(as_text=True)
    assert 'data-skel-container="cart"' in html and '<template id="skel-cart">' in html and "js/ui-states.js" in html


def test_toasts_switch_between_status_and_alert():
    for js in ("shop.js", "shell.js"):
        src = (STATIC / "js" / js).read_text(encoding="utf-8")
        assert 'toast.setAttribute("role", bad ? "alert" : "status")' in src
    assert 'id="toast" role="status"' in (Path(STATIC).parent / "templates" / "shop" / "layout.html").read_text(encoding="utf-8")


def test_skeletons_respect_reduced_motion():
    assert re.search(r"prefers-reduced-motion:\s*reduce\)\s*\{\s*\.skel\s*\{\s*animation:\s*none", CSS)
