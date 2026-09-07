from __future__ import annotations

import re
from pathlib import Path


def apply(ns=None):
    # USER15 is installed very late and historically re-injected v361_user15.js
    # into the main stock page and coin page. That script owns MutationObservers
    # and explicitly removes trade-filter controls. Keep it only on detail pages;
    # v364/coin.js are the sole owners of the two main pages.
    for rel in ("static/index.html", "static/coin.html"):
        p = Path(rel)
        if not p.exists():
            continue
        text = p.read_text(encoding="utf-8")
        text = re.sub(
            r'\s*<script\s+src=["\']/static/v361_user15\.js(?:\?[^"\']*)?["\']\s*></script>\s*',
            '\n',
            text,
            flags=re.I,
        )
        p.write_text(text, encoding="utf-8")
