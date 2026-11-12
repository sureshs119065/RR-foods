"""Real-browser layout audit (Chromium via Playwright) against a RUNNING, SEEDED site.

  pip install playwright && playwright install chromium
  BASE_URL=http://127.0.0.1:5000 AUDIT_USER=... AUDIT_OWNER=... AUDIT_ADMIN=... python scripts/layout_audit.py

Narrow a run (recommended, the full run is slow):  AUDIT_ROLES=public,user  AUDIT_WIDTHS=360,1366  AUDIT_OUT=report.json
Set CHROME_PATH if Playwright cannot find its browser.

Per page and width it checks: sideways page scroll, elements sticking out of the screen, tap targets under 44 px and inputs
under 16 px (phones only), JS errors, failed requests, images without alt text, and layout shift (CLS).
Exit code 1 on a hard failure (sideways scroll, JS error, failed request). This is a local-server check: it does NOT replace
Lighthouse or a test on real phones.
"""
import json
import os
import sys
from collections import defaultdict

from playwright.sync_api import sync_playwright

BASE = os.environ.get("BASE_URL", "http://127.0.0.1:5000").rstrip("/")
CHROME = os.environ.get("CHROME_PATH") or None
WIDTHS = [(320, 640), (360, 640), (390, 844), (412, 915), (480, 800), (768, 1024), (1024, 768), (1366, 768), (1920, 1080)]
_only = {int(x) for x in os.environ.get("AUDIT_WIDTHS", "").split(",") if x}
if _only:
    WIDTHS = [wh for wh in WIDTHS if wh[0] in _only]
PHONE_MAX = 480
EMAIL = {"user": "user@nurseskitchen.local", "owner": "owner@nurseskitchen.local", "admin": "admin@nurseskitchen.local"}
LOGIN = {"user": "/login", "owner": "/owner/login", "admin": "/admin/login"}
PW = {r: os.environ.get(f"AUDIT_{r.upper()}", "") for r in EMAIL}
PAGES = {
    None: ["/", "/shop", "/shop?q=milet", "/offers", "/compare", "/login", "/register", "/forgot", "/offline", "/no-such-page"],
    "user": ["/account", "/cart", "/checkout", "/account/orders", "/account/addresses", "/account/addresses/new", "/account/wishlist", "/notifications"],
    "owner": ["/owner/", "/owner/inventory", "/owner/orders", "/owner/orders?tab=all", "/owner/stock-history", "/owner/questions", "/owner/password"],
    "admin": ["/admin/", "/admin/products", "/admin/products/new", "/admin/categories", "/admin/offers", "/admin/coupons",
              "/admin/header-banners", "/admin/header-banners/new", "/admin/users", "/admin/audit", "/admin/reviews", "/admin/password"],
}
JS_MEASURE = """(phone) => {
  const vw = document.documentElement.clientWidth;
  const res = {scrollW: document.documentElement.scrollWidth, vw, overflow: [], small: [], smallInputs: [], noAlt: []};
  const sel = (e) => e.tagName.toLowerCase() + (e.id ? '#' + e.id : '') + (e.className && typeof e.className === 'string' ? '.' + e.className.trim().split(/\\s+/).slice(0, 2).join('.') : '');
  const visible = (e) => { const r = e.getBoundingClientRect(); const s = getComputedStyle(e); return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none'; };
  const scrollsX = (e) => { for (let p = e.parentElement; p; p = p.parentElement) { const o = getComputedStyle(p).overflowX; if ((o === 'auto' || o === 'scroll' || o === 'hidden') && p !== document.body && p !== document.documentElement) return true; } return false; };
  for (const e of document.body.querySelectorAll('*')) {
    if (!visible(e)) continue;
    const r = e.getBoundingClientRect();
    if (r.right > vw + 1 && !scrollsX(e) && getComputedStyle(e).position !== 'fixed') res.overflow.push(sel(e) + ' right=' + Math.round(r.right));
  }
  if (phone) {
    for (const e of document.querySelectorAll('a[href], button, input:not([type=hidden]), select, textarea, summary, [role=button]')) {
      if (!visible(e) || e.classList.contains('skip')) continue;
      const r = e.getBoundingClientRect(), s = getComputedStyle(e);
      if (e.tagName === 'A' && s.display === 'inline') continue;
      if (e.type === 'checkbox' || e.type === 'radio') { const lab = e.closest('label'); if (lab && lab.getBoundingClientRect().height >= 44) continue; }
      if (r.width < 43.5 || r.height < 43.5) res.small.push(sel(e) + ' ' + Math.round(r.width) + 'x' + Math.round(r.height));
      if (/^(INPUT|SELECT|TEXTAREA)$/.test(e.tagName) && !['checkbox','radio','file','range','submit','button'].includes(e.type) && parseFloat(s.fontSize) < 16) res.smallInputs.push(sel(e) + ' ' + s.fontSize);
    }
  }
  for (const i of document.images) if (!i.hasAttribute('alt')) res.noAlt.push(i.getAttribute('src'));
  return res;
}"""
INIT = "window.__cls = 0; new PerformanceObserver((l) => { for (const e of l.getEntries()) if (!e.hadRecentInput) window.__cls += e.value; }).observe({type: 'layout-shift', buffered: true});"


def sign_in(browser, role):
    ctx = browser.new_context(viewport={"width": 390, "height": 844})
    page = ctx.new_page()
    page.goto(BASE + LOGIN[role])
    page.fill('input[name="email"]', EMAIL[role])
    page.fill('input[name="password"]', PW[role])
    page.click('form button[type="submit"], form input[type="submit"]')
    page.wait_for_load_state("networkidle")
    state = ctx.storage_state()
    ctx.close()
    return state


def audit():
    report, hard = defaultdict(list), []
    roles = os.environ.get("AUDIT_ROLES", "public,user,owner,admin").split(",")
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=CHROME, args=["--no-sandbox"])
        for role, urls in PAGES.items():
            if (role or "public") not in roles:
                continue
            state = sign_in(browser, role) if role else None
            for w, h in WIDTHS:
                ctx = browser.new_context(viewport={"width": w, "height": h}, storage_state=state, has_touch=w <= PHONE_MAX, is_mobile=w <= PHONE_MAX)
                ctx.add_init_script(INIT)
                for path in urls:
                    page = ctx.new_page()
                    problems = []
                    page.on("console", lambda m: problems.append(("console", m.text)) if m.type == "error" and "404" not in m.text else None)
                    page.on("pageerror", lambda e: problems.append(("js", str(e))))
                    page.on("requestfailed", lambda r: problems.append(("request", f"{r.url} {r.failure}")))
                    page.goto(BASE + path, wait_until="networkidle")
                    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    page.wait_for_timeout(300)
                    page.evaluate("window.scrollTo(0, 0)")
                    m = page.evaluate(JS_MEASURE, w <= PHONE_MAX)
                    m["cls"] = round(page.evaluate("window.__cls"), 3)
                    key = f"{role or 'public'} {path} @{w}"
                    if m["scrollW"] > m["vw"] + 1:
                        hard.append(f"SIDEWAYS SCROLL {key}: page {m['scrollW']}px in {m['vw']}px; e.g. {m['overflow'][:3]}")
                    for kind, msg in problems:
                        hard.append(f"{kind.upper()} {key}: {msg[:200]}")
                    for k in ("overflow", "small", "smallInputs", "noAlt"):
                        report[k] += [f"{key}: {i}" for i in m[k]]
                    if m["cls"] > 0.1:
                        report["cls"].append(f"{key}: CLS {m['cls']}")
                    page.close()
                ctx.close()
        browser.close()
    out = {"hard_failures": sorted(set(hard))}
    out.update({k: sorted(set(v)) for k, v in report.items()})
    json.dump(out, open(os.environ.get("AUDIT_OUT", "audit-report.json"), "w"), indent=1)
    print(f"hard failures: {len(out['hard_failures'])}")
    for k in ("overflow", "small", "smallInputs", "noAlt", "cls"):
        print(f"{k}: {len(out.get(k, []))}")
    for line in out["hard_failures"][:25]:
        print("  !", line)
    return 1 if out["hard_failures"] else 0


if __name__ == "__main__":
    sys.exit(audit())
