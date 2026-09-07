from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

_INSTALLED = False
_LOCK = threading.RLock()
_CACHE: dict[tuple[str, str, str], tuple[float, list[dict], str]] = {}
_ERRORS: dict[tuple[str, str, str], str] = {}
_KEY_LOCKS: dict[tuple[str, str, str], threading.Lock] = {}
_TARGETS = {"1m": 60, "3m": 30, "5m": 30, "20m": 30}
_TTL = {"1m": 20.0, "3m": 30.0, "5m": 30.0, "20m": 60.0}


def _f(v, default=0.0):
    try:
        return float(str(v).replace(",", "").strip())
    except Exception:
        return float(default)


def _tf(v: str) -> str:
    s = str(v or "1m").strip().lower()
    aliases = {
        "1min": "1m", "minute": "1m", "3min": "3m", "5min": "5m",
        "20min": "20m", "1분": "1m", "3분": "3m", "5분": "5m", "20분": "20m",
    }
    return aliases.get(s, s)


def _digits(v) -> str:
    return "".join(ch for ch in str(v or "") if ch.isdigit())


def _time_key(b: dict) -> str:
    raw = b.get("time") or b.get("datetime") or b.get("timestamp") or b.get("date") or ""
    s = _digits(raw)
    if len(s) >= 14:
        return s[:14]
    if len(s) >= 12:
        return s[:12] + "00"
    if len(s) == 8:
        return s + "000000"
    return s


def _norm(rows) -> list[dict]:
    out = {}
    for b in list(rows or []):
        if not isinstance(b, dict):
            continue
        t = _time_key(b)
        o = _f(b.get("open") if b.get("open") is not None else b.get("stck_oprc") or b.get("ovrs_oprc") or b.get("open_prc"))
        h = _f(b.get("high") if b.get("high") is not None else b.get("stck_hgpr") or b.get("ovrs_hgpr") or b.get("high_prc"))
        l = _f(b.get("low") if b.get("low") is not None else b.get("stck_lwpr") or b.get("ovrs_lwpr") or b.get("low_prc"))
        c = _f(b.get("close") if b.get("close") is not None else b.get("stck_prpr") or b.get("stck_clpr") or b.get("ovrs_prpr") or b.get("close_prc") or b.get("trdprc"))
        v = _f(b.get("volume") if b.get("volume") is not None else b.get("vol") or b.get("movolume") or b.get("acvol") or b.get("acml_vol"))
        if len(t) < 12 or min(o, h, l, c) <= 0:
            continue
        if h < max(o, c) or l > min(o, c):
            continue
        out[t] = {"time": t, "open": o, "high": h, "low": l, "close": c, "volume": max(0.0, v)}
    return [out[k] for k in sorted(out)]


def _rows(block) -> list[dict]:
    if isinstance(block, list):
        return [x for x in block if isinstance(x, dict)]
    if isinstance(block, dict):
        return [block]
    return []


def _response_rows(data) -> list[dict]:
    raw = []
    if not isinstance(data, dict):
        return raw
    for key in (
        "Output_0", "output0", "output_0", "Output0",
        "Output_1", "output1", "output_1", "Output1", "output",
    ):
        raw.extend(_rows(data.get(key)))
    return raw


def _date_candidates(tz, n=8):
    d = datetime.now(tz).date()
    out = []
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.strftime("%Y%m%d"))
        d -= timedelta(days=1)
    return out


def _parse_period_rows(raw) -> list[dict]:
    parsed = []
    for x in raw:
        date = _digits(
            x.get("bsop_date") or x.get("qry_date") or x.get("trade_date")
            or x.get("xymd") or x.get("date")
        )[:8]
        tm = _digits(
            x.get("bsop_time") or x.get("qry_time") or x.get("trade_time")
            or x.get("xytm") or x.get("time")
        )
        if len(tm) >= 6:
            tm = tm[:6]
        elif len(tm) == 4:
            tm += "00"
        elif tm:
            tm = tm.ljust(6, "0")
        else:
            tm = "000000"
        parsed.append({
            "time": date + tm,
            "open": x.get("stck_oprc") if x.get("stck_oprc") is not None else x.get("ovrs_oprc") if x.get("ovrs_oprc") is not None else x.get("open_prc") or x.get("open"),
            "high": x.get("stck_hgpr") if x.get("stck_hgpr") is not None else x.get("ovrs_hgpr") if x.get("ovrs_hgpr") is not None else x.get("high_prc") or x.get("high"),
            "low": x.get("stck_lwpr") if x.get("stck_lwpr") is not None else x.get("ovrs_lwpr") if x.get("ovrs_lwpr") is not None else x.get("low_prc") or x.get("low"),
            "close": x.get("stck_prpr") if x.get("stck_prpr") is not None else x.get("stck_clpr") if x.get("stck_clpr") is not None else x.get("ovrs_prpr") if x.get("ovrs_prpr") is not None else x.get("close_prc") if x.get("close_prc") is not None else x.get("trdprc") or x.get("close"),
            "volume": x.get("vol") if x.get("vol") is not None else x.get("movolume") if x.get("movolume") is not None else x.get("acvol") if x.get("acvol") is not None else x.get("acml_vol") or x.get("volume"),
        })
    return _norm(parsed)


def _merge(a, b, target: int) -> list[dict]:
    rows = {}
    for x in _norm(a) + _norm(b):
        rows[_time_key(x)] = x
    return [rows[k] for k in sorted(rows)][-target:]


def _aggregate(source: list[dict], minutes: int, target: int) -> list[dict]:
    buckets = {}
    for b in _norm(source):
        t = str(b.get("time") or "")
        if len(t) < 12:
            continue
        hh, mm = int(t[8:10]), int(t[10:12])
        slot = (mm // minutes) * minutes
        key = t[:8] + f"{hh:02d}{slot:02d}00"
        g = buckets.get(key)
        if g is None:
            g = {"time": key, "open": b["open"], "high": b["high"], "low": b["low"], "close": b["close"], "volume": 0.0}
            buckets[key] = g
        else:
            g["high"] = max(g["high"], b["high"])
            g["low"] = min(g["low"], b["low"])
            g["close"] = b["close"]
        g["volume"] += _f(b.get("volume"))
    return [buckets[k] for k in sorted(buckets)][-target:]


def _kr_fetch(core, code: str, tf: str, target: int) -> tuple[list[dict], str]:
    from nhplug import call
    mins = int(tf[:-1])
    errors = []
    market_order = list(getattr(core.feed, "_market_order", lambda: ["KRX"])() or ["KRX"])
    got = []
    for market_cd in market_order:
        got = []
        for edate in _date_candidates(core.KST, 6):
            try:
                data = call("/krstock/quote/v1/period", {
                    "market_cd": market_cd,
                    "iem_cd": code,
                    "mrkt_div_cls_code": "",
                    "edate": edate,
                    "array_cnt": f"{max(target, 60):04d}",
                    "maxavg": "000",
                    "gubun": "5",
                    "xtick": f"{mins:03d}",
                    "today_cls_code": "0",
                    "fake_tick": "0",
                    "sur_flag": "0",
                    "sur_gb_day_cnt": "00",
                    "sur_bf_end_time": "",
                    "out1_scale_change": "0",
                    "out2_scale_change": "0",
                })
                got = _merge(got, _parse_period_rows(_response_rows(data)), max(target * 3, 180))
                if len(got) >= target:
                    return got[-target:], f"NHPLUG KR {tf} official"
            except Exception as exc:
                errors.append(f"{market_cd}/{edate}:{exc}")
                if "IGW40020" in str(exc):
                    break
        if len(got) >= target:
            return got[-target:], f"NHPLUG KR {tf} official"
    if got:
        return got[-target:], f"NHPLUG KR {tf} official partial"
    raise RuntimeError(" | ".join(errors)[-700:] or "KR minute bars empty")


def _us_fetch(core, code: str, tf: str, target: int) -> tuple[list[dict], str]:
    from nhplug import call
    mins = int(tf[:-1])
    errors = []
    got = []
    for end_dt in _date_candidates(ZoneInfo("America/New_York"), 6):
        try:
            data = call("/gbstock/quote/v1/period", {
                "iem_cd": code,
                "end_dt": end_dt,
                "count": f"{max(target, 60):04d}",
                "maxavg": "000",
                "gubun": "2",
                "xtick": f"{mins:04d}",
                "today_cls": "0",
                "market_cls": "1",
            })
            got = _merge(got, _parse_period_rows(_response_rows(data)), max(target * 3, 180))
            if len(got) >= target:
                return got[-target:], f"NHPLUG US {tf} official"
        except Exception as exc:
            errors.append(f"{end_dt}:{exc}")
    if got:
        return got[-target:], f"NHPLUG US {tf} official partial"
    raise RuntimeError(" | ".join(errors)[-700:] or "US minute bars empty")


def _direct_fetch(core, market: str, code: str, tf: str, target: int):
    return _kr_fetch(core, code, tf, target) if market == "KR" else _us_fetch(core, code, tf, target)


def _fallback_from_finer(core, market: str, code: str, tf: str, target: int) -> tuple[list[dict], str]:
    if tf == "20m":
        finer, src = _direct_fetch(core, market, code, "5m", target * 4 + 8)
        rows = _aggregate(finer, 20, target)
        return rows, src + " -> local 20m grouping"
    if tf in ("3m", "5m"):
        mins = int(tf[:-1])
        finer, src = _direct_fetch(core, market, code, "1m", target * mins + mins * 2)
        rows = _aggregate(finer, mins, target)
        return rows, src + f" -> local {tf} grouping"
    return [], ""


def _key_lock(key):
    with _LOCK:
        lk = _KEY_LOCKS.get(key)
        if lk is None:
            lk = threading.Lock()
            _KEY_LOCKS[key] = lk
        return lk


def install(core) -> bool:
    global _INSTALLED
    if _INSTALLED:
        return True
    feed = getattr(core, "feed", None)
    if feed is None or not hasattr(feed, "bars"):
        return False
    original = feed.bars

    def bars(market, code, timeframe="1m", *args, **kwargs):
        tf = _tf(timeframe)
        m = str(market or "").upper()
        c = str(code or "").upper().strip()
        if m not in ("KR", "US") or tf not in _TARGETS or not c:
            return original(market, code, timeframe, *args, **kwargs)
        target = _TARGETS[tf]
        key = (m, c, tf)
        now = time.time()
        try:
            live = list(original(market, code, timeframe, *args, **kwargs) or [])
        except Exception:
            live = []
        with _LOCK:
            cached = _CACHE.get(key)
            if cached and now - cached[0] < _TTL[tf] and len(cached[1]) >= target:
                return _merge(cached[1], live, target)
        with _key_lock(key):
            now = time.time()
            with _LOCK:
                cached = _CACHE.get(key)
                if cached and now - cached[0] < _TTL[tf] and len(cached[1]) >= target:
                    return _merge(cached[1], live, target)
            errors = []
            try:
                official, source = _direct_fetch(core, m, c, tf, target)
                merged = _merge(official, live, target)
                if len(merged) < target and tf != "1m":
                    try:
                        fallback, fallback_source = _fallback_from_finer(core, m, c, tf, target)
                        merged = _merge(merged, fallback, target)
                        if len(fallback) >= target:
                            source = fallback_source
                    except Exception as exc:
                        errors.append(f"fallback:{exc}")
                with _LOCK:
                    _CACHE[key] = (now, merged, source)
                    if len(merged) >= target:
                        _ERRORS.pop(key, None)
                    else:
                        _ERRORS[key] = f"{source}: {len(merged)}/{target}" + (" | " + " | ".join(errors) if errors else "")
                return merged
            except Exception as exc:
                errors.append(str(exc))
                if tf != "1m":
                    try:
                        fallback, source = _fallback_from_finer(core, m, c, tf, target)
                        merged = _merge(fallback, live, target)
                        with _LOCK:
                            _CACHE[key] = (now, merged, source)
                            if len(merged) >= target:
                                _ERRORS.pop(key, None)
                            else:
                                _ERRORS[key] = f"{source}: {len(merged)}/{target}"
                        return merged
                    except Exception as fexc:
                        errors.append(f"fallback:{fexc}")
                with _LOCK:
                    _ERRORS[key] = " | ".join(errors)[-700:]
                    cached = _CACHE.get(key)
                if cached:
                    return _merge(cached[1], live, target)
                return _merge([], live, target)

    bars._namuh_official_intraday = True
    bars._namuh_all_symbols_on_demand = True
    feed.bars = bars

    def intraday_snapshot(market: str, code: str) -> dict:
        m = str(market or "").upper()
        c = str(code or "").upper().strip()
        if m == "COIN":
            cf = getattr(core, "coin_feed", None)
            if cf is None:
                return {"market": m, "code": c, "bars": {}, "counts": {}, "targets": dict(_TARGETS)}
            out = {}
            for tf, target in _TARGETS.items():
                try:
                    if tf == "20m":
                        raw = cf.chart(c, "5m", target * 4 + 8)
                        out[tf] = _aggregate(raw, 20, target)
                    else:
                        out[tf] = list(cf.chart(c, tf, target) or [])[-target:]
                except Exception:
                    out[tf] = []
            counts = {k: len(v) for k, v in out.items()}
            return {
                "market": m, "code": c, "bars": out, "counts": counts,
                "targets": dict(_TARGETS), "complete": {k: counts.get(k, 0) >= v for k, v in _TARGETS.items()},
                "all_ready": all(counts.get(k, 0) >= v for k, v in _TARGETS.items()),
                "source": "Coinone official OHLCV",
            }
        try:
            feed.q(m, c)
        except Exception:
            pass
        out = {tf: list(feed.bars(m, c, tf) or [])[-target:] for tf, target in _TARGETS.items()}
        counts = {k: len(v) for k, v in out.items()}
        return {
            "market": m, "code": c, "bars": out, "counts": counts,
            "targets": dict(_TARGETS), "complete": {k: counts.get(k, 0) >= v for k, v in _TARGETS.items()},
            "all_ready": all(counts.get(k, 0) >= v for k, v in _TARGETS.items()),
            "source": "NHPLUG official OHLCV",
            "all_symbols_on_demand": True,
            "errors": {tf: _ERRORS.get((m, c, tf), "") for tf in _TARGETS},
        }

    core.intraday_snapshot = intraday_snapshot
    if not any(getattr(r, "path", "") == "/api/v360/intraday/{market}/{code}" for r in core.app.router.routes):
        @core.app.get("/api/v360/intraday/{market}/{code}")
        def v360_intraday(market: str, code: str):
            return intraday_snapshot(market, code)

    core._NAMUH_INTRADAY_AUDIT = {"status": "scheduled", "items": {}}

    def _audit():
        time.sleep(4.0)
        tests = (("KR", "005930"), ("KR", "373220"), ("US", "IBM"))
        result = {}
        for market, code in tests:
            try:
                snap = intraday_snapshot(market, code)
                item = {
                    "counts": dict(snap.get("counts") or {}),
                    "complete": dict(snap.get("complete") or {}),
                    "all_ready": bool(snap.get("all_ready")),
                    "errors": dict(snap.get("errors") or {}),
                }
            except Exception as exc:
                item = {"counts": {}, "complete": {}, "all_ready": False, "errors": {"audit": str(exc)[:300]}}
            result[f"{market}:{code}"] = item
            print(f"NAMUH INTRADAY AUDIT {market}:{code} counts={item['counts']} all_ready={item['all_ready']} errors={item['errors']}", flush=True)
        core._NAMUH_INTRADAY_AUDIT = {"status": "done", "items": result, "updated_at": time.time()}

    threading.Thread(target=_audit, name="namuh-intraday-audit", daemon=True).start()

    _INSTALLED = True
    print("NAMUH OFFICIAL INTRADAY active: all symbols on-demand; 1m=60, 3m/5m/20m=30", flush=True)
    return True
