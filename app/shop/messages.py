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


@bp.post("/account/messages/quick")
@limiter.limit("10 per hour")
def message_quick():
    """The home page support form: saved with fetch() so the customer stays where they are. Same shared inbox as /account/messages/new."""
    from .. import validation as v
    user = g.get("user")
    if user is None:
        return jsonify(ok=False, message="Please sign in to send a message.", login=url_for("auth.login", next=url_for("shop.home") + "#customer-message")), 401
    if user.role != "user":
        return jsonify(ok=False, message="Only customer accounts can send messages."), 403
    data = request.get_json(silent=True) if request.is_json else request.form
    data = data or {}
    subject = v.one_line(data.get("subject"))
    body = "\n".join(line.rstrip() for line in v.strip_controls(str(data.get("body") or "")).replace("\r\n", "\n").replace("\r", "\n").split("\n")).strip()
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
    if errors:
        return jsonify(ok=False, message="Please check the highlighted fields.", errors=errors), 422
    try:
        create_thread(user, subject, body)
        db.session.commit()
    except Exception:  # noqa: BLE001
        db.session.rollback()
        from flask import current_app
        current_app.logger.exception("Support message could not be saved")
        return jsonify(ok=False, message="We could not send your message right now. Please try again in a moment."), 500
    return jsonify(ok=True, message="Your message was sent successfully.")
