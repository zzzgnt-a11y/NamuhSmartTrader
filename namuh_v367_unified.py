from __future__ import annotations

import hashlib
import inspect
import json
import os
import re
import threading
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

KST = timezone(timedelta(hours=9))
ROOT = Path(__file__).resolve().parent
_INSTALLED = False
_CACHE_LOCK = threading.RLock()
_ROUTE_CACHE: dict[tuple, tuple[float, Any]] = {}
_LEDGER_LOCK = threading.RLock()
_LEDGER_STATE: dict[str, Any] | None = None
_STATS = {
    "route_cache_hit": 0,
    "route_cache_miss": 0,
    "route_cache_stale": 0,
    "ledger_sync": 0,
    "pipeline_rows": 0,
}


def _f(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except Exception:
        return float(default)


def _market(v: Any) -> str:
    m = str(v or "").upper().strip()
    if m == "COIN":
        return "COIN"
    if m == "US":
        return "US"
    return "KR"


def _trade_market(t: dict) -> str:
    m = str(t.get("market") or t.get("market_type") or "").upper().strip()
    if m in ("KR", "US", "COIN"):
        return m
    code = str(t.get("code") or t.get("symbol") or "").upper().strip()
    if code.startswith("KRW-") or str(t.get("currency") or "").upper() == "KRW" and not code.isdigit():
        return "COIN"
    return "US" if code and not code.isdigit() else "KR"


def _trade_day(t: dict) -> str:
    # Prefer an execution timestamp when one exists so the accounting boundary is
    # unambiguously 00:00 Asia/Seoul. Existing date fields are already KST in the
    # current engine and remain the compatibility fallback.
    for k in ("timestamp", "ts", "executed_at", "filled_at", "time_ts"):
        v = t.get(k)
        if v in (None, ""):
            continue
        try:
            if isinstance(v, (int, float)) or str(v).replace(".", "", 1).isdigit():
                x = float(v)
                if x > 1e12:
                    x /= 1000.0
                return datetime.fromtimestamp(x, KST).strftime("%Y-%m-%d")
            s = str(v).strip().replace("Z", "+00:00")
            dt = datetime.fromisoformat(s)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=KST)
            return dt.astimezone(KST).strftime("%Y-%m-%d")
        except Exception:
            pass
    s = str(t.get("date") or "").strip()
    d = re.sub(r"[^0-9]", "", s)
    if len(d) >= 8:
        return f"{d[:4]}-{d[4:6]}-{d[6:8]}"
    return datetime.now(KST).strftime("%Y-%m-%d")


def _trade_id(t: dict, market: str) -> str:
    keep = {
        "market": market,
        "date": _trade_day(t),
        "time": t.get("time"),
        "timestamp": t.get("timestamp") or t.get("ts") or t.get("executed_at"),
        "code": t.get("code") or t.get("symbol"),
        "side": t.get("side"),
        "qty": t.get("qty"),
        "price": t.get("price"),
        "gross_krw": t.get("gross_krw"),
        "pnl": t.get("pnl"),
        "pnl_pct": t.get("pnl_pct"),
        "strategy": t.get("strategy"),
        "reason": t.get("reason"),
    }
    raw = json.dumps(keep, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha1(raw).hexdigest()


def _blank_ledger() -> dict:
    return {"version": 1, "seen": [], "days": {"KR": {}, "US": {}, "COIN": {}}, "updated_at": 0.0}


def _load_ledger(core) -> dict:
    global _LEDGER_STATE
    with _LEDGER_LOCK:
        if isinstance(_LEDGER_STATE, dict):
            return _LEDGER_STATE
        try:
            saved = core.store.load_json("v367_realized_ledger", {}) or {}
        except Exception:
            saved = {}
        state = _blank_ledger()
        if isinstance(saved, dict):
            state["seen"] = list(saved.get("seen") or [])[-20000:]
            old_days = saved.get("days") if isinstance(saved.get("days"), dict) else {}
            for m in ("KR", "US", "COIN"):
                state["days"][m] = dict(old_days.get(m) or {})
            state["updated_at"] = _f(saved.get("updated_at"))
        _LEDGER_STATE = state
        return state


def _current_trades(core, market: str) -> list[dict]:
    try:
        raw = list(core.coin_paper.trades or []) if market == "COIN" else list(core.paper.trades or [])
    except Exception:
        raw = []
    return [dict(x) for x in raw if isinstance(x, dict) and _trade_market(x) == market]


def _sync_ledger(core) -> dict:
    state = _load_ledger(core)
    changed = False
    with _LEDGER_LOCK:
        seen = set(state.get("seen") or [])
        seen_order = list(state.get("seen") or [])
        for market in ("KR", "US", "COIN"):
            days = state["days"].setdefault(market, {})
            for t in _current_trades(core, market):
                if str(t.get("side") or "").upper() != "SELL":
                    continue
                tid = _trade_id(t, market)
                if tid in seen:
                    continue
                seen.add(tid)
                seen_order.append(tid)
                day = _trade_day(t)
                row = days.setdefault(day, {"realized_pnl": 0.0, "sell_count": 0, "sells": []})
                pnl = _f(t.get("pnl"))
                row["realized_pnl"] = _f(row.get("realized_pnl")) + pnl
                row["sell_count"] = int(row.get("sell_count") or 0) + 1
                item = {
                    "id": tid,
                    "date": day,
                    "time": str(t.get("time") or ""),
                    "market": market,
                    "code": str(t.get("code") or t.get("symbol") or ""),
                    "name": str(t.get("name") or t.get("code") or t.get("symbol") or ""),
                    "side": "SELL",
                    "qty": t.get("qty"),
                    "price": t.get("price"),
                    "gross_krw": t.get("gross_krw"),
                    "pnl": pnl,
                    "pnl_pct": _f(t.get("pnl_pct")),
                    "strategy": str(t.get("strategy") or ""),
                    "reason": str(t.get("reason") or ""),
                }
                row.setdefault("sells", []).append(item)
                if len(row["sells"]) > 250:
                    row["sells"] = row["sells"][-250:]
                changed = True
        state["seen"] = seen_order[-20000:]
        if changed:
            state["updated_at"] = time.time()
            try:
                core.store.save_json("v367_realized_ledger", state)
            except Exception:
                pass
            _STATS["ledger_sync"] += 1
        return state


def _ledger_payload(core, market: str) -> dict:
    market = _market(market)
    state = _sync_ledger(core)
    stored = dict((state.get("days") or {}).get(market) or {})
    live = _current_trades(core, market)
    live_by_day: dict[str, list[dict]] = defaultdict(list)
    for t in live:
        live_by_day[_trade_day(t)].append(t)
    dates = sorted(set(stored) | set(live_by_day))
    out_days = []
    cumulative = 0.0
    for day in dates:
        base = dict(stored.get(day) or {})
        realized = _f(base.get("realized_pnl"))
        cumulative += realized
        sells = [dict(x) for x in list(base.get("sells") or []) if isinstance(x, dict)]
        symbols: dict[str, dict] = {}
        for t in sells:
            code = str(t.get("code") or "-")
            x = symbols.setdefault(code, {"code": code, "name": str(t.get("name") or code), "realized_pnl": 0.0, "sell_count": 0})
            x["realized_pnl"] += _f(t.get("pnl"))
            x["sell_count"] += 1
        items = [dict(t) for t in live_by_day.get(day, [])]
        out_days.append({
            "date": day,
            "realized_pnl": round(realized),
            "cumulative_pnl": round(cumulative),
            "sell_count": int(base.get("sell_count") or len(sells)),
            "trade_count": len(items) if items else len(sells),
            "symbols": sorted(symbols.values(), key=lambda x: abs(_f(x.get("realized_pnl"))), reverse=True),
            "sells": sells,
            "items": items,
        })
    return {
        "ok": True,
        "market": market,
        "timezone": "Asia/Seoul",
        "day_boundary": "00:00 KST",
        "pnl_mode": "REALIZED_SELL_ONLY",
        "days": out_days,
        "day_map": {x["date"]: x for x in out_days},
        "total_realized_pnl": round(cumulative),
        "updated_at": _f(state.get("updated_at")),
    }


def _numeric_components(row: dict) -> dict[str, float]:
    src = row.get("score_breakdown") or row.get("breakdown") or row.get("components") or {}
    out: dict[str, float] = {}
    if isinstance(src, dict):
        for k, v in src.items():
            if isinstance(v, bool):
                continue
            try:
                n = float(v)
            except Exception:
                continue
            if abs(n) < 10000:
                out[str(k)] = round(n, 3)
    return out


def _threshold(row: dict, market: str, core=None) -> float:
    for obj in (row, row.get("condition1") if isinstance(row.get("condition1"), dict) else {}):
        if isinstance(obj, dict):
            for k in ("entry_threshold", "threshold", "total_threshold_value"):
                if obj.get(k) not in (None, ""):
                    return _f(obj.get(k), 70.0)
    if market == "COIN" and core is not None:
        try:
            return _f(core._coin_settings_snapshot().get("entry_score"), 66.0)
        except Exception:
            return 66.0
    return 70.0


def _enrich_pipeline(row: dict, market: str, core=None) -> dict:
    if not isinstance(row, dict):
        return row
    comps = _numeric_components(row)
    total = round(sum(comps.values()), 3)
    final = _f(row.get("score"))
    adjustment = round(final - total, 3)
    threshold = _threshold(row, market, core)
    row["score_pipeline"] = {
        "market": market,
        "components": comps,
        "component_total": total,
        "normalization_adjustment": adjustment,
        "final_score": round(final, 2),
        "entry_threshold": threshold,
        "entry_ready": bool(final >= threshold),
        "formula": "component sum + normalization/gate adjustment = final score",
        "decision_unchanged": True,
    }
    _STATS["pipeline_rows"] += 1
    return row


def _find_candidate(core, market: str, code: str) -> dict | None:
    market = _market(market)
    code = str(code or "").upper().strip()
    if market == "COIN":
        try:
            for x in list(core.coin_feed.candidates(80) or []):
                if str(x.get("code") or x.get("symbol") or "").upper() == code:
                    return _enrich_pipeline(dict(x), market, core)
        except Exception:
            return None
        return None
    try:
        with core.cache_lock:
            rows = list((core.CACHE.get(market) or {}).get("scalp") or [])
        for x in rows:
            if str(x.get("code") or "").upper() == code:
                return _enrich_pipeline(dict(x), market, core)
    except Exception:
        pass
    try:
        q = core.feed.quotes_for(market).get(code)
        if q is None:
            return None
        with core.cache_lock:
            sectors = list((core.CACHE.get(market) or {}).get("sectors") or [])
            stockmap = dict((core.CACHE.get(market) or {}).get("stock_strength") or {})
        secmap = {str(x.get("sector") or ""): _f(x.get("score")) for x in sectors}
        leaders = {str(x.get("sector") or ""): x.get("leader_code") for x in sectors}
        ranks = {str(x.get("sector") or ""): i + 1 for i, x in enumerate(sectors)}
        row = core.candidate(q, market, False, secmap, stockmap, leaders, ranks)
        return _enrich_pipeline(dict(row), market, core) if isinstance(row, dict) else None
    except Exception:
        return None


def _find_route(app, path: str):
    for r in list(getattr(app, "routes", []) or []):
        if getattr(r, "path", None) == path:
            return getattr(r, "endpoint", None)
    return None


def _call_endpoint(fn, **kwargs):
    if not callable(fn):
        raise RuntimeError("upstream endpoint unavailable")
    sig = inspect.signature(fn)
    use = {k: v for k, v in kwargs.items() if k in sig.parameters}
    return fn(**use)


def _cached_call(key: tuple, ttl: float, stale_ttl: float, fn):
    now = time.monotonic()
    old = None
    with _CACHE_LOCK:
        old = _ROUTE_CACHE.get(key)
        if old and now - old[0] <= ttl:
            _STATS["route_cache_hit"] += 1
            return old[1]
    _STATS["route_cache_miss"] += 1
    try:
        value = fn()
        with _CACHE_LOCK:
            _ROUTE_CACHE[key] = (now, value)
            if len(_ROUTE_CACHE) > 600:
                for k, _ in sorted(_ROUTE_CACHE.items(), key=lambda kv: kv[1][0])[:150]:
                    _ROUTE_CACHE.pop(k, None)
        return value
    except Exception:
        if old and now - old[0] <= stale_ttl:
            _STATS["route_cache_stale"] += 1
            return old[1]
        raise


def _inject_js(asset: str):
    ver = (os.getenv("RENDER_GIT_COMMIT") or os.getenv("GY_BUILD_ID") or str(int(time.time())))[:12]
    for rel in ("static/index.html", "static/stock.html", "static/index-detail.html", "static/coin.html", "static/coin-detail.html"):
        p = ROOT / rel
        try:
            text = p.read_text(encoding="utf-8")
            text = re.sub(r'\s*<script\s+src=["\']/static/v367_unified_runtime\.js(?:\?[^"\']*)?["\']\s*></script>\s*', '\n', text, flags=re.I)
            tag = f'  <script src="/static/{asset}?v={ver}"></script>'
            text = text.replace("</body>", f"{tag}\n</body>")
            p.write_text(text, encoding="utf-8")
        except Exception:
            pass


def _rewrite_graph_urls():
    changes = (
        ("static/stock.js", "/api/v344/stock/", "/api/v367/stock/"),
        ("static/coin-detail.js", "/api/coin/chart/", "/api/v367/coin/chart/"),
        ("static/index.js", "/api/index/", "/api/v367/index/"),
    )
    for rel, old, new in changes:
        p = ROOT / rel
        try:
            text = p.read_text(encoding="utf-8")
            if old in text:
                p.write_text(text.replace(old, new), encoding="utf-8")
        except Exception:
            pass


def apply(ns):
    global _INSTALLED
    if _INSTALLED:
        return True
    core = ns.get("core") if isinstance(ns, dict) else None
    if core is None:
        return False
    _INSTALLED = True

    # Preserve every existing UI position/design. Only behavior, caching and data
    # payloads are changed by this layer.
    try:
        from starlette.middleware.gzip import GZipMiddleware
        if not any(getattr(x, "cls", None) is GZipMiddleware for x in core.app.user_middleware):
            core.app.add_middleware(GZipMiddleware, minimum_size=900, compresslevel=5)
    except Exception:
        pass

    try:
        @core.app.middleware("http")
        async def _v367_cache_headers(request, call_next):
            response = await call_next(request)
            path = str(request.url.path)
            if path.startswith("/static/"):
                response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
            elif path.startswith("/api/"):
                response.headers.setdefault("Cache-Control", "no-store")
            response.headers["X-Namuh-Runtime"] = "v367"
            return response
    except Exception:
        pass

    # Enrich the final stock cache without changing any score or trading decision.
    old_rebuild = core.rebuild_cache
    if not getattr(old_rebuild, "_namuh_v367_pipeline", False):
        def rebuild_cache(market, now=None):
            scalp, smart = old_rebuild(market, now)
            m = _market(market)
            for x in list(scalp or []):
                _enrich_pipeline(x, m, core)
            for x in list(smart or []):
                _enrich_pipeline(x, m, core)
            return scalp, smart
        rebuild_cache._namuh_v367_pipeline = True
        rebuild_cache._old = old_rebuild
        core.rebuild_cache = rebuild_cache

    try:
        with core.cache_lock:
            for m in ("KR", "US"):
                for x in list((core.CACHE.get(m) or {}).get("scalp") or []):
                    _enrich_pipeline(x, m, core)
                for x in list((core.CACHE.get(m) or {}).get("smart") or []):
                    _enrich_pipeline(x, m, core)
    except Exception:
        pass

    try:
        old_coin_candidates = core.coin_feed.candidates
        if not getattr(old_coin_candidates, "_namuh_v367_pipeline", False):
            def coin_candidates(*args, **kwargs):
                rows = old_coin_candidates(*args, **kwargs)
                for x in list(rows or []):
                    _enrich_pipeline(x, "COIN", core)
                return rows
            coin_candidates._namuh_v367_pipeline = True
            coin_candidates._old = old_coin_candidates
            core.coin_feed.candidates = coin_candidates
    except Exception:
        pass

    stock_ep = _find_route(core.app, "/api/v344/stock/{market}/{code}")
    coin_chart_ep = _find_route(core.app, "/api/coin/chart/{symbol}")
    index_ep = _find_route(core.app, "/api/index/{market}/{key}")

    @core.app.get("/api/v367/ledger")
    def v367_ledger(market: str = "KR"):
        return _ledger_payload(core, market)

    @core.app.get("/api/v367/score-pipeline")
    def v367_score_pipeline(market: str = "KR", code: str = ""):
        row = _find_candidate(core, market, code)
        if row is None:
            return {"ok": False, "market": _market(market), "code": str(code).upper(), "error": "score row not ready"}
        return {"ok": True, "market": _market(market), "code": str(code).upper(), "score": row.get("score"), "pipeline": row.get("score_pipeline"), "breakdown": row.get("score_breakdown") or row.get("breakdown") or {}, "condition": row.get("condition_display") or ""}

    @core.app.get("/api/v367/runtime")
    def v367_runtime():
        out = {"ok": True, "version": "v367", "stats": dict(_STATS), "markets": {}}
        for m in ("KR", "US"):
            try:
                with core.cache_lock:
                    c = dict(core.CACHE.get(m) or {})
                scalp = list(c.get("scalp") or [])
                sectors = list(c.get("sectors") or [])
                out["markets"][m] = {
                    "cache_updated_at": _f(c.get("updated_at")),
                    "scalp_count": len(scalp),
                    "top_scalp": scalp[0] if scalp else None,
                    "sector_count": len(sectors),
                    "leading_sector": sectors[0] if sectors else None,
                }
            except Exception as exc:
                out["markets"][m] = {"error": str(exc)[:160]}
        try:
            coins = list(core.coin_feed.candidates(30) or [])
            out["markets"]["COIN"] = {"candidate_count": len(coins), "top_scalp": coins[0] if coins else None}
        except Exception as exc:
            out["markets"]["COIN"] = {"error": str(exc)[:160]}
        return out

    if callable(stock_ep):
        @core.app.get("/api/v367/stock/{market}/{code}")
        def v367_stock(market: str, code: str, timeframe: str = "1d", days: int = 60):
            tf = str(timeframe or "1d").lower()
            ttl = 20.0 if tf in ("1d", "d", "day") else 6.0
            key = ("stock", _market(market), str(code).upper(), tf, int(days or 60))
            return _cached_call(key, ttl, 120.0, lambda: _call_endpoint(stock_ep, market=market, code=code, timeframe=timeframe, tf=timeframe, days=days))

    if callable(coin_chart_ep):
        @core.app.get("/api/v367/coin/chart/{symbol}")
        def v367_coin_chart(symbol: str, timeframe: str = "1d", count: int = 120):
            tf = str(timeframe or "1d").lower()
            ttl = 12.0 if tf in ("1d", "d", "day") else 4.0
            key = ("coin", str(symbol).upper(), tf, int(count or 120))
            return _cached_call(key, ttl, 90.0, lambda: _call_endpoint(coin_chart_ep, symbol=symbol, timeframe=timeframe, tf=timeframe, count=count, limit=count))

    if callable(index_ep):
        @core.app.get("/api/v367/index/{market}/{key}")
        def v367_index(market: str, key: str, timeframe: str = "1d"):
            tf = str(timeframe or "1d").lower()
            cache_key = ("index", _market(market), str(key).lower(), tf)
            return _cached_call(cache_key, 30.0, 300.0, lambda: _call_endpoint(index_ep, market=market, key=key, timeframe=timeframe, tf=timeframe))

    try:
        old_health = core.health_payload
        if not getattr(old_health, "_namuh_v367", False):
            def health():
                d = dict(old_health())
                d["v367"] = {
                    "active": True,
                    "layout_unchanged": True,
                    "score_pipeline": True,
                    "ledger_boundary": "00:00 KST",
                    "graph_cache": True,
                    "stats": dict(_STATS),
                }
                return d
            health._namuh_v367 = True
            core.health_payload = health
    except Exception:
        pass

    _rewrite_graph_urls()
    _inject_js("v367_unified_runtime.js")
    try:
        _sync_ledger(core)
    except Exception:
        pass
    print("NAMUH V367 active: stable fast runtime + score pipeline + persistent 00:00 KST ledger; UI layout untouched", flush=True)
    return True
