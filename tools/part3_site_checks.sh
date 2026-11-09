#!/usr/bin/env bash
# Part 3: live-site checks (headers, cookies, exposure, SEO, rate limit).
# Usage: bash part3_site_checks.sh https://shop.example.com [product-slug]
# Needs only curl. Prints PASS / FAIL / WARN per check.
BASE="${1:?usage: $0 https://your-site [product-slug]}"; BASE="${BASE%/}"
SLUG="${2:-}"
pass=0; fail=0; warn=0
ok(){ echo "PASS  $1"; pass=$((pass+1)); }
bad(){ echo "FAIL  $1"; fail=$((fail+1)); }
wr(){ echo "WARN  $1"; warn=$((warn+1)); }
code(){ curl -s -o /dev/null -w '%{http_code}' --max-time 15 "$@"; }
H="$(curl -sI --max-time 15 "$BASE/")"

echo "== Transport and headers"
case "$BASE" in https://*) ok "site served over HTTPS";; *) bad "not HTTPS";; esac
HTTP_BASE="http://${BASE#https://}"
loc="$(curl -sI --max-time 15 "$HTTP_BASE/" | tr -d '\r' | awk 'tolower($1)=="location:"{print $2}')"
case "$loc" in https://*) ok "HTTP redirects to HTTPS";; *) bad "HTTP does not redirect to HTTPS";; esac
for h in strict-transport-security content-security-policy x-frame-options x-content-type-options referrer-policy permissions-policy; do
  echo "$H" | grep -qi "^$h:" && ok "header $h" || bad "missing header $h"
done
echo "$H" | grep -qi "^strict-transport-security:.*max-age=[0-9]\{7,\}" || wr "HSTS max-age should be >= 1 year (31536000)"
echo "$H" | grep -qi "^server:.*[0-9]\.[0-9]" && wr "Server header leaks a version: $(echo "$H" | grep -i '^server:')"
echo "$H" | grep -qi "^x-powered-by" && wr "X-Powered-By present"

echo "== Cookies (login page)"
C="$(curl -sI --max-time 15 "$BASE/login" | grep -i '^set-cookie')"
if [ -z "$C" ]; then wr "no cookie set on /login (cannot check flags)"; else
  echo "$C" | grep -qi "secure" && ok "cookie Secure" || bad "cookie missing Secure (set FLASK_ENV=production)"
  echo "$C" | grep -qi "httponly" && ok "cookie HttpOnly" || bad "cookie missing HttpOnly"
  echo "$C" | grep -qi "samesite" && ok "cookie SameSite" || bad "cookie missing SameSite"
fi

echo "== Exposure"
for p in /.env /.git/config /.git/HEAD /requirements.txt /app/config.py /deploy/nginx.conf /instance/ /uploads/../.env /uploads/..%2f.env /static/../.env /admin/users /owner/orders; do
  s="$(code "$BASE$p")"
  case "$s" in 200) bad "$p returns 200";; *) ok "$p -> $s";; esac
done
s="$(code "$BASE/this-page-does-not-exist-xyz")"; [ "$s" = 404 ] && ok "unknown URL gives real 404" || bad "unknown URL gives $s (soft-404 hurts SEO)"
curl -s --max-time 15 "$BASE/this-page-does-not-exist-xyz" | grep -qiE "traceback|werkzeug|debugger" && bad "debug/traceback visible on error page" || ok "no debug output on error page"

echo "== Rate limit on login (14 fast bad attempts)"
JAR="$(mktemp)"; TOK="$(curl -s -c "$JAR" --max-time 15 "$BASE/login" | grep -o 'name="csrf_token" value="[^"]*"' | head -1 | sed 's/.*value="//; s/"$//')"
hit=0; for i in $(seq 1 14); do s="$(code -b "$JAR" -c "$JAR" -X POST --data-urlencode "email=x@x.com" --data-urlencode "password=bad-pass-$i" --data-urlencode "csrf_token=$TOK" "$BASE/login")"; { [ "$s" = 429 ] || [ "$s" = 503 ]; } && hit=1; done
rm -f "$JAR"
[ $hit = 1 ] && ok "login is rate limited (429/503 seen)" || bad "no rate limit seen on /login"

echo "== SEO"
R="$(curl -s --max-time 15 "$BASE/robots.txt")"
echo "$R" | grep -qi "^sitemap:" && ok "robots.txt lists sitemap" || bad "robots.txt has no Sitemap line"
for d in /admin /owner /account /cart /checkout; do echo "$R" | grep -q "Disallow: $d" && ok "robots blocks $d" || bad "robots does not block $d"; done
S="$(curl -s --max-time 20 "$BASE/sitemap.xml")"
n="$(echo "$S" | grep -o "<loc>" | wc -l)"; [ "$n" -gt 0 ] && ok "sitemap has $n URLs" || bad "sitemap empty/invalid"
echo "$S" | grep -q "<lastmod>" || wr "sitemap has no <lastmod>"
echo "$S" | grep -q "http://" && wr "sitemap contains http:// URLs (check SITE_URL / TRUST_PROXY)"
HOME_HTML="$(curl -s --max-time 15 "$BASE/")"
for t in '<title>' 'name="description"' 'rel="canonical"' 'property="og:title"' 'property="og:image"' 'twitter:card' 'application/ld+json'; do
  echo "$HOME_HTML" | grep -q "$t" && ok "home has $t" || wr "home missing $t"
done
[ -z "$SLUG" ] && SLUG="$(echo "$S" | grep -o "<loc>[^<]*/product/[^<]*" | head -1 | sed 's/<loc>//' | awk -F/ '{print $NF}')"
if [ -n "$SLUG" ]; then
  P="$(curl -s --max-time 15 "$BASE/product/$SLUG")"
  for t in '"@type": "Product"' '"availability"' '"priceCurrency"' 'rel="canonical"' 'og:image' '<h1'; do
    echo "$P" | grep -q "$t" && ok "product page has $t" || wr "product page missing $t (check slug/route)"
  done
fi
for p in /cart /login /account/orders; do
  curl -sL --max-time 15 "$BASE$p" | grep -qi 'name="robots" content="noindex' && ok "$p is noindex" || wr "$p not noindex (or redirected)"
done
echo; echo "SUMMARY: $pass pass, $fail fail, $warn warn"; [ $fail -eq 0 ]
