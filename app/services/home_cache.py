"""Per-worker cache for the storefront's shared fragments: category tiles, category counts and New Arrivals (Step 4.6).

What is cached is the *query result* (detached ORM objects with images, variants and category already loaded), never
rendered HTML. The product cards contain per-visitor parts (CSRF token, wishlist heart, return URL), so caching HTML would
hand one visitor's token and wishlist state to the next. Caching the data keeps every request rendering its own page.

Rules
  * Each entry lives HOME_CACHE_SECONDS (default 60) in this worker's memory. 0 turns the cache off (also the kill switch).
  * Any committed change to a product, product image, variant or category empties the cache of the worker that handled it,
    so an admin or owner edit shows up on the next home page load. Other workers catch up within the TTL. There is no shared
    store on purpose: a shared store would cost a round trip per request, which is what this cache exists to avoid.
  * The cached objects are shared between threads and must be treated as read-only; templates only read them.
  * A load that started before an edit is never stored (generation check), so a slow refill cannot resurrect old data.
"""
from __future__ import annotations

import threading
import time
from itertools import chain
from typing import Any, Callable

from flask import current_app
from sqlalchemy import event
from sqlalchemy.orm import Session

from ..extensions import db

DEFAULT_SECONDS = 60
_DIRTY = "home_cache_dirty"

_lock = threading.Lock()
_entries: dict[str, tuple[Any, float]] = {}  # key -> (value, monotonic expiry)
_generation = 0
_stats = {"hits": 0, "misses": 0, "busts": 0}


def ttl() -> int:
    try:
        return max(0, int(current_app.config.get("HOME_CACHE_SECONDS", DEFAULT_SECONDS)))
    except (TypeError, ValueError):
        return DEFAULT_SECONDS


def get(key: str, loader: Callable[[Session], Any]) -> Any:
    """Return the cached value for `key`, or run `loader(session)` and keep the result for the TTL.

    With the cache off the loader simply runs on the request's own session (exactly the pre-cache behaviour). With it on, the
    loader runs on a separate short-lived session and its objects are detached, so they never leak into, or depend on, a
    request's session."""
    seconds = ttl()
    if seconds <= 0:
        return loader(db.session)
    now = time.monotonic()
    with _lock:
        hit = _entries.get(key)
        if hit is not None and now < hit[1]:
            _stats["hits"] += 1
            return hit[0]
        started_at = _generation
        _stats["misses"] += 1
    with Session(db.engine, expire_on_commit=False, autoflush=False) as sess:
        value = loader(sess)
        sess.expunge_all()  # keep what was loaded, drop the session ties
    with _lock:
        if _generation == started_at:  # nothing was edited while we were loading
            _entries[key] = (value, time.monotonic() + seconds)
    return value


def bust() -> None:
    """Forget everything this worker has cached."""
    global _generation
    with _lock:
        _generation += 1
        _entries.clear()
        _stats["busts"] += 1


def mark_dirty(session: Session) -> None:
    """For writes that skip the ORM (Core `update(...)`): empty the cache when this session commits."""
    session.info[_DIRTY] = True


def stats() -> dict[str, int]:
    with _lock:
        return {**_stats, "entries": len(_entries)}


# ----------------------------------------------------------------- invalidation
def _watched() -> tuple[type, ...]:
    from ..models import Category, Product, ProductImage, ProductVariant
    return (Product, ProductImage, ProductVariant, Category)


def _after_flush(session: Session, _ctx) -> None:
    watched = _watched()
    if any(isinstance(obj, watched) for obj in chain(session.new, session.dirty, session.deleted)):
        session.info[_DIRTY] = True


def _after_commit(session: Session) -> None:
    if session.info.pop(_DIRTY, False):
        bust()


def _after_rollback(session: Session) -> None:
    session.info.pop(_DIRTY, None)


_registered = False


def init_app(app) -> None:
    """Listen for committed product/category changes (once per process; the listeners are on the Session class)."""
    global _registered
    if _registered:
        return
    event.listen(Session, "after_flush", _after_flush)
    event.listen(Session, "after_commit", _after_commit)
    event.listen(Session, "after_soft_rollback", lambda session, _prev: _after_rollback(session))
    _registered = True
