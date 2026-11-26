"""Part 3: the "Insights" sheet (native charts + rule-based suggestions) in every Excel download, identical for Admin and Owner."""
import io
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from openpyxl import load_workbook
from openpyxl.chart import BarChart, DoughnutChart

from app.models import User
from app.services import report_insights as ri
from app.services.xlsx_export import INT, MONEY, TEXT, ChartBlock, InsightsSheet, build_workbook
from tests.helpers import make_user
from tests.test_part4_products_stock_exports import admin, cat, owner  # noqa: F401  (fixtures)
from tests.test_step2_models import make_product
from tests.test_step5_owner import mk_order

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
NOW = datetime.now(timezone.utc)


def ago(days):
    return NOW - timedelta(days=days)


def month_start(back):
    y, m = NOW.year, NOW.month - back
    while m < 1:
        y, m = y - 1, m + 12
    return datetime(y, m, 15, 9, 0, tzinfo=timezone.utc)


def seed_shop(session, cat):
    """A shop where every rule has something to say: Ragi is the top seller and nearly out of stock, Jaggery never sells, orders are
    cancelled, nobody orders twice, everyone is in one pincode, and revenue fell against the window before."""
    buyers = [make_user(session, "user", f"c{i}@x.com") for i in range(1, 7)]
    ragi = make_product(session, category=cat, sku="R1", slug="r1", name="Ragi Flour", stock_qty=2, low_stock_threshold=5)
    millet = make_product(session, category=cat, sku="M1", slug="m1", name="Millet Mix", stock_qty=50)
    evil = make_product(session, category=cat, sku="E1", slug="e1", name="=HYPERLINK(\"http://evil\",\"x\")", stock_qty=30)
    make_product(session, category=cat, sku="J1", slug="j1", name="Jaggery", stock_qty=40)
    session.commit()
    n = 100
    def order(buyer, product, qty, status, days):
        nonlocal n
        n += 1
        return mk_order(session, buyer, product, qty=qty, status=status, number=f"NK-{n}", created_at=ago(days))
    for i in range(4):
        order(buyers[i], ragi, 3, "confirmed", i)                  # 4 x 300 now
    order(buyers[4], millet, 1, "delivered", 1)
    order(buyers[5], evil, 1, "delivered", 2)
    order(buyers[0], ragi, 1, "cancelled", 1)
    order(buyers[1], ragi, 1, "rejected", 2)
    for i in range(5):
        order(buyers[i], millet, 10, "confirmed", 7 + i % 3)        # 5 x 1000 in the window before
    return {"ragi": ragi, "millet": millet, "evil": evil}


def workbook(response):
    assert response.status_code == 200 and response.mimetype == XLSX
    return load_workbook(io.BytesIO(response.get_data()))


def texts(ws):
    return [c.value for row in ws.iter_rows() for c in row if isinstance(c.value, str)]


def not_enough(ws):
    """How many suggestion boxes say there is not enough data (each box is one merged cell holding the title and the sentence)."""
    return sum(ri.NOT_ENOUGH in t for t in texts(ws))


def chart_titles(ws):
    out = []
    for ch in ws._charts:
        runs = ch.title.tx.rich.p[0].r
        out.append("".join(r.t for r in runs))
    return out


def all_formula_free(wb):
    return not any(c.data_type == "f" for ws in wb.worksheets for row in ws.iter_rows() for c in row)


RANGE = "range=custom&start_date={}&end_date={}".format((date.today() - timedelta(days=5)).isoformat(), date.today().isoformat())


# ---------------------------------------------------------------- sales report
def test_sales_report_insights_has_three_native_charts_and_data_driven_suggestions(admin, owner, session, cat):
    seed_shop(session, cat)
    wb = workbook(admin.get(f"/admin/analytics.xlsx?{RANGE}"))
    assert wb.sheetnames[-1] == "Insights" and wb.sheetnames[0] == "Summary"
    ws = wb["Insights"]
    kinds = [type(c) for c in ws._charts]
    assert kinds == [BarChart, BarChart, DoughnutChart]                         # revenue by period, top products, order status
    titles = chart_titles(ws)
    assert titles[0].startswith("Revenue by") and titles[1] == "Top products by sales" and titles[2] == "Orders by status"
    assert not any("payment" in t.lower() for t in titles) and not any("payment" in t.lower() for t in texts(ws))
    for ch in ws._charts[:2]:                                                   # axis titles, data labels, brand colour
        assert ch.x_axis.title and ch.y_axis.title and ch.dataLabels.showVal and str(ch.series[0].graphicalProperties.solidFill.srgbClr).endswith("183D2B")
    assert ws._charts[2].dataLabels.showPercent

    said = " ".join(texts(ws))
    assert "Ragi Flour brings in" in said and "Stock up on Ragi Flour and promote the next best sellers to reduce dependence on one product." in said
    assert "Ragi Flour is selling fast but is almost out of stock. Restock now." in said
    assert "Jaggery had no sales" in said and "Consider a discount or a combo for Jaggery." in said
    assert "Revenue is down" in said and "versus the previous 6 days" in said and "coupon or a homepage banner" in said
    assert "Review delivery pincodes and stock accuracy." in said
    assert "Offer a coupon on the second order" in said
    assert "Plan delivery slots for this pincode." in said and "600001" in said
    assert all_formula_free(wb)


def test_admin_and_owner_get_the_same_insights_sheet(admin, owner, session, cat):
    seed_shop(session, cat)
    a = workbook(admin.get(f"/admin/analytics.xlsx?{RANGE}"))["Insights"]
    o = workbook(owner.get(f"/owner/analytics.xlsx?{RANGE}"))["Insights"]
    assert [[c.value for c in r] for r in a.iter_rows()] == [[c.value for c in r] for r in o.iter_rows()]
    assert chart_titles(a) == chart_titles(o) and len(a.merged_cells.ranges) == len(o.merged_cells.ranges)


def test_suggestion_boxes_are_wrapped_merged_light_yellow_with_borders(admin, session, cat):
    seed_shop(session, cat)
    ws = workbook(admin.get(f"/admin/analytics.xlsx?{RANGE}"))["Insights"]
    box = next(c for row in ws.iter_rows() for c in row if isinstance(c.value, str) and c.value.startswith("Suggestion"))
    assert box.alignment.wrap_text and box.fill.start_color.rgb.endswith("FFF8CC") and box.border.left.style == "thin"
    assert any(box.coordinate in r for r in ws.merged_cells.ranges)
    header = ws["J4"] if ws["J4"].value else next(c for row in ws.iter_rows() for c in row if c.value == "Revenue (₹)")
    assert header.fill.start_color.rgb.endswith("183D2B") and header.font.bold                      # same dark green header as the other sheets


def test_money_and_percent_cells_in_insights_use_the_report_formats(admin, session, cat):
    seed_shop(session, cat)
    ws = workbook(admin.get(f"/admin/analytics.xlsx?{RANGE}"))["Insights"]
    money = next(c for row in ws.iter_rows() for c in row if c.value == "Sales (₹)")
    cells = [ws.cell(row=money.row + 1, column=money.column), ws.cell(row=money.row + 1, column=money.column + 1)]
    assert cells[0].number_format == '"₹"#,##0.00' and cells[1].number_format == '0.0"%"'
    assert ws.cell(row=money.row + 1, column=money.column - 1).value.startswith("Ragi")


def test_a_product_name_that_looks_like_a_formula_is_never_a_formula(admin, owner, session, cat):
    seed_shop(session, cat)
    for who, url in ((admin, "/admin/analytics.xlsx"), (owner, "/owner/analytics.xlsx")):
        wb = workbook(who.get(f"{url}?{RANGE}"))
        assert all_formula_free(wb)
        assert any(t.startswith("'=HYPERLINK") for t in texts(wb["Insights"]))              # chart category cell, neutralised like the other sheets


def test_empty_date_range_still_gives_a_valid_file_without_invented_suggestions(admin, owner, session):
    for who, url in ((admin, "/admin/analytics.xlsx"), (owner, "/owner/analytics.xlsx")):
        wb = workbook(who.get(f"{url}?range=custom&start_date=2001-01-01&end_date=2001-01-31"))
        ws = wb["Insights"]
        assert ws._charts == [] and wb.sheetnames[-1] == "Insights"
        said = texts(ws)
        assert not_enough(ws) == 4                                                       # all four boxes say so
        assert not any("%" in t and "Suggestion" in t for t in said)                        # no numbers made up
    assert workbook(admin.get("/admin/analytics.xlsx")).sheetnames[-1] == "Insights"        # default range with no orders at all


# ---------------------------------------------------------------- orders
def test_orders_export_insights_orders_by_status_and_revenue_by_day(admin, owner, session, cat):
    seed_shop(session, cat)
    a = workbook(admin.get("/admin/orders/export.xlsx"))
    o = workbook(owner.get("/owner/orders/export.xlsx"))
    assert a.sheetnames == ["Orders", "Insights"] and o.sheetnames == ["Orders", "Insights"]
    ws = a["Insights"]
    assert chart_titles(ws) == ["Orders by status", "Revenue by day"] and [type(c) for c in ws._charts] == [DoughnutChart, BarChart]
    said = " ".join(texts(ws))
    assert "Review delivery pincodes and stock accuracy." in said and "Plan delivery slots for this pincode." in said
    assert "Revenue is down" in said and "earlier half" in said
    assert [[c.value for c in r] for r in ws.iter_rows()] == [[c.value for c in r] for r in o["Insights"].iter_rows()]   # same for the owner
    said = " ".join(texts(ws))                                                    # no contact details reach the insights (the owner's file has no e-mails)
    assert "@" not in said and "9876543210" not in said and "Asha Rao" not in said


def test_orders_export_with_too_few_orders_says_not_enough_data(admin, session, cat):
    buyer = make_user(session, "user", "one@x.com")
    p = make_product(session, category=cat, sku="S1", slug="s1", name="Solo")
    session.commit()
    mk_order(session, buyer, p, qty=1, status="confirmed", number="NK-1")
    ws = workbook(admin.get("/admin/orders/export.xlsx"))["Insights"]
    assert not_enough(ws) == 2


# ---------------------------------------------------------------- users
def test_users_export_insights_new_users_per_month_and_role_split(admin, session, cat):
    seed_shop(session, cat)
    for i, u in enumerate(session.query(User).filter(User.role == "user").order_by(User.id)):
        u.created_at = month_start(2 if i < 5 else 1)             # five joined two months ago, one last month
    session.commit()
    wb = workbook(admin.get("/admin/users/export.xlsx"))
    assert wb.sheetnames[-1] == "Insights"
    ws = wb["Insights"]
    assert chart_titles(ws) == ["New accounts per month", "Role split"] and [type(c) for c in ws._charts] == [BarChart, DoughnutChart]
    said = " ".join(texts(ws))
    assert "New accounts fell 80%" in said and "coupon or a homepage banner" in said
    assert "Offer a coupon on the second order" not in said or "Only" in said
    assert all_formula_free(wb)


# ---------------------------------------------------------------- stock and products (owner stock file, admin products file)
def test_stock_and_products_insights_chips_charts_and_restock_suggestions(admin, owner, session, cat):
    seed_shop(session, cat)
    for who, url in ((owner, "/owner/inventory/export.xlsx"), (admin, "/admin/products/export.xlsx")):
        wb = workbook(who.get(url))
        assert wb.sheetnames[-1] == "Insights"
        ws = wb["Insights"]
        assert [type(c) for c in ws._charts] == [DoughnutChart, BarChart]
        assert chart_titles(ws)[0] == "Stock levels" and chart_titles(ws)[1].startswith("Low-stock products")
        tiles = [c for row in ws.iter_rows(max_col=8) for c in row if c.value in ("Out of stock", "Low stock", "Healthy")]
        chips = {c.value: ws.cell(row=c.row + 1, column=c.column).value for c in tiles}
        assert chips == {"Out of stock": 0, "Low stock": 1, "Healthy": 3}
        fills = {c.value: c.fill.start_color.rgb[-6:] for c in tiles}
        assert fills == {"Out of stock": "F8D7DA", "Low stock": "FFF1C2", "Healthy": "DCEBDF"}
        said = " ".join(texts(ws))
        assert "Restock Ragi Flour" in said and "Ragi Flour is selling fast but is almost out of stock. Restock now." in said
        assert "Jaggery had no sales in the last 30 days" in said and "Consider a discount or a combo for Jaggery." in said
    a = workbook(admin.get("/admin/products/export.xlsx"))["Insights"]
    o = workbook(owner.get("/owner/inventory/export.xlsx"))["Insights"]
    assert [[c.value for c in r] for r in a.iter_rows()] == [[c.value for c in r] for r in o.iter_rows()]   # one shared builder, one wording


def test_product_import_still_reads_the_first_sheet(admin, session, cat):
    seed_shop(session, cat)
    from app.admin.csvio import export_xlsx, import_csv  # noqa: F401
    from app.models import Product
    wb = load_workbook(io.BytesIO(export_xlsx(session.query(Product).all())))
    assert wb.worksheets[0].title == "Products" and wb.worksheets[-1].title == "Insights"


def test_stock_report_with_no_products_is_valid(owner, session):
    wb = workbook(owner.get("/owner/inventory/export.xlsx"))
    ws = wb["Insights"]
    assert not_enough(ws) == 3 and ws._charts == []


# ---------------------------------------------------------------- permissions stay as they were
@pytest.mark.parametrize("url", ["/owner/analytics.xlsx", "/owner/orders/export.xlsx", "/owner/inventory/export.xlsx"])
def test_owner_routes_stay_owner_only(admin, session, url):
    assert admin.get(url).status_code in (302, 401, 403, 404)


# ---------------------------------------------------------------- the rules themselves
def test_rules_fire_only_above_their_thresholds_and_never_on_thin_data():
    assert ri.rule_top_product_share("X", 31, 10) and not ri.rule_top_product_share("X", 30, 10) and not ri.rule_top_product_share("X", 90, 4)
    assert ri.rule_cancelled(3, 20) and not ri.rule_cancelled(2, 20) and not ri.rule_cancelled(4, 4)
    assert ri.rule_repeat_rate(19.9, 10) and not ri.rule_repeat_rate(20, 10) and not ri.rule_repeat_rate(0, 4)
    assert ri.rule_pincode(Counter({"600001": 5, "600002": 5}), 10) and not ri.rule_pincode(Counter({"600001": 4, "600002": 6, "600003": 6}), 16)
    assert not ri.rule_pincode(Counter({"Unknown": 10}), 10)                             # an unknown pincode is not advice
    assert ri.rule_revenue_drop(Decimal(80), Decimal(100), 5)[0][1].startswith("Revenue is down 20% versus the previous period")
    assert not ri.rule_revenue_drop(Decimal(95), Decimal(100), 5) and not ri.rule_revenue_drop(Decimal(0), Decimal(100), 2) and not ri.rule_revenue_drop(Decimal(10), Decimal(0), 9)
    assert ri.rule_fast_but_low([("A", "out"), ("B", "ok"), ("C", "low")]) == [
        ("Restock A", "A is selling fast but is out of stock. Restock now."), ("Restock C", "C is selling fast but is almost out of stock. Restock now.")]
    assert ri.rule_no_sales([], 0) == [] and "Consider a discount or a combo for A and B." in ri.rule_no_sales(["A", "B"], 2)[0][1]
    assert ri._finish([], False) == [("No suggestions yet", ri.NOT_ENOUGH)] and ri._finish([], True) == [ri.ALL_CLEAR]


def test_a_workbook_with_an_empty_chart_block_is_valid():
    block = ChartBlock("Nothing", "bar", ["Month", "Sales (₹)"], [TEXT, MONEY], [], suggestions=[("t", "body")])
    wb = load_workbook(io.BytesIO(build_workbook([InsightsSheet(blocks=[block, ChartBlock("Text", "text", suggestions=[("a", "b")])])])))
    assert wb["Insights"]._charts == [] and any("No data" in t for t in texts(wb["Insights"]))
