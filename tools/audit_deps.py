#!/usr/bin/env python3
"""Dependency audit gate (step 5.7). Runs pip-audit and FAILS on any known vulnerability.

pip-audit's report has no severity field, so "fail on high severity" is done the strict way: every advisory fails the
build unless it is listed in security/audit-ignore.txt with a reason and an expiry date (max 90 days ahead).

    python tools/audit_deps.py                       # audits requirements.txt (needs `pip install pip-audit`, network)
    python tools/audit_deps.py -r requirements.lock  # audit the exact pins
    python tools/audit_deps.py --from-json report.json   # evaluate a saved `pip-audit -f json` report (offline / tests)
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAX_IGNORE_DAYS = 90


def parse_ignore(text: str, today: date) -> tuple[dict[str, date], list[str]]:
    """Returns ({advisory id: expiry}, [problems with the file itself])."""
    allowed: dict[str, date] = {}
    problems: list[str] = []
    for n, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split("|", 2)]
        if len(parts) != 3 or not all(parts):
            problems.append(f"audit-ignore line {n}: need '<id> | <YYYY-MM-DD> | <reason>'")
            continue
        try:
            expiry = date.fromisoformat(parts[1])
        except ValueError:
            problems.append(f"audit-ignore line {n}: bad date {parts[1]!r}")
            continue
        if expiry > today + timedelta(days=MAX_IGNORE_DAYS):
            problems.append(f"audit-ignore line {n}: expiry {expiry} is more than {MAX_IGNORE_DAYS} days away")
            continue
        allowed[parts[0].upper()] = expiry
    return allowed, problems


def evaluate(report: dict, allowed: dict[str, date], today: date) -> tuple[list[str], list[str]]:
    """Returns (failures, accepted). A vulnerability passes only if its id or an alias is allowed and not expired."""
    failures: list[str] = []
    accepted: list[str] = []
    for dep in report.get("dependencies", []):
        for vuln in dep.get("vulns") or []:
            ids = [str(vuln.get("id", ""))] + [str(a) for a in vuln.get("aliases") or []]
            hit = next((i for i in ids if i.upper() in allowed), None)
            label = f"{dep.get('name')}=={dep.get('version')}: {ids[0]}"
            fix = ", ".join(vuln.get("fix_versions") or []) or "no fix released"
            if hit and allowed[hit.upper()] >= today:
                accepted.append(f"{label} (accepted until {allowed[hit.upper()]})")
            elif hit:
                failures.append(f"{label} - the exception for {hit} expired on {allowed[hit.upper()]}; fix: {fix}")
            else:
                failures.append(f"{label} - fix: {fix}")
    return failures, accepted


def run_pip_audit(requirements: str) -> dict:
    cmd = [sys.executable, "-m", "pip_audit", "-r", requirements, "-f", "json", "--progress-spinner", "off"]
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT)
    if proc.returncode not in (0, 1):   # 1 = vulnerabilities found (we read them); anything else = the tool itself broke
        sys.stderr.write(proc.stderr)
        raise SystemExit(f"pip-audit failed to run (exit {proc.returncode}); the audit is not a pass")
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        sys.stderr.write(proc.stderr)
        raise SystemExit("pip-audit printed no JSON; the audit is not a pass")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-r", "--requirements", default="requirements.txt")
    ap.add_argument("--ignore-file", default=str(ROOT / "security" / "audit-ignore.txt"))
    ap.add_argument("--from-json", help="evaluate a saved pip-audit JSON report instead of running pip-audit")
    ap.add_argument("--today", help="override today's date (YYYY-MM-DD), for tests")
    args = ap.parse_args(argv)

    today = date.fromisoformat(args.today) if args.today else date.today()
    ignore_path = Path(args.ignore_file)
    allowed, problems = parse_ignore(ignore_path.read_text() if ignore_path.exists() else "", today)
    report = json.loads(Path(args.from_json).read_text()) if args.from_json else run_pip_audit(args.requirements)
    failures, accepted = evaluate(report, allowed, today)

    deps = report.get("dependencies", [])
    print(f"audited {len(deps)} packages")
    for a in accepted:
        print("ACCEPTED", a)
    for p in problems:
        print("IGNORE-FILE", p)
    for f in failures:
        print("VULNERABLE", f)
    if failures or problems:
        print("FAIL: fix the packages above (bump the version) or add a dated, justified line to security/audit-ignore.txt")
        return 1
    print("OK: no known vulnerabilities")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
