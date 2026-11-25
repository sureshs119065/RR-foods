"""Questions for staff: product questions plus customer messages (home contact form / My messages), answered in one place.
Admin and Owner use exactly the same queries and actions."""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import joinedload, selectinload

from ..admin.helpers import page_number
from ..auth.service import audit
from ..extensions import db
from ..models import CustomerMessage, CustomerMessageThread, Product, ProductQuestion, User
from ..models.base import utcnow
from .notify import notify


def _needs_reply_clause():
    """The newest message in the thread was written by the customer who started it."""
    last_sender = (select(CustomerMessage.sender_id).where(CustomerMessage.thread_id == CustomerMessageThread.id)
                   .order_by(CustomerMessage.created_at.desc(), CustomerMessage.id.desc()).limit(1).correlate(CustomerMessageThread).scalar_subquery())
    return last_sender == CustomerMessageThread.user_id


def counts() -> dict:
    waiting = db.session.scalar(select(func.count(ProductQuestion.id)).where(ProductQuestion.is_deleted.is_(False), ProductQuestion.answer.is_(None))) or 0
    messages = db.session.scalar(select(func.count(CustomerMessageThread.id)).where(_needs_reply_clause())) or 0
    return {"questions": waiting, "messages": messages, "feedback": messages, "total": waiting + messages}


def questions_page(show: str):
    q = select(ProductQuestion).where(ProductQuestion.is_deleted.is_(False))
    q = q.where(ProductQuestion.answer.is_(None) if show == "open" else ProductQuestion.answer.is_not(None))
    order = ProductQuestion.id.asc() if show == "open" else ProductQuestion.id.desc()
    page = db.paginate(q.order_by(order), page=page_number(), per_page=20, error_out=False)
    products = {p.id: p for p in db.session.scalars(select(Product).where(Product.id.in_({i.product_id for i in page.items} or {0})))}
    asked_by = {u.id: u for u in db.session.scalars(select(User).where(User.id.in_({i.user_id for i in page.items} or {0})))}
    return page, products, asked_by


def threads_page(show: str):
    q = select(CustomerMessageThread).options(joinedload(CustomerMessageThread.customer), selectinload(CustomerMessageThread.messages))
    if show == "needs":
        q = q.where(_needs_reply_clause())
    page = db.paginate(q.order_by(CustomerMessageThread.last_message_at.desc()), page=page_number(), per_page=20, error_out=False)
    waiting = {t.id: bool(t.messages) and t.messages[-1].sender_id == t.user_id for t in page.items}
    return page, waiting


def get_thread(thread_id: int):
    return db.session.scalar(select(CustomerMessageThread).where(CustomerMessageThread.id == thread_id).options(
        joinedload(CustomerMessageThread.customer), selectinload(CustomerMessageThread.messages).joinedload(CustomerMessage.sender)))


def get_question(question_id: int):
    q = db.session.get(ProductQuestion, question_id)
    return None if q is None or q.is_deleted else q


def answer_question(q: ProductQuestion, answer: str, actor) -> None:
    first = q.answer is None
    q.answer, q.answered_by, q.answered_at = answer, actor.id, utcnow()
    p = db.session.get(Product, q.product_id)
    audit("question.answer", entity_type="product", entity_id=q.product_id, actor_id=actor.id, after={"question_id": q.id})
    if first and p is not None:
        notify(q.user_id, "question_answered", f"Your question about {p.name} was answered", answer[:200], link=f"/product/{p.slug}#qa")


def delete_question(q: ProductQuestion, actor) -> None:
    q.is_deleted = True
    audit("question.delete", entity_type="product", entity_id=q.product_id, actor_id=actor.id, after={"question_id": q.id})
