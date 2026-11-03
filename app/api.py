from flask import Blueprint, jsonify

from .extensions import limiter
from .services.header_banners import CACHE_SECONDS, cached_payload

bp = Blueprint("api", __name__, url_prefix="/api")


@bp.get("/header-banners")
@limiter.limit("120 per minute")
def header_banners():
    """Live, in-schedule banners in display order. Cached for 60 seconds (or until the next schedule change)."""
    resp = jsonify(cached_payload())
    resp.headers["Cache-Control"] = f"public, max-age={CACHE_SECONDS}"
    return resp
