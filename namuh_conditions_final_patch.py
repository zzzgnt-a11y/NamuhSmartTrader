from __future__ import annotations

import math
import threading
import time
from collections import deque
from datetime import datetime
from zoneinfo import ZoneInfo

_INSTALLED = False
_STATE_KEY = "conditions_final_v1"
_VOLUME_KEY = "condition_volume15_history_v1"
_FEE_BUFFER = 0.05
_C1_THRESHOLD = 72.0
_C2_THRESHOLD = 70.0

# KR condition windows (KST). US retains its current market-specific 22:00~24:00 window.
_KR_C1_AM = (9 * 60, 9 * 60 + 20)
_KR_C1_PM = (13 * 60, 14 * 60)
_KR_C2_AM = (9 * 60, 9 * 60 + 45)
_KR_C2_PM = (13 * 60, 14 * 60)
_KR_C3_MON_AM = (9 * 60, 10 * 60)
_KR_C3_MON_PM = (13 * 60, 14 * 60)
_KR_C3_BUY_AM = (10 * 60 + 30, 13 * 60)
_KR_C3_BUY_PM = (14 * 60, 15 * 60 + 25)
_US_ENTRY = (22 * 60, 24 * 60)
_US_C3_MON = (20 * 60, 22 * 60)


def _f(v, default=0.0):
    try:
        return float(v)
    except Exception:
        return float(default)


def _clamp(v, lo=0.0, hi=100.0):
    return max(lo, min(hi, _f(v)))


def _mins(dt):
    return int(dt.hour) * 60 + int(dt.minute)


def _in_window(m, w, inclusive_end=True):
    return w[0] <= m <= w[1] if inclusive_end else w[0] <= m < w[1]


def _blocked(q):
    blocked = bool(getattr(q, "event_blocked", False))
    try:
        blocked = blocked or any(bool(e.get("blocked")) for e in list(getattr(q, "events", []) or []) if isinstance(e, dict))
    except Exception:
        pass
    return blocked


def _walk(v):
    if isinstance(v, dict):
        yield v
        for x in v.values():
            yield from _walk(x)
    elif isinstance(v, (list, tuple)):
        for x in v:
            yield from _walk(x)


def _pick_num(data, keys):
    for obj in _walk(data):
        if not isinstance(obj, dict):
            continue
        for k in keys:
            if k in obj and obj[k] not in (None, ""):
                try:
                    return float(str(obj[k]).replace(",", "").replace("+", "").strip())
                except Exception:
                    pass
    return 0.0


def _orderbook_ratio(core, q, market):
    """Sell queue / buy queue. Quantity only; never substitutes ask/bid prices."""
    ask = 0.0
    bid = 0.0
    for k in ("total_ask_qty", "ask_total_qty", "ask_qty", "askp_rsqn1", "ask_rsqn", "ovrs_ask_qty"):
        ask = _f(getattr(q, k, 0))
        if ask > 0:
            break
    for k in ("total_bid_qty", "bid_total_qty", "bid_qty", "bidp_rsqn1", "bid_rsqn", "ovrs_bid_qty"):
        bid = _f(getattr(q, k, 0))
        if bid > 0:
            break
    # PC minute-sync may contain actual queue quantities even when currentPrice does not.
    if (ask <= 0 or bid <= 0) and str(market).upper() == "KR":
        try:
            with core.MINUTE_SYNC_LOCK:
                row = dict((core.MINUTE_SYNC.get("rows") or {}).get(str(q.code).upper()) or {})
        except Exception:
            row = {}
        if ask <= 0:
            ask = _pick_num(row, ("total_ask_qty", "ask_total_qty", "ask_qty", "askp_rsqn1", "ask_rsqn"))
        if bid <= 0:
            bid = _pick_num(row, ("total_bid_qty", "bid_total_qty", "bid_qty", "bidp_rsqn1", "bid_rsqn"))
    ratio = ask / bid if ask > 0 and bid > 0 else None
    return ratio, ask, bid


def _order8(r):
    if r is None:
        return 0.0
    r = _f(r)
    if r >= 2.0:
        return 8.0
    if r >= 1.5:
        return 7.0
    if r >= 1.3:
        return 5.0
    if r >= 1.1:
        return 4.0
    if r >= 1.0:
        return 3.0
    if r >= 0.9:
        return 2.0
    return 0.0


def _execution_gate(q, now_ts=None, history=None):
    strength = _f(getattr(q, "execution_strength", getattr(q, "volume_power", 0)))
    if strength >= 110:
        return True, "체결강도 110+"
    if strength < 90:
        return False, "체결강도 90 미만"
    hist = list(history if history is not None else getattr(q, "execution_history", []) or [])
    if len(hist) < 2:
        return False, "체결강도 50초 추세 축적 중"
    end = _f(now_ts, hist[-1][0])
    vals = []
    for age in (50, 40, 30, 20, 10, 0):
        target = end - age
        rows = [x for x in hist if target - 7.5 <= _f(x[0]) <= target + 2.5]
        if not rows:
            return False, "체결강도 50초 추세 축적 중"
        vals.append(_f(min(rows, key=lambda x: abs(_f(x[0]) - target))[1]))
    if min(vals) < 90:
        return False, "체결강도 90 미만 구간"
    if all(vals[i + 1] - vals[i] >= 0.5 for i in range(5)):
        return True, "체결강도 90+ · 10초당 +0.5 · 50초"
    return False, "체결강도 상승속도 부족"


def _execution12(q, ok):
    return 12.0 if ok else 0.0


def _execution40(q, ok):
    if not ok:
        return 0.0
    s = _f(getattr(q, "execution_strength", getattr(q, "volume_power", 0)))
    if s >= 110:
        return 40.0
    # Passed 90~110 rising rule: retain priority differentiation without inventing another gate.
    return round(20.0 + _clamp((s - 90.0) / 20.0, 0, 1) * 20.0, 1)


def _date_digits(v):
    return "".join(ch for ch in str(v or "") if ch.isdigit())[:8]


def _completed_daily(q, today):
    rows = []
    for b in list(getattr(q, "daily_bars", []) or []):
        if not isinstance(b, dict):
            continue
        d = _date_digits(b.get("date") or b.get("time"))
        c = _f(b.get("close"))
        if c <= 0:
            continue
        if d and d >= today:
            continue
        rows.append({
            "date": d, "open": _f(b.get("open"), c), "high": _f(b.get("high"), c),
            "low": _f(b.get("low"), c), "close": c, "volume": _f(b.get("volume")),
        })
    return rows


def _daily10(q, today):
    rows = _completed_daily(q, today)
    if not rows:
        return 0.0, False, {"ready": False}
    prev = rows[-1]
    low, high = _f(prev.get("low")), _f(prev.get("high"))
    px = _f(getattr(q, "price", 0))
    if low <= 0 or high <= low or px <= 0:
        return 0.0, False, {"ready": False}
    ref = low + (high - low) * 0.5
    ok = px > ref
    return (10.0 if ok else 0.0), ok, {"ready": True, "prev_low": low, "prev_high": high, "midpoint": ref, "price": px}


def _minute_reversal10(core, q, market):
    try:
        bars = [dict(x) for x in list(core.feed.bars(market, q.code, "1m") or []) if isinstance(x, dict)]
    except Exception:
        bars = []
    if len(bars) < 3:
        return 0.0, False, {"ready": False, "bars": len(bars)}
    prev2, prev, cur = bars[-3], bars[-2], bars[-1]
    p2c = _f(prev2.get("close")); po = _f(prev.get("open")); pc = _f(prev.get("close")); pl = _f(prev.get("low")); p2l = _f(prev2.get("low")); ph = _f(prev.get("high"))
    co = _f(cur.get("open")); cc = _f(getattr(q, "price", 0), _f(cur.get("close")))
    decline = bool(pc < po or (p2c > 0 and pc < p2c))
    low_formed = bool(pl > 0 and (p2l <= 0 or pl <= p2l))
    breakout = bool(ph > 0 and cc > ph)
    bullish = bool(co > 0 and cc > co)
    ok = bool(decline and low_formed and breakout and bullish)
    return (10.0 if ok else 0.0), ok, {
        "ready": True, "decline": decline, "low_formed": low_formed,
        "previous_high": ph, "breakout": breakout, "current_bullish": bullish,
    }


def _price_structure10(q, today):
    completed = _completed_daily(q, today)
    px = _f(getattr(q, "price", 0))
    low_today = _f(getattr(q, "low", 0), px)
    high_today = _f(getattr(q, "high", 0), px)
    if px <= 0:
        return 0.0, {"three": 0.0, "box": 0.0, "reason": "현재가 대기"}
    today_row = {"date": today, "open": _f(getattr(q, "open", 0), px), "high": high_today or px, "low": low_today or px, "close": px}

    three_score = 0.0
    three_ok = False
    if len(completed) >= 2:
        a, b = completed[-2], completed[-1]
        close_up = _f(a["close"]) < _f(b["close"]) < px
        low_up = _f(a["low"]) < _f(b["low"]) < _f(today_row["low"])
        if close_up and low_up:
            three_score = 10.0
            three_ok = True
        elif close_up:
            three_score = 7.0
            three_ok = True

    box_score = 0.0
    box_ok = False
    ten = (completed[-9:] + [today_row]) if len(completed) >= 9 else []
    box_meta = {}
    if len(ten) == 10:
        lo = min(_f(x.get("low")) for x in ten if _f(x.get("low")) > 0)
        hi = max(_f(x.get("high")) for x in ten)
        lower = lo * 1.10
        upper = hi * 0.90
        if lo > 0 and hi > lo and upper > lower and lower <= px <= upper:
            box_ok = True
            pos = (px - lower) / max(upper - lower, 1e-9) * 100.0
            if pos <= 15:
                box_score = 10.0
            elif pos <= 30:
                box_score = 8.0
            elif pos <= 40:
                box_score = 5.0
            elif pos <= 50:
                box_score = 2.0
            elif pos <= 60:
                box_score = 1.0
            else:
                box_score = 0.0
            box_meta = {"low10": lo, "high10": hi, "lower": lower, "upper": upper, "position_pct": round(pos, 1)}
    if three_ok and box_ok:
        final = (three_score + box_score) / 2.0
    elif three_ok:
        final = three_score
    elif box_ok:
        final = box_score
    else:
        final = 0.0
    return round(final, 1), {"three": three_score, "three_applicable": three_ok, "box": box_score, "box_applicable": box_ok, **box_meta}


def _interp_volume15(ratio):
    if ratio is None:
        return 0.0
    r = _f(ratio)
    pts = [(0.5, 0.0), (0.6, 1.0), (0.7, 3.0), (0.8, 6.0), (0.9, 9.0), (1.0, 10.0), (1.1, 12.5), (1.2, 14.0), (1.3, 15.0)]
    if r <= pts[0][0]:
        return 0.0
    if r >= pts[-1][0]:
        return 15.0
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if x0 <= r <= x1:
            return round(y0 + (r - x0) / (x1 - x0) * (y1 - y0), 1)
    return 0.0


def _market_clock(market, now):
    if str(market).upper() == "US":
        return now.astimezone(ZoneInfo("America/New_York"))
    return now


def _volume_ratio_same_time(volume_state, market, code, current_volume, now):
    dt = _market_clock(market, now)
    day = dt.strftime("%Y%m%d")
    minute = dt.hour * 60 + dt.minute
    m = str(market).upper(); c = str(code).upper()
    md = volume_state.setdefault(m, {}).setdefault(c, {})
    today = md.setdefault(day, {})
    if current_volume >= 0:
        today[str(minute)] = float(current_volume)
    # retain newest 16 session dates only
    for old_day in sorted(md)[:-16]:
        md.pop(old_day, None)
    prior_days = [d for d in sorted(md) if d < day][-15:]
    vals = []
    for d in prior_days:
        snapshots = md.get(d) or {}
        candidates = []
        for k, v in snapshots.items():
            try:
                km = int(k)
            except Exception:
                continue
            if km <= minute and minute - km <= 3:
                candidates.append((km, _f(v)))
        if candidates:
            vals.append(max(candidates, key=lambda x: x[0])[1])
    # Final rule uses the prior 15 trading sessions at the same clock time.
    # Until all 15 are accumulated, the volume component stays at 0 rather than
    # substituting a different statistic.
    if len(vals) < 15 or _f(current_volume) <= 0:
        return None, len(vals)
    avg = sum(vals) / 15.0
    return (_f(current_volume) / avg if avg > 0 else None), len(vals)


def _standard45(core, q, market, sec_score, stock_score, now, volume_state):
    try:
        a = core.scalp_analysis(q, sec_score, stock_score, market, now)
    except Exception:
        try:
            import engine
            a = engine.scalp_analysis(q, sec_score, stock_score, market, now)
        except Exception:
            a = {"breakdown": {}}
    b = dict((a or {}).get("breakdown") or {})
    today = _market_clock(market, now).strftime("%Y%m%d")
    vr, sample_days = _volume_ratio_same_time(volume_state, market, q.code, _f(getattr(q, "volume", 0)), now)
    vol15 = _interp_volume15(vr)
    struct10, struct_meta = _price_structure10(q, today)
    raw = {
        "MACD": _clamp(b.get("MACD"), 0, 10),
        "RSI": _clamp(b.get("RSI"), 0, 10),
        "볼린저": _clamp(b.get("볼린저"), 0, 10),
        "거래량": _clamp(vol15, 0, 15),
        "이평": _clamp(b.get("이평"), 0, 10),
        "가격구조": _clamp(struct10, 0, 10),
        "엘리어트": _clamp(b.get("엘리어트"), 0, 10),
    }
    raw_total = sum(raw.values())
    std45 = round(_clamp(raw_total / 75.0 * 45.0, 0, 45), 1)
    return std45, raw, {"volume_ratio": None if vr is None else round(vr, 3), "volume_history_days": sample_days, "price_structure": struct_meta}


def _bonus15(core, q, out, sector_rankmap):
    # Keep the already-live ranking inputs, only rescale to the finalized 7.5/3.75/3.75 structure.
    leading5 = 0.0
    inner5 = 0.0
    try:
        import namuh_condition1_v2_patch as c1old
        leading5, _, _ = c1old._leading_sector5(core, q, out, sector_rankmap)
        inner5, _, _ = c1old._sector_inner_flow5(core, q)
    except Exception:
        try:
            rank = int(out.get("sector_rank") or 999)
        except Exception:
            rank = 999
        leading5 = 5.0 if rank == 1 else 4.0 if rank == 2 else 3.0 if rank == 3 else 2.0 if rank == 4 else 1.0 if rank == 5 else 0.0
        inner5 = _clamp((out.get("score_components") or {}).get("sector_flow5"), 0, 5)
    news5 = _clamp(out.get("fresh_event_points", (out.get("score_components") or {}).get("news5", 0)), 0, 5)
    sector75 = round(_clamp(leading5 / 5.0 * 7.5, 0, 7.5), 2)
    flow375 = round(_clamp(inner5 / 5.0 * 3.75, 0, 3.75), 2)
    news375 = round(_clamp(news5 / 5.0 * 3.75, 0, 3.75), 2)
    return round(sector75 + flow375 + news375, 2), {"sector_relative7_5": sector75, "leading_sector_flow3_75": flow375, "news3_75": news375}


def _benchmark_1m(core, market, now):
    key = "kospi" if str(market).upper() == "KR" else "nasdaq"
    try:
        bars = list(core.feed.market_bars(key, "1m") or [])
    except Exception:
        bars = []
    if not bars:
        return {"ready": False, "up": False, "market": key.upper()}
    # market_bars only contains completed buckets plus current. Exclude current minute by timestamp when possible.
    local = _market_clock(market, now)
    bucket = int(local.timestamp() // 60) * 60
    completed = []
    has_timestamp = any(_f(b.get("time")) > 0 for b in bars if isinstance(b, dict))
    if has_timestamp:
        for b in bars:
            ts = _f(b.get("time")) if isinstance(b, dict) else 0
            if ts and ts < bucket:
                completed.append(b)
    else:
        completed = bars[:-1] if len(bars) >= 2 else []
    if not completed and len(bars) >= 2:
        completed = bars[:-1]
    if not completed:
        return {"ready": False, "up": False, "market": key.upper()}
    b = completed[-1]
    o, c = _f(b.get("open")), _f(b.get("close"))
    return {"ready": o > 0 and c > 0, "up": bool(c > o > 0), "market": key.upper(), "open": o, "close": c, "time": b.get("time")}


def _change5(q, completed):
    prev_close = _f(completed[-1].get("close")) if completed else 0.0
    px = _f(getattr(q, "price", 0))
    if prev_close <= 0 or px <= 0:
        return 0.0, None
    ch = (px / prev_close - 1.0) * 100.0
    if ch <= 0:
        p20 = 0.0
    elif ch < 1:
        p20 = 4.0 * ch
    elif ch < 2:
        p20 = 4.0 + (ch - 1.0) * 4.0
    elif ch < 3:
        p20 = 8.0 + (ch - 2.0) * 4.0
    elif ch < 5:
        p20 = 12.0 + (ch - 3.0) * 4.0
    else:
        p20 = 20.0
    return round(_clamp(p20 / 20.0 * 5.0, 0, 5), 1), round(ch, 3)


def _score_rising(hist):
    h = list(hist or [])
    if len(h) < 3:
        return False
    a, b, c = [_f(x[1]) for x in h[-3:]]
    return a < b < c


def _score_exit(hist):
    h = list(hist or [])
    if len(h) < 3:
        return False, ""
    a, b, c = [_f(x[1]) for x in h[-3:]]
    if b > a and c <= b:
        return True, f"3분 점수 고립상승 {a:.1f}→{b:.1f}→{c:.1f}"
    if c <= b - 0.4:
        return True, f"3분 점수 하락 {b:.1f}→{c:.1f}"
    return False, ""


def _c3_zone_transitions(samples):
    """Internal detector: lower/upper extremes are 15%/85% of the observed range."""
    vals = [_f(x[1]) for x in samples if _f(x[1]) > 0]
    if len(vals) < 5:
        return 0, None
    lo, hi = min(vals), max(vals)
    if lo <= 0 or hi <= lo or (hi - lo) / lo * 100.0 < 3.0:
        return 0, {"low": lo, "high": hi, "width_pct": ((hi - lo) / lo * 100.0 if lo > 0 else 0.0)}
    last = None; transitions = 0
    for p in vals:
        pos = (p - lo) / (hi - lo)
        z = "L" if pos <= 0.15 else "H" if pos >= 0.85 else None
        if z is not None and z != last:
            if last is not None:
                transitions += 1
            last = z
    return transitions, {"low": lo, "high": hi, "width_pct": (hi - lo) / lo * 100.0, "last_zone": last}


def _c3_current_pos(px, low, high):
    if low <= 0 or high <= low:
        return None
    return (px - low) / (high - low)


def _session_tag_kr(now):
    m = _mins(now)
    if _in_window(m, _KR_C3_MON_AM, False):
        return now.strftime("%Y%m%d") + "_AM"
    if _in_window(m, _KR_C3_MON_PM, False):
        return now.strftime("%Y%m%d") + "_PM"
    if _in_window(m, _KR_C3_BUY_AM, False):
        return now.strftime("%Y%m%d") + "_AM"
    if _in_window(m, _KR_C3_BUY_PM, True):
        return now.strftime("%Y%m%d") + "_PM"
    return ""


def apply(ns):
    global _INSTALLED
    if _INSTALLED:
        return True
    core = ns.get("core") if isinstance(ns, dict) else None
    if core is None:
        return False
    _INSTALLED = True

    lock = threading.RLock()
    try:
        state = core.store.load_json(_STATE_KEY, {}) or {}
    except Exception:
        state = {}
    if not isinstance(state, dict):
        state = {}
    state.setdefault("positions", {})
    try:
        volume_state = core.store.load_json(_VOLUME_KEY, {}) or {}
    except Exception:
        volume_state = {}
    if not isinstance(volume_state, dict):
        volume_state = {}
    last_volume_save = [0.0]
    score_hist = {}
    score_last = {}
    exec_hist_coin = {}
    c3_hist = {"KR": {}, "US": {}}
    c3_session = {"KR": "", "US": ""}
    c3_qualified = {"KR": {}, "US": {}}
    coin_chart_cache = {}

    def persist(force=False):
        now_ts = time.time()
        try:
            core.store.save_json(_STATE_KEY, state)
        except Exception:
            pass
        if force or now_ts - last_volume_save[0] >= 300:
            last_volume_save[0] = now_ts
            try:
                core.store.save_json(_VOLUME_KEY, volume_state)
            except Exception:
                pass

    # Capture quantity fields if the already-used quote endpoint exposes them.
    try:
        from nhfeed import pick
        for name in ("_apply_kr", "_apply_us"):
            old_apply = getattr(core.feed, name, None)
            if not callable(old_apply) or getattr(old_apply, "_namuh_final_book_qty", False):
                continue
            def make_wrapper(fn, market):
                def wrapped(code, data):
                    fn(code, data)
                    q = core.feed.q(market, code)
                    ask_total = pick(data, ("total_ask_qty", "ask_total_qty", "total_askp_rsqn", "askp_rsqn_tot"))
                    bid_total = pick(data, ("total_bid_qty", "bid_total_qty", "total_bidp_rsqn", "bidp_rsqn_tot"))
                    ask1 = pick(data, ("ask_qty", "askp_rsqn1", "ask_rsqn", "ovrs_ask_qty"))
                    bid1 = pick(data, ("bid_qty", "bidp_rsqn1", "bid_rsqn", "ovrs_bid_qty"))
                    if ask_total > 0: setattr(q, "total_ask_qty", ask_total)
                    if bid_total > 0: setattr(q, "total_bid_qty", bid_total)
                    if ask1 > 0: setattr(q, "ask_qty", ask1)
                    if bid1 > 0: setattr(q, "bid_qty", bid1)
                wrapped._namuh_final_book_qty = True
                return wrapped
            setattr(core.feed, name, make_wrapper(old_apply, "KR" if name == "_apply_kr" else "US"))
    except Exception:
        pass

    old_candidate = core.candidate

    def candidate(q, market, smart=False, secmap=None, stockmap=None, leadermap=None, sector_rankmap=None, now=None):
        out = old_candidate(q, market, smart, secmap, stockmap, leadermap, sector_rankmap, now)
        mkt = str(market or "").upper()
        if smart or mkt not in ("KR", "US") or not isinstance(out, dict):
            return out
        now_dt = (now or core.datetime.now(core.KST)).astimezone(core.KST)
        local_today = _market_clock(mkt, now_dt).strftime("%Y%m%d")
        sec = core.sector_name(q, mkt)
        sec_score = _f((secmap or {}).get(sec, out.get("sector_score", 0)))
        stock_score = _f((stockmap or {}).get(q.code, 0))

        daily10, daily_ok, daily_meta = _daily10(q, local_today)
        minute10, minute_ok, minute_meta = _minute_reversal10(core, q, mkt)
        try:
            exec_ok, exec_reason = _execution_gate(q, now_dt.timestamp())
        except Exception:
            exec_ok, exec_reason = False, "체결강도 확인 대기"
        exec12 = _execution12(q, exec_ok)
        ratio, ask_qty, bid_qty = _orderbook_ratio(core, q, mkt)
        order8 = _order8(ratio)
        order_ok = ratio is not None and ratio >= 0.9
        std45, rawtech, techmeta = _standard45(core, q, mkt, sec_score, stock_score, now_dt, volume_state)
        bonus15, bonusparts = _bonus15(core, q, out, sector_rankmap)
        prereq40 = round(daily10 + minute10 + exec12 + order8, 1)
        total = round(_clamp(prereq40 + std45 + bonus15, 0, 100), 1)
        blocked = _blocked(q)
        c1_gate = bool(not blocked and daily_ok and minute_ok and exec_ok and order_ok and total >= _C1_THRESHOLD)
        if blocked:
            total = 0.0

        completed = _completed_daily(q, local_today)
        vol25 = round(_clamp(rawtech.get("거래량", 0) / 15.0 * 25.0, 0, 25), 1)
        exec40 = _execution40(q, exec_ok)
        book25 = round(_clamp(order8 / 8.0 * 25.0, 0, 25), 1)
        ch5, ch_pct = _change5(q, completed)
        tech5 = round(_clamp(std45 / 45.0 * 5.0, 0, 5), 1)
        c2_total = round(_clamp(vol25 + exec40 + book25 + ch5 + tech5, 0, 100), 1)
        bench = _benchmark_1m(core, mkt, now_dt)
        long_ready = len(completed) >= 100
        c2_gate = bool(not blocked and c2_total > _C2_THRESHOLD and bench.get("ready") and bench.get("up") and long_ready)

        c1 = {
            "label": "조건1", "score": total, "gate": c1_gate, "entry_threshold": _C1_THRESHOLD,
            "prerequisite_score": prereq40, "standard_score": std45, "bonus_score": bonus15,
            "breakdown": {
                "daily10": daily10, "minute10": minute10, "execution12": exec12, "orderbook8": order8,
                "standard45": std45, **bonusparts,
            },
            "standard_raw": rawtech,
            "gates": {"daily": daily_ok, "minute1m": minute_ok, "execution": exec_ok, "orderbook": order_ok, "event_block": blocked, "total72": total >= _C1_THRESHOLD},
            "daily_meta": daily_meta, "minute_meta": minute_meta, "execution_reason": exec_reason,
            "orderbook": {"ratio": ratio, "ask_qty": ask_qty, "bid_qty": bid_qty},
            "technical_meta": techmeta,
            "model": "선행조건40 + 스탠다드45 + 추가가점15",
        }
        c2 = {
            "label": "조건2", "score": c2_total, "gate": c2_gate, "entry_threshold": _C2_THRESHOLD,
            "breakdown": {"volume25": vol25, "execution40": exec40, "orderbook25": book25, "change5": ch5, "technical5": tech5},
            "priority": [exec40, book25, vol25, tech5, ch5],
            "change_pct": ch_pct, "market_1m": bench, "long_daily_ready": long_ready, "history_days": len(completed),
            "orderbook": {"ratio": ratio, "ask_qty": ask_qty, "bid_qty": bid_qty},
            "execution_reason": exec_reason,
            "model": "체결40 + 호가25 + 거래량25 + 기술5 + 등락5",
        }
        out["score"] = total
        out["priority_score"] = total
        out["condition1"] = c1
        out["condition2"] = c2
        out["condition2_score"] = c2_total
        out["condition2_gate_pass"] = c2_gate
        # C3 candidate status is attached by the monitor/trade layer below.
        old_c3 = dict(out.get("condition3") or {})
        out["condition3"] = {"label": "조건3", "gate": False, "strategy": "횡보 종목 진입형", **{k: v for k, v in old_c3.items() if k in ("sector_rank",)}}
        labels = []
        if c1_gate:
            labels.append("조건1")
        if c2_gate:
            labels.append("조건2")
        out["condition_labels"] = labels
        out["condition_display"] = "복합조건" if len(labels) > 1 else (labels[0] if labels else "")
        reasons = [r for r in list(out.get("reasons") or []) if not str(r).startswith(("조건1", "조건2", "50/30/20", "레시피"))]
        reasons.insert(0, f"조건1 {total:.1f}/100 · 선행 {prereq40:.1f}/40 + 스탠다드 {std45:.1f}/45 + 가점 {bonus15:.1f}/15")
        reasons.insert(1, f"조건2 {c2_total:.1f}/100 · 체결 {exec40:.1f}/40 > 호가 {book25:.1f}/25 > 거래량 {vol25:.1f}/25 > 기술 {tech5:.1f}/5 > 등락 {ch5:.1f}/5")
        out["reasons"] = reasons[:12]
        persist(False)
        return out

    core.candidate = candidate

    def _sample_score(market, condition, code, score, ts):
        key = f"{market}:{condition}:{code}"
        if ts - _f(score_last.get(key)) < 175:
            return
        score_last[key] = ts
        score_hist.setdefault(key, deque(maxlen=8)).append((ts, _f(score)))

    def _hist(market, condition, code):
        return score_hist.get(f"{market}:{condition}:{code}", deque())

    def _kr_sync_universe():
        rows = {}
        try:
            with core.MINUTE_SYNC_LOCK:
                raw = dict(core.MINUTE_SYNC.get("rows") or {})
            for code, x in raw.items():
                if not isinstance(x, dict):
                    continue
                px = _pick_num(x, ("price", "current_price", "close", "stck_prpr", "now_price"))
                if px <= 0:
                    continue
                meta = (getattr(core.feed, "kr_master_meta", {}) or {}).get(str(code), {}) or {}
                rows[str(code)] = {"code": str(code), "price": px, "sector": str(x.get("sector") or meta.get("sector") or ""), "name": str(x.get("name") or meta.get("name") or code)}
        except Exception:
            pass
        if not rows:
            for code, q in list(core.feed.quotes_for("KR").items()):
                if _f(getattr(q, "price", 0)) > 0:
                    rows[str(code)] = {"code": str(code), "price": _f(q.price), "sector": core.sector_name(q, "KR"), "name": str(getattr(q, "name", "") or code)}
        return rows

    def _top3_sectors(market):
        try:
            arr = list((core.CACHE.get(market) or {}).get("sectors") or [])
            return {str(x.get("sector") or ""): i + 1 for i, x in enumerate(arr[:3]) if str(x.get("sector") or "")}
        except Exception:
            return {}

    def _monitor_c3_kr(now):
        tag = _session_tag_kr(now)
        m = _mins(now)
        monitoring = _in_window(m, _KR_C3_MON_AM, False) or _in_window(m, _KR_C3_MON_PM, False)
        if not tag:
            return
        if c3_session["KR"] != tag:
            c3_session["KR"] = tag
            c3_hist["KR"] = {}
            c3_qualified["KR"] = {}
        if not monitoring:
            return
        ts = now.timestamp()
        universe = _kr_sync_universe()
        top3 = _top3_sectors("KR")
        for code, row in universe.items():
            h = c3_hist["KR"].setdefault(code, deque(maxlen=180))
            if h and ts - _f(h[-1][0]) < 55:
                continue
            h.append((ts, _f(row.get("price"))))
            transitions, meta = _c3_zone_transitions(h)
            if not meta or transitions < 4:
                continue
            sector = str(row.get("sector") or "")
            sr = top3.get(sector)
            if not sr:
                continue
            c3_qualified["KR"][code] = {**meta, "transitions": transitions, "round_trips": transitions // 2, "sector": sector, "sector_rank": sr, "name": row.get("name"), "qualified_at": ts}
        # exactly up to three strongest candidates are kept for the session.
        ranked = sorted(c3_qualified["KR"].items(), key=lambda kv: (int(kv[1].get("round_trips") or 0), _f(kv[1].get("width_pct"))), reverse=True)[:3]
        c3_qualified["KR"] = dict(ranked)

    def _monitor_c3_us(candidates, now):
        m = _mins(now)
        if not _in_window(m, _US_C3_MON, False):
            return
        tag = now.strftime("%Y%m%d") + "_US"
        if c3_session["US"] != tag:
            c3_session["US"] = tag
            c3_hist["US"] = {}
            c3_qualified["US"] = {}
        ts = now.timestamp(); top3 = _top3_sectors("US")
        qmap = core.feed.quotes_for("US")
        for x in list(candidates or []):
            code = str(x.get("code") or "").upper(); q = qmap.get(code)
            if not q or _f(getattr(q, "price", 0)) <= 0:
                continue
            h = c3_hist["US"].setdefault(code, deque(maxlen=180))
            if h and ts - _f(h[-1][0]) < 55:
                continue
            h.append((ts, _f(q.price)))
            transitions, meta = _c3_zone_transitions(h)
            if not meta or transitions < 4:
                continue
            sector = core.sector_name(q, "US"); sr = top3.get(sector)
            if not sr:
                continue
            c3_qualified["US"][code] = {**meta, "transitions": transitions, "round_trips": transitions // 2, "sector": sector, "sector_rank": sr, "name": getattr(q, "name", code), "qualified_at": ts}
        ranked = sorted(c3_qualified["US"].items(), key=lambda kv: (int(kv[1].get("round_trips") or 0), _f(kv[1].get("width_pct"))), reverse=True)[:3]
        c3_qualified["US"] = dict(ranked)

    def _c3_rows(market):
        qmap = core.feed.quotes_for(market)
        out = []
        for code, meta in list(c3_qualified[market].items()):
            q = qmap.get(code)
            if market == "KR" and (q is None or _f(getattr(q, "price", 0)) <= 0):
                # PC sync can qualify a stock before NH live quote reaches it; entry still requires a tradable quote.
                try:
                    q = core.feed.q("KR", code)
                except Exception:
                    q = None
            px = _f(getattr(q, "price", 0)) if q is not None else 0.0
            pos = _c3_current_pos(px, _f(meta.get("low")), _f(meta.get("high")))
            if px > 0 and pos is not None and pos <= 0.15:
                out.append({"market": market, "code": code, "name": meta.get("name") or code, "price": px, "condition3": {"label": "조건3", "gate": True, **meta, "current_position": round(pos, 3)}})
        out.sort(key=lambda x: (int(x["condition3"].get("round_trips") or 0), _f(x["condition3"].get("width_pct"))), reverse=True)
        return out[:3]

    old_trade = core.trade_scalp

    def _buy_stock(item, market, condition, now, entry_session):
        code = str(item.get("code") or "").upper()
        if not code or f"{market}:{code}" in core.paper.positions or code in getattr(core, "protected", set()):
            return False
        if len(core.paper.market_positions(market)) >= 3:
            return False
        # The legacy C3 threshold wrapper is bypassed with the neutral SCALP label;
        # immediately after a successful fill the position/trade is relabeled to the finalized condition.
        buy_label = "SCALP" if condition == "조건3" else condition
        try:
            if not core._buy_one(market, item, buy_label, entry_session, now):
                return False
        except Exception:
            return False
        p = core.paper.positions.get(f"{market}:{code}")
        if p is not None:
            p.strategy = condition
        try:
            for t in list(core.paper.trades or []):
                if str(t.get("side") or "").upper() == "BUY" and str(t.get("market") or "").upper() == market and str(t.get("code") or "").upper() == code:
                    t["strategy"] = condition
                    break
        except Exception:
            pass
        meta = {"condition": condition, "entry_ts": _f(getattr(p, "entry_ts", now.timestamp()), now.timestamp()), "max_pnl_30m": -999.0, "loss_started": None}
        if condition == "조건3":
            meta.update(dict((item.get("condition3") or {})))
        state["positions"][f"{market}:{code}"] = meta
        try: core._persist_paper()
        except Exception: pass
        persist(True)
        return True

    def trade_scalp(market, candidates, now=None):
        mkt = str(market or "").upper()
        if mkt not in ("KR", "US"):
            return old_trade(market, candidates, now)
        now_dt = (now or core.datetime.now(core.KST)).astimezone(core.KST)
        ts = now_dt.timestamp(); m = _mins(now_dt)
        rows = list(candidates or [])
        for x in rows:
            code = str(x.get("code") or "").upper()
            if code:
                _sample_score(mkt, "조건1", code, x.get("score"), ts)
                _sample_score(mkt, "조건2", code, x.get("condition2_score"), ts)

        if mkt == "KR":
            _monitor_c3_kr(now_dt)
            c3_time = _in_window(m, _KR_C3_BUY_AM, False) or _in_window(m, _KR_C3_BUY_PM, True)
            if c3_time:
                for z in _c3_rows("KR"):
                    if _buy_stock(z, "KR", "조건3", now_dt, "C3_AM" if m < 13 * 60 else "C3_PM"):
                        return
            # C1: standard windows plus 3-minute continuously rising score exception while a KR trading session is open.
            sess = core.scalp_session(now_dt)
            for x in sorted(rows, key=lambda r: _f(r.get("score")), reverse=True):
                code = str(x.get("code") or "").upper()
                if not code or f"KR:{code}" in core.paper.positions:
                    continue
                c1 = bool((x.get("condition1") or {}).get("gate"))
                c1_time = _in_window(m, _KR_C1_AM) or _in_window(m, _KR_C1_PM)
                exception = sess in ("PRE08", "REGULAR", "LATE") and _score_rising(_hist("KR", "조건1", code))
                if c1 and (c1_time or exception):
                    session = "C1_AM" if _in_window(m, _KR_C1_AM) else "C1_PM" if _in_window(m, _KR_C1_PM) else ("C1_PRE" if sess == "PRE08" else "C1_LATE" if sess == "LATE" else "C1_SCORE_RISE")
                    if _buy_stock(x, "KR", "조건1", now_dt, session):
                        return
            # C2: no out-of-window exception; priority = execution > orderbook > volume > technical > change.
            c2_time = _in_window(m, _KR_C2_AM) or _in_window(m, _KR_C2_PM)
            if c2_time:
                ranked = sorted(rows, key=lambda r: tuple((r.get("condition2") or {}).get("priority") or [0, 0, 0, 0, 0]), reverse=True)
                for x in ranked:
                    if bool((x.get("condition2") or {}).get("gate")):
                        if _buy_stock(x, "KR", "조건2", now_dt, "C2_AM" if _in_window(m, _KR_C2_AM) else "C2_PM"):
                            return
            return

        # US keeps the existing market-specific clock windows; only condition internals are replaced.
        _monitor_c3_us(rows, now_dt)
        if _in_window(m, _US_ENTRY, False):
            for z in _c3_rows("US"):
                if _buy_stock(z, "US", "조건3", now_dt, "US_C3_22_24"):
                    return
        for x in sorted(rows, key=lambda r: _f(r.get("score")), reverse=True):
            code = str(x.get("code") or "").upper()
            if not code or f"US:{code}" in core.paper.positions:
                continue
            c1 = bool((x.get("condition1") or {}).get("gate"))
            c1_time = _in_window(m, _US_ENTRY, False)
            us_active = bool(core.trading_window(now_dt) == "US") if hasattr(core, "trading_window") else c1_time
            if c1 and (c1_time or (us_active and _score_rising(_hist("US", "조건1", code)))):
                if _buy_stock(x, "US", "조건1", now_dt, "US_C1_22_24" if c1_time else "US_C1_SCORE_RISE"):
                    return
        if _in_window(m, _US_ENTRY, False):
            ranked = sorted(rows, key=lambda r: tuple((r.get("condition2") or {}).get("priority") or [0, 0, 0, 0, 0]), reverse=True)
            for x in ranked:
                if bool((x.get("condition2") or {}).get("gate")):
                    if _buy_stock(x, "US", "조건2", now_dt, "US_C2_22_24"):
                        return

    core.trade_scalp = trade_scalp

    old_sell = core.mark_and_sell

    def _sell_stock(p, q, reason):
        market = str(p.market).upper(); px = _f(getattr(q, "price", 0), _f(getattr(p, "current_price", 0)))
        if px <= 0:
            return False
        fx = core._fx(market)
        try: core.paper.mark(market, p.code, px, fx)
        except Exception: pass
        if core.paper.sell(market, p.code, px, fx, reason):
            state["positions"].pop(f"{market}:{p.code}", None)
            try: core._persist_paper()
            except Exception: pass
            persist(True)
            return True
        return False

    def _force_reason(p, now_kst):
        market = str(p.market).upper(); strategy = str(getattr(p, "strategy", "")); m = _mins(now_kst)
        if market == "KR":
            sess = str(getattr(p, "entry_session", "") or "")
            if "PRE" in sess and m >= 8 * 60 + 49:
                return "프리마켓 종료 전 강제청산"
            # C3 explicitly trades until 15:25, so close it immediately before the regular close.
            if strategy == "조건3":
                if 9 * 60 <= m < 15 * 60 + 40 and m >= 15 * 60 + 29:
                    return "정규장 종료 전 강제청산"
            elif 9 * 60 <= m < 15 * 60 + 40 and m >= 15 * 60 + 19:
                return "정규장 동시호가 전 강제청산"
            if ("LATE" in sess or m >= 15 * 60 + 40) and m >= 19 * 60 + 59:
                return "오픈마켓 종료 전 강제청산"
            return ""
        try:
            ny = now_kst.astimezone(ZoneInfo("America/New_York")); nm = _mins(ny)
            if ny.weekday() < 5 and nm >= 15 * 60 + 59:
                return "미장 정규장 종료 전 강제청산"
        except Exception:
            pass
        return ""

    def mark_and_sell(market, scalp, smart, now=None):
        mkt = str(market or "").upper()
        if mkt not in ("KR", "US"):
            return old_sell(market, scalp, smart, now)
        now_dt = (now or core.datetime.now(core.KST)).astimezone(core.KST); ts = now_dt.timestamp(); m = _mins(now_dt)
        qmap = core.feed.quotes_for(mkt); imap = {str(x.get("code") or "").upper(): x for x in list(scalp or [])}
        handled_keys = []
        for p in list(core.paper.market_positions(mkt)):
            condition = str(getattr(p, "strategy", "") or "")
            if condition not in ("조건1", "조건2", "조건3"):
                continue
            handled_keys.append(p.key)
            q = qmap.get(p.code)
            if q is None or _f(getattr(q, "price", 0)) <= 0:
                continue
            try: core.paper.mark(mkt, p.code, _f(q.price), core._fx(mkt))
            except Exception: pass
            pnl = _f(p.pnl_pct); item = imap.get(str(p.code).upper()) or {}
            meta = state["positions"].setdefault(f"{mkt}:{p.code}", {"condition": condition, "entry_ts": _f(getattr(p, "entry_ts", ts), ts), "max_pnl_30m": -999.0, "loss_started": None})
            age = max(0.0, (ts - _f(getattr(p, "entry_ts", meta.get("entry_ts", ts)), ts)) / 60.0)
            reason = _force_reason(p, now_dt)
            target = item.get("vi_target") or item.get("vi_pre")
            if not reason and target and _f(target) > _f(getattr(p, "avg_price", 0)) and _f(q.price) >= _f(target):
                reason = "VI 직전 목표가 익절"

            if condition == "조건1" and not reason:
                # persistent -1.2% or worse for 5 minutes; recovery resets the timer.
                if pnl <= -1.2:
                    if not meta.get("loss_started"):
                        meta["loss_started"] = ts
                    elif ts - _f(meta.get("loss_started")) >= 300:
                        reason = "조건1 손실 -1.2% 이하 5분 지속"
                else:
                    meta["loss_started"] = None
                meta["max_pnl_30m"] = max(_f(meta.get("max_pnl_30m"), -999), pnl) if age <= 30 else _f(meta.get("max_pnl_30m"), -999)
                score = item.get("score")
                if score is not None:
                    _sample_score(mkt, "조건1", p.code, score, ts)
                    sig, why = _score_exit(_hist(mkt, "조건1", p.code))
                    if sig:
                        reason = why
                if not reason and age >= 30 and _f(meta.get("max_pnl_30m"), 999) <= 0.5 and pnl > _FEE_BUFFER:
                    reason = "조건1 30분 +0.5% 이하 유지 · 순이익 전환 청산"

            elif condition == "조건2" and not reason:
                if pnl >= 1.5:
                    reason = "조건2 +1.5% 이상 익절"
                elif pnl <= -1.5:
                    reason = "조건2 -1.5% 손절"
                score = item.get("condition2_score")
                if not reason and score is not None:
                    _sample_score(mkt, "조건2", p.code, score, ts)
                    sig, why = _score_exit(_hist(mkt, "조건2", p.code))
                    if sig:
                        reason = why
                if not reason and pnl > _FEE_BUFFER:
                    if mkt == "KR":
                        sess = str(getattr(p, "entry_session", ""))
                        if sess == "C2_AM" and m >= 10 * 60 + 30:
                            reason = "조건2 오전 목표 미달 · 10:30 이후 순이익 청산"
                        elif sess == "C2_PM" and m >= 14 * 60 + 50:
                            reason = "조건2 오후 목표 미달 · 14:50 이후 순이익 청산"
                    else:
                        # preserve the existing US market-specific deadline behavior; no KR clock is imposed.
                        try:
                            entered = datetime.fromtimestamp(_f(getattr(p, "entry_ts", ts)), core.KST).astimezone(ZoneInfo("America/New_York"))
                            ny = now_dt.astimezone(ZoneInfo("America/New_York"))
                            if (ny - entered).total_seconds() >= 90 * 60:
                                reason = "조건2 미장 목표 미달 · 순이익 청산"
                        except Exception:
                            pass

            elif condition == "조건3" and not reason:
                low = _f(meta.get("low")); high = _f(meta.get("high")); pos = _c3_current_pos(_f(q.price), low, high)
                if pos is not None and pos >= 0.85:
                    reason = "조건3 횡보구간 상단 도달"

            if reason:
                _sell_stock(p, q, reason)

        # Preserve SMART/other strategies, but hide Condition1/2/3 so no legacy exit can touch them.
        hidden = {}
        try:
            for k in handled_keys:
                if k in core.paper.positions:
                    hidden[k] = core.paper.positions.pop(k)
            old_sell(mkt, scalp, smart, now_dt)
        finally:
            for k, p in hidden.items():
                if k not in core.paper.positions:
                    core.paper.positions[k] = p
        persist(False)

    core.mark_and_sell = mark_and_sell

    # ---------------- Coin: update only the condition numbers that already exist (C1 + C2). No C3 is added. ----------------
    original_coin_candidates = core.coin_feed.candidates

    def _coin_exec(sym, q, now_ts):
        h = exec_hist_coin.setdefault(sym, deque(maxlen=120))
        val = _f(getattr(q, "volume_power", 0))
        if not h or now_ts - _f(h[-1][0]) >= 4.5:
            h.append((now_ts, val))
        class CQ:
            execution_strength = val
        return _execution_gate(CQ(), now_ts, list(h))

    def _coin_chart(sym, interval="1m", size=80, ttl=30):
        key = (sym, interval, size); now_ts = time.time(); row = coin_chart_cache.get(key)
        if row and now_ts - row[0] < ttl:
            return row[1]
        try:
            bars = list(core.coin_feed.chart(sym, interval, size) or [])
        except Exception:
            bars = []
        coin_chart_cache[key] = (now_ts, bars)
        return bars

    def _coin_minute10(sym, q):
        bars = _coin_chart(sym, "1m", 80, 20)
        if len(bars) < 3:
            return 0.0, False, {"ready": False, "bars": len(bars)}
        # newest exchange candle may be forming: use it as the current candle and previous as completed.
        p2, prev, cur = bars[-3], bars[-2], bars[-1]
        decline = _f(prev.get("close")) < _f(prev.get("open")) or _f(prev.get("close")) < _f(p2.get("close"))
        low_formed = _f(prev.get("low")) <= _f(p2.get("low"))
        breakout = _f(q.price) > _f(prev.get("high")) > 0
        bullish = _f(q.price) > _f(cur.get("open")) > 0
        ok = bool(decline and low_formed and breakout and bullish)
        return 10.0 if ok else 0.0, ok, {"ready": True, "decline": decline, "low_formed": low_formed, "breakout": breakout, "current_bullish": bullish}

    def _coin_btc_up():
        bars = _coin_chart("BTC", "1m", 10, 20)
        if len(bars) < 2:
            return {"ready": False, "up": False, "market": "BTC"}
        b = bars[-2]
        return {"ready": _f(b.get("open")) > 0 and _f(b.get("close")) > 0, "up": _f(b.get("close")) > _f(b.get("open")) > 0, "market": "BTC", "open": _f(b.get("open")), "close": _f(b.get("close"))}

    def coin_candidates(n=20):
        rows = list(original_coin_candidates(n) or [])
        settings = core._coin_settings_snapshot(); c1_threshold = _f(settings.get("entry_score"), 66)
        now_ts = time.time(); btc = _coin_btc_up(); out = []
        for x0 in rows:
            x = dict(x0); sym = str(x.get("code") or "").upper(); q = core.coin_feed.quote(sym)
            if not sym or q is None:
                out.append(x); continue
            dmeta = dict(x.get("daily_reference") or {})
            mid = _f(dmeta.get("mid")); daily_ok = mid > 0 and _f(q.price) > mid; d10 = 10.0 if daily_ok else 0.0
            m10, minute_ok, minute_meta = _coin_minute10(sym, q)
            exec_ok, exec_reason = _coin_exec(sym, q, now_ts); e12 = 12.0 if exec_ok else 0.0
            ratio = (_f(q.ask_qty) / _f(q.bid_qty)) if _f(q.ask_qty) > 0 and _f(q.bid_qty) > 0 else None
            o8 = _order8(ratio); order_ok = ratio is not None and ratio >= 0.9
            std45 = _clamp(x.get("technical_score"), 0, 45)
            prereq = d10 + m10 + e12 + o8
            c1score = round(_clamp(prereq + std45, 0, 100), 1)  # coin has no sector/news bonus feed: bonus remains 0.
            c1_gate = bool(daily_ok and minute_ok and exec_ok and order_ok and c1score >= c1_threshold)

            sc = dict(x.get("score_components") or {})
            base_v15 = _clamp(sc.get("volume15"), 0, 15)
            v25 = round(base_v15 / 15.0 * 25.0, 1)
            e40 = _execution40(q, exec_ok)
            b25 = round(o8 / 8.0 * 25.0, 1)
            ch = _f(getattr(q, "change_pct", x.get("change_pct", 0)))
            # same existing 0..20 change shape -> 0..5
            if ch <= 0: p20 = 0
            elif ch < 1: p20 = 4 * ch
            elif ch < 2: p20 = 4 + (ch - 1) * 4
            elif ch < 3: p20 = 8 + (ch - 2) * 4
            elif ch < 5: p20 = 12 + (ch - 3) * 4
            else: p20 = 20
            ch5 = round(_clamp(p20 / 20 * 5, 0, 5), 1)
            t5 = round(std45 / 45.0 * 5.0, 1)
            c2score = round(_clamp(v25 + e40 + b25 + ch5 + t5, 0, 100), 1)
            long_ready = bool(dmeta) and bool(x.get("technical_ready", std45 > 0))
            c2_gate = bool(c2score > _C2_THRESHOLD and btc.get("ready") and btc.get("up") and long_ready)
            x["score"] = c1score; x["score_total"] = c1score
            x["condition1"] = {"label": "조건1", "score": c1score, "gate": c1_gate, "entry_threshold": c1_threshold, "prerequisite_score": round(prereq, 1), "standard_score": round(std45, 1), "bonus_score": 0.0,
                               "breakdown": {"daily10": d10, "minute10": m10, "execution12": e12, "orderbook8": o8, "standard45": round(std45, 1), "bonus15": 0.0}, "minute_meta": minute_meta, "execution_reason": exec_reason, "orderbook": {"ratio": ratio}}
            x["condition2"] = {"label": "조건2", "score": c2score, "gate": c2_gate, "entry_threshold": _C2_THRESHOLD, "breakdown": {"volume25": v25, "execution40": e40, "orderbook25": b25, "change5": ch5, "technical5": t5}, "priority": [e40, b25, v25, t5, ch5], "market_1m": btc, "long_daily_ready": long_ready}
            x["condition2_score"] = c2score; x["condition2_gate_pass"] = c2_gate
            labels = [name for name, ok in (("조건1", c1_gate), ("조건2", c2_gate)) if ok]
            x["condition_labels"] = labels; x["condition_display"] = "복합조건" if len(labels) > 1 else (labels[0] if labels else "")
            out.append(x)
        out.sort(key=lambda z: _f(z.get("score")), reverse=True)
        return out[:n]

    core.coin_feed.candidates = coin_candidates

    def coin_trade_loop():
        st = core.COIN_LOOP_STATE; st["started_at"] = time.time(); last_persist = 0.0
        while True:
            st["last_tick"] = time.time(); st["iterations"] += 1
            try:
                rows = coin_candidates(50); now_ts = time.time(); changed = False
                imap = {str(x.get("code") or "").upper(): x for x in rows}
                for x in rows:
                    sym = str(x.get("code") or "").upper()
                    _sample_score("COIN", "조건1", sym, x.get("score"), now_ts)
                    _sample_score("COIN", "조건2", sym, x.get("condition2_score"), now_ts)
                for p in list(core.coin_paper.positions.values()):
                    q = core.coin_feed.quote(p.symbol)
                    if not q or _f(q.price) <= 0:
                        continue
                    core.coin_paper.mark(p.symbol, q.price); item = imap.get(p.symbol) or {}; strategy = str(getattr(p, "strategy", "") or "조건1")
                    if strategy not in ("조건1", "조건2"):
                        strategy = "조건1"; p.strategy = strategy
                    meta = state["positions"].setdefault(f"COIN:{p.symbol}", {"condition": strategy, "entry_ts": _f(p.entry_ts, now_ts), "max_pnl_30m": -999.0, "loss_started": None})
                    age = max(0.0, (now_ts - _f(p.entry_ts, now_ts)) / 60.0); pnl = _f(p.pnl_pct); reason = ""
                    if strategy == "조건1":
                        if pnl <= -1.2:
                            if not meta.get("loss_started"): meta["loss_started"] = now_ts
                            elif now_ts - _f(meta.get("loss_started")) >= 300: reason = "조건1 손실 -1.2% 이하 5분 지속"
                        else: meta["loss_started"] = None
                        if age <= 30: meta["max_pnl_30m"] = max(_f(meta.get("max_pnl_30m"), -999), pnl)
                        sig, why = _score_exit(_hist("COIN", "조건1", p.symbol))
                        if sig: reason = why
                        if not reason and age >= 30 and _f(meta.get("max_pnl_30m"), 999) <= 0.5 and pnl > _FEE_BUFFER: reason = "조건1 30분 +0.5% 이하 유지 · 순이익 전환 청산"
                    else:
                        if pnl >= 1.5: reason = "조건2 +1.5% 이상 익절"
                        elif pnl <= -1.5: reason = "조건2 -1.5% 손절"
                        if not reason:
                            sig, why = _score_exit(_hist("COIN", "조건2", p.symbol))
                            if sig: reason = why
                    if reason and core.coin_paper.sell(p.symbol, q.price, reason):
                        core.COIN_COOLDOWN[p.symbol] = now_ts; state["positions"].pop(f"COIN:{p.symbol}", None); changed = True

                settings = core._coin_settings_snapshot(); entry = _f(settings.get("entry_score"), 66)
                if settings.get("auto_trade_enabled", True):
                    # Existing coin budget/position sizing/cooldown variables are retained unchanged.
                    ranked = sorted(rows, key=lambda r: (bool((r.get("condition1") or {}).get("gate")), _f(r.get("score"))), reverse=True)
                    for item in ranked:
                        sym = str(item.get("code") or "").upper()
                        if not sym or f"COIN:{sym}" in core.coin_paper.positions or _f(item.get("fresh_age"), 9999) > 30 or now_ts - _f(core.COIN_COOLDOWN.get(sym)) < 300:
                            continue
                        c1 = bool((item.get("condition1") or {}).get("gate"))
                        c2 = bool((item.get("condition2") or {}).get("gate"))
                        if not (c1 or c2):
                            continue
                        q = core.coin_feed.quote(sym); available = core._coin_available_budget(); budget = core._coin_effective_budget()
                        if not q or q.price <= 0 or available < 10000:
                            continue
                        strategy = "조건1" if c1 else "조건2"
                        if core.coin_paper.buy(q, min(available, max(10000.0, budget * 0.20)), strategy):
                            state["positions"][f"COIN:{sym}"] = {"condition": strategy, "entry_ts": now_ts, "max_pnl_30m": -999.0, "loss_started": None}
                            changed = True; break
                if changed:
                    core._persist_coin(); core._persist_coin_settings(); persist(True)
                if now_ts - last_persist >= 60:
                    core._persist_coin(); core._persist_coin_settings(); persist(False); last_persist = now_ts
                st["last_ok"] = time.time(); st["last_error"] = ""
            except Exception as exc:
                st["last_error"] = str(exc)[:300]
                print("NAMUH FINAL CONDITIONS COIN LOOP ERROR:", exc, flush=True)
            time.sleep(core.AUTO_LOOP_SECONDS)

    core.coin_trade_loop = coin_trade_loop

    # Strategy-related health metadata only; no unrelated site/runtime variables are modified.
    try:
        old_health = core.health_payload
        def health():
            d = dict(old_health())
            d["condition_models_final"] = {
                "condition1": "prerequisite40 + standard45 + bonus15; envelope removed",
                "condition2": "volume25 + execution40 + orderbook25 + change5 + technical5; >70",
                "condition3": "sideways >=3%; >=2 round trips; sector top3; lower buy/upper sell",
                "markets": {"KR": [1, 2, 3], "US": [1, 2, 3], "COIN": [1, 2]},
            }
            d["condition_entry_scores"] = {"condition2": ">70", "condition3": "sideways pattern only; no AI score threshold"}
            return d
        core.health_payload = health
    except Exception:
        pass

    print("NAMUH FINAL CONDITIONS active: KR/US C1-C3 + COIN C1-C2; unrelated site variables untouched", flush=True)
    return True
