"""Step 5.3: strict CSP kept, report-uri route that logs violations, Permissions-Policy and COEP review."""
import json
import logging

import pytest

from app.extensions import limiter
from tests.helpers import make_user, sign_in

LEGACY = {"csp-report": {"document-uri": "https://shop.example/product/ragi?utm=1#top", "blocked-uri": "https://evil.example/x.js?token=abc",
                         "violated-directive": "script-src-elem", "effective-directive": "script-src-elem", "disposition": "enforce",
                         "source-file": "https://shop.example/static/a.js", "line-number": 12, "column-number": 3, "status-code": 200}}
API_STYLE = [{"type": "csp-violation", "url": "https://shop.example/", "body": {"documentURL": "https://shop.example/cart", "blockedURL": "inline",
              "effectiveDirective": "script-src-elem", "disposition": "enforce", "lineNumber": 5}},
             {"type": "deprecation", "body": {"id": "x"}},
             {"type": "csp-violation", "body": {"documentURL": "https://shop.example/", "blockedURL": "eval", "effectiveDirective": "script-src"}}]


class Capture(logging.Handler):
    def __init__(self):
        super().__init__()
        self.lines = []

    def emit(self, record):
        self.lines.append(record.getMessage())


@pytest.fixture()
def logs(app):
    h = Capture()
    app.logger.addHandler(h)
    yield h.lines
    app.logger.removeHandler(h)


@pytest.fixture(autouse=True)
def _fresh():
    limiter.reset()


def report(app, payload, ctype="application/csp-report", raw=None):
    return app.test_client().post("/csp-report", data=raw if raw is not None else json.dumps(payload), content_type=ctype)


def violations(lines):
    return [json.loads(l.split(" ", 1)[1]) for l in lines if l.startswith("csp_violation ")]


# ---------------------------------------------------------------- the policy itself
def test_csp_stays_strict_and_reports(app):
    csp = app.test_client().get("/").headers["Content-Security-Policy"]
    assert "script-src 'self'" in csp and "style-src 'self'" in csp and "default-src 'self'" in csp
    assert "unsafe-inline" not in csp and "unsafe-eval" not in csp
    for needed in ("object-src 'none'", "frame-ancestors 'none'", "base-uri 'self'", "form-action 'self'"):
        assert needed in csp
    assert "report-uri /csp-report" in csp and "report-to csp-endpoint" in csp


def test_reporting_endpoints_header_matches_the_csp_group(app):
    assert app.test_client().get("/").headers["Reporting-Endpoints"] == 'csp-endpoint="/csp-report"'


def test_csp_is_on_error_pages_too(app):
    r = app.test_client().get("/no-such-page")
    assert r.status_code == 404 and "report-uri /csp-report" in r.headers["Content-Security-Policy"]


# ---------------------------------------------------------------- Permissions-Policy
@pytest.mark.parametrize("feature", ["camera", "microphone", "geolocation", "payment", "usb", "serial", "bluetooth", "hid",
                                     "magnetometer", "display-capture", "browsing-topics", "interest-cohort"])
def test_permissions_policy_turns_unused_features_off(app, feature):
    assert f"{feature}=()" in app.test_client().get("/").headers["Permissions-Policy"]


def test_permissions_policy_leaves_what_the_youtube_embed_asks_for(app):
    pp = app.test_client().get("/").headers["Permissions-Policy"]
    for needed in ("accelerometer", "gyroscope", "autoplay", "encrypted-media", "picture-in-picture", "clipboard-write", "web-share", "fullscreen"):
        assert needed not in pp   # not listed = default allowlist, so the iframe's allow="" attribute keeps working


# ---------------------------------------------------------------- COEP review (documented in docs/security-headers.md)
def test_coep_is_deliberately_not_require_corp(app):
    """require-corp would block the YouTube frame and every https product photo that lacks a CORP header, and nothing here
    needs cross-origin isolation (no SharedArrayBuffer). Isolation of the page itself comes from COOP and CORP."""
    h = app.test_client().get("/").headers
    assert "Cross-Origin-Embedder-Policy" not in h
    assert h["Cross-Origin-Opener-Policy"] == "same-origin-allow-popups" and h["Cross-Origin-Resource-Policy"] == "same-site"


def test_security_headers_review_is_written_down():
    text = open("docs/security-headers.md", encoding="utf-8").read()
    for word in ("Cross-Origin-Embedder-Policy", "Permissions-Policy", "report-uri", "youtube-nocookie"):
        assert word in text


# ---------------------------------------------------------------- the report route
def test_legacy_report_is_accepted_and_logged(app, logs):
    r = report(app, LEGACY)
    assert r.status_code == 204 and r.get_data() == b""
    (v,) = violations(logs)
    assert v["violated"] == "script-src-elem" and v["disposition"] == "enforce" and v["line"] == "12"
    assert v["document"] == "https://shop.example/product/ragi" and v["blocked"] == "https://evil.example/x.js"   # query and fragment dropped


def test_reporting_api_batch_logs_only_csp_violations(app, logs):
    r = report(app, API_STYLE, ctype="application/reports+json")
    assert r.status_code == 204
    got = violations(logs)
    assert [g["blocked"] for g in got] == ["inline", "eval"]
    assert got[0]["effective"] == "script-src-elem" and got[0]["document"] == "https://shop.example/cart"


def test_report_needs_no_csrf_token_and_no_cookie(app, logs):
    assert report(app, LEGACY).status_code == 204


def test_report_cannot_forge_log_lines_or_leak_tokens(app, logs):
    evil = {"csp-report": {"document-uri": "https://shop.example/reset/SECRET-TOKEN-123?next=/x", "blocked-uri": "inline",
                           "violated-directive": "script-src\nWARNING fake line\r\x00 injected", "disposition": "x" * 5000,
                           "unknown-field": "dropped", "source-file": {"nested": "object"}}}
    assert report(app, evil).status_code == 204
    assert len(logs) == 1 and "\n" not in logs[0] and "\r" not in logs[0] and "\x00" not in logs[0]
    (v,) = violations(logs)
    assert "SECRET-TOKEN" not in logs[0] and v["document"] == "https://shop.example/reset/[redacted]"
    assert len(v["disposition"]) == 200 and "unknown-field" not in v and "source" not in v


def test_at_most_ten_reports_per_request(app, logs):
    many = [{"type": "csp-violation", "body": {"blockedURL": f"https://x.example/{i}"}} for i in range(40)]
    assert report(app, many, ctype="application/reports+json").status_code == 204
    assert len(violations(logs)) == 10


@pytest.mark.parametrize("raw", ["not json", "[]", "{}", '"text"', "123", '{"csp-report": "nope"}', '[{"type": "network-error"}]'])
def test_malformed_or_foreign_reports_get_400_and_log_nothing(app, logs, raw):
    assert report(app, None, raw=raw).status_code == 400
    assert not violations(logs)


def test_oversized_report_is_refused_before_it_is_read(app, logs):
    big = json.dumps({"csp-report": {"document-uri": "https://a.example/" + "a" * 20000}})
    assert report(app, None, raw=big).status_code == 413
    assert not violations(logs)


def test_report_route_is_post_only(app):
    assert app.test_client().get("/csp-report").status_code == 405


def test_report_route_is_rate_limited(app, monkeypatch):
    monkeypatch.setitem(app.config["RATE_LIMITS"], "csp_report", "2 per minute")
    codes = [report(app, LEGACY).status_code for _ in range(3)]
    assert codes == [204, 204, 429]


def test_report_route_writes_nothing_to_the_database(app, session, logs):
    from sqlalchemy import func, select
    from app.models import AuditLog
    before = session.scalar(select(func.count(AuditLog.id)))
    report(app, LEGACY)
    assert session.scalar(select(func.count(AuditLog.id))) == before


def test_signed_in_users_can_report_too(app, session, logs):
    make_user(session, "user")
    c = app.test_client()
    sign_in(c, "user")
    assert c.post("/csp-report", data=json.dumps(LEGACY), content_type="application/csp-report").status_code == 204
