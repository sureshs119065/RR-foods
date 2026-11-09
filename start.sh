#!/bin/sh
# Container start script: prints diagnostics, runs migrations, then starts gunicorn.
set -e
echo "== nk start: $(python -V 2>&1)"
python -c "import flask, sqlalchemy, psycopg; print('deps ok: flask', flask.__version__)"
echo "== running migrations"
flask db upgrade
echo "== starting gunicorn (PORT=${PORT:-unset})"
exec gunicorn -c gunicorn.conf.py wsgi:app
