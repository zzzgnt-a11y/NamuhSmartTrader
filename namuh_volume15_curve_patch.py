from __future__ import annotations

import threading
import time
from datetime import timedelta
from queue import Queue, Empty, Full

_INSTALLED = False
_LOCK = threading.RLock()
_Q: Queue = Queue(maxsize=96)
_PENDING: set[str] = set()
_CACHE: dict[str, dict[str, dict[str, float]]] = {}
_STATS = {"queued": 0, "ready": 0, "failed": 0}
_STORE_KEY = "condition_volume15_full_curve_v2"


def _f(v, default=0.0):
    try:
        return float(str(v).replace(",", "").replace("+", "").strip())
    except Exception:
        return float(default)


def _clamp(v, lo=0.0, hi=100.0):
    return max(float(lo), min(float(hi), _f(v)))


def _digits(v):
    return "".join(ch for ch in str(v or "") if ch.isdigit())


def _walk(v):
    if isinstance(v, dict):
        yield v
        for x in v.values():
            yield from _walk(x)
    elif isinstance(v, (list, tuple)):
        for x in v:
            yield from _walk(x)


def _first(row, keys):
    for k in keys:
        if k in row and row[k] not in (None, ""):
            return row[k]
    return None


def _row_clock(row):
    ds = _digits(_first(row, ("bsop_date", "stck_bsop_date", "qry_date", "trade_date", "xymd", "date")))
    ts = _digits(_first(row, ("bsop_time", "stck_cntg_hour", "qry_time", "trade_time", "xytm", "time")))
    if len(ds) < 8 or len(ts) < 4:
        return "", -1
    hh, mm = int(ts[:2]), int(ts[2:4])
    if not (0 <= hh <= 23 and 0 <= mm <= 59):
        return "", -1
    return ds[:8], hh * 60 + mm


def _curve_from_response(data, target_date):
    cumulative = {}
    incremental = {}
    for row in _walk(data):
        if not isinstance(row, dict):
            continue
        d, minute = _row_clock(row)
        if d != target_date or minute < 0:
            continue
        cv = _f(_first(row, ("acml_vol", "acvol", "cum_volume", "acc_volume", "total_volume")))
        if cv > 0:
            cumulative[minute] = max(cumulative.get(minute, 0.0), cv)
            continue
        iv = _f(_first(row, ("vol", "movolume", "volume", "trade_volume", "trqu", "cntg_vol")))
        if iv >= 0:
            incremental[minute] = max(incremental.get(minute, 0.0), iv)
    if cumulative:
        # Make every minute queryable. If there was no trade in a minute, the
        # cumulative volume is unchanged from the preceding minute.
        out = {}
        last = 0.0
        for minute in range(9 * 60, 15 * 60 + 31):
            if minute in cumulative:
                last = cumulative[minute]
            if last > 0:
                out[str(minute)] = float(last)
        return out
    if incremental:
        out = {}
        total = 0.0
        for minute in range(9 * 60, 15 * 60 + 31):
            total += incremental.get(minute, 0.0)
            if total > 0:
                out[str(minute)] = float(total)
        return out
    return {}


def _fetch_curve(core, code, date):
    from nhplug import call
    orders = ["KRX"]
    try:
        for x in list(core.feed._market_order() or []):
            x = str(x or "").upper()
            if x and x not in orders:
                orders.append(x)
    except Exception:
        pass
    last = None
    for market_cd in orders:
        try:
            data = call("/krstock/quote/v1/period", {
                "market_cd": market_cd, "iem_cd": code, "mrkt_div_cls_code": "", "edate": date,
                "array_cnt": "0720", "maxavg": "000", "gubun": "5", "xtick": "001",
                "today_cls_code": "0", "fake_tick": "0", "sur_flag": "0", "sur_gb_day_cnt": "00",
                "sur_bf_end_time": "", "out1_scale_change": "0", "out2_scale_change": "0",
            }, timeout=10, raise_on_error=False)
            curve = _curve_from_response(data, date)
            if curve:
                return curve
        except Exception as exc:
            last = exc
    if last:
        raise last
    return {}


def _prior_weekdays(now_local, limit=34):
    d = now_local.date() - timedelta(days=1)
    out = []
    while len(out) < limit:
        if d.weekday() < 5:
            out.append(d.strftime("%Y%m%d"))
        d -= timedelta(days=1)
    return out


def _save(core):
    try:
        with _LOCK:
            data = {code: dict(days) for code, days in _CACHE.items()}
        core.store.save_json(_STORE_KEY, data)
    except Exception:
        pass


def _backfill(core, code):
    import namuh_conditions_final_patch as c
    now = core.datetime.now(core.KST) if hasattr(core, "datetime") else __import__("datetime").datetime.now(core.KST)
    local = c._market_clock("KR", now)
    try:
        with _LOCK:
            days = _CACHE.setdefault(code, {})
        valid = [d for d, curve in days.items() if isinstance(curve, dict) and curve]
        if len(valid) < 15:
            for d in _prior_weekdays(local, 34):
                with _LOCK:
                    existing = dict(days.get(d) or {})
                if existing:
                    continue
                curve = _fetch_curve(core, code, d)
                if curve:
                    with _LOCK:
                        days[d] = curve
                    valid.append(d)
                # Avoid request bursts while still finishing the first 15 sessions quickly.
                time.sleep(0.04)
                if len(set(valid)) >= 15:
                    break
        with _LOCK:
            keep = sorted(days)[-18:]
            _CACHE[code] = {d: days[d] for d in keep if days.get(d)}
            ready = len(_CACHE[code]) >= 15
            if ready:
                _STATS["ready"] += 1
            else:
                _STATS["failed"] += 1
        if ready:
            _save(core)
    except Exception:
        with _LOCK:
            _STATS["failed"] += 1
    finally:
        with _LOCK:
            _PENDING.discard(code)


def _schedule(core, code):
    code = str(code or "").upper().strip()
    if not code:
        return False
    with _LOCK:
        if len(_CACHE.get(code, {})) >= 15:
            return True
        if code in _PENDING:
            return False
        try:
            _Q.put_nowait((core, code))
        except Full:
            return False
        _PENDING.add(code)
        _STATS["queued"] += 1
    return False


def _worker():
    while True:
        try:
            core, code = _Q.get(timeout=1)
        except Empty:
            continue
        try:
            _backfill(core, code)
        finally:
            _Q.task_done()


def _volume_ratio(code, minute, current_volume):
    with _LOCK:
        days = dict(_CACHE.get(str(code).upper(), {}) or {})
    vals = []
    for d in sorted(days)[-18:]:
        curve = days.get(d) or {}
        v = _f(curve.get(str(minute)))
        if v <= 0:
            # Cumulative volume at an exact clock time is the last observed
            # cumulative amount at or before that minute.
            prior = []
            for k, value in curve.items():
                try:
                    km = int(k)
                except Exception:
                    continue
                if km <= minute and _f(value) > 0:
                    prior.append((km, _f(value)))
            if prior:
                v = max(prior, key=lambda x: x[0])[1]
        if v > 0:
            vals.append(v)
    vals = vals[-15:]
    if len(vals) < 15 or _f(current_volume) <= 0:
        return None, len(vals)
    avg = sum(vals) / 15.0
    return (_f(current_volume) / avg if avg > 0 else None), 15


def apply(ns=None):
    global _INSTALLED, _CACHE
    if _INSTALLED:
        return True
    core = ns.get("core") if isinstance(ns, dict) else None
    if core is None:
        return False
    try:
        saved = core.store.load_json(_STORE_KEY, {}) or {}
        if isinstance(saved, dict):
            _CACHE = {
                str(code).upper(): {str(d): dict(curve) for d, curve in (days or {}).items() if isinstance(curve, dict)}
                for code, days in saved.items() if isinstance(days, dict)
            }
    except Exception:
        pass

    for i in range(3):
        threading.Thread(target=_worker, daemon=True, name=f"volume15-curve-{i+1}").start()

    # Samsung first, then the rest of the fixed watch list. A full historical
    # curve is fetched once per past session, so the next minute never falls back
    # to DATA_WAIT again merely because the clock advanced by one minute.
    fixed = list(dict.fromkeys(list(getattr(core.feed, "fixed", {}).get("KR", []) or [])))
    if "005930" in fixed:
        fixed.remove("005930")
    for code in ["005930", *fixed]:
        _schedule(core, code)

    old_candidate = core.candidate
    if getattr(old_candidate, "_namuh_volume15_curve", False):
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
            if q is None or smart or market != "KR":
                return out
            code = str(getattr(q, "code", "") or out.get("code") or "").upper()
            if not code:
                return out
            _schedule(core, code)
            now = kwargs.get("now")
            if now is None and len(args) > 7:
                now = args[7]
            now = (now or core.datetime.now(core.KST)).astimezone(core.KST)
            minute = now.hour * 60 + now.minute
            ratio, days = _volume_ratio(code, minute, _f(getattr(q, "volume", 0)))
            if ratio is None or days < 15:
                return out

            import namuh_conditions_final_patch as c
            vol_actual = round(c._clamp(c._interp_volume15(ratio), 0, 15), 1)
            vol_c1 = max(1.0, vol_actual)

            c1 = dict(out.get("condition1") or {})
            if c1:
                raw = dict(c1.get("standard_raw") or {})
                actual = dict(c1.get("standard_raw_before_floor") or raw)
                actual["거래량"] = vol_actual
                raw["거래량"] = vol_c1
                raw_total = sum(_f(raw.get(k)) for k in ("MACD", "RSI", "볼린저", "거래량", "이평", "가격구조", "엘리어트"))
                std45 = round(_clamp(raw_total / 75.0 * 45.0, 0, 45), 1)
                bd = dict(c1.get("breakdown") or {})
                bd["standard45"] = std45
                prereq = round(_f(bd.get("daily10")) + _f(bd.get("minute10")) + _f(bd.get("execution12")) + _f(bd.get("orderbook8")), 1)
                bonus = round(_f(bd.get("sector_relative7_5")) + _f(bd.get("leading_sector_flow3_75")) + _f(bd.get("news3_75")), 1)
                gates = dict(c1.get("gates") or {})
                blocked = bool(gates.get("event_block", False))
                total = round(_clamp(prereq + std45 + bonus, 0, 100), 1)
                if blocked:
                    total = 0.0
                threshold = _f(c1.get("entry_threshold"), 72.0)
                gate = bool(not blocked and gates.get("daily") and gates.get("minute1m") and gates.get("execution") and gates.get("orderbook") and total >= threshold)
                gates["total72"] = total >= threshold
                tm = dict(c1.get("technical_meta") or {})
                tm["volume_ratio"] = round(ratio, 3)
                tm["volume_history_days"] = 15
                tm["volume_backfill_queued"] = False
                tm["volume_source"] = "NHPLUG prior 15 sessions full 1m cumulative curves"
                availability = dict(tm.get("availability") or {})
                availability["거래량"] = True
                tm["availability"] = availability
                tm["missing"] = [x for x in list(tm.get("missing") or []) if x != "거래량"]
                audit = dict(tm.get("zero_audit") or {})
                audit["거래량"] = "RECIPE_ZERO" if vol_actual == 0 else "SCORED"
                tm["zero_audit"] = audit
                c1.update({
                    "score": total, "gate": gate, "breakdown": bd,
                    "standard_raw": raw, "standard_raw_before_floor": actual,
                    "standard_score": std45, "prerequisite_score": prereq, "bonus_score": bonus,
                    "gates": gates, "technical_meta": tm,
                })
                out["condition1"] = c1
                out["condition1_score"] = total
                out["score"] = total
                out["priority_score"] = total

            c2 = dict(out.get("condition2") or {})
            if c2:
                c2b = dict(c2.get("breakdown") or {})
                c2b["volume25"] = round(_clamp(vol_actual / 15.0 * 25.0, 0, 25), 1)
                actual = dict((out.get("condition1") or {}).get("standard_raw_before_floor") or {})
                actual_total = sum(_f(actual.get(k)) for k in ("MACD", "RSI", "볼린저", "거래량", "이평", "가격구조", "엘리어트"))
                c2b["technical5"] = round(_clamp(actual_total / 75.0 * 5.0, 0, 5), 1)
                total2 = round(_clamp(_f(c2b.get("execution40")) + _f(c2b.get("orderbook25")) + _f(c2b.get("volume25")) + _f(c2b.get("technical5")) + _f(c2b.get("change5")), 0, 100), 1)
                bench = dict(c2.get("market_1m") or {})
                blocked = bool(((out.get("condition1") or {}).get("gates") or {}).get("event_block", False))
                gate2 = bool(not blocked and total2 > _f(c2.get("entry_threshold"), 70.0) and bench.get("ready") and bench.get("up") and c2.get("long_daily_ready"))
                c2.update({"score": total2, "gate": gate2, "breakdown": c2b})
                out["condition2"] = c2
                out["condition2_score"] = total2
                out["condition2_gate_pass"] = gate2

            labels = [x for x in list(out.get("condition_labels") or []) if x not in ("조건1", "조건2")]
            if (out.get("condition1") or {}).get("gate"):
                labels.insert(0, "조건1")
            if (out.get("condition2") or {}).get("gate"):
                labels.append("조건2")
            labels = list(dict.fromkeys(labels))
            out["condition_labels"] = labels
            out["condition_display"] = "복합조건" if len(labels) > 1 else (labels[0] if labels else "")
        except Exception as exc:
            out["volume15_curve_error"] = str(exc)[:180]
        return out

    candidate._namuh_volume15_curve = True
    core.candidate = candidate

    old_health = getattr(core, "health_payload", None)
    if callable(old_health):
        def health():
            d = dict(old_health())
            with _LOCK:
                d["volume15_full_curve"] = {**_STATS, "symbols": len(_CACHE), "pending": len(_PENDING), "queue": _Q.qsize()}
            return d
        core.health_payload = health

    _INSTALLED = True
    print("NAMUH VOLUME15 CURVE active: prior-15 full minute cumulative curves, persistent", flush=True)
    return True
