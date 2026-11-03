from flask import current_app, jsonify, make_response, render_template, send_from_directory

from . import bp


@bp.get("/manifest.webmanifest")
def manifest():
    resp = jsonify({
        "name": "RR FOODS", "short_name": "RR FOODS", "start_url": "/", "scope": "/", "display": "standalone",
        "background_color": "#FFFFFF", "theme_color": "#183D2B",
        "icons": [{"src": "/static/img/rr-foods-icon-192.png", "sizes": "192x192", "type": "image/png"},
                  {"src": "/static/img/rr-foods-icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any maskable"}],
    })
    resp.mimetype = "application/manifest+json"
    return resp


@bp.get("/sw.js")
def service_worker():
    """Served from the site root so it can cover every page. Never cached by the browser for long, so updates arrive."""
    resp = make_response(send_from_directory(current_app.static_folder, "js/sw.js", mimetype="application/javascript"))
    resp.headers["Cache-Control"] = "no-cache"
    resp.headers["Service-Worker-Allowed"] = "/"
    return resp


@bp.get("/offline")
def offline():
    return render_template("shop/offline.html")
