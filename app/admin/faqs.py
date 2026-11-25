"""Admin > FAQ: list, add, edit, delete, show/hide, move up/down, and the home-page display settings.

Saving a Faq empties the storefront home cache by itself (services/home_cache.py watches the model), so nothing here has to."""
from flask import abort, flash, redirect, render_template, request, url_for
from sqlalchemy import func, select

from ..extensions import db
from ..models import Faq
from ..services import faqs as faq_svc
from . import bp
from .helpers import clean, clean_multiline, log, to_int

STEP = 10
MAX_QUESTION, MAX_ANSWER = 300, 2000


def _ordered():
    return db.session.scalars(select(Faq).order_by(Faq.sort_order, Faq.id)).all()


def _snap(f: Faq) -> dict:
    return {"question": f.question, "is_active": f.is_active, "sort_order": f.sort_order}


def _back(faq_id=None):
    return redirect(url_for("admin.faqs", _anchor=f"faq-{faq_id}" if faq_id else None))


@bp.get("/faq")
def faqs():
    items = _ordered()
    return render_template("admin/faqs.html", items=items, cfg=faq_svc.get_settings(), live=sum(1 for f in items if f.is_active),
                           min_count=faq_svc.MIN_COUNT, max_count=faq_svc.MAX_COUNT)


@bp.route("/faq/new", methods=["GET", "POST"])
@bp.route("/faq/<int:faq_id>/edit", methods=["GET", "POST"])
def faq_form(faq_id=None):
    item = db.session.get(Faq, faq_id) if faq_id else None
    if faq_id and item is None:
        abort(404)
    errors, values = {}, {"question": item.question if item else "", "answer": item.answer if item else "",
                          "is_active": item.is_active if item else True}
    if request.method == "POST":
        values = {"question": clean(request.form.get("question"), MAX_QUESTION),
                  "answer": clean_multiline(request.form.get("answer"), MAX_ANSWER),
                  "is_active": request.form.get("is_active") == "1"}
        if not values["question"]:
            errors["question"] = "Enter the question."
        if not values["answer"]:
            errors["answer"] = "Enter the answer."
        if not errors:
            before = _snap(item) if item else None
            if item is None:
                top = db.session.scalar(select(func.max(Faq.sort_order)))
                item = Faq(sort_order=(top or 0) + STEP)
                db.session.add(item)
            item.question, item.answer, item.is_active = values["question"], values["answer"], values["is_active"]
            db.session.flush()
            log("faq.update" if before else "faq.create", "faq", item.id, before=before, after=_snap(item))
            db.session.commit()
            flash("FAQ saved.", "success")
            return _back(item.id)
        flash("Please fix the highlighted fields.", "error")
    return render_template("admin/faq_form.html", item=item, values=values, errors=errors,
                           max_question=MAX_QUESTION, max_answer=MAX_ANSWER)


@bp.post("/faq/<int:faq_id>/delete")
def faq_delete(faq_id):
    item = db.session.get(Faq, faq_id)
    if item is None:
        abort(404)
    log("faq.delete", "faq", item.id, before=_snap(item))
    db.session.delete(item)
    db.session.commit()
    flash("FAQ deleted.", "success")
    return _back()


@bp.post("/faq/<int:faq_id>/toggle")
def faq_toggle(faq_id):
    item = db.session.get(Faq, faq_id)
    if item is None:
        abort(404)
    before = _snap(item)
    item.is_active = not item.is_active
    log("faq.show" if item.is_active else "faq.hide", "faq", item.id, before=before, after=_snap(item))
    db.session.commit()
    flash("FAQ is now shown." if item.is_active else "FAQ is now hidden.", "success")
    return _back(item.id)


@bp.post("/faq/<int:faq_id>/move")
def faq_move(faq_id):
    direction = request.form.get("direction")
    if direction not in ("up", "down"):
        abort(400)
    rows = _ordered()
    ids = [f.id for f in rows]
    if faq_id not in ids:
        abort(404)
    i = ids.index(faq_id)
    j = i - 1 if direction == "up" else i + 1
    if 0 <= j < len(rows):
        rows[i], rows[j] = rows[j], rows[i]
        for pos, f in enumerate(rows):  # renumber, so equal or gappy sort_order values can never make a move do nothing
            f.sort_order = (pos + 1) * STEP
        log("faq.move", "faq", faq_id, after={"direction": direction})
        db.session.commit()
    return _back(faq_id)


@bp.post("/faq/settings")
def faq_settings():
    errors = {}
    count = to_int(request.form.get("max_count"), "max_count", errors, min_=faq_svc.MIN_COUNT, max_=faq_svc.MAX_COUNT)
    if errors:
        flash(f"Number of questions on the home page: {errors['max_count']}", "error")
        return redirect(url_for("admin.faqs"))
    enabled = request.form.get("enabled") == "1"
    before = faq_svc.get_settings()
    faq_svc.save_settings(enabled, count)
    log("faq.settings", "faq_settings", "home_faq", before=before, after={"enabled": enabled, "max_count": count})
    db.session.commit()
    flash("Home page FAQ settings saved.", "success")
    return redirect(url_for("admin.faqs"))
