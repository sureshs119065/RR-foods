from pathlib import PurePosixPath

from flask import Blueprint, abort, current_app, send_from_directory

bp = Blueprint("media", __name__)

# Step 5.5: the only things /uploads/ will ever serve, each with a fixed Content-Type. The type is never guessed from the
# file name, so a stray .html, .svg, .php or .js in the folder is a 404 instead of a page that could run script.
SERVED_TYPES = {
    ".webp": "image/webp", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
    ".mp4": "video/mp4", ".webm": "video/webm", ".mov": "video/quicktime",
}


@bp.get("/uploads/<path:filename>")
def uploaded(filename):
    """Serves uploaded images and videos only. send_from_directory blocks ../ tricks. Long cache: file names never repeat."""
    path = PurePosixPath(filename)
    mimetype = SERVED_TYPES.get(path.suffix.lower())
    if mimetype is None or any(part.startswith(".") for part in path.parts):
        abort(404)
    resp = send_from_directory(current_app.config["UPLOAD_DIR"], filename, mimetype=mimetype, conditional=True, max_age=31536000)
    resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    resp.headers["Content-Disposition"] = "inline"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Content-Security-Policy"] = "default-src 'none'; sandbox"  # if one is ever opened as a page, nothing runs
    return resp
