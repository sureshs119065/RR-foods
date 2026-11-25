"""One "Questions & Feedback" page with two tabs (Questions, Feedback), registered on both the Admin and the Owner blueprint so the
two panels behave and look the same. The old Customer Inbox URLs (/inbox, /inbox/<id>) redirect here."""
from flask import abort, flash, g, redirect, render_template, request, url_for

from .extensions import db
from .services import feedback_hub as hub
from .services.customer_inbox import add_reply


def register(bp, portal: str) -> None:
    def ep(name: str) -> str:
        return f"{portal}.{name}"

    @bp.get("/questions", endpoint="questions")
    def questions():
        tab = "feedback" if request.args.get("tab") == "feedback" else "questions"
        show = request.args.get("show", "")
        ctx = {"portal": portal, "tab": tab, "counts": hub.counts()}
        if tab == "feedback":
            show = "needs" if show == "needs" else "all"
            page, waiting = hub.threads_page(show)
            return render_template("staff/feedback.html", page=page, show=show, waiting=waiting, **ctx)
        show = "answered" if show == "answered" else "open"
        page, products, asked_by = hub.questions_page(show)
        return render_template("staff/feedback.html", page=page, show=show, products=products, asked_by=asked_by, **ctx)

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

    @bp.route("/feedback/<int:thread_id>", methods=["GET", "POST"], endpoint="feedback_thread")
    def feedback_thread(thread_id):
        thread = hub.get_thread(thread_id) or abort(404)
        if request.method == "POST":
            body = " ".join((request.form.get("body") or "").split())
            if not 1 <= len(body) <= 4000:
                flash("Write a reply (up to 4,000 characters).", "error")
            else:
                add_reply(thread, g.user, body)
                db.session.commit()
                flash("Reply sent to the customer.", "success")
                return redirect(url_for(ep("feedback_thread"), thread_id=thread.id))
        return render_template("staff/feedback_thread.html", thread=thread, portal=portal, counts=hub.counts())

    # ---- the retired Customer Inbox: old links, bookmarks and old notifications still land in the right place
    @bp.get("/inbox", endpoint="legacy_inbox")
    def legacy_inbox():
        return redirect(url_for(ep("questions"), tab="feedback"), code=301)

    @bp.get("/inbox/<int:thread_id>", endpoint="legacy_inbox_thread")
    def legacy_inbox_thread(thread_id):
        return redirect(url_for(ep("feedback_thread"), thread_id=thread_id), code=301)
