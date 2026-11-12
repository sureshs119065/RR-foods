"""Header offer carousel: which banners are live right now, and the cached JSON the home page reads."""
import threading
from datetime import datetime, timedelta

from sqlalchemy import select

from ..extensions import db
from ..models import HeaderBanner, SiteSetting
from ..models import base as _base

CACHE_SECONDS = 60
DEFAULTS = {
    "header_carousel_interval_ms": 5000,
    "header_carousel_autoplay": True,
    "header_carousel_transition": "slide",
    "header_carousel_max_banners": 5,
}

_lock = threading.Lock()
_cache: dict = {"payload": None, "valid_until": None}


def get_settings() -> dict:
    out = dict(DEFAULTS)
    for row in db.session.scalars(select(SiteSetting).where(SiteSetting.key.in_(DEFAULTS))):
        out[row.key] = row.value
    return out


def status_of(b: HeaderBanner, now: datetime) -> str:
    if not b.is_active:
        return "off"
    if b.start_at and b.start_at > now:
        return "scheduled"
    if b.end_at and b.end_at <= now:
        return "expired"
    return "live"


def live_banners(now: datetime, limit: int | None = None) -> list[HeaderBanner]:
    q = select(HeaderBanner).where(HeaderBanner.is_active.is_(True)).order_by(HeaderBanner.sort_order, HeaderBanner.id)
    rows = [b for b in db.session.scalars(q) if status_of(b, now) == "live"]
    return rows[:limit] if limit else rows


def resolve_href(b: HeaderBanner) -> str:
    target = b.link_target or ""
    if b.link_type == "category":
        return f"/shop?category={target}"
    if b.link_type == "product":
        return f"/product/{target}"
    if b.link_type == "coupon":
        return f"/offers?coupon={target}"
    return target or "/shop"


def _payload(now: datetime) -> tuple[dict, datetime]:
    settings = get_settings()
    banners = live_banners(now, settings["header_carousel_max_banners"])
    # Cache only until something is due to start or expire, so schedules switch on time
    boundaries = [b.end_at for b in banners if b.end_at]
    boundaries += [b.start_at for b in db.session.scalars(select(HeaderBanner).where(HeaderBanner.is_active.is_(True))) if b.start_at and b.start_at > now]
    valid_until = min([now + timedelta(seconds=CACHE_SECONDS)] + boundaries)
    one = len(banners) <= 1
    payload = {
        "settings": {
            "interval_ms": settings["header_carousel_interval_ms"],
            "autoplay": bool(settings["header_carousel_autoplay"]) and not one,  # a single banner never auto-rotates
            "transition": settings["header_carousel_transition"],
            "arrows": not one,
        },
        "banners": [{
            "id": b.id, "title": b.title, "subtitle": b.subtitle, "badge": b.badge_text,
            "desktop_image": b.desktop_image, "mobile_image": b.mobile_image or b.desktop_image,
            "bg_color": b.bg_color, "text_color": b.text_color, "button_text": b.button_text, "href": resolve_href(b),
            "ends_at": b.end_at.isoformat() if (b.countdown_enabled and b.end_at) else None,
        } for b in banners],
    }
    return payload, valid_until


def cached_payload() -> dict:
    now = _base.utcnow()
    with _lock:
        if _cache["payload"] is not None and _cache["valid_until"] and now < _cache["valid_until"]:
            return _cache["payload"]
    payload, valid_until = _payload(now)
    with _lock:
        _cache["payload"], _cache["valid_until"] = payload, valid_until
    return payload


def bust_cache() -> None:
    with _lock:
        _cache["payload"] = _cache["valid_until"] = None
