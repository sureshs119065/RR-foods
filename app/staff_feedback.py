"""One "Questions" page registered on both the Admin and the Owner blueprint so the two panels behave and look the same.
The customer-message "Feedback" tab was removed; the old Customer Inbox and Feedback URLs redirect to Questions."""
from flask import abort, flash, g, redirect, render_template, request, url_for

from .extensions import db
from .services import feedback_hub as hub


def register(bp, portal: str) -> None:
    def ep(name: str) -> str:
        return f"{portal}.{name}"

    @bp.get("/questions", endpoint="questions")
    def questions():
        show = "answered" if request.args.get("show") == "answered" else "open"
        page, products, asked_by = hub.questions_page(show)
        return render_template("staff/feedback.html", page=page, show=show, products=products, asked_by=asked_by, portal=portal, tab="questions", counts=hub.counts())

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

    # ---- retired: the Feedback tab and the old Customer Inbox. Old links, bookmarks and notifications land on Questions.
    @bp.route("/feedback/<int:thread_id>", methods=["GET", "POST"], endpoint="feedback_thread")
    def feedback_thread(thread_id):
        return redirect(url_for(ep("questions")), code=301)

    @bp.get("/inbox", endpoint="legacy_inbox")
    def legacy_inbox():
        return redirect(url_for(ep("questions")), code=301)

    @bp.get("/inbox/<int:thread_id>", endpoint="legacy_inbox_thread")
    def legacy_inbox_thread(thread_id):
        return redirect(url_for(ep("questions")), code=301)
