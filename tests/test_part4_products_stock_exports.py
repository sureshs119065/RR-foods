"""Part 4: archived toggle, Duplicate removed, admin stock alerts redesign, styled Excel exports and the CSV option."""
import csv
import io
import re
from decimal import Decimal

import pytest
from openpyxl import load_workbook
from sqlalchemy import select

from app.models import Product
from app.services.xlsx_export import MIXED, MONEY, TEXT, Sheet, Typed, build_workbook
from tests.helpers import make_user, post, token
from tests.test_step2_models import make_category, make_product
from tests.test_step4_products import admin, cat, get_product, pdata  # noqa: F401  (fixtures)
from tests.test_step5_owner import ADDR, mk_order, owner  # noqa: F401  (fixtures)

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def sheet_of(response, name=None):
    wb = load_workbook(io.BytesIO(response.get_data()))
    return wb[name] if name else wb.active


# ---------------------------------------------------------------- archived toggle
def test_archived_toggle_badge_view_archived_link_and_restore(admin, session, cat):
    make_product(session, category=cat, sku="A1", slug="a1", name="Keep me")
    make_product(session, category=cat, sku="A2", slug="a2", name="Archive me")
    session.commit()
    html = admin.get("/admin/products").get_data(as_text=True)
    assert "Show archived" in html and re.search(r'Show archived <span class="badge">0</span>', html)

    victim = get_product(session, "A2")
    r = post(admin, f"/admin/products/{victim.id}/archive", page="/admin/products")
    html = admin.get(r.headers["Location"]).get_data(as_text=True)
    assert "View archived" in html and "status=archived" in html          # link right after archiving
    assert re.search(r'Show archived <span class="badge badge--warn">1</span>', html)

    html = admin.get("/admin/products?status=archived").get_data(as_text=True)
    assert "Back to products" in html and "Show archived" not in html     # the toggle flips
    assert "Archive me" in html and "Keep me" not in html
    assert ">Restore</button>" in html and "Duplicate" not in html

    r = post(admin, f"/admin/products/{victim.id}/restore", {"view": "archived"}, page="/admin/products?status=archived")
    assert r.status_code == 302 and r.headers["Location"].endswith("/admin/products")   # nothing left in the archive
    assert not get_product(session, "A2").is_deleted


def test_restore_stays_in_archive_while_more_remain(admin, session, cat):
    for n in (1, 2):
        make_product(session, category=cat, sku=f"R{n}", slug=f"r{n}", name=f"Item {n}", is_deleted=True)
    session.commit()
    first = get_product(session, "R1")
    r = post(admin, f"/admin/products/{first.id}/restore", {"view": "archived"}, page="/admin/products?status=archived")
    assert r.headers["Location"].endswith("/admin/products?status=archived")


def test_duplicate_is_gone_everywhere(admin, session, cat, app):
    post(admin, "/admin/products/new", pdata(cat))
    p = get_product(session)
    assert post(admin, f"/admin/products/{p.id}/duplicate", page="/admin/products").status_code in (404, 405)
    assert "Duplicate" not in admin.get("/admin/products").get_data(as_text=True)
    assert "Duplicate" not in admin.get(f"/admin/products/{p.id}/edit").get_data(as_text=True)
    from app.admin import products as module
    assert not hasattr(module, "duplicate_product") and not hasattr(module, "product_duplicate")
    assert "admin.product_duplicate" not in app.view_functions and "admin.product_duplicate" not in {r.endpoint for r in app.url_map.iter_rules()}


# ---------------------------------------------------------------- admin stock alerts
@pytest.fixture()
def stocked(session, cat):
    make_product(session, category=cat, sku="OUT1", slug="out1", name="Ragi Out", stock_qty=0, low_stock_threshold=5)
    make_product(session, category=cat, sku="LOW1", slug="low1", name="Jowar Low", stock_qty=2, low_stock_threshold=5)
    make_product(session, category=cat, sku="OK1", slug="ok1", name="Bajra Healthy", stock_qty=50, low_stock_threshold=5)
    session.commit()


def chip_counts(html):
    return {re.sub(r"\s+", " ", label).strip(): int(n) for label, n in re.findall(r'class="chip[^"]*"[^>]*>([A-Za-z ]+?) <span class="chip__n">(\d+)</span>', html)}


def test_stock_alerts_chips_counts_filters_and_inline_form(admin, stocked):
    html = admin.get("/admin/stock-alerts").get_data(as_text=True)
    assert chip_counts(html) == {"Needs attention": 2, "Out": 1, "Low": 1, "Healthy": 1, "All": 3}
    assert "Ragi Out" in html and "Jowar Low" in html and "Bajra Healthy" not in html       # default: needs attention
    assert 'data-inline="stock"' in html and 'class="table table--stock"' in html and 'data-state-badge>Out<' in html and 'data-state-badge>Low<' in html
    assert "css/stock-ui.css" in html and "js/stock-inline.js" in html and 'id="toast"' in html

    out = admin.get("/admin/stock-alerts?level=out").get_data(as_text=True)
    assert "Ragi Out" in out and "Jowar Low" not in out
    low = admin.get("/admin/stock-alerts?level=low").get_data(as_text=True)
    assert "Jowar Low" in low and "Ragi Out" not in low
    healthy = admin.get("/admin/stock-alerts?level=in").get_data(as_text=True)
    assert "Bajra Healthy" in healthy and 'data-state-badge>Healthy<' in healthy and "Jowar Low" not in healthy
    assert "Bajra Healthy" in admin.get("/admin/stock-alerts?level=all").get_data(as_text=True)
    # search narrows the chip counts too
    narrowed = chip_counts(admin.get("/admin/stock-alerts?level=all&q=jowar").get_data(as_text=True))
    assert narrowed["All"] == 1 and narrowed["Low"] == 1 and narrowed["Out"] == 0
    assert admin.get("/admin/stock-alerts?level=nonsense&page=abc&sort=zzz").status_code == 200


def test_stock_alerts_link_from_a_notification_opens_that_product(admin, stocked, session):
    pid = get_product(session, "OK1").id
    html = admin.get(f"/admin/stock-alerts?q=stock-id-{pid}").get_data(as_text=True)
    assert "Bajra Healthy" in html and "Ragi Out" not in html


def test_stock_alert_inline_update_json_stale_and_plain_post(admin, stocked, session):
    pid = get_product(session, "OUT1").id
    tok = token(admin, "/admin/stock-alerts")
    r = admin.post(f"/admin/stock-alerts/{pid}/update", data={"qty": "9", "expected": "0", "csrf_token": tok}, headers={"Accept": "application/json"})
    body = r.get_json()
    assert r.status_code == 200 and body["ok"] and body["qty"] == 9 and body["state"] == "ok" and body["label"] == "Healthy"
    assert get_product(session, "OUT1").stock_qty == 9
    # a stale page cannot overwrite what changed in the meantime
    r = admin.post(f"/admin/stock-alerts/{pid}/update", data={"qty": "1", "expected": "0", "csrf_token": tok}, headers={"Accept": "application/json"})
    assert r.status_code == 409 and r.get_json()["current"] == 9 and get_product(session, "OUT1").stock_qty == 9
    r = admin.post(f"/admin/stock-alerts/{pid}/update", data={"qty": "-3", "csrf_token": tok}, headers={"Accept": "application/json"})
    assert r.status_code == 422 and not r.get_json()["ok"]
    # without JavaScript: normal form post, flash, back to the same filtered page
    r = admin.post(f"/admin/stock-alerts/{pid}/update", data={"qty": "2", "expected": "9", "csrf_token": tok, "next": "/admin/stock-alerts?level=low"})
    assert r.status_code == 302 and r.headers["Location"].endswith("/admin/stock-alerts?level=low")
    assert get_product(session, "OUT1").stock_qty == 2
    r = admin.post(f"/admin/stock-alerts/{pid}/update", data={"qty": "2", "csrf_token": tok, "next": "https://evil.example/"})
    assert "evil.example" not in r.headers["Location"]


# ---------------------------------------------------------------- Excel builder
def test_builder_styles_every_sheet_and_never_writes_a_formula():
    data = build_workbook([Sheet("Demo", ["Name", "Qty", "Price"], [TEXT, "int", MONEY],
                                 [["=1+1", 5, 10.5], ["short", 1234567, 3], ["x" * 200, None, "oops"], ["-5%", 2, 0]])],
                          clean=lambda s: "'" + s if s[:1] in ("=", "+", "-", "@") else s)
    ws = load_workbook(io.BytesIO(data))["Demo"]
    head = ws["A1"]
    assert head.font.bold and head.font.color.rgb.endswith("FFFFFF") and head.fill.start_color.rgb.endswith("183D2B")
    assert ws.freeze_panes == "A2" and ws.auto_filter.ref == "A1:C5"
    assert ws["A2"].value == "'=1+1" and ws["A2"].data_type == "s"                      # injection neutralised, not a formula
    assert ws["B2"].alignment.horizontal == "right" and ws["A3"].alignment.horizontal == "left"
    assert ws["C2"].number_format == '"₹"#,##0.00' and ws["B3"].number_format == "#,##0"
    assert ws["C4"].value == "oops" and ws["C4"].alignment.horizontal == "left"          # not a number: stays text
    assert ws["A2"].border.left.style == "thin" and ws["A1"].border.bottom.style == "thin"
    assert ws["A3"].fill.start_color.rgb.endswith("EEF6F0") and ws["A2"].fill.fill_type is None   # zebra
    assert 8 <= ws.column_dimensions["A"].width <= 60 and ws.column_dimensions["A"].width == 60   # capped
    assert ws.column_dimensions["B"].width >= len("1,234,567")


# ---------------------------------------------------------------- admin product export / import
def test_product_export_xlsx_is_styled_with_readable_headers_and_a_summary_sheet(admin, session, cat):
    from app.admin.csvio import COLUMNS, HEADERS
    make_product(session, category=cat, sku="X1", slug="x1", name='=HYPERLINK("http://evil","click")', mrp=Decimal("1250.5"), final_price=Decimal("1250.5"), stock_qty=7)
    make_product(session, category=cat, sku="X2", slug="x2", name="@cmd", mrp=Decimal(60), final_price=Decimal(60))
    session.commit()
    r = admin.get("/admin/products/export.xlsx")
    assert r.mimetype == XLSX and "attachment" in r.headers["Content-Disposition"] and "products.xlsx" in r.headers["Content-Disposition"]
    wb = load_workbook(io.BytesIO(r.get_data()))
    assert wb.sheetnames == ["Products", "Summary"]                           # the import reads the first sheet; totals live on the second
    ws = wb["Products"]
    assert [c.value for c in ws[1]] == [HEADERS[c] for c in COLUMNS]
    rows = {row[0].value: row for row in ws.iter_rows(min_row=2)}
    assert rows["X1"][1].value.startswith("'=") and rows["X2"][1].value == "'@cmd" and rows["X1"][1].data_type == "s"
    mrp, stock = COLUMNS.index("mrp"), COLUMNS.index("stock_qty")
    assert rows["X1"][mrp].value == 1250.5 and rows["X1"][mrp].number_format == '"₹"#,##0.00' and rows["X1"][mrp].alignment.horizontal == "right"
    assert rows["X1"][stock].value == 7 and rows["X1"][stock].number_format == "#,##0"
    assert ws["A1"].fill.start_color.rgb.endswith("183D2B") and ws.freeze_panes == "A2" and ws.auto_filter.ref.startswith("A1:")


def test_product_export_respects_the_current_filters_and_csv_has_a_bom(admin, session, cat):
    make_product(session, category=cat, sku="F1", slug="f1", name="Findable")
    make_product(session, category=cat, sku="F2", slug="f2", name="Other")
    session.commit()
    ws = sheet_of(admin.get("/admin/products/export.xlsx?q=findable"))
    assert [row[0].value for row in ws.iter_rows(min_row=2)] == ["F1"]
    raw = admin.get("/admin/products/export.csv").get_data()
    assert raw.startswith(b"\xef\xbb\xbfSKU,Product Name,")


def test_exported_xlsx_and_csv_import_back_cleanly(admin, session, cat):
    make_product(session, category=cat, sku="RT1", slug="rt1", name="=SUM(1)", mrp=Decimal("99.50"), final_price=Decimal("99.50"), stock_qty=4)
    make_product(session, category=cat, sku="RT2", slug="rt2", name="Plain", mrp=Decimal("10"), final_price=Decimal("10"), stock_qty=0, brand="Nurse")
    session.commit()
    for url, name, body in (("/admin/products/export.xlsx", "p.xlsx", None), ("/admin/products/export.csv", "p.csv", None)):
        data = admin.get(url).get_data()
        r = post(admin, "/admin/products/import", {"default_stock": "0"}, files={"file": (io.BytesIO(data), name)})
        assert r.status_code == 302, r.get_data(as_text=True)[:600]
        p1, p2 = get_product(session, "RT1"), get_product(session, "RT2")
        assert p1.name == "=SUM(1)" and p1.mrp == Decimal("99.50") and p1.stock_qty == 4     # no stray apostrophe, same values
        assert p2.brand == "Nurse" and p2.stock_qty == 0
    assert session.scalar(select(Product.id).where(Product.sku == "RT1")) is not None


def test_import_rejects_a_broken_xlsx_without_crashing(admin, session, cat):
    r = post(admin, "/admin/products/import", {}, files={"file": (io.BytesIO(b"PK\x03\x04 this is not a workbook"), "bad.xlsx")})
    assert r.status_code == 422 and "could not be read" in r.get_data(as_text=True)


# ---------------------------------------------------------------- owner sales report
def test_owner_report_xlsx_has_four_sheets_with_the_date_range_on_summary(owner, session):
    buyer = make_user(session, "user", email="buyer@x.com")
    p = make_product(session, sku="S1", slug="s1", name="Ragi Flour")
    session.commit()
    mk_order(session, buyer, p, qty=3, status="confirmed", number="NK-2001")
    r = owner.get("/owner/analytics.xlsx?range=year")
    assert r.status_code == 200 and r.mimetype == XLSX and "rr-foods-sales-report.xlsx" in r.headers["Content-Disposition"]
    wb = load_workbook(io.BytesIO(r.get_data()))
    assert wb.sheetnames == ["Summary", "Top products", "Coupons", "Pincodes"]
    summary = {row[0].value: row[1] for row in wb["Summary"].iter_rows(min_row=2)}
    assert {"Date range", "From", "To"} <= set(summary) and summary["Date range"].value
    assert summary["Total sales"].value == 300 and summary["Total sales"].number_format == '"₹"#,##0.00' and summary["Total sales"].alignment.horizontal == "right"
    assert summary["Orders"].value == 1 and summary["Orders"].number_format == "#,##0"
    assert summary["Repeat customer rate"].number_format == '0.0"%"' and summary["Date range"].alignment.horizontal == "left"
    top = wb["Top products"]
    assert [c.value for c in top[1]] == ["Rank", "Product", "Sales (₹)"] and top["B2"].value == "Ragi Flour" and top["C2"].value == 300
    assert wb["Pincodes"]["A2"].value == "600001" and wb["Pincodes"]["B2"].value == 300
    for ws in wb.worksheets:                                                  # same styling on every sheet
        assert ws.freeze_panes == "A2" and ws["A1"].font.bold and ws["A1"].fill.start_color.rgb.endswith("183D2B") and ws.auto_filter.ref


def test_owner_report_xlsx_with_no_orders_still_downloads_and_csv_is_tidy_with_bom(owner):
    wb = load_workbook(io.BytesIO(owner.get("/owner/analytics.xlsx").get_data()))
    assert wb["Top products"].max_row == 1 and wb["Coupons"].max_row == 1       # header only
    r = owner.get("/owner/analytics.csv")
    assert r.get_data().decode("utf-8").startswith("\ufeffSection,Metric,Value,Unit,Orders,Discount (₹)")
    rows = list(csv.DictReader(io.StringIO(r.get_data().decode("utf-8-sig"))))
    assert rows[0]["Section"] == "Summary" and rows[0]["Metric"] == "Date range"


def test_owner_report_downloads_are_owner_only(admin, app):
    assert app.test_client().get("/owner/analytics.xlsx").status_code in (302, 401, 403)
    assert admin.get("/owner/analytics.xlsx").status_code in (302, 401, 403)
