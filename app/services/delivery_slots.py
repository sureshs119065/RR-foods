"""Zero-cost, database-backed delivery slot scheduling. All times are in SHOP_TIMEZONE."""
from copy import deepcopy
from datetime import date, time, timedelta

from sqlalchemy import func, select

from ..admin.helpers import shop_tz
from ..extensions import db
from ..models import Order, SiteSetting
from ..models.base import utcnow

SETTING_KEY = "delivery_slot_settings"
DEFAULTS = {"cutoff_time": "14:00", "max_orders_per_slot": 20, "blocked_dates": [], "days_ahead": 7}
SLOTS = ("Morning", "Evening")
CLOSED_STATUSES = ("cancelled", "rejected", "returned", "refunded")


def _clean(value):
    data = dict(DEFAULTS)
    if isinstance(value, dict):
        data.update(value)
    try:
        hh, mm = str(data["cutoff_time"]).split(":", 1)
        time(int(hh), int(mm))
        data["cutoff_time"] = f"{int(hh):02d}:{int(mm):02d}"
    except (TypeError, ValueError):
        data["cutoff_time"] = DEFAULTS["cutoff_time"]
    try:
        data["max_orders_per_slot"] = max(1, min(500, int(data["max_orders_per_slot"])))
    except (TypeError, ValueError):
        data["max_orders_per_slot"] = DEFAULTS["max_orders_per_slot"]
    try:
        data["days_ahead"] = max(1, min(60, int(data["days_ahead"])))
    except (TypeError, ValueError):
        data["days_ahead"] = DEFAULTS["days_ahead"]
    blocked = data.get("blocked_dates") if isinstance(data.get("blocked_dates"), list) else []
    data["blocked_dates"] = sorted({str(x) for x in blocked if _valid_date(str(x))})
    return data


def _valid_date(raw):
    try:
        date.fromisoformat(raw)
        return True
    except (TypeError, ValueError):
        return False


def get_settings():
    row = db.session.get(SiteSetting, SETTING_KEY)
    return _clean(row.value if row else None)


def _locked_settings_row():
    row = db.session.scalar(select(SiteSetting).where(SiteSetting.key == SETTING_KEY).with_for_update().execution_options(populate_existing=True))
    if row is None:
        row = SiteSetting(key=SETTING_KEY, value=deepcopy(DEFAULTS))
        db.session.add(row)
        db.session.flush()
        row = db.session.scalar(select(SiteSetting).where(SiteSetting.key == SETTING_KEY).with_for_update().execution_options(populate_existing=True))
    return row


def local_now():
    return utcnow().astimezone(shop_tz())


def earliest_date(settings=None, now=None):
    settings = settings or get_settings()
    now = now or local_now()
    cutoff = time.fromisoformat(settings["cutoff_time"])
    return now.date() + timedelta(days=1 if now.time().replace(tzinfo=None) < cutoff else 2)


def _count(day: date, slot: str) -> int:
    return int(db.session.scalar(select(func.count(Order.id)).where(
        Order.delivery_date == day, Order.delivery_slot == slot, Order.status.not_in(CLOSED_STATUSES)
    )) or 0)


def slots_for(day: date, settings=None):
    settings = settings or get_settings()
    if day.isoformat() in settings["blocked_dates"]:
        return []
    cap = settings["max_orders_per_slot"]
    return [slot for slot in SLOTS if _count(day, slot) < cap]


def available_dates(settings=None, now=None):
    settings = settings or get_settings()
    first = earliest_date(settings, now)
    last = (now or local_now()).date() + timedelta(days=settings["days_ahead"])
    out = []
    day = first
    while day <= last:
        slots = slots_for(day, settings)
        if slots:
            out.append({"value": day.isoformat(), "label": day.strftime("%a, %d %b %Y"), "slots": slots})
        day += timedelta(days=1)
    return out


def validate_and_lock(day_value: str | None, slot: str | None):
    """Lock the settings row to serialize capacity checks across checkout transactions."""
    row = _locked_settings_row()
    settings = _clean(row.value)
    try:
        day = date.fromisoformat((day_value or "").strip())
    except ValueError:
        raise ValueError("Choose a valid delivery date.")
    slot = (slot or "").strip().title()
    if slot not in SLOTS:
        raise ValueError("Choose Morning or Evening delivery.")
    now = local_now()
    if day < earliest_date(settings, now):
        raise ValueError(f"Choose a delivery date after the {settings['cutoff_time']} order cutoff.")
    if day > now.date() + timedelta(days=settings["days_ahead"]):
        raise ValueError("That delivery date is outside the booking window.")
    if day.isoformat() in settings["blocked_dates"]:
        raise ValueError("That date is unavailable. Choose another delivery date.")
    if _count(day, slot) >= settings["max_orders_per_slot"]:
        raise ValueError("That delivery slot is full. Choose another date or time.")
    return day, slot


def first_available():
    choices = available_dates()
    if not choices:
        return None, None
    return choices[0]["value"], choices[0]["slots"][0]
