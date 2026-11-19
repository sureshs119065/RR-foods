#!/usr/bin/env bash
# Step 6: collect every number the verification report needs, in one run. Needs PostgreSQL, Chromium, node, network.
#   TEST_DATABASE_URL=... SECRET_KEY=... FLASK_ENV=development bash tools/verify_all.sh
set -euo pipefail
OUT=verification-out; mkdir -p "$OUT"
rm -rf app/static/dist
echo "== pytest ==";            pytest -q -p no:cacheprovider | tee "$OUT/pytest.txt" | tail -3
echo "== contrast ==";          python tools/check_contrast.py | tee "$OUT/contrast.txt" | tail -1
python tools/build_assets.py | tee "$OUT/build.txt"
echo "== bundle sizes (gzip) =="
for f in app/static/dist/*.css app/static/dist/*.js; do printf "%s %s\n" "$f" "$(gzip -9c "$f" | wc -c)"; done | tee "$OUT/bundles.txt"
FLASK_ENV=production gunicorn -b 127.0.0.1:5055 wsgi:app --daemon --pid "$OUT/g.pid"; sleep 3
echo "== perf budget ==";       python tools/perf_audit.py http://127.0.0.1:5055 | tee "$OUT/perf_audit.txt" | tail -3
echo "== axe ==";               python tools/axe_audit.py http://127.0.0.1:5055 --login "${AXE_LOGIN:?set AXE_LOGIN=email:password}" --json "$OUT/axe.json" | tail -3
echo "== lighthouse (mobile, 3 runs) =="; npx @lhci/cli autorun --config=lighthouserc.json | tee "$OUT/lighthouse.txt" | tail -20
kill "$(cat "$OUT/g.pid")"
echo "Done. Copy the numbers from $OUT/ into docs/VERIFICATION-REPORT.md"
