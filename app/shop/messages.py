from flask import abort, flash, g, redirect, render_template, request, url_for
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
        subject = " ".join((request.form.get("subject") or "").split())[:160]
        body = " ".join((request.form.get("body") or "").split())
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
        body = " ".join((request.form.get("body") or "").split())
        if not 1 <= len(body) <= 4000:
            flash("Write a message (up to 4,000 characters).", "error")
        else:
            add_reply(thread, g.user, body)
            db.session.commit()
            flash("Your reply was sent to the RR FOODS team.", "success")
            return redirect(url_for("shop.message_thread", thread_id=thread.id))
    return render_template("shop/messages.html", threads=None, thread=thread)
