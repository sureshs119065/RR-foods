"""Server-side log of requests that look like tampering (price edits, bad quantities, other people's orders).

Nothing here changes what a visitor sees: the request is refused or ignored the same way as before, and the person gets the same
plain message. The log line carries the time (from the log formatter), the signed-in user id, the client address and the page,
and NEVER the submitted values beyond a short, cleaned excerpt, so the log cannot be used to inject lines or store secrets.
"""
import re

from flask import current_app, g, request

# The browser must never be the source of any of these. A normal form from this site never contains them.
FORBIDDEN_FIELDS = frozenset({
    "price", "unit_price", "final_price", "mrp", "total", "subtotal", "grand_total", "amount", "discount", "discount_total",
    "discount_percent", "offer_percent", "offer", "delivery", "delivery_fee", "delivery_charge", "shipping", "tax", "tax_total",
    "line_total", "bundle_price", "status", "payment_status", "paid",
})
_CLEAN = re.compile(r"[^A-Za-z0-9 _.,:@/+-]")


def _clean(value, limit: int = 60) -> str:
    return _CLEAN.sub("?", str(value))[:limit]


def log_suspicious(kind: str, detail: str = "") -> None:
    user = g.get("user")
    current_app.logger.warning(
        "SUSPICIOUS %s user_id=%s role=%s ip=%s %s %s %s", kind, getattr(user, "id", None), getattr(user, "role", None),
        _clean(request.remote_addr or "-", 45), request.method, _clean(request.path, 120), _clean(detail, 120),
    )


def forbidden_fields_sent(form=None) -> list[str]:
    """Names of price-like fields found in the submitted form. They are logged and then ignored: no route reads them."""
    form = request.form if form is None else form
    return sorted({k.lower() for k in form.keys() if k.lower() in FORBIDDEN_FIELDS})


def note_tampered_fields(form=None) -> bool:
    found = forbidden_fields_sent(form)
    if found:
        log_suspicious("price_or_total_field_sent", "fields=" + ",".join(found))
    return bool(found)
