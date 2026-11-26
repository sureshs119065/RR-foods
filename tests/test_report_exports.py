"""Admin and Owner Excel / CSV downloads: readable headers, ₹ / date / status formats, formula safety, summaries and permissions."""
import csv
import io
from decimal import Decimal

from openpyxl import load_workbook

from app.services import report_export as rx
from app.services.xlsx_export import DATETIME, INT, MONEY, TEXT
from tests.helpers import make_user
from tests.test_part4_products_stock_exports import admin, cat, owner  # noqa: F401  (fixtures)
from tests.test_step2_models import make_product
from tests.test_step5_owner import mk_order

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def table(response):
    """(summary dict, header list, data rows) from a downloaded workbook: the table starts at the row whose first cell is the header."""
    ws = load_workbook(io.BytesIO(response.get_data())).worksheets[0]
    rows = [[c.value for c in r] for r in ws.iter_rows()]
    head = next(i for i, r in enumerate(rows) if r[0] in ("Order No.", "Name", "SKU"))
    summary = {r[0]: r[1] for r in rows[:head] if r[0] and r[1] is not None}
    return summary, rows[head], [r for r in rows[head + 1:] if r[0]]


# ---------------------------------------------------------------- pure formatting
def test_formula_guard_leaves_numbers_and_the_dash_alone():
    assert rx.clean_text('=HYPERLINK("x")').startswith("'=") and rx.clean_text("@cmd") == "'@cmd" and rx.clean_text("-5 off") == "'-5 off"
    assert rx.clean_text(None) == "-" and rx.clean_text("") == "-" and rx.clean_text("-") == "-"
    rep = rx.Report("T", "t", "S", ["Name", "Amount (₹)", "Qty", "When"], [TEXT, MONEY, INT, DATETIME], [["=1+1", Decimal("-10"), None, None]])
    line = rx.render_csv(rep).splitlines()[-1]
    assert line == "'=1+1,-10.00,0,-"                                  # negative money stays a number, nothing becomes a formula


def test_status_and_payment_labels_are_words():
    assert rx.status_label("out_for_delivery") == "Out for delivery" and rx.status_label(None) == "-"
    assert rx.PAYMENT_METHOD_LABELS["cod"] == "Cash on delivery"


# ---------------------------------------------------------------- admin
def test_admin_orders_export_is_readable_with_summary(admin, session, owner):
    buyer = make_user(session, "user", email="buyer@x.com")
    p = make_product(session, sku="S1", slug="s1", name="=Ragi Flour")
    session.commit()
    mk_order(session, buyer, p, qty=3, status="confirmed", number="NK-3001")
    mk_order(session, buyer, p, qty=1, status="cancelled", number="NK-3002")
    r = admin.get("/admin/orders/export.xlsx")
    assert r.status_code == 200 and r.mimetype == XLSX and "rr-foods-orders-" in r.headers["Content-Disposition"]
    summary, head, rows = table(r)
    assert head[:3] == ["Order No.", "Order Date", "Customer Name"] and "Email" in head and "Order Total (₹)" in head and "order_number" not in head
    assert {"Orders in this report", "Total revenue (₹)", "Orders counted as sales", "Average order value (₹)"} <= set(summary)
    assert summary["Orders in this report"] == 2 and summary["Orders counted as sales"] == 1 and summary["Total revenue (₹)"] == 300
    by_no = {row[0]: row for row in rows}
    assert by_no["NK-3001"][head.index("Order Status")] == "Confirmed" and by_no["NK-3002"][head.index("Order Status")] == "Cancelled"
    assert "'=Ragi Flour" in by_no["NK-3001"][head.index("Products Ordered")] or "Ragi" in by_no["NK-3001"][head.index("Products Ordered")]


def test_admin_orders_export_follows_the_list_filters_and_csv_is_clean(admin, session):
    buyer = make_user(session, "user", email="buyer@x.com")
    p = make_product(session, sku="S1", slug="s1", name="Ragi")
    session.commit()
    mk_order(session, buyer, p, qty=1, status="confirmed", number="NK-4001")
    mk_order(session, buyer, p, qty=1, status="cancelled", number="NK-4002")
    r = admin.get("/admin/orders/export.csv?status=cancelled")
    assert r.get_data().startswith(b"\xef\xbb\xbfRR FOODS")
    lines = list(csv.reader(io.StringIO(r.get_data().decode("utf-8-sig"))))
    start = next(i for i, l in enumerate(lines) if l and l[0] == "Order No.")
    data = [l for l in lines[start + 1:] if l]
    assert [l[0] for l in data] == ["NK-4002"] and "status Cancelled" in "".join(lines[1])
    assert admin.get("/admin/orders/export.pdf").status_code == 404


def test_admin_users_export_has_readable_columns_and_no_password_data(admin, session):
    make_user(session, "user", email="=evil@x.com")
    session.commit()
    r = admin.get("/admin/users/export.xlsx")
    summary, head, rows = table(r)
    assert head[:4] == ["Name", "Email", "Phone", "Role"] and "Total Spent (₹)" in head and not any("password" in str(h).lower() for h in head)
    assert {"Accounts in this report", "Customers", "Blocked accounts"} <= set(summary)
    assert any(str(row[1]).startswith("'=") for row in rows)           # an e-mail that starts with = cannot run as a formula
    assert admin.get("/admin/users/export.csv?role=owner").status_code == 200


def test_admin_dashboard_sales_downloads_work_for_the_admin(admin):
    assert admin.get("/admin/analytics.xlsx").status_code == 200 and admin.get("/admin/analytics.csv").status_code == 200
    html = admin.get("/admin/").get_data(as_text=True)
    assert "/admin/analytics.xlsx" in html and "/owner/analytics.xlsx" not in html


# ---------------------------------------------------------------- owner
def test_owner_orders_export_hides_email_and_stock_export_has_totals(owner, session):
    buyer = make_user(session, "user", email="buyer@x.com")
    p = make_product(session, sku="S1", slug="s1", name="Ragi Flour", stock_qty=7)
    session.commit()
    mk_order(session, buyer, p, qty=2, status="confirmed", number="NK-5001")
    summary, head, rows = table(owner.get("/owner/orders/export.xlsx"))
    assert "Email" not in head and "Order Total (₹)" in head and [r[0] for r in rows] == ["NK-5001"] and summary["Total revenue (₹)"] == 200
    wb = load_workbook(io.BytesIO(owner.get("/owner/inventory/export.xlsx").get_data()))
    ws = wb.worksheets[0]
    values = [[c.value for c in r] for r in ws.iter_rows()]
    assert any(r[0] == "SKU" and "Stock Status" in r for r in values) and any(r[0] == "Total" for r in values)
    csv_resp = owner.get("/owner/inventory/export.csv")
    assert csv_resp.mimetype == "text/csv" and "Stock value at selling price" in csv_resp.get_data(as_text=True)


# ---------------------------------------------------------------- permissions
def test_exports_are_limited_to_their_own_role(admin, owner, app, session):
    anon = app.test_client()
    for url in ("/admin/orders/export.csv", "/admin/users/export.xlsx", "/owner/orders/export.csv", "/owner/inventory/export.xlsx"):
        assert anon.get(url).status_code in (302, 401, 403)
    assert admin.get("/owner/orders/export.csv").status_code in (302, 401, 403)       # an admin cannot use the owner's downloads
    assert owner.get("/admin/orders/export.csv").status_code in (302, 401, 403)       # an owner cannot use the admin's downloads
    assert owner.get("/admin/users/export.csv").status_code in (302, 401, 403)        # customer contact lists are admin-only
