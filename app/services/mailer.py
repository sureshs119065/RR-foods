"""Email outbox. Sending never happens inside a web request.

queue_email() writes a row (notifications.channel = 'email', sent_at empty). `flask send-emails` (run it every minute from cron) sends the
waiting rows and stamps sent_at only after the mail server accepted the message, so a failure is retried next time and nothing is lost.
"""
import smtplib
from email.message import EmailMessage

from flask import current_app
from sqlalchemy import select

from ..extensions import db
from ..models import Notification, User
from ..models.base import utcnow

EMAIL_KINDS = {"order_status", "return_status", "password_reset", "back_in_stock"}


def enabled() -> bool:
    return current_app.config.get("MAIL_MODE", "off") != "off"


def queue_email(user_id: int, kind: str, title: str, body: str | None, link: str | None = None) -> bool:
    """Queue one email for a user. Returns False when mail is off or the user has no address. The caller commits."""
    if not enabled():
        return False
    user = db.session.get(User, user_id)
    if user is None or not user.email or user.is_deleted or user.is_blocked:
        return False
    db.session.add(Notification(user_id=user_id, channel="email", kind=kind[:40], title=title[:150], body=(body or "")[:500] or None, link=link[:300] if link else None))
    return True


def _compose(user: User, n: Notification) -> EmailMessage:
    cfg = current_app.config
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = n.title, cfg["MAIL_FROM"], user.email
    lines = [f"Hello {user.name.split()[0] if user.name else 'there'},", "", n.body or "", ""]
    if n.link:
        lines += [f"{cfg['SITE_URL']}{n.link}", ""]
    lines += ["RR FOODS"]
    msg.set_content("\n".join(lines))
    return msg


def deliver_pending(limit: int = 100) -> tuple[int, int]:
    """Send waiting emails. Returns (sent, failed)."""
    mode = current_app.config.get("MAIL_MODE", "off")
    if mode == "off":
        return 0, 0
    rows = db.session.scalars(select(Notification).where(Notification.channel == "email", Notification.sent_at.is_(None))
                              .order_by(Notification.id).limit(limit).with_for_update(skip_locked=True)).all()
    sent = failed = 0
    server = None
    try:
        if mode == "smtp" and rows:
            cfg = current_app.config
            server = smtplib.SMTP(cfg["MAIL_SERVER"], cfg["MAIL_PORT"], timeout=20)
            if cfg["MAIL_USE_TLS"]:
                server.starttls()
            if cfg["MAIL_USERNAME"]:
                server.login(cfg["MAIL_USERNAME"], cfg["MAIL_PASSWORD"])
        for n in rows:
            user = db.session.get(User, n.user_id)
            try:
                if user is None or not user.email:
                    n.sent_at = utcnow()  # nobody to send to: stop retrying
                    continue
                msg = _compose(user, n)
                if mode == "smtp":
                    server.send_message(msg)
                else:
                    print(f"--- EMAIL to {user.email} ---\n{msg['Subject']}\n{msg.get_content()}")
                n.sent_at = utcnow()
                sent += 1
            except Exception as e:  # leave sent_at empty: tried again on the next run
                failed += 1
                current_app.logger.warning("email %s failed: %s", n.id, e)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        current_app.logger.error("email run failed: %s", e)
        failed += len(rows) - sent
    finally:
        if server is not None:
            try:
                server.quit()
            except Exception:
                pass
    return sent, failed
