"""Hashed, minified static assets, long-lived caching and response compression (step 4.1).

`tools/build_assets.py` writes app/static/dist/ with a manifest. Templates call `asset_url("css/storefront.css")` (one file) or
`asset_urls("js/storefront.bundle.js")` (the list of scripts to load). With a manifest they get the hashed, minified build; without
one (development, tests) they get the source files with an mtime `?v=` so nothing has to be built to work on the site.
"""
from __future__ import annotations

import json
from pathlib import Path

from flask import Flask, request, url_for
from flask_compress import Compress

IMMUTABLE = "public, max-age=31536000, immutable"
MEDIA_CACHE = "public, max-age=604800"  # images and fonts keep their names, so a week rather than a year
# What the bundle is made of when no manifest exists. Keep in step with STOREFRONT_JS in tools/build_assets.py.
BUNDLE_SOURCES = {
    "js/storefront.bundle.js": ["js/theme.js", "js/shop.js", "js/shell.js", "js/storefront-layout.js", "js/share.js"],
}

compress = Compress()


def init_assets(app: Flask) -> None:
    app.config.setdefault("COMPRESS_ALGORITHM", ["br", "gzip"])
    app.config.setdefault("COMPRESS_MIMETYPES", [
        "text/html", "text/css", "text/plain", "text/xml", "text/javascript", "application/javascript",
        "application/json", "application/manifest+json", "image/svg+xml",
    ])
    app.config.setdefault("COMPRESS_ALGORITHM_STREAMING", ["br", "gzip"])  # static files are streamed responses
    app.config.setdefault("COMPRESS_MIN_SIZE", 500)
    app.config.setdefault("COMPRESS_REGISTER", True)
    compress.init_app(app)

    static = Path(app.static_folder)
    manifest_path = static / "dist" / "manifest.json"
    manifest: dict[str, str] = {}
    if manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            app.logger.warning("static/dist/manifest.json is unreadable; serving unminified assets")
    app.extensions["asset_manifest"] = manifest

    def _source_url(rel: str) -> str:
        try:
            version = int((static / rel).stat().st_mtime)
        except OSError:
            version = 0
        return url_for("static", filename=rel, v=version)

    def asset_url(rel: str) -> str:
        built = manifest.get(rel)
        return url_for("static", filename=built) if built else _source_url(rel)

    def asset_urls(name: str) -> list[str]:
        built = manifest.get(name)
        if built:
            return [url_for("static", filename=built)]
        return [_source_url(rel) for rel in BUNDLE_SOURCES.get(name, [name])]

    from .imaging import init_images
    init_images(app)

    app.jinja_env.globals["asset_url"] = asset_url
    app.jinja_env.globals["asset_urls"] = asset_urls

    @app.after_request
    def _static_cache_headers(resp):
        path = request.path
        if not path.startswith("/static/") or resp.status_code not in (200, 304):
            return resp
        # Runs after (and so overrides) the "signed-in pages are never cached" rule: assets hold no personal data.
        if path.startswith("/static/dist/"):
            resp.headers["Cache-Control"] = IMMUTABLE
        elif path.startswith(("/static/img/", "/static/fonts/")):
            resp.headers["Cache-Control"] = MEDIA_CACHE
        return resp
