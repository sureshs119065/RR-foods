from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from flask_wtf.csrf import CSRFProtect

db = SQLAlchemy()
migrate = Migrate()
csrf = CSRFProtect()  # every POST/PUT/PATCH/DELETE must carry a valid CSRF token
# No storage_uri here on purpose: a constructor value beats RATELIMIT_STORAGE_URI, which silently kept Redis switched off.
limiter = Limiter(get_remote_address, default_limits=[])
