"""Safe image uploads.

Every file is opened and re-encoded with Pillow, so a renamed script or a disguised file cannot get through.
Names are random, never taken from the visitor. Metadata (EXIF, GPS) is dropped. Output is WebP.
"""
import io
import shutil
import uuid
from pathlib import Path

from flask import current_app
from PIL import Image, ImageOps, UnidentifiedImageError

Image.MAX_IMAGE_PIXELS = 40_000_000  # refuse "decompression bomb" images
ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP"}
MAX_FILE_BYTES = 5 * 1024 * 1024


class UploadError(ValueError):
    """Message is safe to show to the admin."""


def upload_root() -> Path:
    root = Path(current_app.config["UPLOAD_DIR"])
    root.mkdir(parents=True, exist_ok=True)
    return root


def _read(file_storage) -> bytes:
    data = file_storage.read(MAX_FILE_BYTES + 1)
    if not data:
        raise UploadError("The file is empty.")
    if len(data) > MAX_FILE_BYTES:
        raise UploadError("Each image must be 5 MB or smaller.")
    return data


def save_image(file_storage, subdir: str, max_side: int = 1600, thumb_side: int | None = 400) -> tuple[str, str | None]:
    """Validates, resizes and stores one image. Returns (url, thumb_url). Raises UploadError with a friendly message."""
    name = getattr(file_storage, "filename", "") or "image"
    data = _read(file_storage)
    try:
        probe = Image.open(io.BytesIO(data))
        probe.verify()  # structure check
        img = Image.open(io.BytesIO(data))  # verify() leaves the object unusable, so reopen
        fmt = img.format
        if fmt not in ALLOWED_FORMATS:
            raise UploadError(f"{name}: use a JPG, PNG or WebP image.")
        img = ImageOps.exif_transpose(img)
        img.load()
    except UploadError:
        raise
    except (UnidentifiedImageError, OSError, SyntaxError, Image.DecompressionBombError, ValueError):
        raise UploadError(f"{name}: this is not a valid image (or it is too large).")

    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGBA" if "A" in img.getbands() or img.mode == "P" and "transparency" in img.info else "RGB")

    stem = uuid.uuid4().hex
    folder = upload_root() / subdir
    folder.mkdir(parents=True, exist_ok=True)

    main = img.copy()
    main.thumbnail((max_side, max_side), Image.LANCZOS)
    main.save(folder / f"{stem}.webp", "WEBP", quality=85, method=4)
    url = f"/uploads/{subdir}/{stem}.webp"

    thumb_url = None
    if thumb_side:
        t = img.copy()
        t.thumbnail((thumb_side, thumb_side), Image.LANCZOS)
        t.save(folder / f"{stem}_t.webp", "WEBP", quality=80, method=4)
        thumb_url = f"/uploads/{subdir}/{stem}_t.webp"
    return url, thumb_url


def _path_for(url: str | None) -> Path | None:
    """Maps /uploads/... back to a file, only if it really is inside the upload folder."""
    if not url or not url.startswith("/uploads/"):
        return None
    root = upload_root().resolve()
    target = (root / url[len("/uploads/"):]).resolve()
    return target if root in target.parents else None


def delete_files(*urls: str | None) -> None:
    for url in urls:
        p = _path_for(url)
        if p and p.is_file():
            p.unlink(missing_ok=True)


def copy_file(url: str | None) -> str | None:
    """Physical copy, so deleting the duplicate product's image never breaks the original."""
    src = _path_for(url)
    if not src or not src.is_file():
        return url  # external link or missing file: keep the reference as it is
    new = src.with_name(f"{uuid.uuid4().hex}{'_t' if src.stem.endswith('_t') else ''}{src.suffix}")
    shutil.copyfile(src, new)
    return f"/uploads/{new.relative_to(upload_root().resolve()).as_posix()}"


VIDEO_MAX_BYTES = 50 * 1024 * 1024
VIDEO_EXTENSIONS = {".mp4", ".webm", ".mov"}

def save_video(file_storage, subdir: str) -> str | None:
    """Store a bounded video upload; extension and MIME are checked before saving."""
    if not file_storage or not getattr(file_storage, "filename", ""):
        return None
    from werkzeug.utils import secure_filename
    name = secure_filename(file_storage.filename)
    ext = Path(name).suffix.lower()
    mime = (getattr(file_storage, "mimetype", "") or "").lower()
    allowed_mimes = {"video/mp4", "video/webm", "video/quicktime"}
    if ext not in VIDEO_EXTENSIONS or mime not in allowed_mimes:
        raise UploadError("Use an MP4, WebM or MOV video.")
    data = file_storage.read(VIDEO_MAX_BYTES + 1)
    if not data:
        raise UploadError("The video file is empty.")
    if len(data) > VIDEO_MAX_BYTES:
        raise UploadError("Videos must be 50 MB or smaller.")
    folder = upload_root() / subdir
    folder.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid.uuid4().hex}{ext}"
    (folder / filename).write_bytes(data)
    return f"/uploads/{subdir}/{filename}"
