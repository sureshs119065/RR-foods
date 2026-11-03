import pytest
from flask_migrate import downgrade, upgrade
from sqlalchemy import text

from app import create_app
from app.config import TestConfig
from app.extensions import db, limiter


@pytest.fixture(scope="session")
def app():
    app = create_app(TestConfig)

    def _fresh_g():
        # The `session` fixture keeps one app context open for the whole test, so Flask's `g` would survive between
        # requests and keep a stale cached CSRF token. In real life every request gets a fresh `g`; mimic that here.
        from flask import g
        g.pop("csrf_token", None)

    app.before_request_funcs[None].insert(0, _fresh_g)  # must run before the CSRF check
    with app.app_context():
        db.session.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))
        db.session.commit()
        upgrade(directory="migrations")  # tests run on the real migration, not create_all()
    yield app
    with app.app_context():
        db.session.remove()
        downgrade(directory="migrations", revision="base")


@pytest.fixture()
def session(app):
    with app.app_context():
        yield db.session
        db.session.rollback()
        names = db.session.execute(
            text("select tablename from pg_tables where schemaname='public' and tablename <> 'alembic_version'")
        ).scalars().all()
        db.session.execute(text("TRUNCATE " + ", ".join(f'"{n}"' for n in names) + " RESTART IDENTITY CASCADE"))
        db.session.commit()


@pytest.fixture(autouse=True)
def _reset_rate_limits(app):
    limiter.reset()
    yield
