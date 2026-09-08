from __future__ import annotations

from collections import deque
from copy import copy
from datetime import datetime

_INSTALLED = False

TECH_MAX = {
    "MACD": 10.0,
    "RSI": 10.0,
    "볼린저": 10.0,
    "거래량": 15.0,
    "이평": 10.0,
    "가격구조": 10.0,
    "엘리어트": 10.0,
}


def _f(v, default=0.0):
    try:
        return float(v)
    except Exception:
        return float(default)


def _clamp(v, lo=0.0, hi=100.0):
    return max(float(lo), min(float(hi), _f(v)))


def _floor1(v, hi):
    return max(1.0, min(float(hi), _f(v)))


def _digits(v):
    return "".join(ch for ch in str(v or "") if ch.isdigit())


def _ema_series(xs, n):
    vals = [float(x) for x in xs]
    if len(vals) < n:
        return []
    seed = sum(vals[:n]) / n
    out = [seed]
    a = 2.0 / (n + 1.0)
    cur = seed
    for x in vals[n:]:
        cur = a * x + (1.0 - a) * cur
        out.append(cur)
    return out


def _macd_standard(xs):
    vals = [float(x) for x in xs if _f(x) > 0]
    if len(vals) < 35:
        return 0.0, 0.0
    e12 = _ema_series(vals, 12)
    e26 = _ema_series(vals, 26)
    offset = 26 - 12
    macd_line = [e12[i + offset] - e26[i] for i in range(len(e26)) if i + offset < len(e12)]
    if not macd_line:
        return 0.0, 0.0
    sig = _ema_series(macd_line, 9)
    signal = sig[-1] if sig else macd_line[-1]
    return macd_line[-1], signal


def _rsi_wilder(xs, n=14):
    vals = [float(x) for x in xs if _f(x) > 0]
    if len(vals) < n + 1:
        return 50.0
    changes = [vals[i] - vals[i - 1] for i in range(1, len(vals))]
    gains = [max(x, 0.0) for x in changes]
    losses = [max(-x, 0.0) for x in changes]
    avg_gain = sum(gains[:n]) / n
    avg_loss = sum(losses[:n]) / n
    for i in range(n, len(changes)):
        avg_gain = (avg_gain * (n - 1) + gains[i]) / n
        avg_loss = (avg_loss * (n - 1) + losses[i]) / n
    if avg_loss <= 1e-12:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - 100.0 / (1.0 + rs)


def _bollinger_standard(xs, n=20, k=2.0):
    vals = [float(x) for x in xs if _f(x) > 0]
    if len(vals) < n:
        return None, None, None
    w = vals[-n:]
    mid = sum(w) / n
    var = sum((x - mid) ** 2 for x in w) / n
    sd = var ** 0.5
    return mid, mid + k * sd, mid - k * sd


def _official_1m(core, market, code, current_price=0.0):
    try:
        rows = [dict(x) for x in list(core.feed.bars(market, code, "1m") or []) if isinstance(x, dict)]
    except Exception:
        rows = []
    clean = []
    for b in rows:
        c = _f(b.get("close"))
        o = _f(b.get("open"), c)
        h = _f(b.get("high"), max(o, c))
        l = _f(b.get("low"), min(o, c))
        if min(o, h, l, c) <= 0 or h < max(o, c) or l > min(o, c):
            continue
        clean.append({
            "time": str(b.get("time") or b.get("datetime") or b.get("date") or ""),
            "open": o, "high": h, "low": l, "close": c,
            "volume": max(0.0, _f(b.get("volume"))),
        })
    clean.sort(key=lambda x: _digits(x.get("time")))
    px = _f(current_price)
    if clean and px > 0:
        clean[-1]["close"] = px
        clean[-1]["high"] = max(clean[-1]["high"], px)
        clean[-1]["low"] = min(clean[-1]["low"], px)
    return clean


def _minute_score(core, q, market, now_dt):
    rows = _official_1m(core, market, q.code, getattr(q, "price", 0))
    local = now_dt
    if str(market).upper() == "US":
        try:
            local = now_dt.astimezone(core.ZoneInfo("America/New_York"))
        except Exception:
            pass
    today = local.strftime("%Y%m%d")
    same_day = [b for b in rows if _digits(b.get("time"))[:8] == today]
    use = same_day if len(same_day) >= 3 else rows
    if len(use) < 3:
        return 1.0, False, {
            "ready": False, "bars": len(use), "source": "official_1m",
            "score_parts": {"pullback2": 0.0, "low2": 0.0, "breakout4": 0.0, "candle2": 0.0},
        }

    prev2, prev, cur = use[-3], use[-2], use[-1]
    p2c = _f(prev2.get("close"))
    po, pc = _f(prev.get("open")), _f(prev.get("close"))
    p2l, pl = _f(prev2.get("low")), _f(prev.get("low"))
    ph = _f(prev.get("high"))
    co = _f(cur.get("open"))
    cl = _f(cur.get("low"))
    cc = _f(getattr(q, "price", 0), _f(cur.get("close")))

    prev_bear = pc < po
    lower_close = p2c > 0 and pc < p2c
    pullback = 2.0 if prev_bear and lower_close else 1.0 if (prev_bear or lower_close) else 0.0

    low_made = pl > 0 and (p2l <= 0 or pl <= p2l)
    low_held = low_made and cl > 0 and cl >= pl
    low_score = 2.0 if low_held else 1.0 if low_made else 0.0

    dist_pct = ((cc / ph) - 1.0) * 100.0 if ph > 0 and cc > 0 else -99.0
    if dist_pct <= -0.8:
        breakout_score = 0.0
    elif dist_pct < -0.4:
        breakout_score = 1.0
    elif dist_pct < 0.0:
        breakout_score = 2.0
    elif dist_pct <= 0.3:
        breakout_score = 4.0
    elif dist_pct <= 0.8:
        breakout_score = 3.5
    else:
        breakout_score = 3.0

    body_pct = ((cc / co) - 1.0) * 100.0 if co > 0 and cc > 0 else -99.0
    if body_pct <= 0:
        candle_score = 0.0
    elif body_pct < 0.10:
        candle_score = 1.0
    elif body_pct < 0.30:
        candle_score = 1.5
    else:
        candle_score = 2.0

    raw = pullback + low_score + breakout_score + candle_score
    score = round(_clamp(max(1.0, raw), 1.0, 10.0), 1)
    breakout = ph > 0 and cc > ph
    bullish = co > 0 and cc > co
    gate = bool(score >= 7.0 and breakout and bullish)
    return score, gate, {
        "ready": True, "bars": len(use), "source": "official_1m",
        "decline_bearish": prev_bear, "decline_lower_close": lower_close,
        "low_formed": low_made, "low_held": low_held,
        "previous_high": ph, "price": cc, "distance_from_prev_high_pct": round(dist_pct, 3),
        "current_open": co, "current_bullish": bullish, "body_pct": round(body_pct, 3),
        "score_parts": {
            "pullback2": pullback, "low2": low_score,
            "breakout4": breakout_score, "candle2": candle_score,
        },
        "gate_rule": "score>=7 + previous-high breakout + bullish current 1m",
    }


def _execution(core, q, now_ts):
    strength = _f(getattr(q, "execution_strength", getattr(q, "volume_power", 0)))
    if strength >= 110.0:
        return 12.0, True, f"체결강도 {strength:.1f} · 110 이상 즉시통과"
    if strength < 90.0:
        return 1.0, False, f"체결강도 {strength:.1f} · 90 미만"
    hist = []
    for row in list(getattr(q, "execution_history", []) or []):
        try:
            hist.append((float(row[0]), float(row[1])))
        except Exception:
            continue
    if len(hist) < 2:
        return 1.0, False, f"체결강도 {strength:.1f} · 50초 추세 부족"
    end = _f(now_ts, hist[-1][0])
    vals = []
    for age in (50, 40, 30, 20, 10, 0):
        target = end - age
        near = [x for x in hist if target - 7.5 <= x[0] <= target + 2.5]
        if not near:
            return 1.0, False, f"체결강도 {strength:.1f} · 50초 추세 부족"
        vals.append(min(near, key=lambda x: abs(x[0] - target))[1])
    ok = min(vals) >= 90.0 and all(vals[i + 1] - vals[i] >= 0.5 for i in range(5))
    if not ok:
        return 1.0, False, f"체결강도 {strength:.1f} · 10초당 +0.5 조건 미충족"
    return 12.0, True, f"체결강도 {strength:.1f} · 50초 상승조건 통과"


def _tech_calc(core, q, market, now_dt, old_c1):
    import engine
    import namuh_conditions_final_patch as c

    bars = _official_1m(core, market, q.code, getattr(q, "price", 0))
    closes = [_f(b.get("close")) for b in bars if _f(b.get("close")) > 0]
    if len(closes) < 35:
        prev = dict(old_c1.get("standard_raw") or {})
        actual = {k: _clamp(prev.get(k), 0, mx) for k, mx in TECH_MAX.items()}
        scored = {k: _floor1(actual[k], mx) for k, mx in TECH_MAX.items()}
        meta = dict(old_c1.get("technical_meta") or {})
        meta.update({"source": "previous_score_fallback", "official_1m_bars": len(closes)})
        return actual, scored, meta

    m, sig = _macd_standard(closes)
    rv = _rsi_wilder(closes, 14)
    mid, upper, lower = _bollinger_standard(closes, 20, 2.0)
    price = _f(getattr(q, "price", 0), closes[-1])

    macd_pts = _clamp(engine.macd_points(m, sig), 0, 10)
    rsi_pts = _clamp(engine.rsi_points(rv), 0, 10)
    boll_pts = _clamp(engine.bollinger_points(price, lower, mid, upper), 0, 10)
    ma_pts, ma_reason = engine.moving_average_points(closes, price)

    today = c._market_clock(market, now_dt).strftime("%Y%m%d")
    temp = copy(q)
    temp.prices = deque(closes[-480:], maxlen=480)
    struct_pts, struct_meta = c._price_structure10(temp, today)

    ell_pts = 0.0
    ell_reason = ""
    try:
        qell = copy(q)
        db = [dict(x) for x in list(getattr(q, "daily_bars", []) or [])
              if isinstance(x, dict) and _f(x.get("close")) > 0]
        if price > 0:
            db = [x for x in db if _digits(x.get("date") or x.get("time"))[:8] != today]
            db.append({
                "date": today,
                "open": _f(getattr(q, "open", 0), price),
                "high": max(_f(getattr(q, "high", 0), price), price),
                "low": min(_f(getattr(q, "low", 0), price), price),
                "close": price,
                "volume": _f(getattr(q, "volume", 0)),
            })
        qell.daily_bars = db
        ell_pts, ell_reason = engine.elliott_points(qell, False)
    except Exception as exc:
        ell_reason = f"elliott:{exc}"

    old_meta = dict(old_c1.get("technical_meta") or {})
    vr = old_meta.get("volume_ratio")
    if vr is None:
        floor_flags = dict(old_meta.get("floor1_applied") or {})
        old_vol = _f((old_c1.get("standard_raw") or {}).get("거래량"))
        vol_pts = 0.0 if floor_flags.get("거래량") and old_vol <= 1.0 else old_vol
    else:
        vol_pts = c._interp_volume15(_f(vr))

    actual = {
        "MACD": round(macd_pts, 1),
        "RSI": round(rsi_pts, 1),
        "볼린저": round(boll_pts, 1),
        "거래량": round(_clamp(vol_pts, 0, 15), 1),
        "이평": round(_clamp(ma_pts, 0, 10), 1),
        "가격구조": round(_clamp(struct_pts, 0, 10), 1),
        "엘리어트": round(_clamp(ell_pts, 0, 10), 1),
    }
    scored = {k: round(_floor1(actual[k], mx), 1) for k, mx in TECH_MAX.items()}
    meta = dict(old_meta)
    meta.update({
        "source": "official_1m_unified",
        "official_1m_bars": len(closes),
        "technical_values": {
            "MACD": round(m, 6), "MACD_signal": round(sig, 6),
            "RSI14_Wilder": round(rv, 2),
            "Bollinger_lower": None if lower is None else round(lower, 4),
            "Bollinger_mid": None if mid is None else round(mid, 4),
            "Bollinger_upper": None if upper is None else round(upper, 4),
            "price": price,
        },
        "technical_reasons": {
            "이평": str(ma_reason or ""),
            "가격구조": struct_meta,
            "엘리어트": str(ell_reason or ""),
        },
        "actual_before_floor": actual,
        "floor1_applied": {k: actual[k] < 1.0 for k in TECH_MAX},
        "complete": True,
        "missing": [],
    })
    return actual, scored, meta


def apply(ns=None):
    global _INSTALLED
    if _INSTALLED:
        return True
    core = ns.get("core") if isinstance(ns, dict) else None
    if core is None:
        return False

    old_candidate = core.candidate
    if getattr(old_candidate, "_namuh_c1_integrity", False):
        _INSTALLED = True
        return True

    def candidate(*args, **kwargs):
        out = old_candidate(*args, **kwargs)
        if not isinstance(out, dict):
            return out
        try:
            q = args[0] if args else kwargs.get("q")
            market = str(args[1] if len(args) > 1 else kwargs.get("market", "")).upper()
            smart = bool(args[2] if len(args) > 2 else kwargs.get("smart", False))
            if q is None or smart or market not in ("KR", "US"):
                return out
            c1 = dict(out.get("condition1") or {})
            if not c1:
                return out
            now_dt = kwargs.get("now")
            if now_dt is None and len(args) > 7:
                now_dt = args[7]
            now_dt = (now_dt or datetime.now(core.KST)).astimezone(core.KST)

            bd = dict(c1.get("breakdown") or {})
            gates = dict(c1.get("gates") or {})

            minute10, minute_ok, minute_meta = _minute_score(core, q, market, now_dt)
            execution12, exec_ok, exec_reason = _execution(core, q, now_dt.timestamp())
            actual_raw, scored_raw, techmeta = _tech_calc(core, q, market, now_dt, c1)

            bd["daily10"] = round(_floor1(bd.get("daily10"), 10), 1)
            bd["minute10"] = minute10
            bd["execution12"] = execution12
            bd["orderbook8"] = round(_floor1(bd.get("orderbook8"), 8), 1)
            raw_total = sum(scored_raw[k] for k in TECH_MAX)
            standard45 = round(_clamp(raw_total / 75.0 * 45.0, 0, 45), 1)
            bd["standard45"] = standard45

            prereq40 = round(
                _f(bd.get("daily10")) + _f(bd.get("minute10")) +
                _f(bd.get("execution12")) + _f(bd.get("orderbook8")), 1
            )
            bonus15 = round(
                _f(bd.get("sector_relative7_5")) +
                _f(bd.get("leading_sector_flow3_75")) +
                _f(bd.get("news3_75")), 1
            )
            blocked = bool(gates.get("event_block", False))
            total = round(_clamp(prereq40 + standard45 + bonus15, 0, 100), 1)
            if blocked:
                total = 0.0

            gates["minute1m"] = minute_ok
            gates["execution"] = exec_ok
            threshold = _f(c1.get("entry_threshold"), 72.0)
            hard = bool(
                gates.get("daily", False) and minute_ok and exec_ok and
                gates.get("orderbook", False)
            )
            gate = bool(not blocked and hard and total >= threshold)
            gates["total72"] = total >= threshold

            audit = dict(c1.get("zero_audit") or {})
            audit["분봉"] = "SCORED"
            audit["체결강도"] = "SCORED"
            for k in TECH_MAX:
                audit[k] = "SCORED"

            c1.update({
                "score": total,
                "gate": gate,
                "breakdown": bd,
                "standard_raw": scored_raw,
                "standard_raw_before_floor": actual_raw,
                "gates": gates,
                "minute_meta": minute_meta,
                "execution_strength": round(_f(getattr(q, "execution_strength", 0)), 2),
                "execution_reason": exec_reason,
                "technical_meta": techmeta,
                "prerequisite_score": prereq40,
                "standard_score": standard45,
                "bonus_score": bonus15,
                "zero_audit": audit,
                "score_status": "READY",
                "score_complete": True,
                "integrity_model": "official 1m unified + Wilder RSI14 + C1 floor1",
            })
            out["condition1"] = c1
            out["condition1_score"] = total
            out["score"] = total
            out["priority_score"] = total

            c2 = dict(out.get("condition2") or {})
            if c2:
                c2b = dict(c2.get("breakdown") or {})
                s = _f(getattr(q, "execution_strength", 0))
                if exec_ok:
                    exec40 = 40.0 if s >= 110 else round(20.0 + _clamp((s - 90.0) / 20.0, 0, 1) * 20.0, 1)
                else:
                    exec40 = 0.0
                vol25 = round(_clamp(actual_raw["거래량"] / 15.0 * 25.0, 0, 25), 1)
                actual_std45 = _clamp(sum(actual_raw[k] for k in TECH_MAX) / 75.0 * 45.0, 0, 45)
                tech5 = round(_clamp(actual_std45 / 45.0 * 5.0, 0, 5), 1)
                c2b["execution40"] = exec40
                c2b["volume25"] = vol25
                c2b["technical5"] = tech5
                c2total = round(_clamp(
                    exec40 + _f(c2b.get("orderbook25")) + vol25 +
                    _f(c2b.get("change5")) + tech5, 0, 100
                ), 1)
                bench = dict(c2.get("market_1m") or {})
                long_ready = bool(c2.get("long_daily_ready"))
                c2gate = bool(not blocked and c2total > _f(c2.get("entry_threshold"), 70.0)
                              and bench.get("ready") and bench.get("up") and long_ready)
                c2.update({
                    "score": c2total, "gate": c2gate, "breakdown": c2b,
                    "priority": [exec40, _f(c2b.get("orderbook25")), vol25, tech5, _f(c2b.get("change5"))],
                    "execution_reason": exec_reason,
                    "integrity_model": "corrected execution + pre-floor technical inputs",
                })
                out["condition2"] = c2
                out["condition2_score"] = c2total
                out["condition2_gate_pass"] = c2gate

            labels = [x for x in list(out.get("condition_labels") or []) if str(x) not in ("조건1", "조건2")]
            if gate:
                labels.insert(0, "조건1")
            if (out.get("condition2") or {}).get("gate"):
                labels.append("조건2")
            labels = list(dict.fromkeys(labels))
            out["condition_labels"] = labels
            out["condition_display"] = "복합조건" if len([x for x in labels if str(x).startswith("조건")]) > 1 else (labels[0] if labels else "")
        except Exception as exc:
            out["score_integrity_error"] = str(exc)[:220]
        return out

    candidate._namuh_c1_integrity = True
    core.candidate = candidate

    old_health = getattr(core, "health_payload", None)
    if callable(old_health):
        def health():
            d = dict(old_health())
            d["c1_score_integrity"] = {
                "active": True,
                "minute": "2+2+4+2, floor1, gate>=7+breakout+bullish",
                "execution": ">=110 immediate 12/12; 90-110 50sec trend; <90 fail",
                "technical_source": "official 1m unified",
                "rsi": "Wilder RSI14, original recipe points",
            }
            return d
        core.health_payload = health

    _INSTALLED = True
    print("NAMUH C1 SCORE INTEGRITY active: minute/exec/7-tech unified on official 1m", flush=True)
    return True
