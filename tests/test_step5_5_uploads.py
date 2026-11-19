"""Step 5.5: uploads. Content type checked with Pillow, EXIF stripped, random names, size caps, no execution paths."""
import io
import os
import re
import stat

import pytest
from PIL import Image
from sqlalchemy import select
from werkzeug.datastructures import FileStorage

from app import uploads
from app.models import Category
from tests.helpers import make_user, post, sign_in, token
from tests.test_step6_shop import cust, catalog  # noqa: F401  (fixtures)

EXIF_MAKE = b"SECRET-CAMERA-MAKE"
EXIF_GPS_MARK = b"GPSLatitudeRef-marker"


@pytest.fixture()
def store(app, tmp_path):
    old = app.config["UPLOAD_DIR"]
    app.config["UPLOAD_DIR"] = str(tmp_path)
    with app.app_context():
        yield tmp_path
    app.config["UPLOAD_DIR"] = old


def fs(data, name="photo.jpg", mime="image/jpeg"):
    return FileStorage(stream=io.BytesIO(data), filename=name, content_type=mime)


def jpeg_with_exif(size=(120, 80), orientation=1):
    exif = Image.Exif()
    exif[0x010F] = EXIF_MAKE.decode()            # Make
    exif[0x0112] = orientation                   # Orientation
    exif[0x8825] = {1: "N", 2: (13.0, 4.0, 5.0)}  # a GPS block
    exif[0x010E] = EXIF_GPS_MARK.decode()        # ImageDescription
    buf = io.BytesIO()
    Image.new("RGB", size, (30, 120, 60)).save(buf, "JPEG", exif=exif, comment=b"camera-comment-xyz")
    return buf.getvalue()


def stored(root):
    return sorted(p for p in root.rglob("*") if p.is_file())


# ---------------------------------------------------------------- metadata
def test_source_really_carries_the_metadata(store):
    raw = jpeg_with_exif()
    assert EXIF_MAKE in raw and b"camera-comment-xyz" in raw  # so the next test proves something


def test_exif_gps_comment_and_xmp_are_not_in_any_stored_file(store):
    url, thumb = uploads.save_image(fs(jpeg_with_exif((1000, 700))), "products")
    files = stored(store)
    assert len(files) >= 2
    for path in files:
        raw = path.read_bytes()
        assert EXIF_MAKE not in raw and EXIF_GPS_MARK not in raw and b"camera-comment-xyz" not in raw, path.name
        assert b"EXIF" not in raw and b"XMP " not in raw and b"ICCP" not in raw, path.name  # WebP metadata chunks
        with Image.open(path) as im:
            assert im.format == "WEBP" and not im.getexif() and "exif" not in im.info and "xmp" not in im.info


def test_exif_rotation_is_applied_before_the_tag_is_dropped(store):
    url, _ = uploads.save_image(fs(jpeg_with_exif((120, 80), orientation=6)), "products", thumb_side=None)
    with Image.open(store / url[len("/uploads/"):]) as im:
        assert im.size == (80, 120)   # a sideways phone photo comes out upright


def test_png_text_chunks_are_dropped(store):
    from PIL.PngImagePlugin import PngInfo
    info = PngInfo()
    info.add_text("Author", "private-author-name")
    buf = io.BytesIO()
    Image.new("RGB", (50, 50), "red").save(buf, "PNG", pnginfo=info)
    assert b"private-author-name" in buf.getvalue()
    uploads.save_image(fs(buf.getvalue(), "a.png", "image/png"), "products")
    assert all(b"private-author-name" not in p.read_bytes() for p in stored(store))


# ---------------------------------------------------------------- names and modes
def test_names_are_random_and_never_the_visitors(store):
    a, _ = uploads.save_image(fs(jpeg_with_exif(), "../../etc/shell.php.jpg"), "products")
    b, _ = uploads.save_image(fs(jpeg_with_exif(), "../../etc/shell.php.jpg"), "products")
    assert a != b
    for url in (a, b):
        assert re.fullmatch(r"/uploads/products/[0-9a-f]{32}\.webp", url), url
    assert all("shell" not in p.name and "php" not in p.name for p in stored(store))
    assert all(store in p.parents for p in stored(store))   # nothing escaped the upload folder


def test_video_names_are_random_and_extension_comes_from_a_short_allow_list(store):
    mp4 = b"\x00\x00\x00\x18ftypmp42" + b"0" * 60
    url = uploads.save_video(fs(mp4, "../../evil.php.mp4", "video/mp4"), "reels")
    assert re.fullmatch(r"/uploads/reels/[0-9a-f]{32}\.mp4", url)
    for name in ("run.php", "run.html", "run.svg", "run.exe", "run"):
        with pytest.raises(uploads.UploadError):
            uploads.save_video(fs(mp4, name, "video/mp4"), "reels")


def test_stored_files_have_no_execute_bit(store):
    uploads.save_image(fs(jpeg_with_exif((1200, 900))), "products")
    uploads.save_image(fs(jpeg_with_exif()), "banners", thumb_side=None, budget=None)
    uploads.save_video(fs(b"\x00\x00\x00\x18ftypmp42" + b"0" * 60, "a.mp4", "video/mp4"), "reels")
    files = stored(store)
    assert len(files) >= 5   # main, 400 px, 800 px, banner, video
    for path in files:
        mode = stat.S_IMODE(path.stat().st_mode)
        assert not mode & 0o111, f"{path.name} is executable ({oct(mode)})"
        assert not mode & 0o022, f"{path.name} is group/world writable ({oct(mode)})"


# ---------------------------------------------------------------- content, not names
def test_a_script_appended_to_a_real_image_does_not_survive(store):
    payload = b"<?php system($_GET['c']); ?><script>alert(1)</script>"
    uploads.save_image(fs(jpeg_with_exif() + payload, "x.jpg"), "products")   # polyglot: valid JPEG, trailing code
    for path in stored(store):
        raw = path.read_bytes()
        assert b"<?php" not in raw and b"<script" not in raw


def _png(size=(10, 10), mode="RGB"):
    buf = io.BytesIO()
    Image.new(mode, size).save(buf, "PNG")
    return buf.getvalue()


def _fmt(fmt):
    buf = io.BytesIO()
    Image.new("RGB", (10, 10), "red").save(buf, fmt)
    return buf.getvalue()


@pytest.mark.parametrize("data,name,mime", [
    (b"<svg xmlns='http://www.w3.org/2000/svg'><script>alert(1)</script></svg>", "logo.svg", "image/svg+xml"),
    (b"<svg xmlns='http://www.w3.org/2000/svg'><script>alert(1)</script></svg>", "logo.png", "image/png"),   # SVG with a PNG name
    (b"<html><script>alert(1)</script></html>", "page.jpg", "image/jpeg"),
    (b"<?php echo 1; ?>", "shell.php", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n" + b"truncated", "cut.png", "image/png"),
    (_fmt("GIF"), "a.gif", "image/gif"),
    (_fmt("BMP"), "a.bmp", "image/bmp"),
    (_fmt("TIFF"), "a.tiff", "image/tiff"),
    (_fmt("ICO"), "a.ico", "image/x-icon"),
    (_fmt("PDF"), "a.pdf", "application/pdf"),
    (b"", "empty.png", "image/png"),
    (b"MZ\x90\x00" + b"\x00" * 200, "tool.png", "image/png"),                                                  # a Windows executable
])
def test_only_real_jpeg_png_webp_files_are_accepted(store, data, name, mime):
    with pytest.raises(uploads.UploadError):
        uploads.save_image(fs(data, name, mime), "products")
    assert stored(store) == []   # a refused file leaves nothing behind


@pytest.mark.parametrize("fmt,name", [("JPEG", "a.jpg"), ("PNG", "a.png"), ("WEBP", "a.webp")])
def test_the_three_real_formats_work_whatever_the_name_or_mime_claims(store, fmt, name):
    url, _ = uploads.save_image(fs(_fmt(fmt), "whatever.txt", "text/plain"), "products")
    assert url.endswith(".webp") and (store / url[len("/uploads/"):]).is_file()


def test_an_image_with_too_many_pixels_is_refused_before_it_is_decoded(store):
    buf = io.BytesIO()
    Image.new("1", (7000, 7000)).save(buf, "PNG")        # 49 megapixels, only a few KB on disk
    assert len(buf.getvalue()) < 100_000
    with pytest.raises(uploads.UploadError, match="pixels"):
        uploads.save_image(fs(buf.getvalue(), "bomb.png", "image/png"), "products")
    assert stored(store) == []


def test_file_size_caps(store):
    big = b"\x89PNG\r\n\x1a\n" + b"\x00" * (uploads.MAX_FILE_BYTES + 10)
    with pytest.raises(uploads.UploadError, match="5 MB"):
        uploads.save_image(fs(big, "big.png", "image/png"), "products")
    with pytest.raises(uploads.UploadError, match="50 MB"):
        uploads.save_video(fs(b"\x00\x00\x00\x18ftypmp42" + b"0" * (uploads.VIDEO_MAX_BYTES + 10), "a.mp4", "video/mp4"), "reels")


def test_error_messages_never_repeat_a_hostile_file_name(store):
    hostile = "../../" + "A" * 300 + "\r\nSet-Cookie: x=1\x00.png"
    with pytest.raises(uploads.UploadError) as err:
        uploads.save_image(fs(b"not an image", hostile, "image/png"), "products")
    msg = str(err.value)
    assert len(msg) < 160 and "\n" not in msg and "\r" not in msg and "\x00" not in msg and "../" not in msg


# ---------------------------------------------------------------- serving: no execution paths
@pytest.fixture()
def planted(app, tmp_path):
    """A hostile file somebody managed to drop into the upload folder (a restore from a bad backup, a shared disk...)."""
    old = app.config["UPLOAD_DIR"]
    app.config["UPLOAD_DIR"] = str(tmp_path)
    (tmp_path / "x").mkdir()
    for name, body in (("evil.html", b"<script>alert(1)</script>"), ("evil.svg", b"<svg onload=alert(1)/>"), ("evil.php", b"<?php ?>"),
                       ("evil.js", b"alert(1)"), ("evil.htm", b"<b>"), ("noext", b"hi"), (".hidden.webp", b"RIFF"), ("evil.webp.html", b"<b>")):
        (tmp_path / "x" / name).write_bytes(body)
    with app.app_context():
        url, _ = uploads.save_image(fs(jpeg_with_exif((300, 200))), "x", thumb_side=None)
    yield app.test_client(), url, tmp_path
    app.config["UPLOAD_DIR"] = old


@pytest.mark.parametrize("name", ["evil.html", "evil.svg", "evil.php", "evil.js", "evil.htm", "noext", ".hidden.webp", "evil.webp.html"])
def test_uploads_route_serves_only_allowed_media_types(planted, name):
    c, _, _ = planted
    assert c.get(f"/uploads/x/{name}").status_code == 404


def test_uploads_route_sends_a_fixed_type_and_locks_the_response_down(planted):
    c, url, root = planted
    r = c.get(url)
    assert r.status_code == 200
    assert r.headers["Content-Type"] == "image/webp"
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["Content-Security-Policy"] == "default-src 'none'; sandbox"
    assert r.headers["Content-Disposition"] == "inline"
    assert "immutable" in r.headers["Cache-Control"]
    assert Image.open(io.BytesIO(r.data)).format == "WEBP"


def test_content_type_follows_the_extension_table_not_a_guess(app, tmp_path):
    old = app.config["UPLOAD_DIR"]
    app.config["UPLOAD_DIR"] = str(tmp_path)
    try:
        (tmp_path / "v").mkdir()
        (tmp_path / "v" / "a.mp4").write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"0" * 20)
        (tmp_path / "v" / "a.webm").write_bytes(b"\x1a\x45\xdf\xa3" + b"0" * 20)
        c = app.test_client()
        assert c.get("/uploads/v/a.mp4").headers["Content-Type"].startswith("video/mp4")
        assert c.get("/uploads/v/a.webm").headers["Content-Type"].startswith("video/webm")
    finally:
        app.config["UPLOAD_DIR"] = old


@pytest.mark.parametrize("path", ["../config.py", "%2e%2e/%2e%2e/etc/passwd", "x/../../secret.webp", "..%2f..%2fapp.webp", "x/%00.webp"])
def test_uploads_route_still_blocks_traversal(planted, path):
    c, _, _ = planted
    assert c.get(f"/uploads/{path}").status_code in (400, 404)


def test_upload_folder_is_not_reachable_through_static(app):
    c = app.test_client()
    assert c.get("/static/../uploads/x.webp").status_code == 404
    assert not os.path.realpath(app.config["UPLOAD_DIR"]).startswith(os.path.realpath(app.static_folder))


def test_production_check_refuses_an_upload_folder_inside_the_code(app):
    from app.prodcheck import config_problems
    old = app.config["UPLOAD_DIR"]
    try:
        for bad in (os.path.join(app.static_folder, "uploads"), os.path.join(app.root_path, "templates", "u"), app.root_path):
            app.config["UPLOAD_DIR"] = bad
            fatal, _ = config_problems(app)
            assert any("UPLOAD_DIR is inside the application folder" in f for f in fatal), bad
        app.config["UPLOAD_DIR"] = "/var/data/uploads"
        fatal, _ = config_problems(app)
        assert not any("inside the application folder" in f for f in fatal)
    finally:
        app.config["UPLOAD_DIR"] = old


# ---------------------------------------------------------------- request size caps
def test_customer_requests_are_capped_but_admin_uploads_are_not(app, session, cust, catalog):
    old = app.config["CUSTOMER_MAX_CONTENT_LENGTH"]
    app.config["CUSTOMER_MAX_CONTENT_LENGTH"] = 200_000
    try:
        _, p = catalog
        big = io.BytesIO(b"\x00" * 400_000)
        r = cust.post(f"/product/{p.slug}/review", data={"csrf_token": token(cust, f"/product/{p.slug}"), "rating": "5",
                                                          "photos": (big, "a.png")}, content_type="multipart/form-data")
        assert r.status_code == 413
        assert "too big" in r.get_data(as_text=True)

        make_user(session, "admin")
        admin = app.test_client()
        sign_in(admin, "admin")
        r = post(admin, "/admin/categories/new", {"name": "Cap"}, files={"image": (io.BytesIO(b"\x00" * 400_000), "a.png")})
        assert r.status_code == 422      # the file is refused as an image, the request itself was not cut off
        assert session.scalar(select(Category).where(Category.name == "Cap")) is None
    finally:
        app.config["CUSTOMER_MAX_CONTENT_LENGTH"] = old


def test_a_review_with_three_normal_photos_is_still_accepted(app, session, cust, catalog):
    """The cap must leave room for MAX_PHOTOS images at the 5 MB limit."""
    assert app.config["CUSTOMER_MAX_CONTENT_LENGTH"] >= 3 * uploads.MAX_FILE_BYTES + 512 * 1024
    assert app.config["CUSTOMER_MAX_CONTENT_LENGTH"] < app.config["MAX_CONTENT_LENGTH"]
