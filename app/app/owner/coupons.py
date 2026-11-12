import re
from decimal import Decimal

from flask import abort, flash, redirect, render_template, request, url_for
from sqlalchemy import func, select

from ..extensions import db
from ..models import Coupon
from ..owner import bp
from ..admin.helpers import checked, clean, local_input, log, parse_local_dt, to_decimal, to_int


@bp.route("/coupons")
def coupons():
    rows = db.session.scalars(select(Coupon).order_by(Coupon.created_at.desc(), Coupon.id.desc())).all()
    return render_template("owner/coupons.html", rows=rows)


def _snap(c: Coupon) -> dict:
    return {"code": c.code, "type": c.discount_type, "value": str(c.discount_value), "min_cart": str(c.min_cart_value),
            "usage_limit": c.usage_limit, "per_user": c.per_user_limit, "is_active": c.is_active}


def _form(coupon: Coupon | None):
    errors: dict[str, str] = {}
    f = request.form
    if request.method == "POST":
        code = clean(f.get("code"), 40).upper()
        if not re.fullmatch(r"[A-Z0-9][A-Z0-9_-]{2,39}", code):
            errors["code"] = "Use 3 to 40 letters, numbers, dash or underscore (no spaces)."
        else:
            q = select(Coupon.id).where(func.upper(Coupon.code) == code)
            if coupon is not None:
                q = q.where(Coupon.id != coupon.id)
            if db.session.scalar(q):
                errors["code"] = "This code already exists."
        dtype = f.get("discount_type", "")
        if dtype not in ("percent", "flat"):
            errors["discount_type"] = "Choose percent or flat amount."
        value = to_decimal(f.get("discount_value"), "discount_value", errors, min_=Decimal("0.01"),
                           max_=Decimal(100) if dtype == "percent" else Decimal(1_000_000))
        max_disc = to_decimal(f.get("max_discount"), "max_discount", errors, min_=Decimal("0.01"), max_=Decimal(1_000_000), required=False, default=None)
        if dtype == "flat":
            max_disc = None
        min_cart = to_decimal(f.get("min_cart_value"), "min_cart_value", errors, min_=Decimal(0), max_=Decimal(1_000_000), required=False, default=Decimal(0))
        expires = parse_local_dt(f.get("expires_at"), "expires_at", errors)
        usage = to_int(f.get("usage_limit"), "usage_limit", errors, min_=1, max_=10_000_000, required=False, default=None)
        per_user = to_int(f.get("per_user_limit"), "per_user_limit", errors, min_=1, max_=1000, required=False, default=1)
        if coupon is not None and usage is not None and usage < coupon.used_count:
            errors["usage_limit"] = f"This coupon has already been used {coupon.used_count} times."
        if not errors:
            is_new = coupon is None
            if is_new:
                coupon = Coupon(code=code, discount_type=dtype, discount_value=value)
                db.session.add(coupon)
            before = None if is_new else _snap(coupon)
            coupon.code, coupon.description = code, clean(f.get("description"), 200) or None
            coupon.discount_type, coupon.discount_value, coupon.max_discount = dtype, value, max_disc
            coupon.min_cart_value, coupon.expires_at, coupon.usage_limit = min_cart, expires, usage
            coupon.per_user_limit, coupon.is_active = per_user, checked("is_active")
            db.session.flush()
            log("coupon.create" if is_new else "coupon.update", "coupon", coupon.id, before, _snap(coupon))
            db.session.commit()
            flash(f"Coupon {code} saved.", "success")
            return redirect(url_for("owner.coupons"))
        values = {k: f.get(k, "") for k in ("code", "description", "discount_type", "discount_value", "max_discount", "min_cart_value",
                                            "expires_at", "usage_limit", "per_user_limit")}
        values["is_active"] = checked("is_active")
        return render_template("owner/coupon_form.html", coupon=coupon, f=values, errors=errors), 422
    if coupon is None:
        values = dict(code="", description="", discount_type="percent", discount_value="", max_discount="", min_cart_value="0",
                      expires_at="", usage_limit="", per_user_limit="1", is_active=True)
    else:
        values = dict(code=coupon.code, description=coupon.description or "", discount_type=coupon.discount_type,
                      discount_value=coupon.discount_value, max_discount=coupon.max_discount or "", min_cart_value=coupon.min_cart_value,
                      expires_at=local_input(coupon.expires_at), usage_limit=coupon.usage_limit or "", per_user_limit=coupon.per_user_limit,
                      is_active=coupon.is_active)
    return render_template("owner/coupon_form.html", coupon=coupon, f=values, errors=errors)


@bp.route("/coupons/new", methods=["GET", "POST"])
def coupon_new():
    return _form(None)


@bp.route("/coupons/<int:coupon_id>/edit", methods=["GET", "POST"])
def coupon_edit(coupon_id):
    return _form(db.session.get(Coupon, coupon_id) or abort(404))


@bp.post("/coupons/<int:coupon_id>/toggle")
def coupon_toggle(coupon_id):
    c = db.session.get(Coupon, coupon_id) or abort(404)
    c.is_active = not c.is_active
    log("coupon.toggle", "coupon", c.id, after={"is_active": c.is_active})
    db.session.commit()
    flash(f"Coupon {c.code} is now {'active' if c.is_active else 'switched off'}.", "success")
    return redirect(url_for("owner.coupons"))


@bp.post("/coupons/<int:coupon_id>/delete")
def coupon_delete(coupon_id):
    c = db.session.get(Coupon, coupon_id) or abort(404)
    if c.used_count:
        flash("This coupon has been used, so it cannot be deleted. Switch it off instead.", "error")
        return redirect(url_for("owner.coupons"))
    log("coupon.delete", "coupon", c.id, before=_snap(c))
    db.session.delete(c)
    db.session.commit()
    flash("Coupon deleted.", "success")
    return redirect(url_for("owner.coupons"))
