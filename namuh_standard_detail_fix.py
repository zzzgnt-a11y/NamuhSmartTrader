from __future__ import annotations

from collections import deque
from copy import copy
from datetime import datetime
from pathlib import Path

_INSTALLED = False


def _f(v, default=0.0):
    try:
        return float(v)
    except Exception:
        return float(default)


def _patch_stock_score_ui(root: Path) -> None:
    p = root / "static" / "stock.js"
    if not p.exists():
        return
    text = p.read_text(encoding="utf-8")
    old = "${v366Metric('엘리어트',raw['엘리어트'],10)}${v366Metric('75점→45점 환산',standard,45)}\n   </div></section>"
    new = "${v366Metric('엘리어트',raw['엘리어트'],10)}\n   </div><div class=\"v366-gate wait\">기술지표 7개 원점수 75점 → 스탠다드 45점 환산</div></section>"
    if old in text:
        text = text.replace(old, new, 1)
    else:
        # Idempotent fallback in case whitespace was changed by another patch.
        text = text.replace("${v366Metric('75점→45점 환산',standard,45)}", "", 1)
    p.write_text(text, encoding="utf-8")


def _detail_quote_with_history(core, market: str, code: str, q):
    """Build a read-only calculation copy for stock-detail display.

    Live trading Quote state is not mutated. The detail page can be opened before
    q.prices has accumulated 20 live ticks, while the chart already has enough
    official history. Reusing those bars prevents the STANDARD block from falsely
    displaying all zeros.
    """
    temp = copy(q)
    temp.prices = deque(maxlen=480)

    bars = []
    for tf in ("1m", "3m", "5m", "20m", "1d"):
        try:
            rows = [x for x in list(core.feed.bars(market, code, tf) or []) if isinstance(x, dict) and _f(x.get("close")) > 0]
        except Exception:
            rows = []
        if len(rows) >= 20:
            bars = rows
            break
        if len(rows) > len(bars):
            bars = rows

    for b in bars[-120:]:
        temp.prices.append(_f(b.get("close")))

    return temp


def _wrap_stock_detail(core) -> None:
    if getattr(core, "_NAMUH_STANDARD_DETAIL_FIX", False):
        return
    old = getattr(core, "stock_detail", None)
    if not callable(old):
        return
    core._NAMUH_STANDARD_DETAIL_FIX = True

    def stock_detail(market: str, code: str, timeframe="1d"):
        d = old(market, code, timeframe)
        try:
            m = str(market or "").upper()
            c = str(code or "").upper()
            if m not in ("KR", "US"):
                return d
            q = core.feed.quotes_for(m).get(c)
            if q is None:
                q = core.feed.q(m, c)
            temp = _detail_quote_with_history(core, m, c, q)
            if len(list(getattr(temp, "prices", []) or [])) < 20:
                return d

            sectors = []
            stockmap = {}
            try:
                with core.cache_lock:
                    sectors = list((core.CACHE.get(m) or {}).get("sectors") or [])
                    stockmap = dict((core.CACHE.get(m) or {}).get("stock_strength") or {})
            except Exception:
                pass
            secmap = {str(x.get("sector") or ""): _f(x.get("score")) for x in sectors if isinstance(x, dict)}
            leadermap = {str(x.get("sector") or ""): str(x.get("leader") or "") for x in sectors if isinstance(x, dict)}
            ranked = sorted([x for x in sectors if isinstance(x, dict)], key=lambda x: _f(x.get("score")), reverse=True)
            rankmap = {str(x.get("sector") or ""): i + 1 for i, x in enumerate(ranked) if str(x.get("sector") or "")}

            cand = core.candidate(temp, m, False, secmap, stockmap, leadermap, rankmap, datetime.now(core.KST))
            if not isinstance(cand, dict):
                return d
            c1 = dict(cand.get("condition1") or {})
            if not c1:
                return d

            out = dict(d)
            sc = dict(out.get("strategy_conditions") or {})
            sc["condition1"] = c1
            # Keep condition2/3 from the previous detail wrapper; this patch only
            # corrects the Condition1 STANDARD display/data source.
            out["strategy_conditions"] = sc
            out["condition1_score"] = _f(c1.get("score"))
            return out
        except Exception as exc:
            try:
                out = dict(d)
                out["standard_detail_fix_error"] = str(exc)[:160]
                return out
            except Exception:
                return d

    core.stock_detail = stock_detail


def apply(ns=None):
    global _INSTALLED
    if _INSTALLED:
        return True
    root = Path(__file__).resolve().parent
    try:
        _patch_stock_score_ui(root)
    except Exception as exc:
        print("NAMUH STANDARD UI FIX ERROR:", str(exc)[:180], flush=True)
    try:
        core = ns.get("core") if isinstance(ns, dict) else None
        if core is not None:
            _wrap_stock_detail(core)
    except Exception as exc:
        print("NAMUH STANDARD DETAIL FIX ERROR:", str(exc)[:180], flush=True)
    # Absolute last score guard: classify every zero as genuine recipe zero or
    # missing-data zero, backfill exact 15-session same-time volume, and label UI waits.
    try:
        import namuh_zero_score_audit_patch
        namuh_zero_score_audit_patch.apply(ns)
    except Exception as exc:
        print("NAMUH ZERO SCORE AUDIT LOAD ERROR:", str(exc)[:180], flush=True)
    _INSTALLED = True
    print("NAMUH standard detail fix active: 7 indicators only; history-backed detail score", flush=True)
    return True
