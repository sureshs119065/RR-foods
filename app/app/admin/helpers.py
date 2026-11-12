import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from flask import current_app, g, request
from sqlalchemy import select

from ..auth.service import audit
from ..extensions import db
from ..seed import slugify


def log(action: str, entity_type: str, entity_id=None, before=None, after=None) -> None:
    """Audit entry for an admin action. The caller commits."""
    audit(action, entity_type=entity_type, entity_id=entity_id, actor_id=g.user.id, before=before, after=after)


def unique_slug(model, base: str, exclude_id: int | None = None) -> str:
    base = slugify(base)[:150]
    slug, n = base, 2
    while True:
        q = select(model.id).where(model.slug == slug)
        if exclude_id:
            q = q.where(model.id != exclude_id)
        if not db.session.scalar(q):
            return slug
        slug, n = f"{base}-{n}", n + 1


def clean(value: str | None, limit: int | None = None) -> str:
    text = " ".join((value or "").split())
    return text[:limit] if limit else text


def clean_multiline(value: str | None, limit: int) -> str:
    return "\n".join(line.rstrip() for line in (value or "").replace("\r\n", "\n").split("\n")).strip()[:limit]


def to_decimal(value: str | None, field: str, errors: dict, *, min_=None, max_=None, required=True, default=None):
    raw = (value or "").strip().replace(",", "")
    if raw == "":
        if required:
            errors[field] = "This field is required."
            return None
        return default
    try:
        number = Decimal(raw)
    except InvalidOperation:
        errors[field] = "Enter a number."
        return None
    if not number.is_finite():
        errors[field] = "Enter a number."
        return None
    if min_ is not None and number < min_:
        errors[field] = f"Must be {min_} or more."
        return None
    if max_ is not None and number > max_:
        errors[field] = f"Must be {max_} or less."
        return None
    return number.quantize(Decimal("0.01"))


def to_int(value: str | None, field: str, errors: dict, *, min_=0, max_=1_000_000, required=True, default=0):
    raw = (value or "").strip()
    if raw == "":
        if required:
            errors[field] = "This field is required."
            return None
        return default
    if not re.fullmatch(r"-?\d+", raw):
        errors[field] = "Enter a whole number."
        return None
    number = int(raw)
    if number < min_ or number > max_:
        errors[field] = f"Enter a number from {min_} to {max_}."
        return None
    return number


def page_number() -> int:
    try:
        return max(1, int(request.args.get("page", "1")))
    except ValueError:
        return 1


def checked(name: str) -> bool:
    return request.form.get(name) in ("1", "on", "true", "yes")


# ---- dates: typed in shop time (default India), stored in UTC ----
def shop_tz() -> ZoneInfo:
    return ZoneInfo(current_app.config["SHOP_TIMEZONE"])


def parse_local_dt(raw: str | None, field: str, errors: dict) -> datetime | None:
    raw = (raw or "").strip()
    if not raw:
        return None
    for fmt in ("%Y-%m-%dT%H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(raw, fmt).replace(tzinfo=shop_tz()).astimezone(timezone.utc)
        except ValueError:
            continue
    errors[field] = "Enter a valid date and time."
    return None


def local_input(dt: datetime | None) -> str:
    """Value for <input type=datetime-local>."""
    return dt.astimezone(shop_tz()).strftime("%Y-%m-%dT%H:%M") if dt else ""


def local_display(dt: datetime | None) -> str:
    return dt.astimezone(shop_tz()).strftime("%d %b %Y, %I:%M %p") if dt else ""


def ago(dt: datetime | None) -> str:
    """'5 min', '3 h', '2 days': how long ago something happened."""
    if not dt:
        return ""
    seconds = max(0, int((datetime.now(timezone.utc) - dt).total_seconds()))
    if seconds < 3600:
        return f"{max(1, seconds // 60)} min"
    if seconds < 86400:
        return f"{seconds // 3600} h"
    days = seconds // 86400
    return f"{days} day{'s' if days != 1 else ''}"
