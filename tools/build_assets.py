"""Build the storefront's production assets (step 4.1).

    python tools/build_assets.py            # writes app/static/dist/ and manifest.json
    python tools/build_assets.py --check    # exit 1 if dist/ is missing or out of date

* `css/storefront.css`            -> dist/storefront.<hash>.css   (minified)
* the five storefront scripts     -> dist/storefront.<hash>.js    (one minified bundle, same order as before)
* every other css/js file         -> dist/<name>.<hash>.<ext>     (minified, so per-page scripts are hashed too)

The hash is the first 10 hex characters of the SHA-256 of the output, so a file's URL changes exactly when its content does and
can be cached for a year (`Cache-Control: public, max-age=31536000, immutable`, set in app/assets.py).
`manifest.json` maps the source path (or bundle name) to the built file. Without a manifest the app serves the unminified sources,
so development and tests need no build.

Pure Python (rcssmin, rjsmin): no Node needed on Render.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import sys
from pathlib import Path

import rcssmin
import rjsmin

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "app" / "static"
DIST = STATIC / "dist"

# Scripts loaded on every storefront page, in the order base.html always loaded them. Each is a self-contained IIFE
# (or a single listener), so joining them with ";\n" cannot make names collide.
STOREFRONT_JS = ["js/theme.js", "js/shop.js", "js/shell.js", "js/storefront-layout.js", "js/share.js"]
BUNDLE_NAME = "js/storefront.bundle.js"
NOT_HASHED = {"js/sw.js"}  # the service worker must keep a stable URL (/sw.js)


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:10]


def _write(stem: str, ext: str, data: bytes) -> str:
    name = f"{stem}.{_digest(data)}.{ext}"
    (DIST / name).write_bytes(data)
    return f"dist/{name}"


def build() -> dict[str, str]:
    if DIST.exists():
        shutil.rmtree(DIST)
    DIST.mkdir(parents=True)
    manifest: dict[str, str] = {}

    bundle = ";\n".join((STATIC / p).read_text(encoding="utf-8") for p in STOREFRONT_JS)
    manifest[BUNDLE_NAME] = _write("storefront", "js", rjsmin.jsmin(bundle).encode("utf-8"))

    for path in sorted(STATIC.glob("css/*.css")) + sorted(STATIC.glob("js/*.js")):
        rel = path.relative_to(STATIC).as_posix()
        if rel in NOT_HASHED:
            continue
        text = path.read_text(encoding="utf-8")
        minified = rcssmin.cssmin(text) if path.suffix == ".css" else rjsmin.jsmin(text)
        manifest[rel] = _write(path.stem, path.suffix[1:], minified.encode("utf-8"))

    (DIST / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def sizes(manifest: dict[str, str]) -> None:
    import gzip

    print(f"{'file':44} {'source':>9} {'minified':>9} {'gzip':>9}")
    for src, built in manifest.items():
        out = (STATIC / built).read_bytes()
        if src == BUNDLE_NAME:
            raw = sum((STATIC / p).stat().st_size for p in STOREFRONT_JS)
        else:
            raw = (STATIC / src).stat().st_size
        print(f"{built:44} {raw:9,} {len(out):9,} {len(gzip.compress(out, 9)):9,}")


def main(argv: list[str]) -> int:
    if "--check" in argv:
        current = json.loads((DIST / "manifest.json").read_text()) if (DIST / "manifest.json").is_file() else None
        if current is None:
            print("dist/manifest.json is missing: run python tools/build_assets.py")
            return 1
        before = {k: v for k, v in current.items()}
        fresh = build()
        if fresh != before:
            print("dist/ was out of date and has been rebuilt")
            return 1
        print("dist/ is up to date")
        return 0
    manifest = build()
    sizes(manifest)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
