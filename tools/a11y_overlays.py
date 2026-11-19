#!/usr/bin/env python3
"""Browser check for Step 3.5 (needs a running app + playwright/chromium).

  python tools/a11y_overlays.py http://127.0.0.1:5055

At 390px: for the menu drawer, search overlay, filter sheet and image zoom it checks that Tab stays inside the open overlay (both
directions), Esc closes it, and focus returns to the control that opened it. It also checks the New Arrivals Pause/Play button.
"""
import sys

from playwright.sync_api import sync_playwright

INSIDE = "(sel) => { const b = document.querySelector(sel); return !!b && b.contains(document.activeElement); }"
VISIBLE = ("(sel) => { const b = document.querySelector(sel); if (!b) return false; const r = b.getBoundingClientRect(); const s = getComputedStyle(b);"
           " return !b.hidden && !b.inert && s.visibility !== 'hidden' && r.right > 0 && r.left < innerWidth && r.bottom > 0 && r.width > 0; }")


def check_overlay(pg, name, opener_sel, box_sel, results, tabs=40):
    pg.click(opener_sel)
    pg.wait_for_timeout(450)
    ok = True
    for key in ["Tab"] * tabs + ["Shift+Tab"] * (tabs // 2):
        pg.keyboard.press(key)
        if not pg.evaluate(INSIDE, box_sel):
            ok = False
            break
    results.append((f"{name}: Tab/Shift+Tab stay inside", ok))
    pg.keyboard.press("Escape")
    pg.wait_for_timeout(450)
    results.append((f"{name}: Esc closes", not pg.evaluate(VISIBLE, box_sel)))
    results.append((f"{name}: focus returns to opener", pg.evaluate("(sel) => document.activeElement === document.querySelector(sel)", opener_sel)))


def main():
    base = sys.argv[1].rstrip("/")
    results = []
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
        pg = ctx.new_page()
        pg.goto(base + "/shop")
        pg.wait_for_load_state("networkidle")
        check_overlay(pg, "menu drawer", "[data-open=drawer]", "#drawer", results)
        check_overlay(pg, "search overlay", "[data-open=search]", "#search-overlay", results)
        if pg.query_selector("[data-sheet-open]"):
            check_overlay(pg, "filter sheet", "[data-sheet-open]", "#filter-form", results)
        pg.goto(base + "/product/ragi-flour")
        pg.wait_for_load_state("networkidle")
        if pg.query_selector("[data-zoom]"):
            check_overlay(pg, "image zoom", "[data-zoom]", "#zoom", results, tabs=6)
        results.append(("closed drawer is inert", pg.evaluate("() => { const d = document.querySelector('#drawer'); return !d || d.inert; }")))
        pg.goto(base + "/")
        pg.wait_for_load_state("networkidle")
        btn = pg.query_selector(".rr-loop__pause")
        if btn:
            btn.click()
            results.append(("loop pause button pressed state", btn.get_attribute("aria-pressed") == "true"))
            x1 = pg.evaluate("document.querySelector('[data-loop]').scrollLeft")
            pg.wait_for_timeout(900)
            x2 = pg.evaluate("document.querySelector('[data-loop]').scrollLeft")
            results.append(("loop stops moving when paused", abs(x2 - x1) < 2))
            btn.click()
            pg.wait_for_timeout(1200)
            x3 = pg.evaluate("document.querySelector('[data-loop]').scrollLeft")
            results.append(("loop moves again after Play", abs(x3 - x2) > 2))
        else:
            results.append(("loop pause button present", False))
        b.close()
    bad = 0
    for label, ok in results:
        print(("OK   " if ok else "FAIL ") + label)
        bad += 0 if ok else 1
    print("TOTAL failures:", bad)
    sys.exit(1 if bad else 0)


main()
