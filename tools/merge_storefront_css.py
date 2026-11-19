#!/usr/bin/env python3
"""ONE-OFF (already run; the sources it read are deleted, storefront.css is now edited directly). Kept as a record.
Merge: the ten storefront stylesheets (in the order the pages loaded them, so the cascade is unchanged)
-> app/static/css/storefront.css, minus the forced-light / dark-mode hacks and minus !important on colour tokens.

Run:  python tools/merge_storefront_css.py          (writes storefront.css and prints a report)
After the merge, storefront.css is the source of truth for the shop; the nine storefront-only source files are deleted.
base.css and rr-foods-design.css stay because the admin and owner panels still load them.
"""
import re
import sys
from pathlib import Path

CSS = Path(__file__).resolve().parent.parent / "app" / "static" / "css"
ORDER = ["base", "rr-foods-design", "shop", "rr-foods-overrides", "rr-storefront-layout", "rr-home-final",
         "rr-frontend-fix", "rr-bundle-deal", "rr-customer-final", "rr-ux-polish"]


def split_blocks(css: str):
    """Yield ('rule'|'at'|'text', prelude, body) at the top level of `css`. Brace/comment/string aware."""
    i, n, out = 0, len(css), []
    while i < n:
        # skip whitespace
        while i < n and css[i].isspace():
            i += 1
        if i >= n:
            break
        if css.startswith("/*", i):
            j = css.find("*/", i + 2)
            j = n if j < 0 else j + 2
            out.append(("comment", css[i:j], None))
            i = j
            continue
        start, depth, j, in_str = i, 0, i, None
        prelude_end = None
        while j < n:
            ch = css[j]
            if in_str:
                if ch == "\\":
                    j += 1
                elif ch == in_str:
                    in_str = None
            elif ch in "\"'":
                in_str = ch
            elif css.startswith("/*", j):
                k = css.find("*/", j + 2)
                j = (n if k < 0 else k + 1)
            elif ch == "{":
                if depth == 0:
                    prelude_end = j
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    break
            elif ch == ";" and depth == 0:
                break
            j += 1
        if prelude_end is None:                       # a statement like @import ...;  or @charset
            out.append(("text", css[start:j + 1].strip(), None))
            i = j + 1
            continue
        prelude = css[start:prelude_end].strip()
        body = css[prelude_end + 1:j]
        out.append(("at" if prelude.startswith("@") else "rule", prelude, body))
        i = j + 1
    return out


def split_selectors(prelude: str):
    parts, depth, cur = [], 0, ""
    for ch in prelude:
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append(cur.strip())
            cur = ""
        else:
            cur += ch
    if cur.strip():
        parts.append(cur.strip())
    return parts


NOT_DARK = re.compile(r':not\(\s*\[data-theme\s*=\s*["\']?dark["\']?\s*\]\s*\)')
ANY_THEME = re.compile(r"\[data-theme(?![-\w])")
TOKEN_IMPORTANT = re.compile(r"(--[\w-]+\s*:[^;{}]*?)\s*!\s*important", re.I)
SCHEME_IMPORTANT = re.compile(r"(color-scheme\s*:[^;{}]*?)\s*!\s*important", re.I)

ROOTISH = re.compile(r'^(:root|html|html\[data-shop\])(:not\(\s*\[data-theme\s*=\s*["\']?light["\']?\s*\]\s*\))?$|^html\[data-shop\]\[data-theme\s*=\s*["\']?dark["\']?\]$')
TOKEN_DECL = re.compile(r"(--[\w-]+)\s*:\s*([^;{}]+?)\s*(!important)?\s*(;|$)", re.I)
registry: dict[str, tuple] = {}     # token -> (important, specificity, order, value)
_order = [0]


def specificity(sel: str):
    sel = re.sub(r":not\((\[[^\]]*\])\)", r"\1", sel)
    ids = sel.count("#")
    cls = len(re.findall(r"\.[\w-]+|\[[^\]]*\]|:(?!:)[\w-]+", sel))
    el = len(re.findall(r"(?:^|[\s>+~])[a-z][\w-]*", sel))
    return (ids, cls, el)


def harvest_tokens(prelude: str, body: str) -> str:
    """Move custom-property declarations of global rules (:root / html / html[data-shop], light state only) into the registry
    and return the rule body without them. The old cascade is replayed: !important first, then specificity, then source order."""
    sels = split_selectors(prelude)
    live = []
    for sel in sels:
        if re.fullmatch(r'html\[data-shop\]\[data-theme\s*=\s*["\']?dark["\']?\]', sel):
            continue                                   # dark alias: not part of the light cascade
        if ROOTISH.match(sel):
            live.append(sel)
    if not live or len(live) != len([x for x in sels if not re.fullmatch(r'html\[data-shop\]\[data-theme\s*=\s*["\']?dark["\']?\]', x)]):
        return body
    spec = max(specificity(x) for x in live)

    def take(m):
        _order[0] += 1
        key = (1 if m.group(3) else 0, spec, _order[0])
        old = registry.get(m.group(1))
        if old is None or key > old[:3]:
            registry[m.group(1)] = (*key, m.group(2).strip())
        return ""
    return TOKEN_DECL.sub(take, body)


stats = {"dropped_rules": 0, "dropped_selectors": 0, "dropped_media": 0, "kept_theme_free": 0}
dropped_log: list[str] = []


def clean_selector_list(prelude: str):
    keep = []
    for sel in split_selectors(prelude):
        sel2 = NOT_DARK.sub("", sel)               # "not dark" is always true in a light-only sheet
        if ANY_THEME.search(sel2):                 # [data-theme=dark] and the forced-light aliases (:not([data-theme=light]))
            stats["dropped_selectors"] += 1
            dropped_log.append(sel[:140])
            continue
        keep.append(sel2)
    return keep


def process(css: str, top: bool = True) -> str:
    out = []
    for kind, prelude, body in split_blocks(css):
        if kind == "comment":
            continue
        if kind == "text":
            out.append(prelude)
        elif kind == "rule":
            if top:
                body = harvest_tokens(prelude, body)
            if re.search(r"body\.owner-panel", prelude):          # owner-panel only exists on pages that never load this file
                stats["dropped_rules"] += 1
                continue
            keep = clean_selector_list(prelude)
            if not keep or not body.strip():
                stats["dropped_rules"] += 1
                continue
            body = TOKEN_IMPORTANT.sub(r"\1", body)
            body = SCHEME_IMPORTANT.sub(r"\1", body)
            out.append(f"{', '.join(keep)} {{{body}}}")
        else:  # at-rule
            low = prelude.lower()
            if "prefers-color-scheme" in low and "dark" in low:
                stats["dropped_media"] += 1
                dropped_log.append(prelude[:140])
                continue
            if low.startswith(("@media", "@supports", "@layer", "@container")):
                inner = process(body, top=False)
                if inner.strip():
                    out.append(f"{prelude} {{\n{inner}\n}}")
            else:                                  # @font-face, @keyframes: verbatim
                body = TOKEN_IMPORTANT.sub(r"\1", body)
                out.append(f"{prelude} {{{body}}}")
    return "\n".join(out)


NEW_TOKENS = """
  /* type scale: 1.2 ratio from a 1rem base */
  --fs-sm: .833rem; --fs-md: 1rem; --fs-lg: 1.2rem; --fs-xl: 1.44rem; --fs-2xl: 1.728rem; --fs-3xl: 2.074rem;
  /* spacing: 4px steps (--sp-1 .. --sp-7 are defined in the original sheet; two more here) */
  --sp-0: 0; --sp-8: 4rem;
  /* shape and elevation */
  --radius-sm: .5rem; --radius-pill: 999px; --shadow-sm: 0 1px 2px rgb(37 42 38 / .06);
  /* status colours (backgrounds and the text that sits on them) */
  --c-success-bg: #e6f4ea; --c-success-ink: #12482b;
  --c-error-bg: #fdecef;   --c-error-ink: #7d1432;
  --c-info-bg: var(--c-soft); --c-info-ink: var(--c-ink);
  --c-warn-bg: #fff4dc;    --c-warn-ink: #5e3c00;
  --c-inverse: #15261c;    /* toast and "sold out" tag background */
  /* keyboard focus ring (one definition; every :focus-visible uses it) */
  --ring-width: 3px; --ring-offset: 2px; --ring-color: var(--c-focus);
  --ring: 0 0 0 var(--ring-width) var(--ring-color);
"""

COMPONENTS = """
/* ===== components: tokens only ===== */
html[data-shop] .btn { background: var(--c-brand); color: var(--c-on-brand); border-radius: var(--radius); min-height: var(--tap); padding-inline: var(--sp-5); font-size: var(--fs-md); }
html[data-shop] .btn:hover { background: var(--c-brand-dark); }
html[data-shop] .btn--ghost { background: transparent; color: var(--c-brand); border: 2px solid var(--c-brand); }
html[data-shop] .btn--ghost:hover { background: var(--c-soft); color: var(--c-brand-dark); }
html[data-shop] .btn--danger { background: transparent; color: var(--c-bad); border: 2px solid var(--c-bad); }
.btn--sm { min-height: var(--tap); padding-inline: var(--sp-3); font-size: var(--fs-sm); }
.input, .field input, .field textarea, .field select { width: 100%; min-height: var(--tap); padding: var(--sp-2) var(--sp-3); border: 2px solid var(--c-line); border-radius: var(--radius); background: var(--c-surface); color: var(--c-ink); font-size: max(16px, var(--fs-md)); }
.input[aria-invalid="true"], .field--error input, .field--error select, .field--error textarea { border-color: var(--c-bad); }
.card { background: var(--c-surface); border: 1px solid var(--c-line); border-radius: var(--radius-lg); padding: var(--sp-4); box-shadow: var(--shadow); }
.alert { padding: var(--sp-3) var(--sp-4); border: 1px solid var(--c-line); border-radius: var(--radius); margin-block: var(--sp-3); background: var(--c-info-bg); color: var(--c-info-ink); }
.alert--error { background: var(--c-error-bg); color: var(--c-error-ink); border-color: var(--c-error-ink); }
.alert--success { background: var(--c-success-bg); color: var(--c-success-ink); border-color: var(--c-success-ink); }
.alert--warning { background: var(--c-warn-bg); color: var(--c-warn-ink); border-color: var(--c-warn-ink); }
.badge { display: inline-flex; align-items: center; gap: var(--sp-1); padding: var(--sp-1) var(--sp-2); border-radius: var(--radius-pill); background: var(--c-soft); color: var(--c-ink); font-size: var(--fs-sm); font-weight: 700; }
.badge--ok { background: var(--c-success-bg); color: var(--c-success-ink); }
.badge--warn { background: var(--c-warn-bg); color: var(--c-warn-ink); }
.badge--bad { background: var(--c-error-bg); color: var(--c-error-ink); }
.toast { background: var(--c-inverse); color: var(--c-on-brand); border-radius: var(--radius); padding: var(--sp-3) var(--sp-4); box-shadow: var(--shadow-pop); }
.toast--error { background: var(--c-error-ink); color: var(--c-on-brand); }
.empty { display: grid; gap: var(--sp-2); justify-items: center; text-align: center; padding: var(--sp-6) var(--sp-4); }
.empty--error .empty__art { background: var(--c-error-bg); color: var(--c-error-ink); }
.skel { display: block; min-height: 1em; border-radius: var(--radius-sm); background: linear-gradient(90deg, var(--c-soft) 25%, var(--c-line) 37%, var(--c-soft) 63%); background-size: 400% 100%; animation: skel-shimmer 1.4s var(--ease) infinite; }
.skel--line { height: var(--sp-3); margin-block: var(--sp-2); }
.skel--title { height: var(--sp-5); width: 60%; }
.skel--img { aspect-ratio: 1 / 1; width: 100%; border-radius: var(--radius); }
.skel--btn { height: var(--tap); width: 8rem; border-radius: var(--radius); }
.skel-card { display: grid; gap: var(--sp-2); padding: var(--sp-3); border: 1px solid var(--c-line); border-radius: var(--radius-lg); background: var(--c-surface); }
.skel-grid { display: grid; gap: var(--sp-3); grid-template-columns: repeat(auto-fill, minmax(10rem, 1fr)); }
@keyframes skel-shimmer { 0% { background-position: 100% 50%; } 100% { background-position: 0 50%; } }
@media (prefers-reduced-motion: reduce) { .skel { animation: none; } }
/* active filter chips, In stock switch, inline forms */
.chips2--wrap { flex-wrap: wrap; overflow: visible; }
.chip--active { gap: var(--sp-2); padding-right: var(--sp-1); background: var(--c-soft); border-color: var(--c-brand); color: var(--c-brand-dark); }
.chip__x { display: inline-grid; place-items: center; min-width: var(--tap); min-height: var(--tap); margin-block: calc(var(--sp-2) * -1); border-radius: var(--radius-pill); color: var(--c-brand-dark); text-decoration: none; font-size: var(--fs-lg); line-height: 1; }
.chip__x:hover { background: var(--c-line); }
.chip-clear { display: inline-flex; align-items: center; min-height: var(--tap); padding-inline: var(--sp-2); color: var(--c-brand); font-weight: 700; }
.switch { display: inline-flex; align-items: center; gap: var(--sp-2); min-height: var(--tap); font-weight: 600; cursor: pointer; }
.switch input { position: absolute; opacity: 0; width: var(--tap); height: var(--tap); margin: 0; cursor: pointer; }
.switch__track { position: relative; width: 2.75rem; height: 1.5rem; flex: none; border-radius: var(--radius-pill); border: 2px solid var(--c-muted); background: var(--c-surface); transition: background var(--dur) var(--ease); }
.switch__track::after { content: ""; position: absolute; top: 2px; left: 2px; width: 1.1rem; height: 1.1rem; border-radius: 50%; background: var(--c-muted); transition: transform var(--dur) var(--ease), background var(--dur) var(--ease); }
.switch input:checked + .switch__track { background: var(--c-brand); border-color: var(--c-brand); }
.switch input:checked + .switch__track::after { transform: translateX(1.25rem); background: var(--c-on-brand); }
.switch input:focus-visible + .switch__track { box-shadow: var(--ring); outline: 2px solid transparent; }
.inline-form { display: inline; margin: 0; }
.ocard__actions { display: inline-flex; flex-wrap: wrap; gap: var(--sp-2); align-items: center; }
"""


def main():
    registry.clear()
    parts = []
    for name in ORDER:
        text = (CSS / f"{name}.css").read_text(encoding="utf-8")
        parts.append(f"/* ===== {name}.css ===== */\n{process(text)}")
    tokens = "\n".join(f"  {k}: {v[3]};" for k, v in sorted(registry.items()))
    head = f"/* RR FOODS storefront stylesheet (generated once by tools/merge_storefront_css.py, now edited by hand).\n   One token set below; components use tokens only. Light theme; dark mode is added in step 2.6. */\n:root {{\n  color-scheme: light;\n{tokens}\n{NEW_TOKENS}}}\n\n"
    merged = head + "\n\n".join(parts) + "\n" + COMPONENTS
    (CSS / "storefront.css").write_text(merged, encoding="utf-8")
    print(f"storefront.css: {len(merged):,} bytes; important left: {merged.count('!important')}")
    print(stats, "tokens:", len(registry))
    if "--log" in sys.argv:
        print("\n".join(dropped_log))
    if "--tokens" in sys.argv:
        for k, v in sorted(registry.items()):
            print(f"{k}: {v[3]}  (important={bool(v[0])})")


if __name__ == "__main__":
    main()
