# Security headers: review (step 5.3)

Set in one place, `_security_headers` in `app/__init__.py`. Every response gets them, including error pages.

| Header | Value | Why |
|---|---|---|
| Content-Security-Policy | `default-src 'self'`; `script-src 'self'`; `style-src 'self'`; `img-src 'self' data: https:`; `connect-src 'self'`; `frame-src https://www.youtube-nocookie.com`; `object-src 'none'`; `base-uri 'self'`; `form-action 'self'`; `frame-ancestors 'none'`; `report-uri /csp-report`; `report-to csp-endpoint` | Strict: no `unsafe-inline`, no `unsafe-eval`, no third-party scripts or styles. `upgrade-insecure-requests` is added on HTTPS. |
| Reporting-Endpoints | `csp-endpoint="/csp-report"` | The group named by `report-to`. `report-uri` is kept as well because Firefox and Safari still use it. |
| Permissions-Policy | camera, microphone, geolocation, payment, usb, serial, bluetooth, hid, midi, magnetometer, display-capture, xr-spatial-tracking, browsing-topics, interest-cohort all `()` | Nothing on the site uses them. `camera` was `(self)`; the admin photo field only uses a file input, which needs no permission. |
| Strict-Transport-Security | `max-age=31536000; includeSubDomains` | Production only (`HSTS_SECONDS`, 0 = off). No `preload` on purpose. |
| Cross-Origin-Opener-Policy | `same-origin-allow-popups` | Isolates the page from windows it did not open, but still lets the WhatsApp and UPI hand-offs work. |
| Cross-Origin-Resource-Policy | `same-site` | Other sites cannot embed our files. |
| X-Frame-Options, X-Content-Type-Options, Referrer-Policy | `DENY`, `nosniff`, `strict-origin-when-cross-origin` | |

## Permissions-Policy: what was deliberately left alone

`accelerometer`, `gyroscope`, `autoplay`, `encrypted-media`, `picture-in-picture`, `clipboard-write`, `web-share` and
`fullscreen` are not listed. The recipe video iframe (`youtube-nocookie`) asks for them in its own `allow=""` attribute and
would stop working if the page denied them. `navigator.share` is used by the share buttons.

## Cross-Origin-Embedder-Policy: reviewed, not set

`Cross-Origin-Embedder-Policy: require-corp` is only needed for cross-origin isolation (`SharedArrayBuffer`, high-resolution
timers), which this site does not use. Turning it on would break:

- the YouTube embed (`youtube-nocookie.com` sends no Cross-Origin-Resource-Policy header), and
- any product or banner image loaded from another `https:` host without CORS or CORP (`img-src` allows `https:`).

Revisit if the site ever self-hosts the videos and serves every image itself; `credentialless` would then be the
gentler option. A test (`test_coep_is_deliberately_not_require_corp`) records the decision so a change is made on purpose.

## CSP violation reports

`POST /csp-report` (`app/csp.py`) accepts `application/csp-report` and `application/reports+json`.

- Logs one `csp_violation {...}` warning line per report. Nothing is written to the database.
- Body capped at 16 KB (413 above that), at most 10 reports per request, 30 requests per minute per IP (`RATE_LIMIT_CSP_REPORT`).
- Only known fields are kept; values lose control characters and are cut to 200 characters; URLs lose their query string,
  fragment and any `/reset/<token>`. A report cannot forge log lines or carry a secret into the logs.
- 204 when accepted, 400 for anything that is not a CSP report, 405 for GET.
- CSRF-exempt: the browser sends it by itself, without a form or token.

Read them with: `grep csp_violation logs/rr-foods.log` (one JSON object per line, in the `message` field). Reports caused by
browser extensions (`blocked: "inline"` or `chrome-extension`) are normal noise; a blocked first-party script is a bug.

## security.txt (step 5.7)

`/.well-known/security.txt` follows RFC 9116. Set `SECURITY_CONTACT` (an email you read, or an https URL). Without it the URL answers 404 on purpose.
