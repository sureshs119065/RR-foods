"""Content-Security-Policy violation reports (step 5.3).

Browsers POST a small JSON report here when the page breaks the CSP (a blocked inline script, an image from a host that
is not allowed...). The route only logs: nothing is written to the database, the body is size-capped and rate-limited,
every logged value is cut down and stripped of control characters, and URLs lose their query string, fragment and any
password-reset token, so a report can neither flood the logs nor leak a secret into them.
"""
import json
import re
from urllib.parse import urlsplit

from flask import Blueprint, current_app, request

from . import ratelimits as limits
from .extensions import csrf, limiter

bp = Blueprint("csp", __name__)

MAX_BODY = 16 * 1024
MAX_REPORTS = 10          # a Reporting API POST may batch several
ENDPOINT = "/csp-report"
GROUP = "csp-endpoint"

# legacy report-uri names and Reporting API names -> one set of log keys
_FIELDS = {
    "document-uri": "document", "documentURL": "document", "documentUrl": "document",
    "blocked-uri": "blocked", "blockedURL": "blocked", "blockedUrl": "blocked",
    "violated-directive": "violated", "effective-directive": "effective", "effectiveDirective": "effective",
    "disposition": "disposition", "source-file": "source", "sourceFile": "source",
    "line-number": "line", "lineNumber": "line", "column-number": "column", "columnNumber": "column",
    "status-code": "status", "statusCode": "status",
}
_URL_KEYS = {"document", "blocked", "source"}
_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f\u2028\u2029]")
_TOKEN_PATH = re.compile(r"^(/reset/).+$")


def _safe_text(value, limit=200) -> str:
    return _CONTROL.sub(" ", str(value))[:limit]


def _safe_url(value) -> str:
    """scheme://host/path only. Keywords such as 'inline' or 'eval' and 'data' pass through unchanged."""
    text = _safe_text(value, 300)
    if "://" not in text:
        return text.split("?")[0].split("#")[0][:60] if text.startswith("/") else text[:40]
    try:
        parts = urlsplit(text)
    except ValueError:
        return "invalid-url"
    path = _TOKEN_PATH.sub(r"\1[redacted]", parts.path)
    return f"{parts.scheme}://{parts.netloc}{path}"[:200]


def clean_report(raw) -> dict | None:
    """Pick the known fields out of one report (either format) and make them log-safe. None if it is not a CSP report."""
    if not isinstance(raw, dict):
        return None
    if raw.get("type") not in (None, "csp-violation"):
        return None
    body = raw.get("csp-report") or raw.get("body") or raw
    if not isinstance(body, dict):
        return None
    out = {}
    for key, value in body.items():
        name = _FIELDS.get(key)
        if name is None or isinstance(value, (dict, list)) or value is None:
            continue
        out[name] = _safe_url(value) if name in _URL_KEYS else _safe_text(value)
    return out or None


def parse_reports(payload) -> list[dict]:
    items = payload if isinstance(payload, list) else [payload]
    cleaned = (clean_report(item) for item in items[:MAX_REPORTS])
    return [c for c in cleaned if c]


@bp.post(ENDPOINT)
@csrf.exempt  # sent by the browser itself, no form and no cookie; it can only add a log line
@limiter.limit(limits.limit("csp_report"))
def csp_report():
    request.max_content_length = MAX_BODY     # 413 for anything bigger, before it is read
    payload = request.get_json(force=True, silent=True)
    reports = parse_reports(payload)
    if not reports:
        return "", 400
    for report in reports:
        current_app.logger.warning("csp_violation %s", json.dumps(report, ensure_ascii=True, sort_keys=True))
    return "", 204
