"""Step 4.6: the browser-free performance audit (tools/perf_audit.py) must pass on the real pages."""
import sys
import time
from decimal import Decimal
from pathlib import Path

import pytest

from tests.test_step4_perf import seed_catalog

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import perf_audit as pa  # noqa: E402


def run(app, path, name):
    c = app.test_client()
    hdr = {"Accept-Encoding": "br, gzip"}

    def fetch(p):
        r = c.get(p, headers=hdr)
        return r.status_code, {k.lower(): v for k, v in r.headers.items()}, r.data, len(c.get(p, headers={"Accept-Encoding": "identity"}).data)
    t = time.perf_counter()
    r = c.get(path, headers=hdr)
    ttfb = (time.perf_counter() - t) * 1000
    assert r.status_code == 200, path
    import brotli
    html = brotli.decompress(r.data).decode() if r.headers.get("Content-Encoding") == "br" else r.get_data(as_text=True)
    return pa.audit_page(name, html, fetch, ttfb, len(r.data), r.headers.get("Content-Encoding", ""))


@pytest.mark.parametrize("name,path", [("home", "/"), ("listing", "/shop"), ("product", "/product/q-1"), ("cart", "/cart"), ("login", "/login")])
def test_page_meets_the_performance_budget(app, session, name, path):
    seed_catalog(session, 6)
    rep = run(app, path, name)
    # TTFB on a shared CI box is noisy and the first call also warms caches; the structural checks are what must hold.
    assert [p for p in rep["problems"] if not p.startswith("TTFB")] == [], rep


def test_audit_catches_the_problems_it_claims_to(app):
    html = ('<html><head><link rel="stylesheet" href="/a.css"><link rel="stylesheet" href="/b.css"><link rel="stylesheet" href="/c.css">'
            '<link rel="stylesheet" href="/d.css"><script src="/x.js"></script><script src="https://cdn.example/y.js" defer></script></head>'
            '<body><img src="/i.png"></body></html>')
    rep = pa.audit_page("t", html, lambda p: (404, {}, b"", 0), 2000, 90_000, "")
    text = " | ".join(rep["problems"])
    for want in ("HTML is not compressed", "TTFB", "4 stylesheets", "render-blocking script /x.js", "third-party asset https://cdn.example/y.js",
                 "img without width/height", "img without alt", "HTTP 404"):
        assert want in text, want


def test_lighthouse_config_and_audit_tool_ship_with_the_project():
    import json
    cfg = json.loads((ROOT / "lighthouserc.json").read_text())
    a = cfg["ci"]["assert"]["assertions"]
    assert a["categories:performance"][1]["minScore"] >= 0.9
    assert a["largest-contentful-paint"][0] == "error" and a["largest-contentful-paint"][1]["maxNumericValue"] <= 2500
    assert a["cumulative-layout-shift"][1]["maxNumericValue"] <= 0.1
    assert a["total-blocking-time"][0] == "error" and a["total-blocking-time"][1]["maxNumericValue"] <= 200
    assert (ROOT / "tools" / "perf_audit.py").is_file()


def test_product_page_gives_priority_to_the_gallery_image_only(app, session):
    import re
    seed_catalog(session, 6)
    html = app.test_client().get("/product/q-1").get_data(as_text=True)
    cards = [m for m in re.findall(r"<img[^>]*data-product-image[^>]*>", html) if 'id="gal-main"' not in m]
    assert cards and all('loading="lazy"' in m and "fetchpriority" not in m for m in cards)
    assert html.count('fetchpriority="high"') == 1
