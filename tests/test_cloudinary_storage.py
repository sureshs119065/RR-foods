import io

import pytest
from werkzeug.datastructures import FileStorage

from app import uploads
from tests.helpers import png_bytes


class FakeUploader:
    def __init__(self):
        self.uploaded, self.destroyed = [], []

    def upload(self, src, public_id, resource_type="image", **kw):
        data = src.read() if hasattr(src, "read") else src
        self.uploaded.append((public_id, resource_type, data))
        return {"secure_url": f"https://res.cloudinary.com/demo/{resource_type}/upload/v1/{public_id}.webp"}

    def destroy(self, public_id, resource_type="image", **kw):
        self.destroyed.append((public_id, resource_type))


@pytest.fixture()
def cloud(app, monkeypatch):
    fake = FakeUploader()
    monkeypatch.setenv("CLOUDINARY_URL", "cloudinary://k:s@demo")
    monkeypatch.setattr(uploads, "_uploader", lambda: fake)
    return fake


def test_images_go_to_cloudinary_not_disk(app, cloud):
    with app.app_context():
        fs = FileStorage(png_bytes(), filename="a.png")
        url, thumb = uploads.save_image(fs, "products")
    assert url.startswith("https://res.cloudinary.com/demo/image/upload/") and "/rrfoods/products/" in url
    assert thumb.endswith("_t.webp")
    assert [u[0].split("/")[1] for u in cloud.uploaded] == ["products", "products"]


def test_delete_removes_from_cloudinary(app, cloud):
    with app.app_context():
        _delete()
    assert cloud.destroyed == [("rrfoods/products/abc", "image"), ("rrfoods/reels/x", "video")]


def _delete():
    uploads.delete_files("https://res.cloudinary.com/demo/image/upload/v1/rrfoods/products/abc.webp",
                         "https://res.cloudinary.com/demo/video/upload/v7/rrfoods/reels/x.mp4", None, "/uploads/none.webp")


def test_copy_makes_an_independent_cloudinary_file(app, cloud):
    src = "https://res.cloudinary.com/demo/image/upload/v1/rrfoods/products/abc.webp"
    new = uploads.copy_file(src)
    assert new != src and new.startswith("https://res.cloudinary.com/") and "/rrfoods/products/" in new


def test_upload_failure_is_a_friendly_error(app, monkeypatch):
    monkeypatch.setenv("CLOUDINARY_URL", "cloudinary://k:s@demo")

    class Boom:
        def upload(self, *a, **k):
            raise RuntimeError("network down")

    monkeypatch.setattr(uploads, "_uploader", lambda: Boom())
    with app.app_context(), pytest.raises(uploads.UploadError):
        uploads.save_image(FileStorage(png_bytes(), filename="a.png"), "products")


def test_without_cloudinary_url_files_stay_on_disk(app, monkeypatch):
    monkeypatch.delenv("CLOUDINARY_URL", raising=False)
    with app.app_context():
        url, _ = uploads.save_image(FileStorage(png_bytes(), filename="a.png"), "products")
    assert url.startswith("/uploads/products/")


def test_csp_allows_cloudinary_video(app):
    r = app.test_client().get("/")
    assert "media-src 'self' https://res.cloudinary.com" in r.headers["Content-Security-Policy"]
