#!/usr/bin/env python3
"""Step 3.6: run axe-core (WCAG 2.0/2.1/2.2 A + AA rules) in Chromium on the key pages. Exit 1 on any serious/critical violation.

  npm install axe-core@4.10.2            (anywhere; point AXE_JS at node_modules/axe-core/axe.min.js)
  python tools/axe_audit.py http://127.0.0.1:5055 --login user@x.local:password [--json report.json]

Pages: home, listing, product, cart, checkout, login, account (checkout and account need --login). Runs at 1280px and 390px.
"""
import json
import os
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

AXE_JS = Path(os.environ.get("AXE_JS", "node_modules/axe-core/axe.min.js"))
PUBLIC = [("home", "/"), ("listing", "/shop"), ("product", "/product/ragi-flour"), ("cart", "/cart"), ("login", "/login")]
PRIVATE = [("checkout", "/checkout"), ("account", "/account")]
TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa", "best-practice"]


def arg(name):
    for i, a in enumerate(sys.argv):
        if a == name and i + 1 < len(sys.argv):
            return sys.argv[i + 1]
        if a.startswith(name + "="):
            return a.split("=", 1)[1]
    return None


def main():
    base = sys.argv[1].rstrip("/")
    login, out = arg("--login"), arg("--json")
    src = AXE_JS.read_text(encoding="utf-8")
    report, blocking = {}, 0
    with sync_playwright() as p:
        b = p.chromium.launch()
        for label, vp, mobile in (("desktop", {"width": 1280, "height": 900}, False), ("mobile", {"width": 390, "height": 844}, True)):
            ctx = b.new_context(viewport=vp, is_mobile=mobile, has_touch=mobile, bypass_csp=True)
            pg = ctx.new_page()
            pages = list(PUBLIC)
            if login:
                email, pw = login.split(":", 1)
                pg.goto(base + "/login")
                pg.fill("input[name=email]", email)
                pg.fill("input[name=password]", pw)
                pg.click("form button[type=submit]")
                pg.wait_for_load_state("networkidle")
                pages += PRIVATE
            for name, path in pages:
                pg.goto(base + path)
                pg.wait_for_load_state("networkidle")
                pg.add_script_tag(content=src)
                res = pg.evaluate("(tags) => axe.run(document, {runOnly: {type: 'tag', values: tags}})", TAGS)
                rows = []
                for v in res["violations"]:
                    rows.append({"id": v["id"], "impact": v["impact"], "help": v["help"], "nodes": [n["target"] for n in v["nodes"]][:6], "count": len(v["nodes"])})
                bad = [r for r in rows if r["impact"] in ("serious", "critical")]
                blocking += len(bad)
                report[f"{label}:{name}"] = {"violations": rows, "passes": len(res["passes"]), "incomplete": len(res["incomplete"])}
                print(("OK   " if not bad else "FAIL ") + f"{label:7} {name:9} serious/critical={len(bad)} other={len(rows) - len(bad)} rules_passed={len(res['passes'])}")
                for r in rows:
                    print(f"       [{r['impact']}] {r['id']} x{r['count']}: {r['help']} {r['nodes'][:3]}")
            ctx.close()
        b.close()
    if out:
        Path(out).write_text(json.dumps(report, indent=1), encoding="utf-8")
    print("TOTAL serious/critical violations:", blocking)
    sys.exit(1 if blocking else 0)


main()
