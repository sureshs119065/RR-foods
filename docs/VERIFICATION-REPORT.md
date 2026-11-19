# RR FOODS - Step 6 verification report

**Read this first.** The sandbox this report was prepared in had no network, no PostgreSQL, no SQLAlchemy/Flask-WTF and no way to start the app. So **nothing below was re-measured by running the app**. Every figure is tagged:

- **[re-run now]**: executed in this sandbox on the files in the zip.
- **[recorded]**: copied from the CHANGELOG, where an earlier session measured it (and said so).
- **[not measured]**: no number exists. Do not quote one.

`tools/verify_all.sh` collects every missing number in one run on your machine; paste the results into the table cells marked "run".

## 1. Lighthouse (mobile preset, production build)

| Page | Performance | Accessibility | Best Practices | SEO | Source |
|---|---|---|---|---|---|
| Home, before Step 4 | 95 | n/a | n/a | n/a | [recorded] LCP 2.82 s |
| Home, after Step 4 | 98 | 100 | 100 | 100 | [recorded] LCP 2.07 s, CLS 0, TBT 30-100 ms (two outliers 146/177 ms) |
| Listing, product, cart | run | run | run | run | [not measured] |

There is no true "before" for the whole project: the first Lighthouse run happened mid-Step 4. The 5.5/10 Performance score in the brief is a rating, not a Lighthouse number.

## 2. axe-core

| Check | Result | Source |
|---|---|---|
| axe 4.10, WCAG 2.0-2.2 A/AA + best practice, 7 pages x (1280 px, 390 px) | 0 violations (0 serious/critical) | [recorded] at end of Step 3 |
| Contrast script, 152 text/background pairs (4.5:1; 3:1 for large text, borders, focus ring) | 0 below threshold | [re-run now] |
| Re-run after Steps 4-5 | run | [not measured] |

## 3. Tests

| Item | Value | Source |
|---|---|---|
| Last full pytest result | 943 passed (end of 5.6) | [recorded] |
| Added by 5.7 and 2.4-2.6 | 27 + 17 expected, **never run** | [recorded] |
| `def test_` functions in `tests/` now | 644 in 47 files (627 + 17 new for Steps 2.4-2.6; parametrised tests expand to more) | [re-run now] |
| Pass rate today | **unknown**. Run `pytest -q` | [not measured] |
| `py_compile` on all of `app/` and `tools/` | OK | [re-run now] |

## 4. Bundle sizes

| Item | Size | Source |
|---|---|---|
| Storefront CSS + JS, gzip, hashed bundle | about 53 KB (budget 150 KB) | [recorded] |
| `storefront.css` source | 263,982 B raw, 48,177 B gzip (not minified) | [re-run now] |
| Rasters over 100 KB in `static/img` | none | [re-run now] |
| Minified `dist/` bundle | run `tools/build_assets.py` (needs rcssmin, rjsmin) | [not measured] |

## 5. Query counts (warm cache)

| Page | Before | After | Budget in test | Source |
|---|---|---|---|---|
| Home | 19 | 11 | 22 | [recorded] |
| Listing | 9 | 8 | 12 | [recorded] |
| Product | 19 | not stated | 22 | [recorded] |

## 6. Scores out of 10

| Area | Score | One-line evidence |
|---|---|---|
| UX | **8** | Guest cart and merge, pincode/ETA, cart progress, checkout error summary, Reorder, filter chips done; **UPI option (1.2) was deferred and is not built**. |
| UI | **8** (provisional) | One stylesheet, one token set, shared states, exact-slug fallback + placeholder + `flask check-images`, 6 New Arrivals cards with inert clones, dark-mode toggle removed (shop is light-only). **Provisional**: the 17 new tests have not been run. |
| Accessibility | **9** | axe 0 violations on 7 pages x 2 widths [recorded]; contrast gate 152 pairs pass [re-run now]; focus, labels, overlays, carousel pause done. |
| Performance | **9** | Home Lighthouse 98, LCP 2.07 s, CLS 0 [recorded]; CSS+JS about 53 KB gzip; no DB write on GET; query budgets in tests. Only the home page was measured. |
| Security | **9** (provisional) | No default SECRET_KEY, Redis limiter, CSP + report route, input validation, upload hardening, 52 cross-user tests, lockout, pip-audit gate. **Provisional**: the 5.7 tests and the real pip-audit have never run, and `requirements.lock` is not committed. |

## 7. Remaining work (anything under 8, plus gaps found)

**UI (8, to reach 9)**
1. Run `pytest -q` and `flask check-images`; upload photos for the products it lists.
2. Dark mode was removed, not finished. If you want it later: move the hard-coded hex colours in `storefront.css` to tokens, add `[data-theme="dark"]` token overrides and a `prefers-color-scheme` default, extend `tools/check_contrast.py` to the dark pairs, then add the toggle back.
3. Measure the home page again: the New Arrivals row now has 6 cards and no duplicates in the HTML.

**UX (8, to reach 9)**
4. 1.2: UPI `upi://` intent link built server-side from `UPI_ID`, amount and order number, beside WhatsApp on `order_placed.html`, with a test. `services/checkout.py` stays untouched.

**Not under 8, but open**
5. Run `pytest -q`; fix anything the 44 never-run tests show.
6. `pip install -r requirements.txt && python tools/pin_requirements.py`, commit `requirements.lock`, switch the Render build command.
7. Run `tools/verify_all.sh`; fill in the "run" cells above (Lighthouse on listing, product and cart; axe after Steps 4-5; real test count).
8. Set `SECURITY_CONTACT` and a real `UPI_ID`/`ADMIN_WHATSAPP_NUMBER` in Render.
