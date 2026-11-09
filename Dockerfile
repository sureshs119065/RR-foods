# Web app image. The database is NOT inside it: give it DATABASE_URL (managed PostgreSQL or your own server).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 FLASK_APP=wsgi.py FLASK_ENV=production
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn

COPY . .
RUN useradd --system --create-home nk && mkdir -p /data/uploads && chown -R nk:nk /data /app
USER nk
ENV UPLOAD_DIR=/data/uploads
VOLUME ["/data/uploads"]
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD python -c "import urllib.request as u; u.urlopen('http://127.0.0.1:8000/readyz', timeout=4)"
CMD ["sh", "start.sh"]
