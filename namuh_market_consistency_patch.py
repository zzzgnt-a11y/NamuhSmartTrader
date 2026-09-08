from __future__ import annotations

import threading
import time
from collections import deque
from datetime import datetime

_INSTALLED = False

TECH_WEIGHTS = {
    "거래량": 22.0,
    "RSI": 20.0,
    "볼린저": 18.0,
    "MACD": 16.0,
    "이평": 14.0,
    "가격구조": 12.0,
    "엘리어트": 10.0,
}
TECH_MAX = {"거래량": 15.0, "RSI": 10.0, "볼린저": 10.0, "MACD": 10.0, "이평": 10.0, "가격구조": 10.0, "엘리어트": 10.0}
_COIN_CHART_LOCK = threading.RLock()
_COIN_CHART_CACHE = {}


def _f(v, default=0.0):
    try:
        return float(v)
    except Exception:
        return float(default)


def _clamp(v, lo=0.0, hi=100.0):
    return max(float(lo), min(float(hi), _f(v)))


def _floor1(v, hi):
    return max(1.0, min(float(hi), _f(v)))


def _weighted45(raw):
    denom = sum(TECH_WEIGHTS.values())
    total = 0.0
    contributions = {}
    for k, w in TECH_WEIGHTS.items():
        mx = TECH_MAX[k]
        v = _floor1((raw or {}).get(k), mx)
        part = (v / mx) * (w / denom) * 45.0
        contributions[k] = round(part, 3)
        total += part
    return round(_clamp(total, 0, 45), 1), contributions


def _current_investor_rows(data):
    if not isinstance(data, dict):
        return []
    rows = []
    for k in ("Output_0", "output_0", "output0", "Output0", "output"):
        v = data.get(k)
        if isinstance(v, list):
            rows.extend(x for x in v if isinstance(x, dict))
    return rows


def _install_investor_fix(core):
    feed = core.feed
    old_apply = getattr(feed, "_apply_investor", None)
    if not callable(old_apply) or getattr(old_apply, "_namuh_schema_fixed", False):
        return
    from nhfeed import num, normalize_date

    def apply_investor(code, data):
        rows = _current_investor_rows(data)
        parsed = {}
        for r in rows:
            d = normalize_date(
                r.get("bsop_date1") or r.get("bsop_date2") or r.get("bsop_date")
                or r.get("stck_bsop_date") or r.get("trade_date") or r.get("date")
            )
            if not d:
                continue
            foreign = num(r.get("frgn_ntby_qty") if r.get("frgn_ntby_qty") not in (None, "") else r.get("invest"))
            institution = num(r.get("gigwan") if r.get("gigwan") not in (None, "") else r.get("orgn_ntby_qty"))
            person = num(r.get("person") if r.get("person") not in (None, "") else r.get("prsn_ntby_qty"))
            program = num(r.get("program") if r.get("program") not in (None, "") else r.get("prgm_ntby_qty"))
            parsed[d] = {"date": d, "foreign": foreign, "institution": institution, "person": person, "program": program}
        if not parsed:
            return old_apply(code, data)
        ordered = [parsed[k] for k in sorted(parsed)][-14:]
        latest = ordered[-1]
        q = feed.q("KR", code)
        q.update_flow(latest["foreign"], latest["institution"], latest["program"])
        q.person_net = latest["person"]
        q.investor_daily = deque(ordered, maxlen=14)
        q.investor_asof = latest["date"]
        q.investor_data_ready = True
        q.investor_updated_at = time.time()

    apply_investor._namuh_schema_fixed = True
    apply_investor._namuh_old = old_apply
    feed._apply_investor = apply_investor

    def investor_loop():
        from nhplug import call
        idx = 0
        while not feed._stop.is_set():
            # Re-read the universe every iteration. The original loop captured the
            # small fixed list before _load_kr_master had finished and never saw
            # the expanded sector universe.
            dynamic = list(getattr(feed, "code_lists", {}).get("KR") or [])
            if not dynamic:
                dynamic = list(getattr(feed, "sector_scan_codes", []) or [])
            fixed = list(getattr(feed, "fixed", {}).get("KR", []) or [])
            codes = list(dict.fromkeys([str(x) for x in fixed + dynamic if str(x)]))
            if not codes:
                feed._stop.wait(1.0)
                continue
            code = codes[idx % len(codes)]
            idx += 1
            for market_cd in feed._market_order():
                try:
                    data = call("/krstock/quote/v1/currentInvestor", {"market_cd": market_cd, "iem_cd": code, "array_cnt": "14"})
                    feed._apply_investor(code, data)
                    feed.investor_updated_at = time.time()
                    break
                except Exception as exc:
                    if "429" in str(exc):
                        feed._stop.wait(1.5)
                        break
            # Keep the original gentle rate; correctness comes from dynamic
            # coverage, not from increasing request pressure.
            feed._stop.wait(.75)

    feed.investor_loop = investor_loop


def _recalc_c2_from_c1(out, c1):
    c2 = dict(out.get("condition2") or {})
    if not c2:
        return None
    bd = dict(c2.get("breakdown") or {})
    std45 = _f(c1.get("standard_score"), _f((c1.get("breakdown") or {}).get("standard45")))
    tech5 = round(_clamp(std45 / 45.0 * 5.0, 0, 5), 1)
    bd["technical5"] = tech5
    total = round(_clamp(
        _f(bd.get("execution40")) + _f(bd.get("orderbook25")) + _f(bd.get("volume25"))
        + tech5 + _f(bd.get("change5")), 0, 100
    ), 1)
    bench = dict(c2.get("market_1m") or {})
    long_ready = bool(c2.get("long_daily_ready"))
    threshold = _f(c2.get("entry_threshold"), 70.0)
    gate = bool(total > threshold and bench.get("ready") and bench.get("up") and long_ready)
    c2.update({"score": total, "gate": gate, "breakdown": bd,
               "priority": [_f(bd.get("execution40")), _f(bd.get("orderbook25")), _f(bd.get("volume25")), tech5, _f(bd.get("change5"))],
               "technical_source": "condition1 weighted Standard45"})
    out["condition2"] = c2
    out["condition2_score"] = total
    out["condition2_gate_pass"] = gate
    return c2


def _install_stock_market_consistency(core):
    old_candidate = core.candidate
    if getattr(old_candidate, "_namuh_market_consistency", False):
        return

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
            bd = dict(c1.get("breakdown") or {})
            gates = dict(c1.get("gates") or {})

            # The latest requested weighted Standard45 is authoritative for both stocks markets.
            raw = dict(c1.get("standard_raw") or {})
            std45, parts = _weighted45(raw)
            bd["standard45"] = std45

            if market == "US":
                # The old bonus helper ranked the US sector correctly but then
                # attempted KR investor-flow lookup for the 3.75 component.
                # US has no KR-style investor feed, so use its live sector
                # strength score for this component instead of a fabricated zero.
                try:
                    rank = int(out.get("sector_rank") or c1.get("leading_sector_rank") or 999)
                except Exception:
                    rank = 999
                r5 = 5.0 if rank == 1 else 4.0 if rank == 2 else 3.0 if rank == 3 else 2.0 if rank == 4 else 1.0 if rank == 5 else 0.0
                sector75 = round(r5 / 5.0 * 7.5, 2)
                strength10 = _clamp(out.get("sector_score"), 0, 10)
                flow375 = round(strength10 / 10.0 * 3.75, 2)
                news375 = _clamp(bd.get("news3_75"), 0, 3.75)
                bd["sector_relative7_5"] = sector75
                bd["leading_sector_flow3_75"] = flow375
                bd["news3_75"] = round(news375, 2)
                c1["leading_sector_rank"] = rank
                c1["us_sector_bonus_source"] = "sector rank 7.5 + live US sector strength 3.75"

            prereq = round(_f(bd.get("daily10")) + _f(bd.get("minute10")) + _f(bd.get("execution12")) + _f(bd.get("orderbook8")), 1)
            bonus = round(_f(bd.get("sector_relative7_5")) + _f(bd.get("leading_sector_flow3_75")) + _f(bd.get("news3_75")), 2)
            threshold = _f(c1.get("entry_threshold"), 72.0)
            blocked = bool(gates.get("event_block", False))
            total = round(_clamp(prereq + std45 + bonus, 0, 100), 1)
            if blocked:
                total = 0.0
            hard = bool(gates.get("daily") and gates.get("minute1m") and gates.get("execution") and gates.get("orderbook"))
            c1gate = bool(not blocked and hard and total >= threshold)
            gates["total72"] = total >= threshold
            tm = dict(c1.get("technical_meta") or {})
            tm["standard45_contribution"] = parts
            c1.update({"score": total, "gate": c1gate, "breakdown": bd, "gates": gates,
                       "prerequisite_score": prereq, "standard_score": std45, "bonus_score": bonus,
                       "technical_meta": tm, "score_consistency_owner": "market_consistency_v1"})
            out["condition1"] = c1
            out["condition1_score"] = total
            out["score"] = total
            out["priority_score"] = total
            c2 = _recalc_c2_from_c1(out, c1)

            labels = []
            if c1gate:
                labels.append("조건1")
            if c2 and c2.get("gate"):
                labels.append("조건2")
            if (out.get("condition3") or {}).get("gate"):
                labels.append("조건3")
            out["condition_labels"] = labels
            out["condition_display"] = "복합조건" if len(labels) > 1 else (labels[0] if labels else "")
        except Exception as exc:
            out["market_consistency_error"] = str(exc)[:220]
        return out

    candidate._namuh_market_consistency = True
    core.candidate = candidate


def _install_coin_chart_cache(core):
    old_chart = core.coin_feed.chart
    if getattr(old_chart, "_namuh_fast_cache", False):
        return

    def chart(symbol, interval="1m", size=120):
        sym = str(symbol or "").upper()
        itv = str(interval or "1m")
        sz = int(size or 120)
        ttl = 20.0 if itv in ("1m", "3m", "5m") else 300.0 if itv == "1d" else 60.0
        key = (sym, itv, sz)
        now = time.time()
        with _COIN_CHART_LOCK:
            row = _COIN_CHART_CACHE.get(key)
            if row and now - row[0] <= ttl:
                return [dict(x) for x in row[1]]
        data = list(old_chart(sym, itv, sz) or [])
        with _COIN_CHART_LOCK:
            _COIN_CHART_CACHE[key] = (time.time(), [dict(x) for x in data])
            if len(_COIN_CHART_CACHE) > 240:
                oldest = sorted(_COIN_CHART_CACHE.items(), key=lambda kv: kv[1][0])[:60]
                for k, _ in oldest:
                    _COIN_CHART_CACHE.pop(k, None)
        return data

    chart._namuh_fast_cache = True
    core.coin_feed.chart = chart


def _coin_minute_progressive(core, sym, q):
    try:
        bars = [dict(x) for x in list(core.coin_feed.chart(sym, "1m", 80) or []) if isinstance(x, dict)]
    except Exception:
        bars = []
    if len(bars) < 3:
        return 1.0, False, {"ready": False, "bars": len(bars), "score_parts": {"pullback2": 0, "low2": 0, "breakout4": 0, "candle2": 0}}
    p2, prev, cur = bars[-3], bars[-2], bars[-1]
    p2c = _f(p2.get("close")); po = _f(prev.get("open")); pc = _f(prev.get("close")); p2l = _f(p2.get("low")); pl = _f(prev.get("low")); ph = _f(prev.get("high"))
    co = _f(cur.get("open")); cl = _f(cur.get("low")); px = _f(q.price, _f(cur.get("close")))
    bear = pc < po
    lower_close = p2c > 0 and pc < p2c
    pullback = 2.0 if bear and lower_close else 1.0 if (bear or lower_close) else 0.0
    low_made = pl > 0 and (p2l <= 0 or pl <= p2l)
    low_held = low_made and cl > 0 and cl >= pl
    low2 = 2.0 if low_held else 1.0 if low_made else 0.0
    dist = ((px / ph) - 1.0) * 100.0 if ph > 0 and px > 0 else -99.0
    if dist <= -0.8: b4 = 0.0
    elif dist < -0.4: b4 = 1.0
    elif dist < 0: b4 = 2.0
    elif dist <= 0.3: b4 = 4.0
    elif dist <= 0.8: b4 = 3.5
    else: b4 = 3.0
    body = ((px / co) - 1.0) * 100.0 if co > 0 and px > 0 else -99.0
    if body <= 0: c2 = 0.0
    elif body < 0.10: c2 = 1.0
    elif body < 0.30: c2 = 1.5
    else: c2 = 2.0
    score = round(_clamp(max(1.0, pullback + low2 + b4 + c2), 1, 10), 1)
    breakout = ph > 0 and px > ph
    bullish = co > 0 and px > co
    gate = bool(score >= 7.0 and breakout and bullish)
    return score, gate, {"ready": True, "bars": len(bars), "previous_high": ph, "price": px,
                         "distance_from_prev_high_pct": round(dist, 3), "current_open": co, "body_pct": round(body, 3),
                         "breakout": breakout, "current_bullish": bullish,
                         "score_parts": {"pullback2": pullback, "low2": low2, "breakout4": b4, "candle2": c2}}


def _coin_raw7(item):
    rows = list(item.get("technical_breakdown") or [])
    by_key = {str(x.get("key") or "").lower(): x for x in rows if isinstance(x, dict)}
    def score(key):
        return _f((by_key.get(key) or {}).get("score"))
    return {
        "거래량": _floor1(score("volume"), 15),
        "RSI": _floor1(score("rsi"), 10),
        "볼린저": _floor1(score("bollinger"), 10),
        "MACD": _floor1(score("macd"), 10),
        "이평": _floor1(score("ma"), 10),
        "가격구조": _floor1(score("structure"), 10),
        "엘리어트": _floor1(score("elliott"), 10),
    }


def _install_coin_consistency(core):
    _install_coin_chart_cache(core)
    old_candidates = core.coin_feed.candidates
    if getattr(old_candidates, "_namuh_market_consistency", False):
        return

    def candidates(n=20):
        rows = list(old_candidates(n) or [])
        out = []
        for base in rows:
            x = dict(base)
            try:
                sym = str(x.get("code") or "").upper()
                q = core.coin_feed.quote(sym)
                c1 = dict(x.get("condition1") or {})
                c2 = dict(x.get("condition2") or {})
                if not sym or q is None or not c1:
                    out.append(x); continue
                oldbd = dict(c1.get("breakdown") or {})
                old_d10 = _f(oldbd.get("daily10"))
                old_e12 = _f(oldbd.get("execution12"))
                ratio = _f((c1.get("orderbook") or {}).get("ratio"), -1)
                daily_ok = old_d10 > 0
                exec_ok = old_e12 > 0
                order_ok = ratio >= 0.9
                m10, minute_ok, mmeta = _coin_minute_progressive(core, sym, q)
                raw7 = _coin_raw7(x)
                std45, parts = _weighted45(raw7)
                d10 = round(_floor1(old_d10, 10), 1)
                e12 = round(_floor1(old_e12, 12), 1)
                o8 = round(_floor1(oldbd.get("orderbook8"), 8), 1)
                prereq = round(d10 + m10 + e12 + o8, 1)
                threshold = _f(c1.get("entry_threshold"), _f((core._coin_settings_snapshot() or {}).get("entry_score"), 66))
                c1score = round(_clamp(prereq + std45, 0, 100), 1)
                c1gate = bool(daily_ok and minute_ok and exec_ok and order_ok and c1score >= threshold)
                c1.update({"score": c1score, "gate": c1gate, "prerequisite_score": prereq, "standard_score": std45, "bonus_score": 0.0,
                           "breakdown": {"daily10": d10, "minute10": m10, "execution12": e12, "orderbook8": o8, "standard45": std45, "bonus15": 0.0},
                           "standard_raw": raw7, "minute_meta": mmeta,
                           "gates": {"daily": daily_ok, "minute1m": minute_ok, "execution": exec_ok, "orderbook": order_ok, "total72": c1score >= threshold},
                           "technical_meta": {"weight_model": dict(TECH_WEIGHTS), "standard45_contribution": parts, "williams_excluded_from_condition1": True},
                           "model": "COIN C1 prerequisite40 + weighted Standard45; no sector/news bonus"})
                x["condition1"] = c1
                x["score"] = c1score
                x["score_total"] = c1score

                if c2:
                    cbd = dict(c2.get("breakdown") or {})
                    t5 = round(std45 / 45.0 * 5.0, 1)
                    cbd["technical5"] = t5
                    c2score = round(_clamp(_f(cbd.get("execution40")) + _f(cbd.get("orderbook25")) + _f(cbd.get("volume25")) + t5 + _f(cbd.get("change5")), 0, 100), 1)
                    btc = dict(c2.get("market_1m") or {})
                    long_ready = bool(c2.get("long_daily_ready"))
                    c2thr = _f(c2.get("entry_threshold"), 70.0)
                    c2gate = bool(c2score > c2thr and btc.get("ready") and btc.get("up") and long_ready)
                    c2.update({"score": c2score, "gate": c2gate, "breakdown": cbd,
                               "priority": [_f(cbd.get("execution40")), _f(cbd.get("orderbook25")), _f(cbd.get("volume25")), t5, _f(cbd.get("change5"))],
                               "technical_source": "same weighted seven-indicator Standard45 as C1"})
                    x["condition2"] = c2
                    x["condition2_score"] = c2score
                    x["condition2_gate_pass"] = c2gate
                labels = []
                if c1gate: labels.append("조건1")
                if (x.get("condition2") or {}).get("gate"): labels.append("조건2")
                x["condition_labels"] = labels
                x["condition_display"] = "복합조건" if len(labels) > 1 else (labels[0] if labels else "")
                x["condition3"] = x.get("condition3") if x.get("condition3") else None
                x["market_consistency_model"] = "C1/C2 live data audited; no C3 added"
            except Exception as exc:
                x["market_consistency_error"] = str(exc)[:220]
            out.append(x)
        out.sort(key=lambda r: _f(r.get("score")), reverse=True)
        return out[:max(1, int(n or 20))]

    candidates._namuh_market_consistency = True
    core.coin_feed.candidates = candidates


def _cached_candidate(core, market, code):
    m = str(market or "").upper(); c = str(code or "").upper()
    try:
        with core.cache_lock:
            rows = list((core.CACHE.get(m) or {}).get("scalp") or [])
        for x in rows:
            if str(x.get("code") or "").upper() == c:
                return dict(x)
    except Exception:
        pass
    try:
        for x in list((getattr(core, "_NAMUH_ALL_SCORES", {}) or {}).get(m, []) or []):
            if str(x.get("code") or "").upper() == c:
                return dict(x)
    except Exception:
        pass
    return None


def _install_detail_consistency(core):
    old_detail = getattr(core, "stock_detail", None)
    if not callable(old_detail) or getattr(old_detail, "_namuh_main_score_consistency", False):
        return

    def stock_detail(market, code, timeframe="1d", *args, **kwargs):
        d = dict(old_detail(market, code, timeframe, *args, **kwargs))
        m = str(market or "").upper(); c = str(code or "").upper()
        row = _cached_candidate(core, m, c)
        if row is None:
            # Fallback uses the live Quote, never an alternate chart-history copy.
            try:
                q = core.feed.quotes_for(m).get(c) or core.feed.q(m, c)
                sectors = list((core.CACHE.get(m) or {}).get("sectors") or [])
                secmap = {str(x.get("sector") or ""): _f(x.get("score")) for x in sectors if isinstance(x, dict)}
                stockmap = dict((core.CACHE.get(m) or {}).get("stock_strength") or {})
                leadermap = {str(x.get("sector") or ""): str(x.get("leader_code") or "") for x in sectors if isinstance(x, dict)}
                rankmap = {str(x.get("sector") or ""): i + 1 for i, x in enumerate(sectors) if isinstance(x, dict) and str(x.get("sector") or "")}
                row = core.candidate(q, m, False, secmap, stockmap, leadermap, rankmap, datetime.now(core.KST))
            except Exception:
                row = None
        if isinstance(row, dict):
            sc = dict(d.get("strategy_conditions") or {})
            for k in ("condition1", "condition2", "condition3"):
                if isinstance(row.get(k), dict):
                    sc[k] = dict(row.get(k) or {})
            d["strategy_conditions"] = sc
            d["condition1_score"] = _f((row.get("condition1") or {}).get("score"), _f(row.get("score")))
            d["main_candidate_score"] = _f(row.get("score"))
            d["score_consistency_source"] = "main CACHE scalp candidate"
        return d

    stock_detail._namuh_main_score_consistency = True
    core.stock_detail = stock_detail


def apply(ns=None):
    global _INSTALLED
    if _INSTALLED:
        return True
    core = ns.get("core") if isinstance(ns, dict) else None
    if core is None:
        return False
    _install_investor_fix(core)
    _install_stock_market_consistency(core)
    _install_coin_consistency(core)
    _install_detail_consistency(core)

    old_health = getattr(core, "health_payload", None)
    if callable(old_health):
        def health():
            d = dict(old_health())
            d["market_consistency_v1"] = {
                "active": True,
                "investor_schema": "currentInvestor bsop_date1/2 + foreign/institution/person/program",
                "investor_universe": "dynamic KR code list",
                "main_detail_score": "same cached candidate",
                "us_bonus": "US sector rank + US live sector strength + news",
                "coin_conditions": [1, 2],
                "coin_c3": False,
                "coin_minute": "2+2+4+2 progressive",
                "technical_weights": dict(TECH_WEIGHTS),
                "coin_chart_cache_entries": len(_COIN_CHART_CACHE),
            }
            return d
        core.health_payload = health

    _INSTALLED = True
    print("NAMUH MARKET CONSISTENCY active: investor sectors + main/detail + US/COIN condition audit", flush=True)
    return True
