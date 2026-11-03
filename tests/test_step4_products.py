import csv
import io
import os
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models import AuditLog, Category, InventoryLog, Offer, Product, ProductImage, ProductVariant
from tests.helpers import img, make_user, post, sign_in
from tests.test_step2_models import make_category, make_product


@pytest.fixture()
def admin(app, session):
    make_user(session, "admin")
    c = app.test_client()
    sign_in(c, "admin")
    return c


@pytest.fixture()
def cat(session):
    c = make_category(session, "Snacks")
    session.commit()
    return c


def pdata(cat, **over):
    data = {"name": "Ragi Cookies", "sku": "p100", "category_id": str(cat.id), "mrp": "150", "discount_type": "none",
            "discount_value": "0", "stock_qty": "10", "low_stock_threshold": "3", "is_active": "1"}
    data.update(over)
    return {k: v for k, v in data.items() if v is not None}


def get_product(session, sku="P100"):
    session.expire_all()
    return session.scalar(select(Product).where(Product.sku == sku))


# ---------------- create / edit ----------------
def test_create_product_with_all_the_basics(admin, session, cat):
    r = post(admin, "/admin/products/new", pdata(cat, discount_type="percent", discount_value="20", tags="low sugar, Millet, low sugar",
                                                specifications="Shelf life: 6 months\nStorage: Cool and dry", nutrition_calories="310",
                                                nutrition_protein="11.5", video_id="dQw4w9WgXcQ", brand="Nurse"))
    assert r.status_code == 302
    p = get_product(session)
    assert p.final_price == Decimal("120.00") and p.discount_percent == 20 and p.slug == "ragi-cookies"
    assert p.sku == "P100"  # upper-cased
    assert p.tags == ["low sugar", "Millet"] and p.specifications == {"Shelf life": "6 months", "Storage": "Cool and dry"}
    assert p.nutrition == {"calories": 310, "protein": 11.5} and p.stock_qty == 10
    log = session.scalar(select(InventoryLog).where(InventoryLog.product_id == p.id))
    assert (log.old_qty, log.new_qty, log.reason) == (0, 10, "initial stock")
    assert "product.create" in [a.action for a in session.scalars(select(AuditLog))]


@pytest.mark.parametrize("over,field", [
    ({"name": ""}, "name"), ({"name": "x"}, "name"),
    ({"sku": ""}, "sku"), ({"sku": "bad sku!"}, "sku"),
    ({"category_id": ""}, "category_id"), ({"category_id": "999"}, "category_id"),
    ({"mrp": ""}, "mrp"), ({"mrp": "-5"}, "mrp"), ({"mrp": "0"}, "mrp"), ({"mrp": "abc"}, "mrp"), ({"mrp": "99999999"}, "mrp"),
    ({"discount_type": "percent", "discount_value": "101"}, "discount_value"),
    ({"discount_type": "percent", "discount_value": "-1"}, "discount_value"),
    ({"discount_type": "flat", "discount_value": "151"}, "discount_value"),
    ({"discount_type": "bogus"}, "discount_type"),
    ({"stock_qty": "-1"}, "stock_qty"), ({"stock_qty": "1.5"}, "stock_qty"),
    ({"video_id": "short"}, "video_id"),
    ({"specifications": "no colon here"}, "specifications"),
    ({"nutrition_fat": "-3"}, "nutrition_fat"),
])
def test_product_validation_errors_are_shown_and_nothing_is_saved(admin, session, cat, over, field):
    r = post(admin, "/admin/products/new", pdata(cat, **over))
    assert r.status_code == 422
    html = r.get_data(as_text=True)
    assert f'id="{field}-err"' in html or field == "category_id" and "Choose a category" in html
    assert session.scalar(select(Product)) is None


def test_failed_form_keeps_what_the_admin_typed(admin, cat):
    r = post(admin, "/admin/products/new", pdata(cat, name="My Product", mrp="-5", description="Long text here"))
    html = r.get_data(as_text=True)
    assert 'value="My Product"' in html and "Long text here" in html and 'value="-5"' in html


def test_duplicate_sku_rejected_case_insensitively_but_own_sku_ok_on_edit(admin, session, cat):
    post(admin, "/admin/products/new", pdata(cat))
    assert post(admin, "/admin/products/new", pdata(cat, sku="P100", name="Other")).status_code == 422
    assert post(admin, "/admin/products/new", pdata(cat, sku="p100", name="Other")).status_code == 422
    p = get_product(session)
    assert post(admin, f"/admin/products/{p.id}/edit", pdata(cat, name="Renamed")).status_code == 302


def test_edit_logs_stock_change_and_keeps_slug(admin, session, cat):
    post(admin, "/admin/products/new", pdata(cat))
    p = get_product(session)
    post(admin, f"/admin/products/{p.id}/edit", pdata(cat, name="Brand New Name", stock_qty="4", discount_type="flat", discount_value="30"))
    p = get_product(session)
    assert p.name == "Brand New Name" and p.slug == "ragi-cookies" and p.final_price == Decimal("120.00")
    last = session.scalars(select(InventoryLog).order_by(InventoryLog.id.desc())).first()
    assert (last.old_qty, last.new_qty, last.reason, last.changed_by) == (10, 4, "admin edit", session.scalar(select(AuditLog.actor_id).limit(1)))
    before = session.scalar(select(AuditLog).where(AuditLog.action == "product.update"))
    assert before.before["stock_qty"] == 10 and before.after["stock_qty"] == 4


def test_subcategory_must_belong_to_the_chosen_category(admin, session, cat):
    other = make_category(session, "Sweets")
    sub = Category(name="Laddu", slug="laddu", parent_id=other.id)
    session.add(sub)
    session.commit()
    assert post(admin, "/admin/products/new", pdata(cat, subcategory_id=str(sub.id))).status_code == 422
    assert post(admin, "/admin/products/new", pdata(other, subcategory_id=str(sub.id))).status_code == 302


def test_variants_are_created_updated_and_removed(admin, session, cat):
    rows = {"variant_id": ["", ""], "variant_option_name": ["Size", "Size"], "variant_option_value": ["200 g", "500 g"],
            "variant_sku": ["", "P100-BIG"], "variant_mrp": ["", "400"], "variant_price": ["150", "350"], "variant_stock": ["5", "8"]}
    assert post(admin, "/admin/products/new", pdata(cat, **rows)).status_code == 302
    p = get_product(session)
    assert sorted((v.option_value, v.sku, int(v.price), v.stock_qty) for v in p.variants) == [("200 g", "P100-1", 150, 5), ("500 g", "P100-BIG", 350, 8)]
    keep = next(v for v in p.variants if v.option_value == "500 g")
    rows2 = {"variant_id": [str(keep.id)], "variant_option_name": ["Size"], "variant_option_value": ["500 g"], "variant_sku": ["P100-BIG"],
             "variant_mrp": ["400"], "variant_price": ["300"], "variant_stock": ["2"]}
    post(admin, f"/admin/products/{p.id}/edit", pdata(cat, **rows2))
    p = get_product(session)
    assert len(p.variants) == 1 and p.variants[0].price == Decimal("300.00") and p.variants[0].stock_qty == 2
    assert session.scalar(select(InventoryLog).where(InventoryLog.variant_id == keep.id, InventoryLog.new_qty == 2)) is not None


@pytest.mark.parametrize("rows,problem", [
    ({"variant_option_value": [""], "variant_price": ["10"]}, "option value"),
    ({"variant_option_value": ["x"], "variant_price": ["-1"]}, "price must be a number"),
    ({"variant_option_value": ["x"], "variant_price": ["10"], "variant_mrp": ["5"]}, "MRP cannot be lower"),
    ({"variant_option_value": ["x", "y"], "variant_price": ["10", "10"], "variant_sku": ["S1", "s1"]}, "used twice"),
])
def test_variant_validation(admin, session, cat, rows, problem):
    n = len(rows.get("variant_option_value", [""]))
    base = {"variant_id": [""] * n, "variant_option_name": ["Size"] * n, "variant_sku": [""] * n, "variant_mrp": [""] * n,
            "variant_stock": ["1"] * n, "variant_price": [""] * n, "variant_option_value": [""] * n}
    base.update(rows)
    r = post(admin, "/admin/products/new", pdata(cat, **base))
    assert r.status_code == 422 and problem in r.get_data(as_text=True)


def test_prefilled_blank_variant_rows_are_ignored(admin, session, cat):
    """A browser submits the spare rows with the default option name "Size"; they must not count as filled in."""
    rows = {"variant_id": ["", ""], "variant_option_name": ["Size", "Size"], "variant_option_value": ["", ""],
            "variant_sku": ["", ""], "variant_mrp": ["", ""], "variant_price": ["", ""], "variant_stock": ["", ""]}
    assert post(admin, "/admin/products/new", pdata(cat, **rows)).status_code == 302
    assert get_product(session).variants == []


def test_offers_and_related_products(admin, session, cat):
    offer = Offer(name="Deal", tag="Deal of the Day")
    session.add(offer)
    other = make_product(session, category=cat, sku="OTHER", slug="other", name="Other")
    session.commit()
    post(admin, "/admin/products/new", pdata(cat, offer_ids=[str(offer.id), "99999"], related_ids=[str(other.id)]))
    p = get_product(session)
    assert [o.tag for o in p.offers] == ["Deal of the Day"] and [r.sku for r in p.related] == ["OTHER"]


# ---------------- images ----------------
def files_on_disk(app):
    return {os.path.join(d, f) for d, _, fs in os.walk(app.config["UPLOAD_DIR"]) for f in fs}


def test_upload_several_images_first_is_main_and_thumbnails_exist(admin, session, cat, app):
    r = post(admin, "/admin/products/new", pdata(cat), files={"images": [img("a.png"), img("b.png", color=(0, 0, 200))]})
    assert r.status_code == 302
    p = get_product(session)
    assert [i.is_primary for i in p.images] == [True, False] and all(i.thumb_url for i in p.images)
    assert admin.get(p.images[0].thumb_url).status_code == 200


def test_bad_image_blocks_the_whole_save_and_leaves_no_files(admin, session, cat, app):
    before = files_on_disk(app)
    r = post(admin, "/admin/products/new", pdata(cat), files={"images": [img("ok.png"), (io.BytesIO(b"<?php evil ?>"), "x.png")]})
    assert r.status_code == 422 and "not a valid image" in r.get_data(as_text=True)
    assert session.scalar(select(Product)) is None
    assert files_on_disk(app) == before


def test_image_limit_per_product(admin, session, cat):
    post(admin, "/admin/products/new", pdata(cat), files={"images": [img(f"{i}.png") for i in range(10)]})
    p = get_product(session)
    assert len(p.images) == 10
    r = post(admin, f"/admin/products/{p.id}/edit", pdata(cat), files={"images": [img("extra.png")]})
    assert r.status_code == 422 and "at most 10" in r.get_data(as_text=True)


def test_set_main_move_and_delete_image_removes_files(admin, session, cat, app):
    post(admin, "/admin/products/new", pdata(cat), files={"images": [img("a.png"), img("b.png"), img("c.png")]})
    p = get_product(session)
    a, b, c = p.images
    page = f"/admin/products/{p.id}/edit"
    post(admin, f"/admin/products/{p.id}/images/{c.id}/primary", page=page)
    post(admin, f"/admin/products/{p.id}/images/{c.id}/move", {"direction": "up"}, page=page)
    p = get_product(session)
    assert [i.id for i in p.images] == [a.id, c.id, b.id] and p.primary_image.id == c.id
    paths = [os.path.join(app.config["UPLOAD_DIR"], u[len("/uploads/"):]) for u in (c.url, c.thumb_url)]
    post(admin, f"/admin/products/{p.id}/images/{c.id}/delete", page=page)
    p = get_product(session)
    assert [i.id for i in p.images] == [a.id, b.id] and p.primary_image is not None
    assert not any(os.path.exists(x) for x in paths)


def test_image_routes_reject_images_of_other_products(admin, session, cat):
    post(admin, "/admin/products/new", pdata(cat, sku="P1", name="One"), files={"images": [img()]})
    post(admin, "/admin/products/new", pdata(cat, sku="P2", name="Two"))
    one, two = get_product(session, "P1"), get_product(session, "P2")
    assert post(admin, f"/admin/products/{two.id}/images/{one.images[0].id}/delete", page="/admin/products").status_code == 404


# ---------------- archive / undo / delete / duplicate ----------------
def test_archive_undo_and_permanent_delete(admin, session, cat, app):
    post(admin, "/admin/products/new", pdata(cat), files={"images": [img()]})
    p = get_product(session)
    urls = [os.path.join(app.config["UPLOAD_DIR"], u[len("/uploads/"):]) for u in (p.images[0].url, p.images[0].thumb_url)]
    r = post(admin, f"/admin/products/{p.id}/archive", page="/admin/products")
    assert r.headers["Location"].endswith(f"/admin/products?undo={p.id}")
    assert get_product(session).is_deleted
    html = admin.get(r.headers["Location"]).get_data(as_text=True)
    assert "Undo" in html and 'value="restore"' in html
    post(admin, "/admin/products/bulk", {"action": "restore", "ids": [str(p.id)]}, page="/admin/products")  # what the Undo button posts
    assert not get_product(session).is_deleted
    # permanent delete: needs archived state + confirm for bulk; single delete needs confirm
    post(admin, f"/admin/products/{p.id}/archive", page="/admin/products")
    post(admin, f"/admin/products/{p.id}/delete", page="/admin/products")
    assert get_product(session) is not None
    post(admin, f"/admin/products/{p.id}/delete", {"confirm": "1"}, page="/admin/products")
    assert get_product(session) is None and not any(os.path.exists(x) for x in urls)


def test_duplicate_is_hidden_has_copied_files_and_own_skus(admin, session, cat, app):
    rows = {"variant_id": [""], "variant_option_name": ["Size"], "variant_option_value": ["500 g"], "variant_sku": [""], "variant_mrp": [""],
            "variant_price": ["300"], "variant_stock": ["4"]}
    post(admin, "/admin/products/new", pdata(cat, **rows), files={"images": [img()]})
    src = get_product(session)
    r = post(admin, f"/admin/products/{src.id}/duplicate", page="/admin/products")
    assert r.status_code == 302
    session.expire_all()
    copy = session.scalar(select(Product).where(Product.id != src.id))
    assert copy.name == "Ragi Cookies (Copy)" and copy.sku == "P100-COPY" and not copy.is_active and copy.stock_qty == 0
    assert copy.images[0].url != src.images[0].url and admin.get(copy.images[0].url).status_code == 200
    assert copy.variants[0].sku != src.variants[0].sku and copy.variants[0].stock_qty == 0
    # deleting the copy must not break the original
    post(admin, f"/admin/products/{copy.id}/archive", page="/admin/products")
    post(admin, f"/admin/products/{copy.id}/delete", {"confirm": "1"}, page="/admin/products")
    assert admin.get(src.images[0].url).status_code == 200
    # a second copy gets its own SKU
    post(admin, f"/admin/products/{src.id}/duplicate", page="/admin/products")
    assert session.scalar(select(Product).where(Product.sku == "P100-COPY")) is not None


# ---------------- list, search, filters ----------------
def test_list_search_filters_and_pagination(admin, session, cat):
    other = make_category(session, "Sweets")
    for i in range(25):
        make_product(session, category=cat if i % 2 else other, sku=f"S{i:02}", slug=f"s{i}", name=f"Item {i:02}",
                     stock_qty=0 if i == 3 else (2 if i == 5 else 50), final_price=Decimal(10 + i), mrp=Decimal(10 + i))
    make_product(session, category=cat, sku="ZZ", slug="zz", name="Special Millet", brand="Nurse")
    session.commit()
    html = admin.get("/admin/products").get_data(as_text=True)
    assert "Page 1 of 2" in html and "Item 24" in html
    assert "Special Millet" in admin.get("/admin/products?q=millet").get_data(as_text=True)
    assert "Special Millet" in admin.get("/admin/products?q=nurse").get_data(as_text=True)
    assert "Item 03" in admin.get("/admin/products?stock=out").get_data(as_text=True)
    low = admin.get("/admin/products?stock=low").get_data(as_text=True)
    assert "Item 05" in low and "Item 03" not in low
    assert admin.get(f"/admin/products?category={cat.id}&q=item").get_data(as_text=True).count("Item ") >= 10
    assert admin.get("/admin/products?page=abc&sort=price_desc").status_code == 200
    assert admin.get("/admin/products?page=999").status_code == 200


# ---------------- bulk actions ----------------
@pytest.fixture()
def three(session, cat):
    ps = [make_product(session, category=cat, sku=f"B{i}", slug=f"b{i}", name=f"Bulk {i}", mrp=Decimal(100), final_price=Decimal(100)) for i in range(3)]
    session.commit()
    return ps


def bulk(admin, ps, action, **extra):
    return post(admin, "/admin/products/bulk", {"action": action, "ids": [str(p.id) for p in ps], **extra}, page="/admin/products")


def test_bulk_hide_show_archive_restore(admin, session, three):
    bulk(admin, three, "hide")
    session.expire_all()
    assert not any(p.is_active for p in three)
    bulk(admin, three, "show")
    session.expire_all()
    assert all(p.is_active for p in three)
    r = bulk(admin, three[:2], "archive")
    assert "undo=" in r.headers["Location"]
    session.expire_all()
    assert [p.is_deleted for p in three] == [True, True, False]
    bulk(admin, three[:2], "restore")
    session.expire_all()
    assert not any(p.is_deleted for p in three)


def test_bulk_discount_and_price_change(admin, session, three):
    bulk(admin, three, "discount", discount_type="percent", value="25")
    session.expire_all()
    assert all(p.final_price == Decimal("75.00") for p in three)
    bulk(admin, three, "price_percent", value="10")
    session.expire_all()
    assert all(p.mrp == Decimal("110.00") and p.final_price == Decimal("82.50") for p in three)
    bulk(admin, three, "discount", discount_type="none")
    session.expire_all()
    assert all(p.final_price == Decimal("110.00") and p.discount_type == "none" for p in three)


@pytest.mark.parametrize("extra,msg", [
    ({"discount_type": "percent", "value": "150"}, "valid discount"),
    ({"discount_type": "flat", "value": "500"}, "more than the MRP"),
    ({"discount_type": "flat", "value": "abc"}, "valid discount"),
])
def test_bulk_discount_rejects_bad_values_and_changes_nothing(admin, session, three, extra, msg):
    r = admin.get(bulk(admin, three, "discount", **extra).headers["Location"])
    assert msg in r.get_data(as_text=True)
    session.expire_all()
    assert all(p.final_price == Decimal("100.00") for p in three)


@pytest.mark.parametrize("value", ["0", "-95", "600", "x"])
def test_bulk_price_change_limits(admin, session, three, value):
    bulk(admin, three, "price_percent", value=value)
    session.expire_all()
    assert all(p.mrp == Decimal("100.00") for p in three)


def test_bulk_move_category_and_delete_rules(admin, session, three, cat):
    other = make_category(session, "Sweets")
    session.commit()
    bulk(admin, three, "move_category", category_id=str(other.id))
    session.expire_all()
    assert all(p.category_id == other.id for p in three)
    bulk(admin, three, "delete", confirm="1")  # still live: refused
    assert session.scalar(select(Product).where(Product.sku == "B0")) is not None
    bulk(admin, three, "archive")
    bulk(admin, three, "delete")  # no confirmation: refused
    assert session.scalar(select(Product).where(Product.sku == "B0")) is not None
    bulk(admin, three, "delete", confirm="1")
    session.expire_all()
    assert session.scalar(select(Product).where(Product.sku == "B0")) is None


def test_bulk_with_no_selection_or_unknown_ids(admin, three):
    assert "Select at least one" in admin.get(post(admin, "/admin/products/bulk", {"action": "hide"}, page="/admin/products").headers["Location"]).get_data(as_text=True)
    r = post(admin, "/admin/products/bulk", {"action": "hide", "ids": ["999999"]}, page="/admin/products")
    assert "no longer exist" in admin.get(r.headers["Location"]).get_data(as_text=True)
    assert post(admin, "/admin/products/bulk", {"action": "explode", "ids": [str(three[0].id)]}, page="/admin/products").status_code == 302


# ---------------- CSV ----------------
def test_export_escapes_formula_injection_and_roundtrips(admin, session, cat):
    make_product(session, category=cat, sku="X1", slug="x1", name='=HYPERLINK("http://evil","click")', mrp=Decimal(50), final_price=Decimal(50))
    make_product(session, category=cat, sku="X2", slug="x2", name="@cmd", mrp=Decimal(60), final_price=Decimal(60))
    session.commit()
    r = admin.get("/admin/products/export.csv")
    assert r.mimetype == "text/csv" and "attachment" in r.headers["Content-Disposition"]
    rows = list(csv.DictReader(io.StringIO(r.get_data(as_text=True))))
    names = {x["sku"]: x["name"] for x in rows}
    assert names["X1"].startswith("'=") and names["X2"] == "'@cmd"


def import_file(admin, text, **extra):
    data = {"default_stock": "7", **extra}
    return post(admin, "/admin/products/import", data, files={"file": (io.BytesIO(text.encode("utf-8")), "p.csv")})


def test_import_new_format_creates_updates_and_logs_stock(admin, session, cat):
    r = import_file(admin, "sku,name,category,mrp,discount_type,discount_value,stock_qty,tags,image_urls\n"
                           "N1,New One,Snacks,100,percent,10,5,\"low sugar, featured\",/images/a.png|https://x.test/b.jpg\n"
                           "N2,New Two,Sweets,200,none,0,0,,\n", create_categories="1")
    assert r.status_code == 302
    session.expire_all()
    n1 = session.scalar(select(Product).where(Product.sku == "N1"))
    assert n1.final_price == Decimal("90.00") and n1.is_bestseller and n1.tags == ["low sugar"] and len(n1.images) == 2 and n1.stock_qty == 5
    assert session.scalar(select(Category).where(Category.name == "Sweets")) is not None
    r = import_file(admin, "sku,name,category,mrp,stock_qty\nn1,New One Renamed,Snacks,120,9\n")
    session.expire_all()
    n1 = session.scalar(select(Product).where(Product.sku == "N1"))
    assert n1.name == "New One Renamed" and n1.mrp == Decimal("120.00") and n1.stock_qty == 9 and len(n1.images) == 2
    assert session.scalar(select(InventoryLog).where(InventoryLog.product_id == n1.id, InventoryLog.reason == "csv import", InventoryLog.new_qty == 9))


def test_import_old_site_format(admin, session, cat):
    r = import_file(admin, "id,name,category,price,weight,image,shortDescription,inStock,tags\n"
                           "P900,Old Style,Snacks,180,200 g,/images/x.png,Short,TRUE,\"a, featured\"\nP901,Sold Out,Snacks,90,100 g,,,FALSE,\n")
    assert r.status_code == 302
    session.expire_all()
    a, b = (session.scalar(select(Product).where(Product.sku == s)) for s in ("P900", "P901"))
    assert (a.stock_qty, b.stock_qty) == (7, 0) and a.pack_size == "200 g" and a.is_bestseller and a.images[0].url == "/images/x.png"


def test_import_is_all_or_nothing_with_row_numbers(admin, session, cat):
    r = import_file(admin, "sku,name,category,mrp,discount_type,discount_value\n"
                           "G1,Good,Snacks,100,none,0\n"
                           "G2,,Snacks,100,none,0\n"
                           "G3,Neg,Snacks,-5,none,0\n"
                           "G4,Cat,Nowhere,10,none,0\n"
                           "G5,Disc,Snacks,10,percent,500\n"
                           "G1,Dup,Snacks,10,none,0\n"
                           "bad sku,X,Snacks,10,none,0\n")
    html = r.get_data(as_text=True)
    assert r.status_code == 422 and "Nothing was imported" in html
    for needle in ("Row 3 (G2)", "Row 4 (G3)", "Row 5 (G4)", "does not exist", "Row 6 (G5)", "appears twice", "Row 8"):
        assert needle in html
    assert session.scalar(select(Product)) is None


@pytest.mark.parametrize("text,msg", [
    ("name,category\nA,B\n", "Missing column"),
    ("sku,name,category,mrp\n", "no product rows"),
    ("sku,name,category,mrp,image_urls\nA1,Name,Snacks,10,javascript:alert(1)\n", "not allowed"),
    ("sku,name,category,mrp,video_id\nA1,Name,Snacks,10,bad\n", "YouTube"),
])
def test_import_rejects_bad_files(admin, session, cat, text, msg):
    r = import_file(admin, text)
    assert r.status_code == 422 and msg in r.get_data(as_text=True)


def test_import_rejects_binary_and_huge_files(admin, cat):
    r = post(admin, "/admin/products/import", {"default_stock": "0"}, files={"file": (io.BytesIO(b"\xff\xfe\x00\x01" * 10), "x.csv")})
    assert r.status_code == 422 and "UTF-8" in r.get_data(as_text=True)
    big = io.BytesIO(b"sku,name,category,mrp\n" + b"A1,Name,Snacks,10\n" * 200000)
    assert post(admin, "/admin/products/import", {"default_stock": "0"}, files={"file": (big, "x.csv")}).status_code == 422


# ---------------- access ----------------
def test_owner_and_customers_cannot_use_product_admin(app, session):
    make_user(session, "owner")
    make_user(session, "user")
    for role in ("owner", "user"):
        c = app.test_client()
        sign_in(c, role)
        for url in ("/admin/products", "/admin/products/new", "/admin/categories", "/admin/products/export.csv", "/admin/products/import"):
            assert c.get(url).status_code == 403, (role, url)
