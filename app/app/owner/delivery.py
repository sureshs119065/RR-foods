from datetime import date

from flask import flash, g, redirect, render_template, request, url_for

from ..auth.service import audit
from ..extensions import db, limiter
from ..models import SiteSetting
from ..services.delivery_slots import SETTING_KEY, get_settings
from . import bp


@bp.get("/delivery-settings")
def delivery_settings():
    return render_template("owner/delivery_settings.html", settings=get_settings())


@bp.post("/delivery-settings")
@limiter.limit("10 per minute")
def delivery_settings_save():
    cutoff = (request.form.get("cutoff_time") or "").strip()
    try:
        hh, mm = cutoff.split(":", 1)
        if not (0 <= int(hh) <= 23 and 0 <= int(mm) <= 59):
            raise ValueError
        cutoff = f"{int(hh):02d}:{int(mm):02d}"
    except (ValueError, TypeError):
        flash("Enter a valid cutoff time.", "error")
        return redirect(url_for("owner.delivery_settings"))
    try:
        capacity = int(request.form.get("max_orders_per_slot", "20"))
        days = int(request.form.get("days_ahead", "7"))
        if not 1 <= capacity <= 500 or not 1 <= days <= 60:
            raise ValueError
    except ValueError:
        flash("Slot capacity must be 1–500 and booking days must be 1–60.", "error")
        return redirect(url_for("owner.delivery_settings"))
    blocked = []
    for raw in (request.form.get("blocked_dates") or "").splitlines()[:180]:
        raw = raw.strip()
        if not raw:
            continue
        try:
            blocked.append(date.fromisoformat(raw).isoformat())
        except ValueError:
            flash(f"Invalid blocked date: {raw}", "error")
            return redirect(url_for("owner.delivery_settings"))
    before = get_settings()
    after = {"cutoff_time": cutoff, "max_orders_per_slot": capacity, "days_ahead": days, "blocked_dates": sorted(set(blocked))}
    row = db.session.get(SiteSetting, SETTING_KEY) or SiteSetting(key=SETTING_KEY, value=after)
    row.value = after
    db.session.add(row)
    audit("delivery_slots.settings", entity_type="site_setting", entity_id=SETTING_KEY, actor_id=g.user.id, before=before, after=after)
    db.session.commit()
    flash("Delivery slot settings saved.", "success")
    return redirect(url_for("owner.delivery_settings"))
