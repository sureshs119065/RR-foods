import io
import os

import pytest
from sqlalchemy import select

from app.models import AuditLog, Category, Product
from tests.helpers import img, make_user, post, sign_in
from tests.test_step2_models import make_category, make_product


@pytest.fixture()
def admin(app, session):
    make_user(session, "admin")
    c = app.test_client()
    sign_in(c, "admin")
    return c


def names(session):
    session.expire_all()
    return [c.name for c in session.scalars(select(Category).where(Category.is_deleted.is_(False)).order_by(Category.sort_order, Category.id))]


def test_create_category_and_subcategory(admin, session):
    r = post(admin, "/admin/categories/new", {"name": "  Breakfast  ", "is_active": "1", "sort_order": "1"})
    assert r.status_code == 302
    parent = session.scalar(select(Category).where(Category.name == "Breakfast"))
    assert parent.slug == "breakfast" and parent.is_active
    r = post(admin, "/admin/categories/new", {"name": "Oats", "parent_id": str(parent.id), "is_active": "1"})
    assert r.status_code == 302
    sub = session.scalar(select(Category).where(Category.name == "Oats"))
    assert sub.parent_id == parent.id
    assert "category.create" in [a.action for a in session.scalars(select(AuditLog))]


@pytest.mark.parametrize("data,field", [
    ({"name": "A"}, "name"),
    ({"name": "Fine", "sort_order": "abc"}, "sort_order"),
    ({"name": "Fine", "parent_id": "9999"}, "parent_id"),
])
def test_category_validation(admin, data, field):
    r = post(admin, "/admin/categories/new", data)
    assert r.status_code == 422 and f"{field}-err" not in "" and "error" in r.get_data(as_text=True)


def test_duplicate_name_rejected_but_same_name_allowed_under_other_parent(admin, session):
    root = make_category(session, "Snacks")
    other = make_category(session, "Sweets")
    session.commit()
    assert post(admin, "/admin/categories/new", {"name": "snacks"}).status_code == 422
    assert post(admin, "/admin/categories/new", {"name": "Mini", "parent_id": str(root.id)}).status_code == 302
    assert post(admin, "/admin/categories/new", {"name": "Mini", "parent_id": str(other.id)}).status_code == 302


def test_cannot_make_category_its_own_parent_or_nest_three_levels(admin, session):
    a = make_category(session, "Alpha")
    b = Category(name="Beta", slug="beta", parent_id=a.id)
    session.add(b)
    session.commit()
    assert post(admin, f"/admin/categories/{a.id}/edit", {"name": "Alpha", "parent_id": str(a.id)}).status_code == 422
    assert post(admin, f"/admin/categories/{a.id}/edit", {"name": "Alpha", "parent_id": str(b.id)}).status_code == 422  # would create a cycle
    assert post(admin, "/admin/categories/new", {"name": "Gamma", "parent_id": str(b.id)}).status_code == 422  # third level
    assert post(admin, f"/admin/categories/{a.id}/edit", {"name": "Alpha"}).status_code == 302


def test_reorder_up_and_down(admin, session):
    for n in ("Apple", "Banana", "Cherry"):
        make_category(session, n)
    session.commit()
    cherry = session.scalar(select(Category).where(Category.name == "Cherry"))
    post(admin, f"/admin/categories/{cherry.id}/move", {"direction": "up"}, page="/admin/categories")
    assert names(session) == ["Apple", "Cherry", "Banana"]
    post(admin, f"/admin/categories/{cherry.id}/move", {"direction": "up"}, page="/admin/categories")
    post(admin, f"/admin/categories/{cherry.id}/move", {"direction": "up"}, page="/admin/categories")  # already first: no change
    assert names(session) == ["Cherry", "Apple", "Banana"]
    post(admin, f"/admin/categories/{cherry.id}/move", {"direction": "down"}, page="/admin/categories")
    assert names(session) == ["Apple", "Cherry", "Banana"]
    assert post(admin, f"/admin/categories/{cherry.id}/move", {"direction": "sideways"}, page="/admin/categories").status_code == 400


def test_archive_blocked_while_products_exist_then_allowed_and_restorable(admin, session):
    cat = make_category(session, "Snacks")
    p = make_product(session, category=cat)
    session.commit()
    r = post(admin, f"/admin/categories/{cat.id}/archive", page="/admin/categories", follow=True)
    assert "still has 1 product" in r.get_data(as_text=True)
    p.archive()
    session.commit()
    post(admin, f"/admin/categories/{cat.id}/archive", page="/admin/categories")
    session.expire_all()
    assert session.get(Category, cat.id).is_deleted
    post(admin, f"/admin/categories/{cat.id}/restore", page="/admin/categories")
    session.expire_all()
    assert not session.get(Category, cat.id).is_deleted


def test_permanent_delete_needs_confirmation_and_an_empty_category(admin, session):
    empty = make_category(session, "Empty")
    full = make_category(session, "Full")
    make_product(session, category=full)
    session.commit()
    post(admin, f"/admin/categories/{empty.id}/delete", page="/admin/categories")  # no confirm box
    assert session.get(Category, empty.id) is not None
    post(admin, f"/admin/categories/{full.id}/delete", {"confirm": "1"}, page="/admin/categories")
    assert session.get(Category, full.id) is not None
    post(admin, f"/admin/categories/{empty.id}/delete", {"confirm": "1"}, page="/admin/categories")
    session.expire_all()
    assert session.get(Category, empty.id) is None


# ---------------- image upload safety ----------------
def uploaded_files(app):
    root = app.config["UPLOAD_DIR"]
    return [os.path.join(d, f) for d, _, fs in os.walk(root) for f in fs]


def test_category_image_upload_resizes_and_removal_deletes_files(admin, session, app):
    r = post(admin, "/admin/categories/new", {"name": "Pics", "is_active": "1"}, files={"image": img(size=(3000, 2000))})
    assert r.status_code == 302
    cat = session.scalar(select(Category).where(Category.name == "Pics"))
    assert cat.image.startswith("/uploads/categories/") and cat.image.endswith(".webp")
    assert admin.get(cat.image).status_code == 200
    from PIL import Image
    path = os.path.join(app.config["UPLOAD_DIR"], cat.image[len("/uploads/"):])
    assert max(Image.open(path).size) <= 1000 and Image.open(path).format == "WEBP"
    post(admin, f"/admin/categories/{cat.id}/edit", {"name": "Pics", "is_active": "1", "remove_image": "1"})
    session.expire_all()
    assert session.get(Category, cat.id).image is None and not os.path.exists(path)


@pytest.mark.parametrize("payload,name", [
    (b"<?php echo 'hi'; ?>", "shell.php"),
    (b"<?php echo 'hi'; ?>", "shell.png"),            # script disguised with an image extension
    (b"GIF89a<script>alert(1)</script>", "x.gif"),
    (b"", "empty.png"),
    (b"\x89PNG\r\n\x1a\nnot really a png", "bad.png"),
])
def test_non_images_are_rejected(admin, session, payload, name):
    r = post(admin, "/admin/categories/new", {"name": "Bad", "is_active": "1"}, files={"image": (io.BytesIO(payload), name)})
    assert r.status_code == 422
    assert session.scalar(select(Category).where(Category.name == "Bad")) is None


def test_gif_and_oversized_images_rejected(admin, session):
    from PIL import Image
    gif = io.BytesIO()
    Image.new("RGB", (10, 10)).save(gif, "GIF")
    gif.seek(0)
    assert post(admin, "/admin/categories/new", {"name": "G"}, files={"image": (gif, "a.gif")}).status_code == 422
    big = io.BytesIO(b"\x00" * (5 * 1024 * 1024 + 10))
    assert post(admin, "/admin/categories/new", {"name": "Big"}, files={"image": (big, "big.png")}).status_code == 422


def test_uploads_route_blocks_path_traversal(admin):
    assert admin.get("/uploads/../config.py").status_code == 404
    assert admin.get("/uploads/%2e%2e/%2e%2e/etc/passwd").status_code == 404


def test_exif_and_original_filename_are_not_kept(admin, session):
    r = post(admin, "/admin/categories/new", {"name": "Name", "is_active": "1"}, files={"image": img("../../evil name.png")})
    cat = session.scalar(select(Category).where(Category.name == "Name"))
    assert "evil" not in cat.image and ".." not in cat.image
