from dotenv import load_dotenv
from flask import Flask, current_app, g, render_template, request, jsonify, url_for
from werkzeug.middleware.proxy_fix import ProxyFix
import logging
import uuid
import re
import json
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler

# Load this project's own .env before Config class attributes are evaluated.
from pathlib import Path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(dotenv_path=PROJECT_ROOT / ".env", override=False)

from .config import Config, BASE_DIR
from .extensions import csrf, db, limiter, migrate


def create_app(config_object=None):
    load_dotenv(dotenv_path=BASE_DIR / ".env", override=False)
    app = Flask(__name__)
    app.config.from_object(config_object or Config)
    # Console + rotating-file logs. Avoid logging request bodies, cookies or credentials.
    log_dir = Path(app.config["LOG_DIR"])
    log_dir.mkdir(parents=True, exist_ok=True)
    app.logger.setLevel(getattr(logging, app.config.get("LOG_LEVEL", "INFO"), logging.INFO))
    if not any(getattr(h, "_rr_foods_handler", False) for h in app.logger.handlers):
        class RequestIdFilter(logging.Filter):
            def filter(self, record):
                try:
                    record.request_id = getattr(g, "request_id", "-")
                except RuntimeError:
                    record.request_id = "-"
                return True
        class JsonLogFormatter(logging.Formatter):
            def format(self, record):
                payload = {
                    "timestamp": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
                    "level": record.levelname,
                    "logger": record.name,
                    "request_id": getattr(record, "request_id", "-"),
                    "message": record.getMessage(),
                }
                if record.exc_info:
                    payload["exception"] = self.formatException(record.exc_info)
                return json.dumps(payload, ensure_ascii=False)
        formatter = JsonLogFormatter()
        console = logging.StreamHandler()
        console.setFormatter(formatter); console.addFilter(RequestIdFilter()); console._rr_foods_handler = True
        file_handler = RotatingFileHandler(log_dir / "rr-foods.log", maxBytes=app.config["LOG_MAX_BYTES"],
                                           backupCount=app.config["LOG_BACKUP_COUNT"], encoding="utf-8")
        file_handler.setFormatter(formatter); file_handler.addFilter(RequestIdFilter()); file_handler._rr_foods_handler = True
        app.logger.addHandler(console); app.logger.addHandler(file_handler)
        app.logger.propagate = False
    if app.config.get("TRUST_PROXY"):
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    from .prodcheck import config_problems, is_production, startup_errors
    import sys
    if not app.config.get("TESTING") and "check-config" not in sys.argv:
        errors = startup_errors(app)
        if errors:
            raise RuntimeError("Refusing to start:\n  - " + "\n  - ".join(errors) + "\nSee .env.production.example.")
    if is_production(app) and "check-config" not in sys.argv:   # `flask check-config` must still run to list the problems
        fatal, _ = config_problems(app)
        if fatal:
            raise RuntimeError("Refusing to start in production with unsafe settings:\n  - " + "\n  - ".join(fatal)
                               + "\nFix these in .env (see .env.production.example), or run `flask check-config` for the full list.")

    from flask.sessions import SecureCookieSessionInterface

    class _SessionInterface(SecureCookieSessionInterface):
        """Static files never set or refresh the session cookie. Without this, a signed-in customer's permanent session was
        re-sent as Set-Cookie on every CSS/JS/image/font response, which shared caches refuse to reuse."""
        def should_set_cookie(self, app, session):
            return request.endpoint != "static" and super().should_set_cookie(app, session)

    app.session_interface = _SessionInterface()

    db.init_app(app)
    from . import models  # noqa: F401  (registers every table with Alembic)
    migrate.init_app(app, db)
    from .services import home_cache
    home_cache.init_app(app)  # empties the home-page cache when a product or category change is committed
    @app.before_request
    def _cap_customer_uploads():
        """Step 5.5: only /admin and /owner may send big uploads (videos, several product photos). Everywhere else the whole
        request is capped (16 MB: three 5 MB review photos plus form fields), and Werkzeug answers 413 before reading it.
        Registered before csrf.init_app(): the CSRF check reads the form, so the cap must already be in place."""
        if not request.path.startswith(("/admin", "/owner")):
            cap = app.config.get("CUSTOMER_MAX_CONTENT_LENGTH")
            if cap and (app.config.get("MAX_CONTENT_LENGTH") or cap) > cap:
                request.max_content_length = cap

    csrf.init_app(app)
    limiter.init_app(app)

    @app.before_request
    def _assign_request_id():
        supplied = request.headers.get("X-Request-ID", "")
        g.request_id = supplied[:64] if supplied and re.fullmatch(r"[A-Za-z0-9._-]{1,64}", supplied) else uuid.uuid4().hex

    @app.before_request
    def _reject_nul_bytes():
        """PostgreSQL text cannot hold a NUL byte, so one in a URL, query string, form field or JSON body used to end in a 500.
        Refuse it up front with a 400 (step 5.4). The CSP report route cleans its own body."""
        if request.endpoint == "csp.csp_report":
            return None
        bad = "\x00" in request.path or any("\x00" in str(x) for x in (request.view_args or {}).values())
        bad = bad or any("\x00" in k or "\x00" in x for k, x in request.args.items(multi=True))
        if not bad and request.method in ("POST", "PUT", "PATCH", "DELETE"):
            bad = any("\x00" in k or "\x00" in x for k, x in request.form.items(multi=True))
            if not bad and request.is_json and (request.content_length or 0) <= 262144:
                raw = request.get_data(cache=True)
                bad = b"\x00" in raw or b"\\u0000" in raw
        if bad:
            from flask import abort
            abort(400)

    @app.after_request
    def _request_id_header(resp):
        resp.headers["X-Request-ID"] = getattr(g, "request_id", "-")
        return resp


    from .auth.routes import bp as auth_bp
    from .auth.service import load_current_user
    from .owner import bp as owner_bp
    from .admin import bp as admin_bp
    app.register_blueprint(auth_bp)
    app.register_blueprint(owner_bp)
    app.register_blueprint(admin_bp)
    from .shop import bp as shop_bp
    app.register_blueprint(shop_bp)
    from .media import bp as media_bp
    app.register_blueprint(media_bp)
    from .api import bp as api_bp
    app.register_blueprint(api_bp)
    from .csp import bp as csp_bp
    app.register_blueprint(csp_bp)

    from .cli import register_check_cli, register_cli, register_mail_cli, register_order_request_cli, register_settings_cli, register_stock_alert_cli
    register_cli(app)
    register_settings_cli(app)
    register_mail_cli(app)
    register_stock_alert_cli(app)
    register_order_request_cli(app)
    from .cli import register_stock_notification_sync_cli
    register_stock_notification_sync_cli(app)
    register_check_cli(app)
    from .cli import register_guest_cart_cli
    register_guest_cart_cli(app)
    from .cli import register_image_cli
    register_image_cli(app)
    from .cli import register_check_images_cli
    register_check_images_cli(app)

    # Stock-alert reconciliation is NOT done per request any more (step 4.2): a GET must never write to the database.
    # It runs from cron: `flask sync-stock-notifications` every 30 minutes (see deploy/crontab.txt and deploy/DEPLOY.md).

    @app.before_request
    def _load_user():
        if request.endpoint == "static":
            # Step 4: CSS/JS/images/fonts hold nothing personal. Loading the user here cost a SELECT per asset for signed-in
            # customers, refreshed the session cookie (Set-Cookie on every file) and added `Vary: Cookie`, which stops shared
            # caches from reusing the "public, immutable" files.
            g.user = None
            return
        load_current_user()

    from .admin.helpers import ago, local_display, local_input
    app.jinja_env.filters["local_input"] = local_input
    app.jinja_env.filters["local_display"] = local_display
    app.jinja_env.filters["ago"] = ago
    from .services.storefront import active_variants, available_qty
    app.jinja_env.globals["available_qty"] = available_qty
    app.jinja_env.globals["active_variants"] = active_variants  # usable inside imported macros
    from .services import whatsapp as wa
    app.jinja_env.globals["wa_owner_link"] = wa.owner_link          # customer -> owner: order already written
    app.jinja_env.globals["wa_order_text"] = wa.order_message
    app.jinja_env.globals["wa_owner_number"] = wa.owner_number  # one place decides which config key holds the shop's number
    app.jinja_env.globals["wa_customer_link"] = wa.customer_link    # owner -> customer: status message already written

    def product_image_fallback(product):
        """Photo for a product with no usable uploaded image: the bundled file named exactly like its slug, else one neutral
        placeholder drawing (step 2.4). Never a photo of a different product."""
        if not product:
            return None
        from .placeholders import PLACEHOLDER, bundled_photo
        filename = bundled_photo(app.static_folder, getattr(product, "slug", ""))
        return url_for("static", filename=f"img/products/{filename}" if filename else PLACEHOLDER)

    def product_image_src(image, product=None, thumbnail=False):
        """Resolve a product image URL against the configured upload store without losing CDN URLs."""
        if not image:
            return product_image_fallback(product) if product else None
        candidates = []
        if thumbnail and getattr(image, "thumb_url", None):
            candidates.append(image.thumb_url)
        if getattr(image, "url", None):
            candidates.append(image.url)
        for raw in candidates:
            raw = (raw or "").strip()
            if not raw:
                continue
            if raw.startswith(("https://", "http://", "//", "data:")):
                return raw
            normalized = raw if raw.startswith("/") else "/" + raw.lstrip("/")
            if normalized.startswith("/uploads/"):
                root = Path(app.config["UPLOAD_DIR"]).resolve()
                target = (root / normalized[len("/uploads/"):]).resolve()
                if root in target.parents and target.is_file():
                    return normalized
                continue
            if normalized.startswith("/static/"):
                static_root = Path(app.static_folder).resolve()
                target = (static_root / normalized[len("/static/"):]).resolve()
                if static_root in target.parents and target.is_file():
                    return normalized
                continue
            if normalized.startswith("/img/"):
                static_root = Path(app.static_folder).resolve()
                target = (static_root / normalized.lstrip("/")).resolve()
                if static_root in target.parents and target.is_file():
                    return url_for("static", filename=normalized.lstrip("/"))
                continue
            # Legacy relative image paths are accepted only when a real bundled static file exists.
            static_root = Path(app.static_folder).resolve()
            target = (static_root / normalized.lstrip("/")).resolve()
            if static_root in target.parents and target.is_file():
                return url_for("static", filename=normalized.lstrip("/"))
        return product_image_fallback(product) if product else None

    app.jinja_env.globals["product_image_fallback"] = product_image_fallback
    app.jinja_env.globals["product_image_src"] = product_image_src

    from .assets import init_assets
    init_assets(app)  # registered before _security_headers, so its hook runs after it and wins for /static/

    @app.context_processor
    def _inject():
        return {"current_user": g.get("user"), "current_language": (g.get("user").preferred_language if g.get("user") else request.cookies.get("language", "en"))}

    @app.after_request
    def _security_headers(resp):
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Permitted-Cross-Domain-Policies", "none")
        resp.headers.setdefault("Cross-Origin-Resource-Policy", "same-site")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        # Step 5.3 review: nothing on the site uses these features, so they are off for the page and for the YouTube frame.
        # Left alone on purpose: accelerometer, gyroscope, autoplay, encrypted-media, picture-in-picture, clipboard-write and
        # web-share, which the embedded recipe video asks for in its allow="" attribute, and fullscreen.
        resp.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=(), usb=(), serial=(), "
                                "bluetooth=(), hid=(), midi=(), magnetometer=(), display-capture=(), xr-spatial-tracking=(), "
                                "browsing-topics=(), interest-cohort=()")
        resp.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin-allow-popups")
        hsts = app.config.get("HSTS_SECONDS", 31536000)
        # Production is HTTPS-only, and behind a proxy without TRUST_PROXY request.is_secure is False, so do not depend on it there.
        if hsts and ((request.is_secure and not app.config.get("TESTING")) or is_production(app)):
            resp.headers.setdefault("Strict-Transport-Security", f"max-age={hsts}; includeSubDomains")
        csp = "default-src 'self'; base-uri 'self'; object-src 'none'; img-src 'self' data: https:; style-src 'self'; script-src 'self'; connect-src 'self'; frame-src https://www.youtube-nocookie.com; frame-ancestors 'none'; form-action 'self'; report-uri /csp-report; report-to csp-endpoint"
        resp.headers.setdefault("Reporting-Endpoints", 'csp-endpoint="/csp-report"')
        if request.is_secure:
            csp += "; upgrade-insecure-requests"
        resp.headers.setdefault("Content-Security-Policy", csp)
        # pages behind a login must never be stored by the browser or a shared cache
        if g.get("user") is not None or request.path.startswith(("/admin", "/owner", "/account")):
            resp.headers["Cache-Control"] = "no-store"
        return resp

    def _error(code, title, message):
        def handler(err):
            if code >= 500:
                app.logger.error("Unhandled application error", exc_info=(type(err), err, err.__traceback__))
            return render_template("errors/error.html", code=code, title=title, message=message), code
        return handler

    app.register_error_handler(403, _error(403, "Not allowed", "Your account does not have access to this page."))
    app.register_error_handler(404, _error(404, "Page not found", "That page does not exist or has moved."))
    app.register_error_handler(413, _error(413, "File too large", "That upload is too big. Use smaller images (5 MB each) and try again."))
    app.register_error_handler(429, _error(429, "Too many attempts", "Please wait a minute and try again."))
    app.register_error_handler(500, _error(500, "Something went wrong", "We could not finish that. Please try again."))
    from flask_wtf.csrf import CSRFError
    app.register_error_handler(CSRFError, _error(400, "Page expired", "For your safety this form expired. Go back, reload the page and try again."))

    @app.get("/health")
    @limiter.exempt
    def health():
        from sqlalchemy import text
        try:
            db.session.execute(text("SELECT 1"))
            return jsonify(status="ok", database="ok", version=app.config["APP_VERSION"]), 200
        except Exception:
            db.session.rollback()
            app.logger.exception("Health check database failure")
            return jsonify(status="error", database="unavailable", version=app.config["APP_VERSION"]), 503

    @app.get("/healthz")
    @limiter.exempt
    def healthz():
        return {"status": "ok"}

    @app.get("/readyz")
    @limiter.exempt
    def readyz():
        """For load balancers/monitoring: 200 only if the database answers."""
        from sqlalchemy import text
        try:
            db.session.execute(text("select 1"))
        except Exception:  # noqa: BLE001  any failure means "not ready"
            return {"status": "database unavailable"}, 503
        return {"status": "ready"}

    return app
