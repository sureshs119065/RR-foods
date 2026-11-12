r"""Move images/videos already stored by the app (/uploads/...) to Cloudinary and update the database.

What it does: for every address in the database that starts with /uploads/, it finds the file, uploads it to
Cloudinary, and replaces the address with the https://res.cloudinary.com/... one. Nothing is deleted from the old
place. Run it first WITHOUT --apply to see what would happen (a dry run changes nothing).

Where it looks for each file:
  1. the local UPLOAD_DIR folder (use this if you downloaded your uploads or run it on the server), then
  2. your live website, if you pass --site https://your-app.onrender.com (the site serves /uploads/... publicly).

Usage (PowerShell, inside the project folder):
  $env:DATABASE_URL   = "<External Database URL from Render>"
  $env:CLOUDINARY_URL = "cloudinary://<api_key>:<api_secret>@<cloud_name>"
  .\.venv\Scripts\python.exe migrate_to_cloudinary.py --site https://your-app.onrender.com            (dry run)
  .\.venv\Scripts\python.exe migrate_to_cloudinary.py --site https://your-app.onrender.com --apply    (do it)

Safe to run again: addresses that are already on Cloudinary are skipped.
"""
import argparse
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

ap = argparse.ArgumentParser()
ap.add_argument("--apply", action="store_true", help="really upload and update the database (default is a dry run)")
ap.add_argument("--site", default=os.environ.get("SITE_URL", ""), help="live site address to download missing files from")
ap.add_argument("--upload-dir", default=None, help="folder that holds the old uploads (default: UPLOAD_DIR setting)")
args = ap.parse_args()

if args.apply and not os.environ.get("CLOUDINARY_URL"):
    sys.exit("Set CLOUDINARY_URL first (Cloudinary dashboard > API Keys).")

from sqlalchemy import select  # noqa: E402

from app import create_app  # noqa: E402
from app.extensions import db  # noqa: E402
from app.models import Bundle, Category, Banner, Combo, HeaderBanner, ProductImage, RecipeVideo, Reel, Review  # noqa: E402
from app.uploads import cloudinary_upload, is_cloudinary_url  # noqa: E402

VIDEO_EXT = {".mp4", ".webm", ".mov"}
# (model, [text columns that may hold an /uploads/ address])
TARGETS = [
    (ProductImage, ["url", "thumb_url"]),
    (Category, ["image"]),
    (Banner, ["image"]),
    (HeaderBanner, ["desktop_image", "mobile_image"]),
    (Bundle, ["image_url"]),
    (Combo, ["image"]),
    (Reel, ["video_url", "thumbnail_url"]),
    (RecipeVideo, ["video_url", "thumbnail_url"]),
]

app = create_app()
done: dict[str, str] = {}      # old address -> new address (so a file used twice is uploaded once)
missing: list[str] = []
counts = {"uploaded": 0, "rows": 0, "already": 0}


def fetch(old: str) -> bytes | None:
    rel = old[len("/uploads/"):]
    root = Path(args.upload_dir or app.config["UPLOAD_DIR"])
    local = root / rel
    if local.is_file():
        return local.read_bytes()
    if args.site:
        try:
            req = urllib.request.Request(args.site.rstrip("/") + old, headers={"User-Agent": "rrfoods-migrate"})
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read()
        except (urllib.error.URLError, TimeoutError):
            return None
    return None


def move(old):
    """Returns the new address, or the old one unchanged when it cannot be moved."""
    if not old or not old.startswith("/uploads/"):
        if is_cloudinary_url(old):
            counts["already"] += 1
        return old
    if old in done:
        return done[old]
    data = fetch(old)
    if data is None:
        missing.append(old)
        return old
    sub, _, name = old[len("/uploads/"):].rpartition("/")
    stem, dot, ext = name.rpartition(".")
    kind = "video" if ("." + ext.lower()) in VIDEO_EXT else "image"
    if args.apply:
        new = cloudinary_upload(data, sub or "misc", stem, kind)
        counts["uploaded"] += 1
    else:
        new = f"(dry run) https://res.cloudinary.com/.../{sub}/{stem}"
        counts["uploaded"] += 1
    done[old] = new
    return new


with app.app_context():
    for model, cols in TARGETS:
        changed = 0
        for row in db.session.scalars(select(model)).all():
            for col in cols:
                old = getattr(row, col)
                new = move(old)
                if new != old:
                    if args.apply:
                        setattr(row, col, new)
                    changed += 1
        counts["rows"] += changed
        print(f"{model.__tablename__:16} {changed} address(es) {'updated' if args.apply else 'to update'}")
    # review photos are a list of addresses
    changed = 0
    for rv in db.session.scalars(select(Review)).all():
        photos = list(rv.photos or [])
        new_photos = [move(u) for u in photos]
        if new_photos != photos:
            if args.apply:
                rv.photos = new_photos
            changed += 1
    counts["rows"] += changed
    print(f"{'reviews':16} {changed} review(s) {'updated' if args.apply else 'to update'}")
    if args.apply:
        db.session.commit()

print()
print(f"{counts['uploaded']} file(s) {'uploaded' if args.apply else 'would be uploaded'}, {counts['rows']} database row(s) {'changed' if args.apply else 'would change'}, {counts['already']} already on Cloudinary.")
if missing:
    uniq = sorted(set(missing))
    print(f"\n{len(uniq)} file(s) could NOT be found (left as they are). On Render without a Disk these were lost on a restart.")
    print("Upload them again in Admin after switching to Cloudinary:")
    for m in uniq[:50]:
        print("  ", m)
if not args.apply:
    print("\nThis was a dry run. Add --apply to do it.")
