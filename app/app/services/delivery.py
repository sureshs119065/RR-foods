"""Delivery area rules.

Every pincode in Tamil Nadu is deliverable by default (Indian Post uses 600001-643999 for the Tamil Nadu circle).
A row in the delivery_zones table is an optional override for one pincode: use it to change the fee or delivery
days, or to stop delivering there (is_serviceable = false). See add_pincodes.py.

Note: Puducherry and Karaikal share the Tamil Nadu postal circle, so their pincodes fall in this range too.
Switch any of them off with:  python add_pincodes.py 605001 --disable
"""
from __future__ import annotations

import os
import re

from ..extensions import db
from ..models import DeliveryZone

TN_PIN_FIRST = int(os.environ.get("TN_PIN_FIRST", "600001"))
TN_PIN_LAST = int(os.environ.get("TN_PIN_LAST", "643999"))
DEFAULT_ETA_DAYS = int(os.environ.get("DEFAULT_DELIVERY_DAYS", "3"))
DEFAULT_FEE = float(os.environ.get("DEFAULT_DELIVERY_FEE", "0"))


def is_tamil_nadu_pincode(pincode: str | None) -> bool:
    pin = (pincode or "").strip()
    return bool(re.fullmatch(r"[1-9][0-9]{5}", pin)) and TN_PIN_FIRST <= int(pin) <= TN_PIN_LAST


def zone_for(pincode: str | None) -> DeliveryZone | None:
    """The delivery zone for a pincode, or None when we do not deliver there.

    A saved row wins (custom fee/days, or switched off). Otherwise any Tamil Nadu pincode gets the default zone.
    The default zone is never added to the session, so nothing is written to the database.
    """
    pin = (pincode or "").strip()
    if not re.fullmatch(r"[0-9]{6}", pin):
        return None
    row = db.session.get(DeliveryZone, pin)
    if row is not None:
        return row if row.is_serviceable else None
    if is_tamil_nadu_pincode(pin):
        return DeliveryZone(pincode=pin, is_serviceable=True, eta_days=DEFAULT_ETA_DAYS, delivery_fee=DEFAULT_FEE)
    return None
