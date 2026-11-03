from flask import render_template

from ..auth.routes import _change_password
from . import bp


@bp.route("/password", methods=["GET", "POST"])
def password():
    return _change_password("admin/password.html", "/admin/")
