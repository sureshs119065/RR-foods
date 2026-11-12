from dotenv import load_dotenv
from flask import Flask, g, render_template, request, jsonify
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

    from .prodcheck import config_problems, is_production
    import sys
    if is_production(app) and "check-config" not in sys.argv:   # `flask check-config` must still run to list the problems
        fatal, _ = config_problems(app)
        if fatal:
            raise RuntimeError("Refusing to start in production with unsafe settings:\n  - " + "\n  - ".join(fatal)
                               + "\nFix these in .env (see .env.production.example), or run `flask check-config` for the full list.")

    db.init_app(app)
    from . import models  # noqa: F401  (registers every table with Alembic)
    migrate.init_app(app, db)
    csrf.init_app(app)
    limiter.init_app(app)

    @app.before_request
    def _assign_request_id():
        supplied = request.headers.get("X-Request-ID", "")
        g.request_id = supplied[:64] if supplied and re.fullmatch(r"[A-Za-z0-9._-]{1,64}", supplied) else uuid.uuid4().hex

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

    from .cli import register_check_cli, register_cli, register_mail_cli, register_settings_cli, register_stock_alert_cli
    register_cli(app)
    register_settings_cli(app)
    register_mail_cli(app)
    register_stock_alert_cli(app)
    from .cli import register_stock_notification_sync_cli
    register_stock_notification_sync_cli(app)
    register_check_cli(app)

    # Lightweight backfill on first request and at most hourly per worker.
    # For reliable scheduling on Render, also run `flask sync-stock-notifications`
    # from a Render Cron Job every 15-60 minutes.
    from datetime import datetime, timedelta, timezone
    _last_stock_sync = [None]
    @app.before_request
    def _periodic_stock_notification_sync():
        now = datetime.now(timezone.utc)
        if _last_stock_sync[0] and now - _last_stock_sync[0] < timedelta(minutes=30):
            return
        _last_stock_sync[0] = now
        try:
            from .services.inventory import sync_stock_notifications
            sync_stock_notifications()
            db.session.commit()
        except Exception:
            db.session.rollback()
            app.logger.exception("Stock notification reconciliation failed")

    @app.before_request
    def _load_user():
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
    app.jinja_env.globals["wa_customer_link"] = wa.customer_link    # owner -> customer: status message already written

    @app.context_processor
    def _inject():
        user = g.get("user")
        wishlist_count = 0
        if user is not None and user.role == "user":
            from sqlalchemy import func, select
            from .models import WishlistItem
            wishlist_count = db.session.scalar(select(func.count(WishlistItem.id)).where(WishlistItem.user_id == user.id)) or 0
        return {"current_user": user, "wishlist_count": wishlist_count,
                "current_language": (user.preferred_language if user else request.cookies.get("language", "en"))}

    @app.after_request
    def _security_headers(resp):
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Permitted-Cross-Domain-Policies", "none")
        resp.headers.setdefault("Cross-Origin-Resource-Policy", "same-site")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        resp.headers.setdefault("Permissions-Policy", "camera=(self), microphone=(), geolocation=()")
        resp.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin-allow-popups")
        if request.is_secure and not app.config.get("TESTING"):  # only meaningful (and only valid) over HTTPS
            resp.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        csp = "default-src 'self'; base-uri 'self'; object-src 'none'; img-src 'self' data: https:; style-src 'self'; script-src 'self'; connect-src 'self'; frame-src https://www.youtube-nocookie.com; frame-ancestors 'none'; form-action 'self'"
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
