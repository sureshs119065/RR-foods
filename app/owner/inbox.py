from flask import abort, flash, g, redirect, render_template, request, url_for
from sqlalchemy import select
from sqlalchemy.orm import joinedload, selectinload
from ..extensions import db
from ..models import CustomerMessage, CustomerMessageThread
from ..services.customer_inbox import add_reply
from . import bp


def _thread(thread_id):
    row = db.session.scalar(select(CustomerMessageThread).where(CustomerMessageThread.id == thread_id).options(joinedload(CustomerMessageThread.customer), selectinload(CustomerMessageThread.messages).joinedload(CustomerMessage.sender)))
    if row is None:
        abort(404)
    return row


@bp.get("/inbox")
def inbox():
    threads = db.session.scalars(select(CustomerMessageThread).options(joinedload(CustomerMessageThread.customer)).order_by(CustomerMessageThread.last_message_at.desc())).all()
    return render_template("staff/inbox.html", threads=threads, thread=None, portal="owner")


@bp.route("/inbox/<int:thread_id>", methods=["GET", "POST"])
def inbox_thread(thread_id):
    thread = _thread(thread_id)
    if request.method == "POST":
        body = " ".join((request.form.get("body") or "").split())
        if not 1 <= len(body) <= 4000:
            flash("Write a reply (up to 4,000 characters).", "error")
        else:
            add_reply(thread, g.user, body)
            db.session.commit()
            flash("Reply sent to the customer.", "success")
            return redirect(url_for("owner.inbox_thread", thread_id=thread.id))
    return render_template("staff/inbox.html", threads=None, thread=thread, portal="owner")
