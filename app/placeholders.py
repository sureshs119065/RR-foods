"""Step 2.4: product image fallback and the "does this product have a real photo?" check.

Rule (replaces the old keyword guessing): a product gets a bundled photo only when a file named after its own slug exists in
static/img/products/ (`<slug>.webp|.png|.jpg`). Anything else gets one neutral placeholder drawing, never a photo of a
different product. `flask check-images` lists the products that end up on the placeholder.
"""
import re
from pathlib import Path

PLACEHOLDER = "img/placeholder-product.svg"   # relative to the static folder
BUNDLED_EXTS = (".webp", ".png", ".jpg")
_SLUG_CLEAN = re.compile(r"[^a-z0-9-]+")


def clean_slug(slug) -> str:
    return _SLUG_CLEAN.sub("-", (slug or "").lower()).strip("-")


def bundled_photo(static_folder, slug) -> str | None:
    """File name (not path) of the bundled photo whose name is exactly the product slug, else None."""
    slug = clean_slug(slug)
    if not slug:
        return None
    root = Path(static_folder) / "img" / "products"
    for ext in BUNDLED_EXTS:
        if (root / f"{slug}{ext}").is_file():
            return f"{slug}{ext}"
    return None


def image_row_is_real(app, image) -> bool:
    """True when a ProductImage row points at something a browser can actually show (remote URL, or a file that exists)."""
    static_root = Path(app.static_folder).resolve()
    upload_root = Path(app.config["UPLOAD_DIR"]).resolve()
    for raw in (getattr(image, "url", None), getattr(image, "thumb_url", None)):
        raw = (raw or "").strip()
        if not raw:
            continue
        if raw.startswith(("https://", "http://", "//")):
            return True
        norm = raw if raw.startswith("/") else "/" + raw.lstrip("/")
        if norm.startswith("/uploads/"):
            root, rel = upload_root, norm[len("/uploads/"):]
        elif norm.startswith("/static/"):
            root, rel = static_root, norm[len("/static/"):]
        else:
            root, rel = static_root, norm.lstrip("/")
        target = (root / rel.split("?", 1)[0]).resolve()
        if root in target.parents and target.is_file():
            return True
    return False


def product_has_real_photo(app, product) -> bool:
    return any(image_row_is_real(app, im) for im in product.images) or bool(bundled_photo(app.static_folder, product.slug))
