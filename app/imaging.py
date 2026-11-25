"""Image budget and responsive variants (step 4.3).

Every stored image `<stem>.webp` may have two siblings: `<stem>_t.webp` (longest side 400 px) and `<stem>_m.webp` (800 px).
Product pages and cards offer them in `srcset`, so a phone downloads the 400 px file and a laptop the 800 px one.
Anything that would be over 100 KB is re-encoded at a lower quality (then, if needed, a smaller size) until it fits.
"""
from __future__ import annotations

import io
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageOps

BUDGET_BYTES = 100 * 1024
THUMB_SIDE = 400
MEDIUM_SIDE = 800
WEBP_START_QUALITY = 85
WEBP_FLOOR_QUALITY = 60
MIN_SIDE = 600  # never shrink a main image below this just to meet the budget


def variant_name(stem: str, kind: str, suffix: str = ".webp") -> str:
    return f"{stem}_{kind}{suffix}"


def is_variant(path: Path) -> bool:
    return path.stem.endswith(("_t", "_m"))


def encode_within_budget(img: Image.Image, fmt: str = "WEBP", budget: int = BUDGET_BYTES,
                         quality: int = WEBP_START_QUALITY, floor: int = WEBP_FLOOR_QUALITY, min_side: int = MIN_SIDE) -> bytes:
    """Smallest-effort encode that fits `budget`: lower the quality first, then the size (never below `min_side`)."""
    work = img
    while True:
        q = quality
        while True:
            buf = io.BytesIO()
            kwargs = {"quality": q, "method": 4} if fmt == "WEBP" else {"quality": q, "optimize": True}
            work.save(buf, fmt, **kwargs)
            if buf.tell() <= budget or q <= floor:
                break
            q -= 5
        if buf.tell() <= budget or max(work.size) * 0.9 < min_side:
            return buf.getvalue()
        w, h = work.size
        work = work.resize((round(w * 0.9), round(h * 0.9)), Image.LANCZOS)


def _fit(img: Image.Image, side: int) -> Image.Image:
    out = img.copy()
    out.thumbnail((side, side), Image.LANCZOS)
    return out


def _write(path: Path, data: bytes) -> None:
    path.write_bytes(data)
    path.chmod(0o644)  # never executable


def write_variants(img: Image.Image, main_path: Path, *, thumb_path: Path | None = None, thumb_side: int = THUMB_SIDE,
                   overwrite: bool = True, want_thumb: bool = True) -> dict[str, Path]:
    """Write the 400 px (`_t`) and 800 px (`_m`) siblings of `main_path` from an already opened image.
    overwrite=False leaves files that already exist alone (used by `flask optimize-images`)."""
    written: dict[str, Path] = {}
    thumb = thumb_path or main_path.with_name(variant_name(main_path.stem, "t", main_path.suffix))
    medium = main_path.with_name(variant_name(main_path.stem, "m", main_path.suffix))
    if want_thumb and (overwrite or not thumb.exists()):
        _write(thumb, encode_within_budget(_fit(img, thumb_side), quality=80))
        written["t"] = thumb
    if max(img.size) > MEDIUM_SIDE and (overwrite or not medium.exists()):   # a smaller original needs no 800 px copy
        _write(medium, encode_within_budget(_fit(img, MEDIUM_SIDE), quality=82))
        written["m"] = medium
    return written


def optimize_file(path: Path, *, dry_run: bool = False) -> tuple[int, int]:
    """Re-encode one image in place if it is over the budget. Returns (bytes_before, bytes_after)."""
    before = path.stat().st_size
    if before <= BUDGET_BYTES or path.suffix.lower() not in {".webp", ".jpg", ".jpeg"}:
        return before, before
    with Image.open(path) as im:
        im.load()
        fmt = "WEBP" if path.suffix.lower() == ".webp" else "JPEG"
        img = ImageOps.exif_transpose(im)
        if fmt == "JPEG" and img.mode != "RGB":
            img = img.convert("RGB")
        data = encode_within_budget(img, fmt, quality=80 if fmt == "JPEG" else WEBP_START_QUALITY, floor=60)
    if len(data) >= before:                                # never make a file bigger
        return before, before
    if not dry_run:
        path.write_bytes(data)
        _width.cache_clear()
    return before, len(data)


@lru_cache(maxsize=4096)
def _width(path_str: str, mtime: float) -> int:
    try:
        with Image.open(path_str) as im:
            return im.size[0]
    except Exception:  # noqa: BLE001  unreadable file: leave it out of srcset
        return 0


def width_of(path: Path) -> int:
    try:
        return _width(str(path), path.stat().st_mtime)
    except OSError:
        return 0


# ---------------------------------------------------------------- template helpers
PRIORITY_IMAGES = 4  # the first product images on a page load eagerly with fetchpriority="high"; everything after is lazy


def init_images(app) -> None:
    from flask import request

    static_root = Path(app.static_folder).resolve()

    def fs_path(url: str | None) -> Path | None:
        """/uploads/... or /static/... -> file on disk (only inside those two folders), else None (remote URL, data: URI...)."""
        if not url:
            return None
        url = url.split("?", 1)[0]
        for prefix, root in (("/uploads/", Path(app.config["UPLOAD_DIR"]).resolve()), ("/static/", static_root)):
            if url.startswith(prefix):
                target = (root / url[len(prefix):]).resolve()
                return target if root in target.parents and target.is_file() else None
        return None

    def sibling(url: str, kind: str) -> str:
        base, dot, ext = url.partition("?")[0].rpartition(".")
        return f"{base}_{kind}.{ext}" if dot else url

    def img_srcset(main_url: str | None, thumb_url: str | None = None, full: bool = False) -> str:
        """`srcset` value for an image: the 400 px copy, the 800 px copy and (with full=True) the original, each with its real
        width. Only files that exist are listed; fewer than two candidates gives "" (the plain `src` is then the right answer)."""
        if not main_url:
            return ""
        found: dict[int, str] = {}
        candidates = [thumb_url or sibling(main_url, "t"), sibling(main_url, "m")] + ([main_url] if full else [])
        for url in candidates:
            path = fs_path(url)
            width = width_of(path) if path else 0
            if width and width not in found:
                found[width] = url
        if len(found) < 2:
            return ""
        return ", ".join(f"{u} {w}w" for w, u in sorted(found.items()))

    def img_priority() -> bool:
        """True for the first PRIORITY_IMAGES product images rendered in this request (per request, not per process)."""
        used = request.environ.get("rr.priority_images", 0)
        if used < PRIORITY_IMAGES:
            request.environ["rr.priority_images"] = used + 1
            return True
        return False

    def img_priority_spent() -> str:
        """Pages with their own hero image (the product gallery) call this so cards further down the page stay lazy."""
        request.environ["rr.priority_images"] = PRIORITY_IMAGES
        return ""

    def img_variant(url: str | None, kind: str = "t") -> str:
        """The 400 px (`t`) or 800 px (`m`) copy of an image when that file exists, else the image itself.
        Lets small spots (category chips, the hero photo) avoid downloading the full-size file; older uploads without copies still work."""
        if not url:
            return ""
        alt = sibling(url, kind)
        return alt if fs_path(alt) else url

    app.jinja_env.globals["img_variant"] = img_variant
    app.jinja_env.globals["img_priority_spent"] = img_priority_spent
    app.jinja_env.globals["img_srcset"] = img_srcset
    app.jinja_env.globals["img_priority"] = img_priority
