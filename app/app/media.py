from flask import Blueprint, current_app, send_from_directory

bp = Blueprint("media", __name__)


@bp.get("/uploads/<path:filename>")
def uploaded(filename):
    """Serves uploaded images only. send_from_directory blocks ../ tricks. Long cache: file names never repeat."""
    resp = send_from_directory(current_app.config["UPLOAD_DIR"], filename, conditional=True, max_age=31536000)
    resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    return resp
