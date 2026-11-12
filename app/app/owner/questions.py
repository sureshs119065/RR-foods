"""Customer questions on product pages: the owner answers (or removes) them here."""
from flask import abort, flash, g, redirect, render_template, request, url_for
from sqlalchemy import select

from ..admin.helpers import page_number
from ..auth.service import audit
from ..extensions import db
from ..models import Product, ProductQuestion, User
from ..models.base import utcnow
from ..services.notify import notify
from . import bp


@bp.route("/questions")
def questions():
    show = request.args.get("show", "open")
    q = select(ProductQuestion).where(ProductQuestion.is_deleted.is_(False))
    q = q.where(ProductQuestion.answer.is_(None) if show == "open" else ProductQuestion.answer.is_not(None))
    page = db.paginate(q.order_by(ProductQuestion.id.desc() if show != "open" else ProductQuestion.id.asc()), page=page_number(), per_page=20, error_out=False)
    products = {p.id: p for p in db.session.scalars(select(Product).where(Product.id.in_({i.product_id for i in page.items} or {0})))}
    asked_by = {u.id: u for u in db.session.scalars(select(User).where(User.id.in_({i.user_id for i in page.items} or {0})))}
    return render_template("owner/questions.html", page=page, show=show, products=products, asked_by=asked_by)


def _get(question_id: int) -> ProductQuestion:
    q = db.session.get(ProductQuestion, question_id)
    if q is None or q.is_deleted:
        abort(404)
    return q


@bp.post("/questions/<int:question_id>/answer")
def question_answer(question_id):
    q = _get(question_id)
    answer = " ".join((request.form.get("answer") or "").split())
    if not 2 <= len(answer) <= 1000:
        flash("Write an answer (up to 1000 characters).", "error")
        return redirect(url_for("owner.questions"))
    first = q.answer is None
    q.answer, q.answered_by, q.answered_at = answer, g.user.id, utcnow()
    p = db.session.get(Product, q.product_id)
    audit("question.answer", entity_type="product", entity_id=q.product_id, actor_id=g.user.id, after={"question_id": q.id})
    if first and p is not None:
        notify(q.user_id, "question_answered", f"Your question about {p.name} was answered", answer[:200], link=f"/product/{p.slug}#qa")
    db.session.commit()
    flash("Answer published on the product page.", "success")
    return redirect(url_for("owner.questions"))


@bp.post("/questions/<int:question_id>/delete")
def question_delete(question_id):
    q = _get(question_id)
    q.is_deleted = True
    audit("question.delete", entity_type="product", entity_id=q.product_id, actor_id=g.user.id, after={"question_id": q.id})
    db.session.commit()
    flash("Question removed.", "success")
    return redirect(url_for("owner.questions"))
