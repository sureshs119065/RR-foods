from flask import abort, flash, g, jsonify, redirect, render_template, request, url_for
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from ..auth.decorators import roles_required
from ..extensions import db, limiter
from ..models import CustomerMessage, CustomerMessageThread
from ..services.customer_inbox import add_reply, create_thread
from . import bp

customer_only = roles_required("user")


@bp.get("/account/messages")
@customer_only
def messages():
    threads = db.session.scalars(select(CustomerMessageThread).where(CustomerMessageThread.user_id == g.user.id).order_by(CustomerMessageThread.last_message_at.desc())).all()
    return render_template("shop/messages.html", threads=threads, thread=None)


@bp.route("/account/messages/new", methods=["GET", "POST"])
@customer_only
@limiter.limit("10 per hour", methods=["POST"])
def message_new():
    if request.method == "POST":
        from .. import validation as v
        subject = v.one_line(request.form.get("subject"))[:160]
        body = v.one_line(request.form.get("body"))
        if len(subject) < 3 or not 5 <= len(body) <= 4000:
            flash("Add a subject and a message between 5 and 4,000 characters.", "error")
        else:
            thread = create_thread(g.user, subject, body)
            db.session.commit()
            flash("Your message was sent to the RR FOODS Admin and Shop Owner inboxes.", "success")
            return redirect(url_for("shop.message_thread", thread_id=thread.id))
    return render_template("shop/message_new.html")


@bp.route("/account/messages/<int:thread_id>", methods=["GET", "POST"])
@customer_only
def message_thread(thread_id):
    thread = db.session.scalar(select(CustomerMessageThread).where(CustomerMessageThread.id == thread_id, CustomerMessageThread.user_id == g.user.id).options(selectinload(CustomerMessageThread.messages).joinedload(CustomerMessage.sender)))
    if thread is None:
        abort(404)
    if request.method == "POST":
        from .. import validation as v
        body = v.one_line(request.form.get("body"))
        if not 1 <= len(body) <= 4000:
            flash("Write a message (up to 4,000 characters).", "error")
        else:
            add_reply(thread, g.user, body)
            db.session.commit()
            flash("Your reply was sent to the RR FOODS team.", "success")
            return redirect(url_for("shop.message_thread", thread_id=thread.id))
    return render_template("shop/messages.html", threads=None, thread=thread)


SUBJECT_MAX, BODY_MAX = 150, 2000


def _wants_json() -> bool:
    return request.is_json or request.accept_mimetypes.best == "application/json" or request.headers.get("X-Requested-With") == "XMLHttpRequest"


def _reply(ok: bool, message: str, status: int = 200, **extra):
    """JSON for the fetch() form; flash + redirect back to the Contact page for a browser without JavaScript."""
    if _wants_json():
        return jsonify(ok=ok, message=message, **extra), status
    flash(message, "success" if ok else "error")
    return redirect(url_for("shop.help_page") + "#contact-form")


def send_support_message():
    """The ONE backend for the contact/support form (home page and Contact page share it).

    Signed-in customer: saved to the shared Admin + Shop Owner inbox using their account name and email.
    Visitor: needs an email address; the message is emailed to SUPPORT_EMAIL. Staff accounts cannot send.
    """
    from flask import current_app
    from .. import validation as v
    from ..auth.passwords import valid_email
    from ..services import mailer

    user = g.get("user")
    if user is not None and user.role != "user":
        return _reply(False, "Only customer accounts can send messages.", 403)
    data = request.get_json(silent=True) if request.is_json else request.form
    data = data or {}
    subject = v.one_line(data.get("subject"))
    body = "\n".join(line.rstrip() for line in v.strip_controls(str(data.get("body") or data.get("message") or "")).replace("\r\n", "\n").replace("\r", "\n").split("\n")).strip()
    errors = {}
    if not subject:
        errors["subject"] = "Enter a subject."
    elif len(subject) < 3:
        errors["subject"] = "The subject needs at least 3 characters."
    elif len(subject) > SUBJECT_MAX:
        errors["subject"] = f"The subject can be up to {SUBJECT_MAX} characters."
    if not body:
        errors["body"] = "Write your message."
    elif len(body) < 5:
        errors["body"] = "Your message needs at least 5 characters."
    elif len(body) > BODY_MAX:
        errors["body"] = f"Your message can be up to {BODY_MAX:,} characters."
    email = ""
    if user is None:
        raw_email = v.one_line(data.get("email"))
        errs: dict = {}
        email = v.email_address(raw_email, "email", errs, valid_email) if raw_email else ""
        if not raw_email:
            errors["email"] = "Enter your email address so we can reply."
        elif errs:
            errors["email"] = errs["email"]
    if errors:
        return _reply(False, "Please check the highlighted fields.", 422, errors=errors)

    if user is not None:
        try:
            create_thread(user, subject, body)
            db.session.commit()
        except Exception:  # noqa: BLE001
            db.session.rollback()
            current_app.logger.exception("Support message could not be saved")
            return _reply(False, "We could not send your message right now. Please try again in a moment.", 500)
        return _reply(True, "Your message was sent successfully.", note="Our Admin team and Shop Owner can both see it. You can read their reply in My messages.")

    to = (current_app.config.get("SUPPORT_EMAIL") or "").strip()
    if not to or not mailer.enabled():
        return _reply(False, "Messaging is not available right now. Please contact us on WhatsApp or by phone.", 503)
    try:
        mailer.send_now(to, f"RR FOODS enquiry: {subject}"[:200], f"Website enquiry\nFrom: {email}\nSubject: {subject}\n\n{body}")
    except Exception:  # noqa: BLE001
        current_app.logger.exception("Contact email could not be sent")
        return _reply(False, "We could not send your message right now. Please try again in a moment.", 500)
    return _reply(True, "Your message was sent successfully.", note="We will reply to the email address you gave.")
