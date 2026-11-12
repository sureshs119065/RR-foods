from ..auth.routes import _change_password
from . import bp


@bp.route("/password", methods=["GET", "POST"])
def password():
    return _change_password("owner/password.html", "/owner/")
