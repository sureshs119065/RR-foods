"""Courier tracking metadata validation and audited updates."""
from datetime import date
from urllib.parse import urlsplit

from ..auth.service import audit
from ..models import Order


# A cancelled or rejected order is never shipped: it has no courier, tracking number or delivery date.
NO_SHIPMENT = ("pending_whatsapp", "cancelled", "rejected")


def clear_shipment(order: Order) -> None:
    """Remove every shipping and delivery detail from an order that will not be shipped."""
    order.courier_name = order.tracking_id = order.tracking_url = None
    order.delivery_date = order.delivery_slot = None


def update_tracking(order: Order, courier: str, tracking_id: str, tracking_url: str, actor, expected_delivery: str | None = None):
    if getattr(order, "status", None) in NO_SHIPMENT:
        raise ValueError("This order was not confirmed or was cancelled, so it has no shipment details.")
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
    raw_date = (expected_delivery or "").strip()
    if raw_date:
        try:
            order.delivery_date = date.fromisoformat(raw_date)
        except ValueError:
            raise ValueError("Enter a valid expected delivery date.")
    else:
        order.delivery_date = None
    order.delivery_slot = None
    audit("order.tracking.update", entity_type="order", entity_id=order.id, actor_id=actor.id, before=before, after=after)
