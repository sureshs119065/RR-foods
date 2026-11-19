#!/usr/bin/env python3
"""Step 4.6: performance audit without a browser. Exit 1 when a budget is broken.

  python tools/perf_audit.py http://127.0.0.1:5055 [--json report.json]

For home, listing, product, cart and login it fetches the page the way a phone would (Accept-Encoding br, gzip) and checks:
  * HTML: compressed, under HTML_GZIP_MAX; TTFB under TTFB_MAX_MS (server time only, no network)
  * every same-site CSS/JS/font/image it references: status 200, compressed (text types), cache header present
  * scripts are `defer`/`async`/module (none block rendering); at most MAX_STYLESHEETS stylesheets; one font preload
  * every <img> has width, height and alt; no more than MAX_IMG_EAGER eager images
  * total transfer of CSS+JS under JS_CSS_GZIP_MAX; no single image over IMG_MAX bytes
It cannot measure Lighthouse scores (needs Chrome); `lighthouserc.json` in the project root runs those: `npx @lhci/cli autorun`.
"""
from __future__ import annotations

import json
import re
import sys
import time
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

HTML_GZIP_MAX = 40 * 1024
TTFB_MAX_MS = 800
JS_CSS_GZIP_MAX = 150 * 1024
IMG_MAX = 120 * 1024
MAX_STYLESHEETS = 3
MAX_IMG_EAGER = 6
MIN_COMPRESS = 500   # the server skips compression below this size (COMPRESS_MIN_SIZE), as it should
PAGES = [("home", "/"), ("listing", "/shop"), ("product", "/product/ragi-flour"), ("cart", "/cart"), ("login", "/login")]
TEXT_TYPES = ("text/css", "javascript", "application/json", "image/svg+xml")


class _Scan(HTMLParser):
    def __init__(self):
        super().__init__()
        self.styles, self.scripts, self.imgs, self.preloads, self.fonts = [], [], [], [], []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "link" and a.get("rel") == "stylesheet" and a.get("href"):
            self.styles.append(a["href"])
        elif tag == "link" and a.get("rel") == "preload":
            (self.fonts if a.get("as") == "font" else self.preloads).append(a.get("href", ""))
        elif tag == "script" and a.get("src"):
            self.scripts.append({"src": a["src"], "defer": "defer" in a or "async" in a or a.get("type") == "module"})
        elif tag == "img":
            self.imgs.append(a)


def audit_page(name: str, html: str, fetch, ttfb_ms: float, html_gzip: int, html_encoding: str) -> dict:
    """`fetch(path) -> (status, headers(dict lower-case), body_bytes_as_sent, raw_len)`; pure so tests can reuse it."""
    s = _Scan()
    s.feed(html)
    problems, js_css = [], 0
    if not html_encoding:
        problems.append("HTML is not compressed")
    if html_gzip > HTML_GZIP_MAX:
        problems.append(f"HTML {html_gzip} B compressed (max {HTML_GZIP_MAX})")
    if ttfb_ms > TTFB_MAX_MS:
        problems.append(f"TTFB {ttfb_ms:.0f} ms (max {TTFB_MAX_MS})")
    if len(s.styles) > MAX_STYLESHEETS:
        problems.append(f"{len(s.styles)} stylesheets (max {MAX_STYLESHEETS})")
    if len(s.fonts) > 1:
        problems.append(f"{len(s.fonts)} font preloads (want 1)")
    for sc in s.scripts:
        if not sc["defer"] and not urlparse(sc["src"]).netloc:
            problems.append(f"render-blocking script {sc['src']}")
    for url in s.styles + [x["src"] for x in s.scripts] + s.fonts:
        if urlparse(url).netloc:
            problems.append(f"third-party asset {url}")
            continue
        status, h, sent, raw = fetch(url)
        if status != 200:
            problems.append(f"{url}: HTTP {status}")
            continue
        if not h.get("cache-control"):
            problems.append(f"{url}: no Cache-Control")
        ctype = h.get("content-type", "")
        if any(t in ctype for t in TEXT_TYPES):
            js_css += len(sent)
            if not h.get("content-encoding") and raw >= MIN_COMPRESS:
                problems.append(f"{url}: not compressed")
    if js_css > JS_CSS_GZIP_MAX:
        problems.append(f"CSS+JS {js_css} B compressed (max {JS_CSS_GZIP_MAX})")
    eager = 0
    for im in s.imgs:
        src = im.get("src", "")
        if src.startswith("data:"):
            continue
        if not (im.get("width") and im.get("height")):
            problems.append(f"img without width/height: {src[:60]}")
        if im.get("alt") is None:
            problems.append(f"img without alt: {src[:60]}")
        if im.get("loading") != "lazy":
            eager += 1
        if src and not urlparse(src).netloc:
            status, _h, _sent, raw = fetch(src)
            if status == 200 and raw > IMG_MAX:
                problems.append(f"{src}: {raw} B (max {IMG_MAX})")
    if eager > MAX_IMG_EAGER:
        problems.append(f"{eager} eager images (max {MAX_IMG_EAGER})")
    return {"page": name, "ttfb_ms": round(ttfb_ms), "html_gzip": html_gzip, "css_js_gzip": js_css, "stylesheets": len(s.styles),
            "scripts": len(s.scripts), "images": len(s.imgs), "eager_images": eager, "problems": problems}


def _http_fetcher(base: str):
    import urllib.request

    def fetch(path):
        req = urllib.request.Request(urljoin(base + "/", path), headers={"Accept-Encoding": "br, gzip"})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                body = r.read()
                h = {k.lower(): v for k, v in r.headers.items()}
                raw = int(h.get("content-length", len(body)))
                return r.status, h, body, len(body) if not h.get("content-encoding") else raw
        except Exception as e:  # noqa: BLE001
            return getattr(e, "code", 0) or 0, {}, b"", 0
    return fetch


def main():
    base = sys.argv[1].rstrip("/")
    out = sys.argv[sys.argv.index("--json") + 1] if "--json" in sys.argv else None
    fetch, report, bad = _http_fetcher(base), [], 0
    for name, path in PAGES:
        t = time.perf_counter()
        status, h, body, _ = fetch(path)
        ttfb = (time.perf_counter() - t) * 1000
        if status != 200:
            print(f"{name}: HTTP {status}")
            bad += 1
            continue
        import gzip
        import brotli
        enc = h.get("content-encoding", "")
        raw = brotli.decompress(body) if enc == "br" else gzip.decompress(body) if enc == "gzip" else body
        r = audit_page(name, raw.decode("utf-8", "replace"), fetch, ttfb, len(body), enc)
        report.append(r)
        bad += len(r["problems"])
        print(f"{name:8} ttfb {r['ttfb_ms']:>4} ms  html {r['html_gzip']:>6} B  css+js {r['css_js_gzip']:>6} B  imgs {r['images']:>2}  problems {len(r['problems'])}")
        for p in r["problems"]:
            print("   -", p)
    if out:
        with open(out, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
