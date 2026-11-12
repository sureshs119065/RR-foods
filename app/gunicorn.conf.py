"""Gunicorn settings. Override with environment variables, e.g. WEB_CONCURRENCY=4."""
import multiprocessing
import os

bind = os.environ.get("GUNICORN_BIND") or (f"0.0.0.0:{os.environ['PORT']}" if os.environ.get("PORT") else "127.0.0.1:8000")  # Render sets PORT
workers = int(os.environ.get("WEB_CONCURRENCY", max(2, min(4, multiprocessing.cpu_count() * 2 + 1))))
threads = int(os.environ.get("GUNICORN_THREADS", "2"))
timeout = 60                 # image uploads are resized in the request
graceful_timeout = 30
keepalive = 5
max_requests = 1000          # restart each worker now and then (guards against slow memory growth)
max_requests_jitter = 100
accesslog = "-"
errorlog = "-"
forwarded_allow_ips = os.environ.get("FORWARDED_ALLOW_IPS", "*" if os.environ.get("PORT") else "127.0.0.1")
