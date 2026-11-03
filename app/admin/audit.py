from flask import render_template, request
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from ..extensions import db
from ..models import AuditLog
from . import bp
from .helpers import page_number


@bp.route("/audit")
def audit():
    q = select(AuditLog).options(joinedload(AuditLog.actor))
    action = (request.args.get("action") or "").strip()
    if action:
        q = q.where(AuditLog.action.startswith(action, autoescape=True))
    entity = (request.args.get("entity") or "").strip()
    if entity:
        q = q.where(AuditLog.entity_type == entity)
    page = db.paginate(q.order_by(AuditLog.id.desc()), page=page_number(), per_page=50, error_out=False)
    args = {k: v for k, v in request.args.items() if k != "page" and v}
    entities = db.session.scalars(select(AuditLog.entity_type).distinct().order_by(AuditLog.entity_type)).all()
    return render_template("admin/audit.html", page=page, args=args, entities=entities)
