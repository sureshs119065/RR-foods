"""Courier tracking metadata validation and audited updates."""
from urllib.parse import urlsplit

from ..auth.service import audit
from ..models import Order


def update_tracking(order: Order, courier: str, tracking_id: str, tracking_url: str, actor):
    courier = " ".join((courier or "").split())[:120]
    tracking_id = " ".join((tracking_id or "").split())[:120]
    tracking_url = (tracking_url or "").strip()[:500]
    if tracking_url:
        parsed = urlsplit(tracking_url)
        try:
            parsed.port  # force validation of malformed ports
        except ValueError:
            raise ValueError("Enter a valid HTTPS tracking URL.")
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("Enter a valid HTTPS tracking URL.")
    if tracking_url and not tracking_id and not courier:
        raise ValueError("Enter a courier name or tracking ID when adding a tracking link.")
    before = {"courier_name": order.courier_name, "tracking_id": order.tracking_id, "tracking_url": order.tracking_url}
    after = {"courier_name": courier or None, "tracking_id": tracking_id or None, "tracking_url": tracking_url or None}
    order.courier_name = after["courier_name"]
    order.tracking_id = after["tracking_id"]
    order.tracking_url = after["tracking_url"]
    audit("order.tracking.update", entity_type="order", entity_id=order.id, actor_id=actor.id, before=before, after=after)
