from __future__ import annotations

import math
import os
import re
import statistics
import threading
import time
from collections import deque
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import requests
import uvicorn

# v33 remains the compatibility layer.  This module is the single v34 entrypoint
# and is imported before FastAPI's lifespan starts, so every monkey-patch below
# is installed before the background trading threads are launched.
import runtime_server as v33

core = v33.core


# ---------------------------------------------------------------------------
# Asset injection
# ---------------------------------------------------------------------------

def _inject(path: str, *, css: bool = True, scripts: tuple[str, ...] = ()):
    p = Path(path)
    if not p.exists():
        return
    text = p.read_text(encoding="utf-8")
    asset_version = "341"
    if css:
        if "/static/v34.css" not in text:
            text = text.replace("</head>", f'  <link rel="stylesheet" href="/static/v34.css?v={asset_version}">\n</head>')
        else:
            text = re.sub(r'(/static/v34\.css)(?:\?v=[^"\']+)?', rf'\1?v={asset_version}', text)
    for script in scripts:
        if script not in text:
            text = text.replace("</body>", f'  <script src="{script}?v={asset_version}"></script>\n</body>')
        else:
            text = re.sub(re.escape(script) + r'(?:\?v=[^"\']+)?', f'{script}?v={asset_version}', text)
    p.write_text(text, encoding="utf-8")


_inject("static/index.html", scripts=("/static/v34.js",))
_inject("static/coin.html", scripts=("/static/coin-v34.js",))
_inject("static/coin-detail.html", scripts=("/static/coin-detail-v34.js", "/static/tooltip-v34.js"))
_inject("static/stock.html", scripts=("/static/stock-v34.js", "/static/tooltip-v34.js"))
_inject("static/index-detail.html", scripts=("/static/tooltip-v34.js",))


def _clamp(v: Any, lo: float = 0.0, hi: float = 100.0) -> float:
    try:
        v = float(v or 0)
    except Exception:
        v = 0.0
    return max(lo, min(hi, v))


# ---------------------------------------------------------------------------
# Realized-PnL only.  Holdings still count toward EQUITY, but never toward the
# displayed profit or the calendar until a SELL is completed.
# ---------------------------------------------------------------------------

def _realized_pnl(trades) -> float:
    return sum(
        float(t.get("pnl") or 0)
        for t in (trades or [])
        if str(t.get("side") or "").upper() == "SELL"
    )


_prev_paper_state = core.paper_state
_prev_coin_account_state = core.coin_account_state
_prev_global_account_state = core.global_account_state


def paper_state_v34(market):
    d = _prev_paper_state(market)
    realized = _realized_pnl(core.paper.trades)
    unrealized = sum(float(p.pnl_krw) for p in core.paper.positions.values())
    d["overall_pnl"] = round(realized)
    d["overall_pnl_pct"] = (
        realized / float(d.get("initial_cash") or 1) * 100
        if d.get("initial_cash")
        else 0.0
    )
    d["realized_pnl"] = round(realized)
    d["unrealized_pnl"] = round(unrealized)
    d["pnl_display_mode"] = "REALIZED_ONLY"
    return d


def coin_account_state_v34():
    d = _prev_coin_account_state()
    realized = _realized_pnl(core.coin_paper.trades)
    unrealized = float(core.coin_paper.unrealized_pnl_krw())
    initial = float(d.get("initial_cash") or core.coin_paper.initial_cash_krw or 1)
    d["pnl"] = round(realized)
    d["pnl_pct"] = realized / initial * 100 if initial else 0.0
    d["total_pnl"] = round(realized)
    d["realized_pnl"] = round(realized)
    d["unrealized_pnl"] = round(unrealized)
    d["pnl_display_mode"] = "REALIZED_ONLY"
    return d


def global_account_state_v34():
    d = _prev_global_account_state()
    stock_realized = _realized_pnl(core.paper.trades)
    coin_realized = _realized_pnl(core.coin_paper.trades)
    d["pnl"] = round(stock_realized + coin_realized)
    d["stock_realized_pnl"] = round(stock_realized)
    d["coin_realized_pnl"] = round(coin_realized)
    d["pnl_display_mode"] = "REALIZED_ONLY"
    return d


core.paper_state = paper_state_v34
core.coin_account_state = coin_account_state_v34
core.global_account_state = global_account_state_v34


# ---------------------------------------------------------------------------
# KR + US disclosure/event score: +5 / 0 / -5.  Severe negative disclosures
# remain a hard new-entry block.  DART's legacy +10/+6 is intentionally ignored
# here; the current rule is one material event adjustment capped to ±5.
# ---------------------------------------------------------------------------

def _event_adjustment(q) -> tuple[float, bool, dict | None]:
    events = list(getattr(q, "events", []) or [])
    blocked = bool(getattr(q, "event_blocked", False)) or any(bool(e.get("blocked")) for e in events)
    if not events:
        return 0.0, blocked, None

    def key(e):
        return (str(e.get("date") or ""), str(e.get("time") or ""))

    material = [e for e in sorted(events, key=key, reverse=True) if e.get("sentiment") in ("positive", "negative")]
    if not material:
        return 0.0, blocked, sorted(events, key=key, reverse=True)[0]
    e = material[0]
    score = 5.0 if e.get("sentiment") == "positive" else -5.0
    return score, blocked, e


_prev_scalp_analysis = core.scalp_analysis


def scalp_analysis_v34(q, sector_score=0, sector_stock_score=0, market="KR", now=None):
    market = str(market or "KR").upper()
    out = dict(_prev_scalp_analysis(q, sector_score, sector_stock_score, market, now))
    br = dict(out.get("breakdown") or {})
    if not br:
        return out

    technical = sum(float(br.get(k, 0) or 0) for k in ("MACD", "RSI", "볼린저", "거래량", "이평", "가격구조", "엘리어트"))
    event_score, event_blocked, event = _event_adjustment(q)

    # Remove the old event term and apply the current ±5 after normalization.
    br.pop("이벤트", None)
    br["공시/이벤트"] = event_score
    reasons = [r for r in list(out.get("reasons") or []) if not str(r).startswith("최근 공시")]
    if event is not None and event_score:
        reasons.append(f"공시/이벤트 {event_score:+.0f}점")

    if event_blocked:
        out.update({"score": 0.0, "gate": False, "breakdown": br,
                    "reasons": ["중대 악재 공시 · 신규진입 차단"] + reasons})
        return out

    if market == "KR":
        # The seven technical components are 75 max.  KR adds flow 10,
        # sector 10 and within-sector strength 5.  Event ±5 is additive.
        if not bool(out.get("gate", False)):
            out.update({"score": 0.0, "breakdown": br, "reasons": reasons})
            return out
        flow = float(br.get("수급", 0) or 0)
        sec = _clamp(br.get("섹터", sector_score), 0, 10)
        inner = _clamp(br.get("섹터내강도", sector_stock_score), 0, 5)
        phase = str(out.get("phase") or "REGULAR")
        pair = float(getattr(q, "foreign_net", 0) or 0) > 0 and float(getattr(q, "institution_net", 0) or 0) > 0
        base_other = technical + sec + inner  # max 90
        if phase == "SLEEP":
            raw = base_other * 0.50 + flow * (5.0 if pair else 3.0)
            denom = 95.0  # 90*0.5 + 10*5
        elif phase == "LATE":
            raw = base_other + flow * 1.5
            denom = 105.0
        else:
            raw = base_other + flow
            denom = 100.0
        base_score = raw / max(1.0, denom) * 100.0
    else:
        # US uses the same seven technical components: true max is 75.
        base_score = technical / 75.0 * 100.0

    out["score"] = round(_clamp(base_score + event_score), 1)
    out["breakdown"] = br
    out["reasons"] = reasons
    out["event_adjustment"] = event_score
    return out


core.scalp_analysis = scalp_analysis_v34


# ---------------------------------------------------------------------------
# Five 1-minute bar confirmation before any new stock entry (KR/US).
# ---------------------------------------------------------------------------

def _five_minute_trend(market: str, code: str) -> dict:
    try:
        bars = list(core.feed.bars(market, code, "1m") or [])[-5:]
    except Exception:
        bars = []
    if len(bars) < 5:
        return {"ready": False, "uptrend": False, "bars": len(bars), "return_pct": 0.0,
                "up_steps": 0, "rising_lows": 0, "label": "1분봉 5개 축적 중"}
    closes = [float(b.get("close") or 0) for b in bars]
    lows = [float(b.get("low") or b.get("close") or 0) for b in bars]
    if min(closes) <= 0:
        return {"ready": False, "uptrend": False, "bars": len(bars), "return_pct": 0.0,
                "up_steps": 0, "rising_lows": 0, "label": "1분봉 가격 대기"}
    up_steps = sum(closes[i] > closes[i - 1] for i in range(1, 5))
    rising_lows = sum(lows[i] >= lows[i - 1] for i in range(1, 5))
    ret = (closes[-1] / closes[0] - 1.0) * 100.0
    uptrend = closes[-1] > closes[0] and up_steps >= 3 and rising_lows >= 2 and ret > 0
    return {
        "ready": True, "uptrend": bool(uptrend), "bars": 5,
        "return_pct": round(ret, 3), "up_steps": up_steps, "rising_lows": rising_lows,
        "label": "5분 상승추세" if uptrend else "5분 상승확인 대기",
    }


_prev_trade_scalp = core.trade_scalp
_prev_trade_smart = core.trade_smart_kr


def trade_scalp_v34(market, candidates, now=None):
    filtered = []
    for item in list(candidates or []):
        # Analysis/UI order may put an abnormal-flow alert first even when its
        # normal entry score is weak.  Trading still requires the ordinary
        # score gate, so a low-score alert can never block later valid names.
        if float(item.get("score", 0) or 0) < 72:
            continue
        tr = _five_minute_trend(str(market).upper(), str(item.get("code") or ""))
        item["five_minute_trend"] = tr
        if tr.get("ready") and tr.get("uptrend"):
            filtered.append(item)
    return _prev_trade_scalp(market, filtered, now)


def trade_smart_v34(candidates, now=None):
    filtered = []
    for item in list(candidates or []):
        if float(item.get("score", 0) or 0) < 72:
            continue
        tr = _five_minute_trend("KR", str(item.get("code") or ""))
        item["five_minute_trend"] = tr
        if tr.get("ready") and tr.get("uptrend"):
            filtered.append(item)
    return _prev_trade_smart(filtered, now)


core.trade_scalp = trade_scalp_v34
core.trade_smart_kr = trade_smart_v34


# ---------------------------------------------------------------------------
# KR abnormal-flow alerts.
# Core 70 = volume 30 + execution acceleration 25 + 5m uptrend 15.
# Foreign/institution/pension/program are optional BUY-side bonuses totaling 30.
# Alerts live for 60 seconds, max three.  An alert gets first analysis priority,
# but it never bypasses the normal score, disclosure or 5m-trend entry gates.
# ---------------------------------------------------------------------------

_FLOW_LOCK = threading.RLock()
_FLOW_ALERTS: dict[str, dict] = {}
_FLOW_COOLDOWN: dict[str, float] = {}
_FLOW_MINUTE_SAVED: set[tuple[str, str, str]] = set()


def _kr_minute_buckets(q, lookback_seconds: int = 900) -> list[dict]:
    """Build completed 1-minute volumes from the cumulative-volume tick stream.

    The scanner may sample a symbol only a few times per minute, so deltas are
    assigned to the minute containing the later sample.  The same procedure is
    used every session, making the 5-session same-clock comparison consistent.
    """
    now = time.time()
    raw = [
        (float(ts), float(vol or 0))
        for ts, _px, vol in list(getattr(q, "tick_history", []) or [])
        if float(ts) >= now - max(180, int(lookback_seconds))
    ]
    if len(raw) < 2:
        return []
    raw.sort(key=lambda x: x[0])
    buckets: dict[tuple[str, str], float] = {}
    prev_ts, prev_vol = raw[0]
    for ts, vol in raw[1:]:
        # Cumulative volume resets on a new session; negative deltas are not
        # trading volume and must never leak into a minute bucket.
        if vol < prev_vol:
            prev_ts, prev_vol = ts, vol
            continue
        delta = vol - prev_vol
        prev_ts, prev_vol = ts, vol
        if delta <= 0:
            continue
        dt = datetime.fromtimestamp(ts, core.KST)
        mins = dt.hour * 60 + dt.minute
        if dt.weekday() >= 5 or not (9 * 60 <= mins <= 15 * 60 + 30):
            continue
        key = (dt.strftime("%Y-%m-%d"), dt.strftime("%H:%M"))
        buckets[key] = buckets.get(key, 0.0) + delta
    current = datetime.now(core.KST).strftime("%Y-%m-%d %H:%M")
    rows = [
        {"date": d, "minute": m, "volume": v}
        for (d, m), v in buckets.items()
        if f"{d} {m}" < current
    ]
    rows.sort(key=lambda x: (x["date"], x["minute"]))
    return rows


def _capture_completed_kr_minutes(q) -> list[dict]:
    rows = _kr_minute_buckets(q)
    for row in rows[-4:]:
        key = (str(q.code), row["date"], row["minute"])
        if key in _FLOW_MINUTE_SAVED:
            continue
        if core.store.save_minute_volume(
            "KR", q.code, row["date"], row["minute"], row["volume"]
        ):
            _FLOW_MINUTE_SAVED.add(key)
    # Bound process memory; persistence remains in DB/SQLite.
    if len(_FLOW_MINUTE_SAVED) > 20000:
        _FLOW_MINUTE_SAVED.clear()
    return rows


def _previous_5_session_dates(q, before_date: str) -> list[str]:
    dates = []
    for b in list(getattr(q, "daily_bars", []) or []):
        raw = str(b.get("date") or "").replace("-", "").replace("/", "")
        if len(raw) != 8 or not raw.isdigit():
            continue
        d = f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}"
        if d < before_date and d not in dates:
            dates.append(d)
    dates.sort()
    return dates[-5:]


def _recent_volume_surge(q) -> dict:
    rows = _capture_completed_kr_minutes(q)
    if not rows:
        return {
            "ratio": 0.0, "recent": 0.0, "baseline": 0.0,
            "baseline_count": 0, "baseline_ready": False,
            "minute": "", "trade_date": "", "baseline_dates": [],
            "required_dates": [], "missing_dates": [],
        }
    latest = rows[-1]
    required_dates = _previous_5_session_dates(q, latest["date"])
    baseline = core.store.minute_volume_for_dates(
        "KR", q.code, latest["minute"], required_dates
    ) if required_dates else {"count": 0, "average": 0.0, "dates": [], "missing_dates": []}
    count = int(baseline.get("count") or 0)
    avg = float(baseline.get("average") or 0)
    # Strict rule: exactly the five immediately preceding trading sessions must
    # all have the same HH:MM minute recorded. Missing a session never falls
    # back to an older day or to daily-volume/390 approximation.
    ready = len(required_dates) == 5 and count == 5 and not baseline.get("missing_dates") and avg > 0
    recent = float(latest.get("volume") or 0)
    ratio = recent / avg if ready else 0.0
    return {
        "ratio": ratio,
        "recent": recent,
        "baseline": avg,
        "baseline_count": count,
        "baseline_ready": ready,
        "minute": latest["minute"],
        "trade_date": latest["date"],
        "baseline_dates": list(baseline.get("dates") or []),
        "required_dates": required_dates,
        "missing_dates": list(baseline.get("missing_dates") or []),
    }


def _execution_accel(q) -> tuple[float, float]:
    cur = float(getattr(q, "execution_strength", 0) or 0)
    now = time.time()
    hist = [(float(ts), float(v or 0)) for ts, v in list(getattr(q, "execution_history", []) or []) if float(ts) >= now - 70]
    if not hist:
        return cur, 0.0
    hist.sort(key=lambda x: x[0])
    old = min(hist, key=lambda x: abs(x[0] - (now - 60)))[1]
    return cur, cur - old


def _flow_side(v) -> str:
    if v is None:
        return "대기"
    try:
        x = float(v)
    except Exception:
        return "대기"
    if x > 0:
        return "매수"
    if x < 0:
        return "매도"
    return "중립"


def _flow_priority(q) -> dict:
    vol = _recent_volume_surge(q)
    ratio = float(vol.get("ratio") or 0)
    recent_vol = float(vol.get("recent") or 0)
    avg5 = float(vol.get("baseline") or 0)
    baseline_ready = bool(vol.get("baseline_ready"))
    strength, accel = _execution_accel(q)
    trend = _five_minute_trend("KR", q.code)

    volume_score = _clamp((ratio - 2.0) / 6.0 * 30.0, 0, 30) if baseline_ready else 0.0
    level_score = _clamp((strength - 100.0) / 40.0 * 15.0, 0, 15)
    accel_score = _clamp(accel / 20.0 * 10.0, 0, 10)
    execution_score = level_score + accel_score
    trend_score = 15.0 if trend.get("uptrend") else 0.0

    foreign = float(getattr(q, "foreign_net", 0) or 0)
    institution = float(getattr(q, "institution_net", 0) or 0)
    pension_raw = getattr(q, "pension_net", None)
    program = float(getattr(q, "program_net", 0) or 0)
    pension = None if pension_raw is None else float(pension_raw or 0)

    bonus = (
        (8.0 if foreign > 0 else 0.0)
        + (8.0 if institution > 0 else 0.0)
        + (6.0 if pension is not None and pension > 0 else 0.0)
        + (8.0 if program > 0 else 0.0)
    )
    total = _clamp(volume_score + execution_score + trend_score + bonus)
    trigger = (
        baseline_ready
        and ratio >= 3.0
        and ((strength >= 110.0 and accel >= 5.0) or strength >= 125.0)
        and bool(trend.get("uptrend"))
    )
    return {
        "trigger": trigger,
        "priority_score": round(total, 1),
        "volume_score": round(volume_score, 1),
        "execution_score": round(execution_score, 1),
        "trend_score": round(trend_score, 1),
        "flow_bonus": round(bonus, 1),
        "volume_ratio_5d_1m": round(ratio, 2),
        "recent_1m_volume": round(recent_vol),
        "prev5_same_minute_avg": round(avg5),
        "baseline_sessions": int(vol.get("baseline_count") or 0),
        "baseline_ready": baseline_ready,
        "baseline_minute": str(vol.get("minute") or ""),
        "baseline_dates": list(vol.get("baseline_dates") or []),
        "baseline_required_dates": list(vol.get("required_dates") or []),
        "baseline_missing_dates": list(vol.get("missing_dates") or []),
        "execution_strength": round(strength, 1),
        "execution_accel_60s": round(accel, 1),
        "trend": trend,
        "flow": {
            "foreign": {"value": foreign, "side": _flow_side(foreign)},
            "institution": {"value": institution, "side": _flow_side(institution)},
            "pension": {"value": pension, "side": _flow_side(pension)},
            "program": {"value": program, "side": _flow_side(program)},
        },
    }


def _purge_flow_alerts(now=None):
    now = float(now or time.time())
    with _FLOW_LOCK:
        for code in list(_FLOW_ALERTS):
            if float(_FLOW_ALERTS[code].get("expires_at") or 0) <= now:
                _FLOW_ALERTS.pop(code, None)
        for code in list(_FLOW_COOLDOWN):
            if float(_FLOW_COOLDOWN[code]) <= now:
                _FLOW_COOLDOWN.pop(code, None)


def _detect_flow_alerts(scalp_candidates):
    now = time.time()
    _purge_flow_alerts(now)
    quotes = core.feed.quotes_for("KR")
    by_code = {str(x.get("code") or ""): x for x in (scalp_candidates or [])}
    new_rows = []
    # Scan every KR quote that the feed is currently updating, not only the
    # cache's top rows.  The feed universe can be widened independently; an
    # alert is still only a priority signal and never a force-buy instruction.
    for code, q in list(quotes.items()):
        if not q or q.price <= 0:
            continue
        metrics = _flow_priority(q)
        item = by_code.get(str(code))
        if item is not None:
            item["abnormal_flow_score"] = metrics["priority_score"]
            item["abnormal_flow"] = metrics
        if not metrics["trigger"]:
            continue
        with _FLOW_LOCK:
            if code in _FLOW_ALERTS or now < float(_FLOW_COOLDOWN.get(code, 0) or 0):
                continue
        row = {
            "market": "KR", "code": code, "name": q.name or code,
            "price": q.price, "created_at": now, "expires_at": now + 60.0,
            **metrics,
        }
        new_rows.append(row)

    if new_rows:
        with _FLOW_LOCK:
            for row in sorted(new_rows, key=lambda x: x["priority_score"], reverse=True):
                _FLOW_ALERTS[row["code"]] = row
                _FLOW_COOLDOWN[row["code"]] = now + 180.0
            # Keep only the strongest three simultaneously.
            keep = sorted(_FLOW_ALERTS.values(), key=lambda x: x["priority_score"], reverse=True)[:3]
            _FLOW_ALERTS.clear()
            _FLOW_ALERTS.update({x["code"]: x for x in keep})


def _active_alert_map():
    _purge_flow_alerts()
    with _FLOW_LOCK:
        return {k: dict(v) for k, v in _FLOW_ALERTS.items()}


_prev_rebuild_cache = core.rebuild_cache


def rebuild_cache_v34(market, now=None):
    scalp, smart = _prev_rebuild_cache(market, now)
    market = str(market or "KR").upper()
    if market == "KR":
        _detect_flow_alerts(scalp)
        alerts = _active_alert_map()
        # Alert first for analysis/re-evaluation.  Entry eligibility is filtered
        # separately in trade_scalp_v34/trade_smart_v34, so a 60-point alert
        # cannot block a later 80-point normal candidate and can never force-buy.
        scalp.sort(
            key=lambda x: (
                x.get("code") in alerts,
                float(alerts.get(x.get("code"), {}).get("priority_score", 0) or 0),
                float(x.get("score", 0) or 0) >= 72,
                float(x.get("priority_score", x.get("score", 0)) or 0),
                float(x.get("score", 0) or 0),
            ),
            reverse=True,
        )
        smart.sort(
            key=lambda x: (
                x.get("code") in alerts,
                float(alerts.get(x.get("code"), {}).get("priority_score", 0) or 0),
                float(x.get("score", 0) or 0) >= 72,
                float(x.get("score", 0) or 0),
            ),
            reverse=True,
        )
        with core.cache_lock:
            core.CACHE["KR"]["scalp"] = list(scalp[:50])
            core.CACHE["KR"]["smart"] = list(smart[:50])
    return scalp, smart


core.rebuild_cache = rebuild_cache_v34


@core.app.get("/api/v34/flow-alerts")
def v34_flow_alerts():
    rows = sorted(_active_alert_map().values(), key=lambda x: x["priority_score"], reverse=True)[:3]
    return {"ok": True, "ttl_seconds": 60, "max_alerts": 3, "items": rows, "build": core.BUILD_ID}


@core.app.get("/api/v34/cached-candidates")
def v34_cached_candidates(market: str = "KR", n: int = 12):
    market = core.normalize_market(market)
    n = max(1, min(30, int(n or 12)))
    if market == "COIN":
        return {"market": "COIN", "scalp": core.coin_feed.candidates(n), "smart": []}
    with core.cache_lock:
        c = core.CACHE[market]
        return {"market": market, "scalp": list(c["scalp"][:n]),
                "smart": list(c["smart"][:n]) if market == "KR" else [],
                "updated_at": c.get("updated_at", 0)}


@core.app.get("/api/v34/trend/{market}/{code}")
def v34_trend(market: str, code: str):
    market = core.normalize_market(market)
    if market not in ("KR", "US"):
        return {"ready": False, "uptrend": False}
    return _five_minute_trend(market, code.upper())


# ---------------------------------------------------------------------------
# Whole-market stock search (KR/US) + on-demand tracking.
# Search uses NHPLUG instrument masters, not only already-warmed quote objects.
# ---------------------------------------------------------------------------

_SEARCH_MASTER_LOCK = threading.RLock()
_SEARCH_CATALOG: dict[str, dict[str, dict]] = {"KR": {}, "US": {}}
_SEARCH_MASTER_ERROR: dict[str, str] = {"KR": "", "US": ""}


def _frame_rows(frame):
    if frame is None:
        return []
    if hasattr(frame, "to_dict"):
        try:
            return frame.to_dict("records")
        except Exception:
            pass
    return frame if isinstance(frame, list) else []


def _ensure_search_catalog(market: str) -> dict[str, dict]:
    market = str(market or "KR").upper()
    with _SEARCH_MASTER_LOCK:
        if _SEARCH_CATALOG.get(market):
            return _SEARCH_CATALOG[market]
        rows: dict[str, dict] = {}
        try:
            if market == "KR":
                if not getattr(core.feed, "kr_master_meta", None):
                    core.feed._load_kr_master()
                for code, meta in dict(getattr(core.feed, "kr_master_meta", {}) or {}).items():
                    code = str(code or "").upper().strip()
                    if not code:
                        continue
                    rows[code] = {
                        "market": "KR", "code": code,
                        "name": str(meta.get("name") or code).strip(),
                        "sector": str(meta.get("sector") or "기타").strip(),
                    }
            else:
                from nhplug.instruments import load_master
                for row in _frame_rows(load_master("m_gtsstock")):
                    code = str(
                        row.get("symbol") or row.get("sSymbol") or row.get("symb")
                        or row.get("code") or ""
                    ).upper().strip()
                    if not code or len(code) > 16:
                        continue
                    name = str(
                        row.get("kor_name") or row.get("eng_name") or row.get("name")
                        or row.get("sKorName") or row.get("sEngName") or code
                    ).strip()
                    industry = str(
                        row.get("industry_name") or row.get("industry_group")
                        or row.get("gIndustryReuter") or row.get("sector_name") or ""
                    ).strip()
                    rows.setdefault(code, {
                        "market": "US", "code": code, "name": name or code,
                        "sector": industry or "미국주식",
                    })
            _SEARCH_MASTER_ERROR[market] = ""
        except Exception as exc:
            _SEARCH_MASTER_ERROR[market] = str(exc)[:240]

        # Never make search worse if a master load is temporarily unavailable.
        for quote in core.feed.quotes_for(market).values():
            code = str(quote.code or "").upper().strip()
            if not code:
                continue
            rows.setdefault(code, {
                "market": market, "code": code, "name": str(quote.name or code),
                "sector": str(core.sector_name(quote, market) or ""),
            })
        _SEARCH_CATALOG[market] = rows
        return rows


def _track_search_stock(market: str, code: str) -> dict:
    market = str(market or "KR").upper()
    code = str(code or "").upper().strip()
    catalog = _ensure_search_catalog(market)
    meta = catalog.get(code)
    if meta is None:
        raise ValueError("master stock not found")

    quote = core.feed.q(market, code)
    quote.name = str(meta.get("name") or quote.name or code)
    quote.sector = str(meta.get("sector") or quote.sector or ("미국주식" if market == "US" else "기타"))
    codes = core.feed.code_lists[market]
    if code not in codes:
        codes.append(code)

    quote_error = ""
    try:
        from nhplug import call
        if market == "KR":
            last = None
            for market_cd in core.feed._market_order():
                try:
                    data = call("/krstock/quote/v1/currentPrice", {"iem_cd": code, "market_cd": market_cd})
                    core.feed._apply_kr(code, data)
                    if quote.price > 0:
                        last = None
                        break
                except Exception as exc:
                    last = exc
            if last is not None and quote.price <= 0:
                raise last
        else:
            data = call("/gbstock/quote/v1/current", {"iem_cd": code})
            core.feed._apply_us(code, data)
    except Exception as exc:
        quote_error = str(exc)[:220]

    try:
        bars = core.feed.ensure_daily_bars(market, code, 30)
    except Exception as exc:
        bars = list(getattr(quote, "daily_bars", []) or [])
        if not quote_error:
            quote_error = str(exc)[:220]

    # Closed-market detail should still show the latest official daily close.
    # Do not stamp updated_at here: a daily fallback must never look trade-fresh.
    if quote.price <= 0 and bars:
        last = bars[-1]
        quote.price = float(last.get("close") or 0)
        quote.open = float(last.get("open") or quote.price)
        quote.high = float(last.get("high") or quote.price)
        quote.low = float(last.get("low") or quote.price)
        quote.volume = float(last.get("volume") or 0)

    return {
        "market": market, "code": code, "name": quote.name or code,
        "sector": quote.sector or meta.get("sector") or "", "price": quote.price,
        "tracked": True, "quote_error": quote_error,
        "daily_bars": len(list(getattr(quote, "daily_bars", []) or [])),
    }


@core.app.get("/api/v34/search")
def v34_search(market: str = "KR", q: str = ""):
    market = core.normalize_market(market)
    if market not in ("KR", "US"):
        return {"market": market, "items": []}
    needle = str(q or "").strip().lower()
    if not needle:
        return {"market": market, "items": []}
    catalog = _ensure_search_catalog(market)
    live = core.feed.quotes_for(market)
    rows = []
    for code, meta in catalog.items():
        name = str(meta.get("name") or code)
        if needle not in code.lower() and needle not in name.lower():
            continue
        quote = live.get(code)
        starts = code.lower().startswith(needle) or name.lower().startswith(needle)
        rows.append({
            "market": market, "code": code, "name": name,
            "price": float(getattr(quote, "price", 0) or 0),
            "sector": str(meta.get("sector") or (core.sector_name(quote, market) if quote else "")),
            "tracked": bool(quote), "starts": starts,
        })
    rows.sort(key=lambda x: (not x["starts"], len(x["name"]), x["name"], x["code"]))
    for x in rows:
        x.pop("starts", None)
    return {
        "market": market, "items": rows[:30], "catalog_count": len(catalog),
        "master_error": _SEARCH_MASTER_ERROR.get(market, ""),
    }


@core.app.post("/api/v34/track/{market}/{code}")
def v34_track_stock(market: str, code: str):
    market = core.normalize_market(market)
    if market not in ("KR", "US"):
        return {"ok": False, "error": "stock market only"}
    try:
        row = _track_search_stock(market, code)
        return {"ok": True, **row}
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:240]}


# ---------------------------------------------------------------------------
# SEC public disclosure feed for US stocks.
# ---------------------------------------------------------------------------

_SEC_LOCK = threading.RLock()
_SEC_TICKERS: dict[str, dict] = {}
_US_EVENTS: list[dict] = []
_US_EVENT_STATUS = "SEC 수신 대기"
_US_EVENT_UPDATED = 0.0
_SEC_SESSION = requests.Session()
_SEC_SESSION.headers.update({
    "User-Agent": os.getenv("SEC_USER_AGENT", "GY-Trading-OS/1.0 public-market-data"),
    "Accept-Encoding": "gzip, deflate",
    "Accept": "application/json,text/html,*/*",
})

_POS_WORDS = (
    "record revenue", "revenue increased", "net income increased", "raises guidance",
    "increases guidance", "share repurchase", "stock repurchase", "authorization of repurchase",
    "new contract", "strategic agreement", "approval", "milestone payment", "profit increased",
)
_NEG_WORDS = (
    "revenue decreased", "net loss", "loss increased", "impairment", "restatement",
    "material weakness", "investigation", "subpoena", "lawsuit", "offering of common stock",
    "dilution", "restructuring charge", "guidance reduced", "lowers guidance", "default",
)
_BLOCK_WORDS = ("chapter 11", "bankruptcy", "delisting notice", "trading suspension", "insolvency")


def _load_sec_tickers():
    global _SEC_TICKERS
    if _SEC_TICKERS:
        return
    r = _SEC_SESSION.get("https://www.sec.gov/files/company_tickers.json", timeout=20)
    r.raise_for_status()
    data = r.json()
    out = {}
    for row in data.values():
        ticker = str(row.get("ticker") or "").upper()
        if ticker:
            out[ticker] = {"cik": int(row.get("cik_str") or 0), "name": row.get("title") or ticker}
    _SEC_TICKERS = out


def _strip_html(text: str) -> str:
    text = re.sub(r"<script[\s\S]*?</script>", " ", text, flags=re.I)
    text = re.sub(r"<style[\s\S]*?</style>", " ", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).lower()[:300000]


def _classify_sec(text: str, form: str, desc: str) -> tuple[str, str, float, bool]:
    hay = f"{form} {desc} {text}".lower()
    if any(k in hay for k in _BLOCK_WORDS):
        return "negative", "강한 악재", -5.0, True
    pos = sum(hay.count(k) for k in _POS_WORDS)
    neg = sum(hay.count(k) for k in _NEG_WORDS)
    if form.upper().startswith("424B") and ("common stock" in hay or "offering" in hay):
        neg += 2
    if neg > pos and neg > 0:
        return "negative", "악재", -5.0, False
    if pos > neg and pos > 0:
        return "positive", "호재", 5.0, False
    return "neutral", "중립", 0.0, False


def _sec_symbol_events(symbol: str, max_items: int = 4) -> list[dict]:
    _load_sec_tickers()
    meta = _SEC_TICKERS.get(symbol.upper())
    if not meta or not meta.get("cik"):
        return []
    cik = int(meta["cik"])
    url = f"https://data.sec.gov/submissions/CIK{cik:010d}.json"
    r = _SEC_SESSION.get(url, timeout=20)
    r.raise_for_status()
    recent = (r.json().get("filings") or {}).get("recent") or {}
    forms = recent.get("form") or []
    dates = recent.get("filingDate") or []
    accessions = recent.get("accessionNumber") or []
    docs = recent.get("primaryDocument") or []
    descs = recent.get("primaryDocDescription") or []
    cutoff = (datetime.now(core.KST).date() - timedelta(days=7)).isoformat()
    accepted_forms = {"8-K", "10-Q", "10-K", "6-K", "20-F", "S-1", "S-3", "DEF 14A"}
    out = []
    for i, form in enumerate(forms):
        date = str(dates[i] if i < len(dates) else "")
        if date and date < cutoff:
            break
        if form not in accepted_forms and not str(form).startswith("424B"):
            continue
        acc = str(accessions[i] if i < len(accessions) else "")
        doc = str(docs[i] if i < len(docs) else "")
        desc = str(descs[i] if i < len(descs) else "")
        archive = ""
        body = ""
        if acc and doc:
            archive = f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc.replace('-', '')}/{doc}"
            try:
                rr = _SEC_SESSION.get(archive, timeout=15)
                if rr.ok:
                    body = _strip_html(rr.text)
            except Exception:
                body = ""
        sentiment, label, score, blocked = _classify_sec(body, str(form), desc)
        out.append({
            "market": "US", "code": symbol.upper(), "corp_name": meta.get("name") or symbol.upper(),
            "title": desc or f"SEC {form}", "form": form, "date": date, "time": "",
            "source": "SEC EDGAR", "url": archive or url, "sentiment": sentiment,
            "impact": "strong" if blocked else ("medium" if score else "low"),
            "label": label, "score": score, "blocked": blocked,
        })
        if len(out) >= max_items:
            break
    return out


def _refresh_us_events_once():
    global _US_EVENTS, _US_EVENT_STATUS, _US_EVENT_UPDATED
    try:
        with core.cache_lock:
            hot = [x.get("code") for x in core.CACHE["US"].get("scalp", [])[:20] if x.get("code")]
        if not hot:
            hot = [q.code for q in list(core.feed.quotes_for("US").values())[:20]]
        all_events = []
        for symbol in dict.fromkeys(hot):
            try:
                evs = _sec_symbol_events(str(symbol).upper(), 3)
                q = core.feed.quotes_for("US").get(str(symbol).upper())
                if q is not None:
                    q.events = evs
                    score, blocked, _ = _event_adjustment(q)
                    q.event_score = score
                    q.event_blocked = blocked
                all_events.extend(evs)
            except Exception:
                continue
            time.sleep(0.12)  # stay comfortably below SEC request-rate guidance
        all_events.sort(key=lambda e: (e.get("date", ""), abs(float(e.get("score") or 0))), reverse=True)
        with _SEC_LOCK:
            _US_EVENTS = all_events[:80]
            _US_EVENT_UPDATED = time.time()
            _US_EVENT_STATUS = "SEC EDGAR 수신" if all_events else "최근 SEC 공시 없음"
    except Exception as exc:
        with _SEC_LOCK:
            _US_EVENT_STATUS = f"SEC 연결 대기 · {str(exc)[:120]}"


def _sec_loop():
    while True:
        _refresh_us_events_once()
        time.sleep(300)


@core.app.get("/api/v34/events")
def v34_events(market: str = "KR"):
    market = core.normalize_market(market)
    if market == "US":
        with _SEC_LOCK:
            return {"market": "US", "items": list(_US_EVENTS[:30]), "status": _US_EVENT_STATUS,
                    "updated_at": _US_EVENT_UPDATED}
    return core.events.state("KR")


@core.app.get("/api/v34/events/{market}/{code}")
def v34_stock_events(market: str, code: str):
    market = core.normalize_market(market)
    code = code.upper()
    q = core.feed.quotes_for(market).get(code) if market in ("KR", "US") else None
    if not q:
        return {"market": market, "code": code, "items": []}
    if market == "US" and not list(getattr(q, "events", []) or []):
        try:
            evs = _sec_symbol_events(code, 4)
            q.events = evs
            score0, blocked0, _ = _event_adjustment(q)
            q.event_score = score0
            q.event_blocked = blocked0
        except Exception:
            pass
    score, blocked, _ = _event_adjustment(q)
    return {"market": market, "code": code, "items": list(q.events or []),
            "event_adjustment": score, "blocked": blocked}


# ---------------------------------------------------------------------------
# COIN score = VALUE 30 + TECHNICAL 70.
# Value raw 100: transaction rank10, execution20, momentum20,
# volume acceleration15, bid advantage15, trend persistence10,
# bid/ask price gap5, volatility suitability5.
# Technical raw 85: MACD10, RSI10, Bollinger10, MA10, Elliott10,
# Williams %R10, volume15, price structure10; normalized to 70.
# ---------------------------------------------------------------------------

_COIN_TECH_LOCK = threading.RLock()
_COIN_TECH: dict[str, dict] = {}
_COIN_VOLUME_HISTORY: dict[str, deque] = {}


def _sma(a, n):
    return sum(a[-n:]) / n if len(a) >= n else None


def _ema_series(a, n):
    if len(a) < n:
        return []
    k = 2.0 / (n + 1.0)
    out = [sum(a[:n]) / n]
    for x in a[n:]:
        out.append(x * k + out[-1] * (1 - k))
    return out


def _rsi14(a):
    if len(a) < 15:
        return None
    gains = []
    losses = []
    for i in range(-14, 0):
        d = a[i] - a[i - 1]
        gains.append(max(0.0, d))
        losses.append(max(0.0, -d))
    g = sum(gains) / 14
    l = sum(losses) / 14
    if l == 0:
        return 100.0
    rs = g / l
    return 100.0 - 100.0 / (1.0 + rs)


def _coin_technical_from_bars(bars: list[dict]) -> dict:
    closes = [float(b.get("close") or 0) for b in bars if float(b.get("close") or 0) > 0]
    if len(closes) < 30:
        return {"ready": False, "raw": 0.0, "weighted": 0.0, "components": [], "volatility": 0.0,
                "trend_up": False}
    c = closes[-1]

    # MACD 10
    e12 = _ema_series(closes, 12)
    e26 = _ema_series(closes, 26)
    overlap = min(len(e12), len(e26))
    macd_line = [e12[-overlap + i] - e26[-overlap + i] for i in range(overlap)] if overlap else []
    sig = _ema_series(macd_line, 9)
    if macd_line and sig:
        m, s = macd_line[-1], sig[-1]
        gap = (m - s) / max(abs(c), 1e-9) * 100
        macd_pts = _clamp(5 + gap * 80, 0, 10) if m >= s else _clamp(5 + gap * 50, 0, 5)
    else:
        macd_pts = 0.0

    # RSI 10: same preferred short-entry zones as the stock model.
    rv = _rsi14(closes)
    if rv is None:
        rsi_pts = 0.0
    elif rv < 30:
        rsi_pts = _clamp(rv / 30 * 4, 0, 4)
    elif rv < 40:
        rsi_pts = 9.0
    elif rv < 50:
        rsi_pts = 10.0
    elif rv < 60:
        rsi_pts = 8.0
    elif rv <= 65:
        rsi_pts = 7.0
    else:
        rsi_pts = 0.0

    # Bollinger 10
    mid = _sma(closes, 20)
    sd = statistics.pstdev(closes[-20:]) if len(closes) >= 20 else 0
    lo, hi = (mid - 2 * sd, mid + 2 * sd) if mid is not None else (None, None)
    if mid is None or hi <= lo:
        boll_pts = 0.0
    elif c <= lo:
        boll_pts = 10.0
    elif c >= hi:
        boll_pts = 0.0
    elif c <= mid:
        boll_pts = 10 - 8 * ((c - lo) / max(mid - lo, 1e-9))
    else:
        boll_pts = max(0.0, 2 - 2 * ((c - mid) / max(hi - mid, 1e-9)))

    # Moving averages 10
    ma5, ma10, ma20 = _sma(closes, 5), _sma(closes, 10), _sma(closes, 20)
    if ma5 and ma10 and ma20 and c >= ma5 > ma10 > ma20:
        ma_pts = 10.0
    elif ma5 and ma10 and ma20 and ma5 > ma10 > ma20:
        ma_pts = 8.0
    elif ma5 and ma10 and ma20 and c >= ma20:
        ma_pts = 5.0
    else:
        ma_pts = 2.0

    # Williams %R 10
    recent14 = bars[-14:]
    hh = max(float(b.get("high") or b.get("close") or 0) for b in recent14)
    ll = min(float(b.get("low") or b.get("close") or 0) for b in recent14)
    wr = -100 * (hh - c) / max(hh - ll, 1e-9)
    if wr <= -90:
        wr_pts = 4.0
    elif wr <= -80:
        wr_pts = 8.0
    elif wr <= -50:
        wr_pts = 10.0
    elif wr <= -30:
        wr_pts = 7.0
    elif wr <= -20:
        wr_pts = 4.0
    else:
        wr_pts = 1.0

    # Elliott-style position 10
    win = closes[-20:]
    mn, mx = min(win), max(win)
    pos = (c - mn) / max(mx - mn, 1e-9) * 100
    recent = closes[-1] - closes[-3]
    if 25 <= pos <= 65 and recent > 0:
        ell_pts = 10.0
    elif pos <= 25 and recent > 0:
        ell_pts = 7.0
    elif pos <= 82 and recent > 0:
        ell_pts = 6.0
    elif pos <= 92:
        ell_pts = 3.0
    else:
        ell_pts = 1.0

    # Volume 15
    vols = [float(b.get("volume") or 0) for b in bars]
    v3 = statistics.fmean(vols[-3:]) if len(vols) >= 3 else 0
    v20 = statistics.fmean(vols[-23:-3]) if len(vols) >= 23 else statistics.fmean(vols[:-3]) if len(vols) > 3 else 0
    vr = v3 / max(v20, 1e-9) if v20 > 0 else 1.0
    if vr <= 0.5:
        vol_pts = 2.0
    elif vr <= 1.0:
        vol_pts = 2 + (vr - 0.5) / 0.5 * 6
    elif vr <= 2.0:
        vol_pts = 8 + (vr - 1.0) * 7
    else:
        vol_pts = max(8.0, 15.0 - min(7.0, (vr - 2.0) * 2.0))

    # Price structure 10
    c5 = closes[-5:]
    lows5 = [float(b.get("low") or b.get("close") or 0) for b in bars[-5:]]
    up_steps = sum(c5[i] > c5[i - 1] for i in range(1, 5))
    low_steps = sum(lows5[i] >= lows5[i - 1] for i in range(1, 5))
    if up_steps >= 4 and low_steps >= 3:
        struct_pts = 10.0
    elif up_steps >= 3 and low_steps >= 2:
        struct_pts = 8.0
    elif c5[-1] > c5[0]:
        struct_pts = 5.0
    else:
        struct_pts = 1.0

    rets = [(closes[i] / closes[i - 1] - 1) * 100 for i in range(max(1, len(closes) - 20), len(closes))]
    volatility = statistics.pstdev(rets) if len(rets) >= 2 else 0.0
    trend_up = c5[-1] > c5[0] and up_steps >= 3

    components = [
        {"key": "macd", "label": "MACD", "score": round(macd_pts, 1), "max": 10},
        {"key": "rsi", "label": "RSI", "score": round(rsi_pts, 1), "max": 10},
        {"key": "bollinger", "label": "볼린저밴드", "score": round(boll_pts, 1), "max": 10},
        {"key": "ma", "label": "이평선", "score": round(ma_pts, 1), "max": 10},
        {"key": "williams", "label": "Williams %R", "score": round(wr_pts, 1), "max": 10},
        {"key": "elliott", "label": "엘리어트", "score": round(ell_pts, 1), "max": 10},
        {"key": "volume", "label": "거래량", "score": round(vol_pts, 1), "max": 15},
        {"key": "structure", "label": "가격구조", "score": round(struct_pts, 1), "max": 10},
    ]
    raw = sum(float(x["score"]) for x in components)
    return {"ready": True, "raw": round(raw, 1), "weighted": round(raw / 85.0 * 70.0, 1),
            "components": components, "volatility": round(volatility, 4), "trend_up": trend_up,
            "rsi": None if rv is None else round(rv, 1), "williams_r": round(wr, 1)}


def _coin_value(q, idx: int, count: int, tech: dict) -> dict:
    # Snapshot cumulative quote volume for acceleration.
    now = time.time()
    hist = _COIN_VOLUME_HISTORY.setdefault(q.symbol, deque(maxlen=80))
    hist.append((now, float(q.quote_volume or 0)))
    while hist and hist[0][0] < now - 300:
        hist.popleft()
    recent_delta = 0.0
    prior_delta = 0.0
    if len(hist) >= 2:
        recent = [x for x in hist if x[0] >= now - 60]
        prior = [x for x in hist if now - 180 <= x[0] < now - 60]
        if len(recent) >= 2:
            recent_delta = max(0.0, recent[-1][1] - recent[0][1])
        if len(prior) >= 2:
            prior_delta = max(0.0, prior[-1][1] - prior[0][1]) / max(1.0, (prior[-1][0] - prior[0][0]) / 60.0)
    accel_ratio = recent_delta / max(prior_delta, 1e-9) if prior_delta > 0 else 1.0

    rank_pts = 10.0 * (1.0 - idx / max(1, count - 1))
    exec_pts = _clamp((float(q.volume_power or 0) - 90.0) / 45.0 * 20.0, 0, 20)
    ch = float(q.change_pct or 0)
    if ch <= -2:
        momentum = 0.0
    elif ch < 1:
        momentum = _clamp((ch + 2) / 3 * 8, 0, 8)
    elif ch <= 8:
        momentum = 8 + (ch - 1) / 7 * 12
    elif ch <= 15:
        momentum = 20 - (ch - 8) / 7 * 10
    else:
        momentum = 6.0
    volume_accel = _clamp((accel_ratio - 0.5) / 2.5 * 15.0, 0, 15) if prior_delta > 0 else 7.5
    imbalance = _clamp((float(q.book_imbalance or 0) + 20) / 60 * 15, 0, 15)
    trend_pts = 10.0 if tech.get("trend_up") else (4.0 if tech.get("ready") else 0.0)
    spread = q.spread_pct
    spread_pts = 5.0 if spread is None else _clamp((0.7 - float(spread)) / 0.7 * 5, 0, 5)
    vol = float(tech.get("volatility") or 0)
    if not tech.get("ready"):
        volatility_pts = 0.0
    elif 0.15 <= vol <= 1.5:
        volatility_pts = 5.0
    elif vol < 0.15:
        volatility_pts = _clamp(vol / 0.15 * 5, 0, 5)
    else:
        volatility_pts = _clamp(5 - (vol - 1.5) * 2, 0, 5)

    components = [
        {"key": "volume_rank", "label": "거래대금순위", "score": round(rank_pts, 1), "max": 10},
        {"key": "execution", "label": "체결강도", "score": round(exec_pts, 1), "max": 20},
        {"key": "momentum", "label": "단기 모멘텀", "score": round(momentum, 1), "max": 20},
        {"key": "volume_accel", "label": "거래량 가속", "score": round(volume_accel, 1), "max": 15},
        {"key": "bid_advantage", "label": "호가 매수우위", "score": round(imbalance, 1), "max": 15},
        {"key": "trend", "label": "추세 지속성", "score": round(trend_pts, 1), "max": 10},
        {"key": "spread", "label": "매수·매도 가격차", "score": round(spread_pts, 1), "max": 5},
        {"key": "volatility", "label": "변동성 적정성", "score": round(volatility_pts, 1), "max": 5},
    ]
    raw = sum(float(x["score"]) for x in components)
    return {"raw": round(raw, 1), "weighted": round(raw / 100.0 * 30.0, 1),
            "components": components, "volume_accel_ratio": round(accel_ratio, 2)}


def _refresh_coin_technical_symbol(symbol: str):
    try:
        bars = core.coin_feed.chart(symbol, "5m", 120)
        tech = _coin_technical_from_bars(bars)
        tech["updated_at"] = time.time()
        with _COIN_TECH_LOCK:
            _COIN_TECH[symbol] = tech
        return tech
    except Exception as exc:
        with _COIN_TECH_LOCK:
            old = dict(_COIN_TECH.get(symbol) or {})
        if old:
            return old
        return {"ready": False, "raw": 0.0, "weighted": 0.0, "components": [],
                "volatility": 0.0, "trend_up": False, "error": str(exc)[:120]}


def _coin_technical_loop():
    while True:
        try:
            symbols = [q.symbol for q in core.coin_feed.top_quotes(20)]
            for symbol in symbols:
                _refresh_coin_technical_symbol(symbol)
                time.sleep(0.08)
        except Exception:
            pass
        time.sleep(60)


def candidates_v34(n=20):
    n = max(1, min(80, int(n or 20)))
    ranked = core.coin_feed.top_quotes(max(core.coin_feed.top_n, n))
    if not ranked:
        return []
    out = []
    count = len(ranked)
    for idx, q in enumerate(ranked):
        with _COIN_TECH_LOCK:
            tech = dict(_COIN_TECH.get(q.symbol) or {})
        if not tech:
            tech = {"ready": False, "raw": 0.0, "weighted": 0.0, "components": [],
                    "volatility": 0.0, "trend_up": False}
        value = _coin_value(q, idx, count, tech)
        total = _clamp(float(value["weighted"]) + float(tech.get("weighted") or 0))
        reasons = []
        if idx < 8:
            reasons.append("거래대금 상위")
        if q.volume_power >= 105:
            reasons.append(f"체결강도 {q.volume_power:.0f}")
        if q.book_imbalance >= 10:
            reasons.append("매수호가 우위")
        if tech.get("trend_up"):
            reasons.append("5분 기술추세 상승")
        if not tech.get("ready"):
            reasons.append("기술점수 축적 중")
        fresh_age = max(0.0, time.time() - q.updated_at) if q.updated_at else 9999
        out.append({
            "market": "COIN", "code": q.symbol, "name": q.name or q.symbol,
            "price": q.price, "change_pct": q.change_pct, "quote_volume": q.quote_volume,
            "target_volume": q.target_volume, "volume_power": q.volume_power,
            "spread_pct": q.spread_pct, "book_imbalance": q.book_imbalance,
            "value_score": value["weighted"], "value_raw": value["raw"],
            "technical_score": round(float(tech.get("weighted") or 0), 1),
            "technical_raw": round(float(tech.get("raw") or 0), 1),
            "score": round(total, 1), "score_total": round(total, 1),
            "value_breakdown": value["components"],
            "technical_breakdown": list(tech.get("components") or []),
            "score_breakdown": [
                {"key": "value", "label": "VALUE SCORE", "score": value["weighted"], "max": 30},
                {"key": "technical", "label": "TECHNICAL SCORE", "score": round(float(tech.get("weighted") or 0), 1), "max": 70},
            ],
            "technical_ready": bool(tech.get("ready")), "reasons": reasons[:5],
            "fresh_age": round(fresh_age, 1), "updated_at": q.updated_at,
        })
    out.sort(key=lambda x: x["score"], reverse=True)
    return out[:n]


core.coin_feed.candidates = candidates_v34


# ---------------------------------------------------------------------------
# Extra background jobs and sole AUTO switch behavior for coin.
# ---------------------------------------------------------------------------

_prev_start_background = core.start_background
_EXTRA_LOCK = threading.Lock()
_EXTRA_STARTED = False


def start_background_v34():
    global _EXTRA_STARTED
    _prev_start_background()
    # Keep only a compact window of persisted intraday baselines.
    try:
        cutoff = (datetime.now(core.KST) - timedelta(days=35)).strftime("%Y-%m-%d")
        core.store.prune_minute_volume(cutoff)
    except Exception:
        pass
    # v34 uses the top global AUTO switch as the only user-facing new-entry
    # control; keep the old coin-local switch permanently enabled underneath.
    try:
        with core.COIN_SETTINGS_LOCK:
            core.COIN_SETTINGS["auto_trade_enabled"] = True
        core._persist_coin_settings()
    except Exception:
        pass
    with _EXTRA_LOCK:
        if _EXTRA_STARTED:
            return
        _EXTRA_STARTED = True
        threading.Thread(target=_sec_loop, daemon=True).start()
        threading.Thread(target=_coin_technical_loop, daemon=True).start()


core.start_background = start_background_v34


@core.app.get("/api/v34/status")
def v34_status():
    return {
        "ok": True,
        "version": "v34.1",
        "new_entries_enabled": v33._entries_enabled(),
        "exit_monitoring_enabled": True,
        "persistence": core.store.status(),
        "flow_alerts": len(_active_alert_map()),
        "flow_volume_baseline": "previous_5_sessions_same_clock_minute",
        "us_events": len(_US_EVENTS),
        "coin_technical_cached": len(_COIN_TECH),
        "loop": dict(core.LOOP_STATE),
        "coin_loop": dict(core.COIN_LOOP_STATE),
        "build": core.BUILD_ID,
    }


if __name__ == "__main__":
    uvicorn.run(
        core.app,
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "8787")),
        reload=False,
    )
