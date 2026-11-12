from flask import abort, flash, redirect, render_template, request, url_for
from sqlalchemy import func, select

from ..extensions import db
from ..models import Offer, product_offers
from ..owner import bp
from ..admin.helpers import checked, clean, log, parse_local_dt


@bp.route("/offers")
def offers():
    rows = db.session.execute(
        select(Offer, func.count(product_offers.c.product_id)).outerjoin(product_offers, product_offers.c.offer_id == Offer.id)
        .group_by(Offer.id).order_by(Offer.name)).all()
    return render_template("owner/offers.html", rows=rows)


def _form(offer: Offer | None):
    errors: dict[str, str] = {}
    if request.method == "POST":
        name, tag = clean(request.form.get("name"), 120), clean(request.form.get("tag"), 60)
        desc = clean(request.form.get("description"), 300) or None
        starts = parse_local_dt(request.form.get("starts_at"), "starts_at", errors)
        ends = parse_local_dt(request.form.get("ends_at"), "ends_at", errors)
        if len(name) < 2:
            errors["name"] = "Enter a name."
        if len(tag) < 2:
            errors["tag"] = "Enter the label shown on products, for example “Deal of the Day”."
        if starts and ends and ends <= starts:
            errors["ends_at"] = "The end must be after the start."
        if not errors:
            is_new = offer is None
            if is_new:
                offer = Offer(name=name, tag=tag)
                db.session.add(offer)
            before = None if is_new else {"name": offer.name, "tag": offer.tag, "is_active": offer.is_active}
            offer.name, offer.tag, offer.description = name, tag, desc
            offer.starts_at, offer.ends_at, offer.is_active = starts, ends, checked("is_active")
            db.session.flush()
            log("offer.create" if is_new else "offer.update", "offer", offer.id, before, {"name": name, "tag": tag, "is_active": offer.is_active})
            db.session.commit()
            flash(f"Offer “{tag}” saved.", "success")
            return redirect(url_for("owner.offers"))
        f = {"name": name, "tag": tag, "description": desc or "", "starts_at": request.form.get("starts_at", ""),
             "ends_at": request.form.get("ends_at", ""), "is_active": checked("is_active")}
        return render_template("owner/offer_form.html", offer=offer, f=f, errors=errors), 422
    from ..admin.helpers import local_input
    f = {"name": "", "tag": "", "description": "", "starts_at": "", "ends_at": "", "is_active": True} if offer is None else {
        "name": offer.name, "tag": offer.tag, "description": offer.description or "", "starts_at": local_input(offer.starts_at),
        "ends_at": local_input(offer.ends_at), "is_active": offer.is_active}
    return render_template("owner/offer_form.html", offer=offer, f=f, errors=errors)


@bp.route("/offers/new", methods=["GET", "POST"])
def offer_new():
    return _form(None)


@bp.route("/offers/<int:offer_id>/edit", methods=["GET", "POST"])
def offer_edit(offer_id):
    return _form(db.session.get(Offer, offer_id) or abort(404))


@bp.post("/offers/<int:offer_id>/delete")
def offer_delete(offer_id):
    offer = db.session.get(Offer, offer_id) or abort(404)
    log("offer.delete", "offer", offer.id, before={"name": offer.name, "tag": offer.tag})
    db.session.delete(offer)  # removes the label from products too
    db.session.commit()
    flash("Offer deleted. The label was removed from its products.", "success")
    return redirect(url_for("owner.offers"))
