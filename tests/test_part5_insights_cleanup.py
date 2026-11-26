"""Insights clean-up: the Payment methods donut is gone (Order status + Sales by category stay), and every download is Excel only."""
import json
import re
from pathlib import Path

import pytest

from tests.test_part4_products_stock_exports import admin, cat, owner  # noqa: F401  (fixtures)

STATIC = Path(__file__).resolve().parent.parent / "app" / "static"


def _payload(html: str) -> dict:
    return json.loads(re.search(r'<script type="application/json" id="sa-data">(.*?)</script>', html, re.S).group(1))


@pytest.mark.parametrize("who,url", [("admin", "/admin/"), ("owner", "/owner/")])
def test_payment_chart_is_gone_and_the_other_two_donuts_stay(admin, owner, who, url):
    client = {"admin": admin, "owner": owner}[who]
    r = client.get(url)
    html = r.get_data(as_text=True)
    assert r.status_code == 200
    assert "sa-payment" not in html and "Payment methods" not in html
    assert 'id="sa-status-chart"' in html and 'id="sa-category-chart"' in html
    assert "sa-chart-grid--2" in html and "sa-chart-grid--3" not in html          # two cards in a two-column row: no empty third slot
    data = _payload(html)
    assert "payment_methods" not in data and "status_breakdown" in data and "categories" in data


def test_javascript_and_css_no_longer_know_the_payment_chart():
    js = (STATIC / "js" / "sales-analytics.js").read_text(encoding="utf-8")
    assert "sa-payment" not in js and "PAYMENT_COLOURS" not in js and "payment_methods" not in js
    assert "sa-status-chart" in js and "sa-category-chart" in js
    for name in ("sales-analytics.css", "admin-dashboard.css", "owner.css"):
        assert "sa-chart-grid--3" not in (STATIC / "css" / name).read_text(encoding="utf-8")


def test_no_csv_download_is_offered_anywhere_and_every_download_link_works(admin, owner, session, cat):
    from tests.test_step2_models import make_product
    make_product(session, category=cat, sku="D1", slug="d1", name="Dal")
    session.commit()
    pages = [(admin, "/admin/"), (admin, "/admin/products"), (admin, "/admin/products/import"), (admin, "/admin/orders"),
             (admin, "/admin/users"), (owner, "/owner/"), (owner, "/owner/orders"), (owner, "/owner/inventory")]
    for client, url in pages:
        r = client.get(url)
        html = r.get_data(as_text=True)
        assert r.status_code == 200, url
        assert not re.search(r'href="[^"]*(?:export|analytics)[^"]*csv', html, re.I) and "Download CSV" not in html and "Export CSV" not in html, url
        for href in set(re.findall(r'href="(/(?:admin|owner)/[^"]*(?:export|analytics)[^"#]*)"', html)):
            href = href.replace("&amp;", "&")
            assert client.get(href).status_code == 200, (url, href)                 # no dead links, no 500s


def test_import_page_tip_mentions_excel_only_but_the_upload_still_takes_csv(admin):
    html = admin.get("/admin/products/import").get_data(as_text=True)
    assert "download your products as" in html and "products/export.xlsx" in html and "export.csv" not in html
    assert ".csv" in html and ".xlsx" in html                                      # the file picker still accepts both


def test_labels_say_download_excel(admin):
    assert "Download catalogue Excel" in admin.get("/admin/").get_data(as_text=True)
    html = admin.get("/admin/products").get_data(as_text=True)
    assert "Download Excel" in html and "Export Excel" not in html


@pytest.mark.parametrize("url", ["/admin/orders/export.csv", "/admin/orders/export.pdf", "/admin/users/export.csv", "/admin/products/export.csv",
                                 "/admin/analytics.csv", "/owner/orders/export.csv", "/owner/inventory/export.csv", "/owner/analytics.csv"])
def test_every_non_excel_export_is_a_404(admin, owner, url):
    client = owner if url.startswith("/owner") else admin
    assert client.get(url).status_code == 404


def test_the_csv_export_helpers_are_removed_but_the_importer_stays():
    from app.admin import csvio
    from app.services import report_export as rx, sales_report
    assert not any(hasattr(rx, n) for n in ("render_csv", "csv_response", "_csv_value", "_summary_csv"))
    assert not hasattr(csvio, "export_csv") and not hasattr(sales_report, "build_csv")
    assert hasattr(csvio, "import_csv") and hasattr(csvio, "export_xlsx")
