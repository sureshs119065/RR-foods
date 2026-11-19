#!/usr/bin/env python3
"""WCAG 2.2 AA contrast gate for the storefront tokens.

Reads the *effective* token values from app/static/css/storefront.css (last declaration in the :root / html blocks wins),
checks every text/background pair listed in PAIRS (4.5:1 normal text, 3:1 large text and UI borders) and exits 1 on any
failure. Run: python tools/check_contrast.py   (also run by tests/test_step3_a11y.py, so CI fails the build).
"""
import re
import sys
from pathlib import Path

CSS = Path(__file__).resolve().parent.parent / "app" / "static" / "css" / "storefront.css"
WHITE, PAPER = "#FFFFFF", "#F7F6F2"          # the two page surfaces named in the brief

# surfaces text can sit on (literal hex or token)
SURFACES = [WHITE, PAPER, "--c-bg", "--c-soft", "--c-surface", "--card"]
# text tokens that must pass 4.5:1 on every surface above
TEXT = ["--c-muted", "--c-ink", "--c-brand", "--c-brand-dark", "--c-warn", "--c-bad", "--c-good", "--c-accent",
        "--c-danger", "--c-focus", "--green", "--green-dark", "--muted", "--ink", "--cx-ink", "--cx-green",
        "--cx-green-dark", "--cx-muted", "--rr-ink", "--rr-muted", "--rr-green", "--rr-green-dark", "--red"]
# (foreground, background, minimum ratio, why)
PAIRS = [
    ("--c-on-brand", "--c-brand", 4.5, "button text"),
    ("--c-on-brand", "--c-brand-dark", 4.5, "button text"),
    ("--c-on-brand", "--c-accent", 4.5, "accent button"),
    ("--c-on-brand", "--c-inverse", 4.5, "toast / sold-out tag"),
    ("--c-success-ink", "--c-success-bg", 4.5, "success alert"),
    ("--c-error-ink", "--c-error-bg", 4.5, "error alert"),
    ("--c-warn-ink", "--c-warn-bg", 4.5, "warning alert"),
    ("--c-warn", "--c-warn-bg", 4.5, "warning text on its tint"),
    ("--c-muted", "--c-soft", 4.5, "muted text on soft panel"),
    ("--c-ink", "--c-warn-bg", 4.5, "body text on warning tint"),
    # UI component boundaries and focus ring (3:1)
    ("--ui-border", WHITE, 3.0, "input / control border"),
    ("--ui-border", PAPER, 3.0, "input / control border"),
    ("--ring-color", WHITE, 3.0, "focus ring"),
    ("--ring-color", PAPER, 3.0, "focus ring"),
]


def effective_tokens(css):
    vals = {}
    for m in re.finditer(r"(?m)^(:root|:root, html, html\[data-shop\]|html\[data-shop\])\s*\{(.*?)\n?\}", css, re.S):
        for d in re.finditer(r"(--[\w-]+)\s*:\s*([^;]+);", m.group(2)):
            vals[d.group(1)] = d.group(2).strip()
    return vals


def resolve(tok, vals, depth=0):
    if tok.startswith("#"):
        return tok
    v = vals.get(tok)
    if v is None:
        raise KeyError(f"token {tok} is not defined in storefront.css")
    m = re.fullmatch(r"var\((--[\w-]+)\)", v)
    if m and depth < 8:
        return resolve(m.group(1), vals, depth + 1)
    if not re.fullmatch(r"#[0-9a-fA-F]{3,8}", v):
        raise ValueError(f"{tok} = {v!r} is not a plain hex colour")
    return v


def lum(hexv):
    h = hexv.lstrip("#")
    if len(h) in (3, 4):
        h = "".join(c * 2 for c in h[:3])
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    f = lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)


def ratio(a, b):
    la, lb = sorted((lum(a), lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def run(css_text=None):
    """Return (rows, failures); each row is (fg, bg, ratio, minimum, why)."""
    vals = effective_tokens(css_text if css_text is not None else CSS.read_text(encoding="utf-8"))
    rows = [(t, s, 4.5, "text") for t in TEXT for s in SURFACES] + [(f, b, m, w) for f, b, m, w in PAIRS]
    out, bad = [], []
    for fg, bg, minimum, why in rows:
        r = ratio(resolve(fg, vals), resolve(bg, vals))
        out.append((fg, bg, r, minimum, why))
        if r < minimum:
            bad.append((fg, bg, r, minimum, why))
    return out, bad


if __name__ == "__main__":
    rows, bad = run()
    print(f"{len(rows)} pairs checked, {len(bad)} below threshold")
    for fg, bg, r, m, why in bad:
        print(f"FAIL {fg} on {bg}: {r:.2f}:1 (needs {m}:1) [{why}]")
    sys.exit(1 if bad else 0)
