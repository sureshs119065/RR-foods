#!/usr/bin/env python3
"""Browser audit for Step 3 (needs a running app + playwright/chromium).

  python tools/a11y_audit.py http://127.0.0.1:5055 [--login user@x.local:password]

Checks per page at a 390px viewport: tap targets < 44px, text inputs < 16px, controls with no accessible name or label,
images without alt, heading order / h1 count, and keyboard-focus visibility (tabs through the first 60 stops).
"""
import json
import sys

from playwright.sync_api import sync_playwright

PAGES = ["/", "/shop", "/shop?q=ragi", "/product/ragi-flour", "/cart", "/login", "/register", "/forgot", "/help", "/offers", "/about", "/bundles", "/recipes"]
AUTH_PAGES = ["/account", "/checkout", "/account/orders", "/account/wishlist", "/account/addresses/new", "/account/messages/new", "/account/password"]

JS = r"""
() => {
  const vis = e => { const r = e.getBoundingClientRect(), s = getComputedStyle(e);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none' && !e.closest('[hidden],[inert],[aria-hidden=true]'); };
  const sel = 'a[href],button,input:not([type=hidden]),select,textarea,summary,[role=button],[role=tab],[tabindex]:not([tabindex="-1"])';
  const out = {small: [], font: [], noname: [], noalt: [], headings: [], h1: 0};
  const name = e => (e.getAttribute('aria-label') || e.getAttribute('aria-labelledby') && document.getElementById(e.getAttribute('aria-labelledby').split(' ')[0])?.textContent
      || e.labels && e.labels[0]?.textContent || e.textContent || e.getAttribute('title') || e.getAttribute('alt') || e.querySelector('img[alt]')?.alt || e.querySelector('svg title')?.textContent || '').trim();
  const desc = e => e.tagName.toLowerCase() + (e.id ? '#' + e.id : '') + (e.className && typeof e.className === 'string' ? '.' + e.className.trim().split(/\s+/).slice(0, 2).join('.') : '') + ' ' + name(e).slice(0, 24);
  document.querySelectorAll(sel).forEach(e => {
    if (!vis(e)) return;
    const r = e.getBoundingClientRect(), t = e.type;
    const inline = e.tagName === 'A' && getComputedStyle(e).display === 'inline' && e.closest('p,li,td,small,span:not([class])') && e.textContent.trim().split(/\s+/).length > 2;
    const hidden_input = (t === 'checkbox' || t === 'radio') && (r.width < 24);
    if (!inline && !hidden_input && (r.height < 43.5 || r.width < 43.5) && !(e.tagName==='A' && e.closest('p'))) out.small.push(desc(e) + ' ' + Math.round(r.width) + 'x' + Math.round(r.height));
    if (['INPUT', 'SELECT', 'TEXTAREA'].includes(e.tagName) && !['checkbox', 'radio', 'submit', 'button', 'range', 'file'].includes(t) && parseFloat(getComputedStyle(e).fontSize) < 15.99) out.font.push(desc(e) + ' ' + getComputedStyle(e).fontSize);
    if (['INPUT', 'SELECT', 'TEXTAREA', 'BUTTON', 'A'].includes(e.tagName) && !name(e)) out.noname.push(desc(e));
  });
  document.querySelectorAll('img').forEach(i => { if (!i.hasAttribute('alt')) out.noalt.push(i.src.split('/').pop().slice(0, 40)); });
  document.querySelectorAll('h1,h2,h3,h4,h5,h6').forEach(h => { if (vis(h)) out.headings.push(+h.tagName[1]); });
  out.h1 = out.headings.filter(x => x === 1).length;
  return out;
}
"""

FOCUS_JS = r"""
() => { const e = document.activeElement; if (!e || e === document.body) return null;
  const s = getComputedStyle(e); const ow = parseFloat(s.outlineWidth) || 0;
  const ring = (s.outlineStyle !== 'none' && ow >= 2) || (s.boxShadow && s.boxShadow !== 'none');
  let p = e.parentElement, within = false;
  while (p && !within) { const ps = getComputedStyle(p); within = p.matches(':focus-within') && ((ps.outlineStyle !== 'none' && parseFloat(ps.outlineWidth) >= 2) || ps.boxShadow !== 'none') && p.tagName !== 'BODY' && p.tagName !== 'HTML' && p !== document.body; p = p.parentElement; if (within) break; if (!p || p.tagName==='BODY') break; }
  return {ok: ring || within, d: e.tagName.toLowerCase() + (e.className && typeof e.className === 'string' ? '.' + e.className.trim().split(/\s+/)[0] : '') + ' ' + (e.textContent || e.getAttribute('aria-label') || '').trim().slice(0, 20)}; }
"""


def heading_problems(h):
    bad = []
    for a, b in zip(h, h[1:]):
        if b > a + 1:
            bad.append(f"h{a}->h{b}")
    return bad


def main():
    base = sys.argv[1].rstrip("/")
    login = next((a.split("=", 1)[1] if "=" in a else sys.argv[sys.argv.index(a) + 1] for a in sys.argv if a.startswith("--login")), None)
    pages = list(PAGES)
    total = 0
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
        pg = ctx.new_page()
        if login:
            email, pw = login.split(":", 1)
            pg.goto(base + "/login"); pg.fill("input[name=email]", email); pg.fill("input[name=password]", pw)
            pg.click("form button[type=submit]"); pg.wait_for_load_state(); pages += AUTH_PAGES
        for path in pages:
            pg.goto(base + path); pg.wait_for_load_state("networkidle")
            r = pg.evaluate(JS)
            nofocus = []
            pg.evaluate("document.activeElement && document.activeElement.blur()")
            for _ in range(60):
                pg.keyboard.press("Tab")
                f = pg.evaluate(FOCUS_JS)
                if f and not f["ok"]:
                    nofocus.append(f["d"])
            issues = {"small_targets": sorted(set(r["small"])), "input_font": sorted(set(r["font"])), "no_name": sorted(set(r["noname"])),
                      "img_no_alt": sorted(set(r["noalt"])), "h1_count": r["h1"] if r["h1"] != 1 else None,
                      "heading_jumps": heading_problems(r["headings"]) or None, "no_focus_ring": sorted(set(nofocus))}
            issues = {k: v for k, v in issues.items() if v}
            total += sum(len(v) if isinstance(v, list) else 1 for v in issues.values())
            print(("OK   " if not issues else "FAIL ") + path)
            if issues:
                print(json.dumps(issues, indent=1)[:1800])
        b.close()
    print("TOTAL issues:", total)
    sys.exit(1 if total else 0)


main()
