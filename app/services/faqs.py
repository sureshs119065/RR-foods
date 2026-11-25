"""Customer FAQs: the list shown on the home page and /faq, the home-page settings, and the FAQPage structured data.

The active list is cached per worker with the other home-page fragments (services/home_cache.py). Any committed change to a
Faq row empties that cache, and saving the home-page settings does too, so an admin edit shows on the next page load.
"""
from __future__ import annotations

from flask import request
from sqlalchemy import select

from ..extensions import db
from ..models import Faq, SiteSetting
from . import home_cache

SETTING_KEY = "home_faq"
MIN_COUNT, MAX_COUNT, DEFAULT_COUNT = 3, 10, 5


def get_settings() -> dict:
    row = db.session.get(SiteSetting, SETTING_KEY)
    cfg = row.value if row and isinstance(row.value, dict) else {}
    try:
        count = int(cfg.get("max_count", DEFAULT_COUNT))
    except (TypeError, ValueError):
        count = DEFAULT_COUNT
    return {"enabled": bool(cfg.get("enabled", True)), "max_count": max(MIN_COUNT, min(MAX_COUNT, count))}


def save_settings(enabled: bool, max_count: int) -> None:
    """Caller commits. Marks the session so the home cache is emptied on commit."""
    row = db.session.get(SiteSetting, SETTING_KEY) or SiteSetting(key=SETTING_KEY, value={})
    row.value = {"enabled": bool(enabled), "max_count": int(max_count)}
    db.session.add(row)
    home_cache.mark_dirty(db.session)


def _load_active(session) -> list[Faq]:
    return list(session.scalars(select(Faq).where(Faq.is_active.is_(True)).order_by(Faq.sort_order, Faq.id)))


def active_faqs() -> list[Faq]:
    """All visible questions in display order (cached; treat the objects as read-only)."""
    return home_cache.get("faqs_active", _load_active)


def home_section() -> dict:
    """What the home page needs: {"show": bool, "items": [...], "total": int}. Computed once per request (the template asks twice:
    once for the <head> markup, once for the section). Kept on the request object, which is new for every request."""
    cached = getattr(request, "_home_faq", None)
    if cached is not None:
        return cached
    cfg = get_settings()
    items = active_faqs() if cfg["enabled"] else []
    out = {"show": bool(items), "items": items[:cfg["max_count"]], "total": len(items)}
    request._home_faq = out
    return out


def jsonld(items) -> dict | None:
    """schema.org FAQPage for exactly the questions shown on the page. Rendered with |tojson (which escapes < > & so the
    value cannot close the script tag) inside <script type="application/ld+json">: a data block, so script-src 'self' allows it."""
    if not items:
        return None
    return {"@context": "https://schema.org", "@type": "FAQPage",
            "mainEntity": [{"@type": "Question", "name": f.question,
                            "acceptedAnswer": {"@type": "Answer", "text": f.answer}} for f in items]}
