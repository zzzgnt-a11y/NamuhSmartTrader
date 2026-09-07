from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

_INSTALLED = False
_LOCK = threading.RLock()
_CACHE: dict[tuple[str, str], tuple[float, list[dict], str]] = {}
_ERRORS: dict[tuple[str, str], str] = {}
_KEY_LOCKS: dict[tuple[str, str], threading.Lock] = {}
_REFRESHING: set[tuple[str, str]] = set()
_TARGETS = {"1m": 60, "3m": 30, "5m": 30, "20m": 30}
_BASE_TARGET = 720
_CACHE_TTL = 600.0


def _f(v, default=0.0):
    try:
        return float(str(v).replace(",", "").strip())
    except Exception:
        return float(default)


def _tf(v: str) -> str:
    s = str(v or "1m").strip().lower()
    aliases = {
        "1min": "1m", "minute": "1m", "3min": "3m", "5min": "5m", "20min": "20m",
        "1분": "1m", "3분": "3m", "5분": "5m", "20분": "20m",
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
    for key in ("Output_0", "output0", "output_0", "Output0", "Output_1", "output1", "output_1", "Output1", "output"):
        raw.extend(_rows(data.get(key)))
    return raw


def _date_candidates(tz, n=4):
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
        date = _digits(x.get("bsop_date") or x.get("qry_date") or x.get("trade_date") or x.get("xymd") or x.get("date"))[:8]
        tm = _digits(x.get("bsop_time") or x.get("qry_time") or x.get("trade_time") or x.get("xytm") or x.get("time"))
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


def _merge(a, b, target: int = _BASE_TARGET) -> list[dict]:
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


def _fetch_base1(core, market: str, code: str) -> tuple[list[dict], str]:
    from nhplug import call
    got = []
    errors = []
    if market == "KR":
        orders = list(getattr(core.feed, "_market_order", lambda: ["KRX"])() or ["KRX"])
        for market_cd in orders:
            local = []
            for edate in _date_candidates(core.KST, 4):
                try:
                    data = call("/krstock/quote/v1/period", {
                        "market_cd": market_cd, "iem_cd": code, "mrkt_div_cls_code": "", "edate": edate,
                        "array_cnt": f"{_BASE_TARGET:04d}", "maxavg": "000", "gubun": "5", "xtick": "001",
                        "today_cls_code": "0", "fake_tick": "0", "sur_flag": "0", "sur_gb_day_cnt": "00",
                        "sur_bf_end_time": "", "out1_scale_change": "0", "out2_scale_change": "0",
                    })
                    local = _merge(local, _parse_period_rows(_response_rows(data)))
                    if len(local) >= 620:
                        return local[-_BASE_TARGET:], "NHPLUG KR 1m shared official"
                except Exception as exc:
                    errors.append(f"{market_cd}/{edate}:{exc}")
                    if "IGW40020" in str(exc):
                        break
            if len(local) > len(got):
                got = local
    else:
        for end_dt in _date_candidates(ZoneInfo("America/New_York"), 4):
            try:
                data = call("/gbstock/quote/v1/period", {
                    "iem_cd": code, "end_dt": end_dt, "count": f"{_BASE_TARGET:04d}", "maxavg": "000",
                    "gubun": "2", "xtick": "0001", "today_cls": "0", "market_cls": "1",
                })
                got = _merge(got, _parse_period_rows(_response_rows(data)))
                if len(got) >= 620:
                    return got[-_BASE_TARGET:], "NHPLUG US 1m shared official"
            except Exception as exc:
                errors.append(f"{end_dt}:{exc}")
    if got:
        return got[-_BASE_TARGET:], f"NHPLUG {market} 1m shared official partial"
    raise RuntimeError(" | ".join(errors)[-700:] or f"{market} 1m bars empty")


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

    def _store_refresh(m: str, c: str):
        key = (m, c)
        try:
            rows, source = _fetch_base1(core, m, c)
            with _LOCK:
                _CACHE[key] = (time.time(), rows, source)
                _ERRORS.pop(key, None)
        except Exception as exc:
            with _LOCK:
                _ERRORS[key] = str(exc)[-700:]
        finally:
            with _LOCK:
                _REFRESHING.discard(key)

    def _background_refresh(m: str, c: str):
        key = (m, c)
        with _LOCK:
            if key in _REFRESHING:
                return
            _REFRESHING.add(key)
        threading.Thread(target=_store_refresh, args=(m, c), daemon=True, name=f"minute-{m}-{c}").start()

    def _base_rows(m: str, c: str, live1: list[dict]) -> tuple[list[dict], str]:
        key = (m, c)
        now = time.time()
        with _LOCK:
            cached = _CACHE.get(key)
        if cached:
            if now - cached[0] > _CACHE_TTL:
                _background_refresh(m, c)
            return _merge(cached[1], live1), cached[2]
        with _key_lock(key):
            with _LOCK:
                cached = _CACHE.get(key)
            if cached:
                return _merge(cached[1], live1), cached[2]
            try:
                rows, source = _fetch_base1(core, m, c)
                merged = _merge(rows, live1)
                with _LOCK:
                    _CACHE[key] = (time.time(), rows, source)
                    _ERRORS.pop(key, None)
                return merged, source
            except Exception as exc:
                with _LOCK:
                    _ERRORS[key] = str(exc)[-700:]
                return _norm(live1)[-_BASE_TARGET:], "live/persisted 1m fallback"

    def bars(market, code, timeframe="1m", *args, **kwargs):
        tf = _tf(timeframe)
        m = str(market or "").upper()
        c = str(code or "").upper().strip()
        if m not in ("KR", "US") or tf not in _TARGETS or not c:
            return original(market, code, timeframe, *args, **kwargs)
        try:
            live1 = list(original(market, code, "1m", *args, **kwargs) or [])
        except Exception:
            live1 = []
        base, _source = _base_rows(m, c, live1)
        if tf == "1m":
            return base[-_TARGETS[tf]:]
        return _aggregate(base, int(tf[:-1]), _TARGETS[tf])

    feed.bars = bars

    def intraday_snapshot(market: str, code: str):
        m = str(market or "").upper()
        c = str(code or "").upper().strip()
        data = {tf: list(bars(m, c, tf) or []) for tf in _TARGETS}
        with _LOCK:
            meta = _CACHE.get((m, c))
            err = _ERRORS.get((m, c), "")
        return {
            "market": m, "code": c, "bars": data,
            "counts": {k: len(v) for k, v in data.items()}, "targets": dict(_TARGETS),
            "strategy_ready": all(len(data[k]) >= _TARGETS[k] for k in _TARGETS),
            "source": meta[2] if meta else "live/persisted 1m fallback", "error": err,
        }

    core.intraday_snapshot = intraday_snapshot
    old_health = getattr(core, "health_payload", None)
    if callable(old_health):
        def health():
            d = dict(old_health())
            with _LOCK:
                d["minute_shared_cache"] = {
                    "symbols": len(_CACHE), "errors": len(_ERRORS), "base_target_1m": _BASE_TARGET,
                    "targets": dict(_TARGETS), "stale_while_revalidate": True,
                }
            return d
        core.health_payload = health
    _INSTALLED = True
    print("NAMUH MINUTE DATA active: shared 1m base -> 1/3/5/20m; stale-while-revalidate", flush=True)
    return True
