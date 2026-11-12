"""Best-effort Web Push delivery. No paid service; pywebpush uses browser Push API/VAPID."""
import json
from flask import current_app
from sqlalchemy import select
from ..extensions import db
from ..models import PushSubscription


def send_user_push(user_id: int, title: str, body: str = "", link: str = "/account") -> int:
    public = current_app.config.get("VAPID_PUBLIC_KEY")
    private = current_app.config.get("VAPID_PRIVATE_KEY")
    if not public or not private:
        return 0
    safe_link = link if isinstance(link, str) and link.startswith("/") and not link.startswith("//") else "/account"
    try:
        from pywebpush import webpush, WebPushException
    except ImportError:
        current_app.logger.warning("Push configured but pywebpush is not installed")
        return 0
    rows = db.session.scalars(select(PushSubscription).where(
        PushSubscription.user_id == user_id, PushSubscription.is_enabled.is_(True)
    )).all()
    sent = 0
    for row in rows:
        try:
            webpush(
                subscription_info={"endpoint": row.endpoint,
                    "keys": {"p256dh": row.p256dh, "auth": row.auth}},
                data=json.dumps({"title": title[:100], "body": body[:180], "url": safe_link}),
                vapid_private_key=private,
                vapid_claims={"sub": current_app.config.get("VAPID_CLAIMS_EMAIL", "mailto:admin@example.com")},
                ttl=3600,
            )
            sent += 1
        except Exception as exc:  # push delivery must never break checkout/order state changes
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if status in (404, 410):
                row.is_enabled = False
            current_app.logger.warning("Web Push delivery failed for subscription %s: %s", row.id, type(exc).__name__)
    return sent
