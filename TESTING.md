# Testing (Step 8, Part 1)

## 1. Automatic tests (no browser needed)
Needs a PostgreSQL server and an empty database for tests:

    createdb nk_test
    export TEST_DATABASE_URL=postgresql+psycopg://postgres@localhost:5432/nk_test
    python -m pytest -q                      # whole suite, about 4-5 minutes
    python -m pytest -q tests/test_step8_access.py tests/test_step8_e2e.py   # only the Step 8 tests, about 30 seconds

New in Step 8:
- tests/test_step8_access.py  Finds EVERY route automatically and checks who may open it.
  Admin pages: admin only. Owner pages: owner only. Customer pages: sign-in needed. Owners/admins cannot shop.
  No route may answer a 5xx error for anonymous, customer, owner or admin. If you add a new page and forget its
  protection, this file fails. (A page that should be public must be added to PUBLIC_GET / PUBLIC_POST on purpose.)
- tests/test_step8_e2e.py  The whole shop through the real forms: sign up, address, search, cart, coupon, checkout,
  owner confirms/packs/ships/delivers, invoice PDF, review, helpful vote, return, restock, refund, audit trail.
  Also: two buyers for the last unit (one after the other), and two checkouts fired at the same instant from
  separate threads, 6 rounds: exactly one order each round, stock never below zero.

- tests/test_step8_prodcheck.py  The production safety check (weak key, example DB password, stub payments, insecure cookies, debug
  are refused at startup in production; softer problems are advice) and the /healthz and /readyz endpoints.

## 2. Real-browser layout audit (needs a running, seeded site)

    pip install playwright && playwright install chromium
    flask db upgrade && flask seed
    flask run            # or gunicorn, in another terminal
    export AUDIT_USER=... AUDIT_OWNER=... AUDIT_ADMIN=...     # the seed passwords from your .env
    AUDIT_ROLES=public,user AUDIT_WIDTHS=360,1366 python scripts/layout_audit.py

Run roles/widths in small groups (the full run is slow). Output: audit-report.json plus a summary.
Hard failures (exit code 1): sideways page scroll, JavaScript errors, failed requests.
Soft findings (listed, to review): elements sticking out, tap targets under 44 px, inputs under 16 px, images without alt, CLS over 0.1.

## 3. Still yours to do (cannot be done from a server)
- Real Android phone and real iPhone.
- Lighthouse mobile (Performance, Accessibility, Best Practices, SEO) and its scores.
- Drag the browser width from 1920 down to 320 and watch for jumps.
- Send one real email through your SMTP server (flask send-emails).
