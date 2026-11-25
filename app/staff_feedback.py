"""One "Questions" page registered on both the Admin and the Owner blueprint so the two panels behave and look the same.
It holds two lists: product questions (answered publicly on the product page) and customer messages (from the home
contact form and the customer Inbox; the reply goes to the customer's My messages). The old Inbox and Feedback URLs redirect here."""
from flask import abort, flash, g, redirect, render_template, request, url_for

from .extensions import db
from .services import feedback_hub as hub
from .services.customer_inbox import add_reply


def register(bp, portal: str) -> None:
    def ep(name: str) -> str:
        return f"{portal}.{name}"

    @bp.get("/questions", endpoint="questions")
    def questions():
        view = "messages" if request.args.get("view") == "messages" else "questions"
        counts = hub.counts()
        if view == "messages":
            show = "all" if request.args.get("show") == "all" else "needs"
            page, waiting = hub.threads_page(show)
            return render_template("staff/feedback.html", page=page, waiting=waiting, show=show, view=view, portal=portal, tab="questions", counts=counts)
        show = "answered" if request.args.get("show") == "answered" else "open"
        page, products, asked_by = hub.questions_page(show)
        return render_template("staff/feedback.html", page=page, show=show, view=view, products=products, asked_by=asked_by, portal=portal, tab="questions", counts=counts)

    @bp.post("/questions/<int:question_id>/answer", endpoint="question_answer")
    def question_answer(question_id):
        q = hub.get_question(question_id) or abort(404)
        answer = " ".join((request.form.get("answer") or "").split())
        if not 2 <= len(answer) <= 1000:
            flash("Write an answer (up to 1000 characters).", "error")
            return redirect(url_for(ep("questions")))
        hub.answer_question(q, answer, g.user)
        db.session.commit()
        flash("Answer published on the product page.", "success")
        return redirect(url_for(ep("questions")))

    @bp.post("/questions/<int:question_id>/delete", endpoint="question_delete")
    def question_delete(question_id):
        q = hub.get_question(question_id) or abort(404)
        hub.delete_question(q, g.user)
        db.session.commit()
        flash("Question removed.", "success")
        return redirect(url_for(ep("questions")))

    # ---- customer messages: read the conversation and reply (the customer sees the reply in My messages)
    @bp.route("/questions/messages/<int:thread_id>", methods=["GET", "POST"], endpoint="message_thread")
    def message_thread(thread_id):
        thread = hub.get_thread(thread_id) or abort(404)
        if request.method == "POST":
            body = " ".join((request.form.get("body") or "").split())
            if not 1 <= len(body) <= 4000:
                flash("Write a reply (up to 4,000 characters).", "error")
            else:
                add_reply(thread, g.user, body)
                db.session.commit()
                flash("Reply sent to the customer.", "success")
                return redirect(url_for(ep("message_thread"), thread_id=thread.id))
        return render_template("staff/inbox.html", thread=thread, portal=portal)

    # ---- retired URLs: the old Customer Inbox and Feedback pages now live inside Questions
    @bp.route("/feedback/<int:thread_id>", methods=["GET", "POST"], endpoint="feedback_thread")
    def feedback_thread(thread_id):
        return redirect(url_for(ep("message_thread"), thread_id=thread_id), code=301)

    @bp.get("/inbox", endpoint="legacy_inbox")
    def legacy_inbox():
        return redirect(url_for(ep("questions"), view="messages"), code=301)

    @bp.get("/inbox/<int:thread_id>", endpoint="legacy_inbox_thread")
    def legacy_inbox_thread(thread_id):
        return redirect(url_for(ep("message_thread"), thread_id=thread_id), code=301)
