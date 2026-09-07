from __future__ import annotations

import threading
import time
from datetime import datetime
from zoneinfo import ZoneInfo

_INSTALLED = False
_LOCK = threading.RLock()
_CACHE: dict[tuple[str, str, str], tuple[float, list[dict], str]] = {}
_ERRORS: dict[tuple[str, str, str], str] = {}
_TARGETS = {"1m": 60, "3m": 30, "5m": 30, "20m": 30}
_TTL = {"1m": 20.0, "3m": 30.0, "5m": 30.0, "20m": 60.0}


def _f(v, default=0.0):
    try:
        return float(v)
    except Exception:
        return float(default)


def _tf(v: str) -> str:
    s = str(v or "1m").strip().lower()
    aliases = {
        "1min": "1m", "minute": "1m", "3min": "3m", "5min": "5m",
        "20min": "20m", "1분": "1m", "3분": "3m", "5분": "5m", "20분": "20m",
    }
    return aliases.get(s, s)


def _time_key(b: dict) -> str:
    raw = str(b.get("time") or b.get("datetime") or b.get("timestamp") or b.get("date") or "")
    return raw.replace("-", "").replace(":", "").replace(" ", "").replace("T", "")


def _norm(rows) -> list[dict]:
    out = {}
    for b in list(rows or []):
        if not isinstance(b, dict):
            continue
        t = _time_key(b)
        o = _f(b.get("open") if b.get("open") is not None else b.get("stck_oprc") or b.get("open_prc"))
        h = _f(b.get("high") if b.get("high") is not None else b.get("stck_hgpr") or b.get("high"))
        l = _f(b.get("low") if b.get("low") is not None else b.get("stck_lwpr") or b.get("low"))
        c = _f(b.get("close") if b.get("close") is not None else b.get("stck_prpr") or b.get("close_prc") or b.get("trdprc"))
        v = _f(b.get("volume") if b.get("volume") is not None else b.get("vol") or b.get("movolume") or b.get("acml_vol"))
        if not t or min(o, h, l, c) <= 0:
            continue
        if h < max(o, c) or l > min(o, c):
            continue
        out[t] = {"time": t, "open": o, "high": h, "low": l, "close": c, "volume": v}
    return [out[k] for k in sorted(out)]


def _rows(block) -> list[dict]:
    if isinstance(block, list):
        return [x for x in block if isinstance(x, dict)]
    if isinstance(block, dict):
        return [block]
    return []


def _kr_fetch(core, code: str, tf: str, target: int) -> tuple[list[dict], str]:
    from nhplug import call
    mins = int(tf[:-1])
    errors = []
    market_order = list(getattr(core.feed, "_market_order", lambda: ["KRX"])() or ["KRX"])
    for market_cd in market_order:
        try:
            data = call("/krstock/quote/v1/period", {
                "market_cd": market_cd,
                "iem_cd": code,
                "mrkt_div_cls_code": "",
                "edate": datetime.now(core.KST).strftime("%Y%m%d"),
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
            raw = []
            for key in ("Output_1", "output1", "output_1", "Output1"):
                raw.extend(_rows(data.get(key) if isinstance(data, dict) else None))
            parsed = []
            for x in raw:
                date = str(x.get("bsop_date") or x.get("qry_date") or "").replace("-", "").replace("/", "")
                tm = str(x.get("bsop_time") or x.get("qry_time") or "").replace(":", "")
                if len(tm) < 6:
                    tm = tm.ljust(6, "0")
                parsed.append({
                    "time": date + tm,
                    "open": x.get("stck_oprc"),
                    "high": x.get("stck_hgpr"),
                    "low": x.get("stck_lwpr"),
                    "close": x.get("stck_prpr"),
                    "volume": x.get("vol") if x.get("vol") is not None else x.get("acml_vol"),
                })
            bars = _norm(parsed)
            if bars:
                return bars[-target:], f"NHPLUG KR {tf} official"
        except Exception as exc:
            errors.append(f"{market_cd}:{exc}")
    raise RuntimeError(" | ".join(errors)[:300] or "KR minute bars empty")


def _us_fetch(core, code: str, tf: str, target: int) -> tuple[list[dict], str]:
    from nhplug import call
    mins = int(tf[:-1])
    ny = datetime.now(ZoneInfo("America/New_York"))
    data = call("/gbstock/quote/v1/period", {
        "iem_cd": code,
        "end_dt": ny.strftime("%Y%m%d"),
        "count": f"{max(target, 60):04d}",
        "maxavg": "000",
        "gubun": "2",
        "xtick": f"{mins:04d}",
        "today_cls": "0",
        "market_cls": "1",
    })
    raw = []
    for key in ("Output_1", "output1", "output_1", "Output1"):
        raw.extend(_rows(data.get(key) if isinstance(data, dict) else None))
    parsed = []
    for x in raw:
        date = str(x.get("trade_date") or x.get("date") or x.get("bsop_date") or "").replace("-", "").replace("/", "")
        tm = str(x.get("trade_time") or x.get("time") or "").replace(":", "")
        if len(tm) < 6:
            tm = tm.ljust(6, "0")
        parsed.append({
            "time": date + tm,
            "open": x.get("open_prc"),
            "high": x.get("high"),
            "low": x.get("low"),
            "close": x.get("close_prc") if x.get("close_prc") is not None else x.get("trdprc"),
            "volume": x.get("movolume") if x.get("movolume") is not None else x.get("acvol"),
        })
    bars = _norm(parsed)
    if not bars:
        raise RuntimeError("US minute bars empty")
    return bars[-target:], f"NHPLUG US {tf} official"


def _merge(a, b, target: int) -> list[dict]:
    rows = {}
    for x in _norm(a) + _norm(b):
        rows[_time_key(x)] = x
    return [rows[k] for k in sorted(rows)][-target:]


def _aggregate_20m(one_minute: list[dict], target: int = 30) -> list[dict]:
    buckets = {}
    for b in _norm(one_minute):
        t = str(b.get("time") or "")
        if len(t) < 12:
            continue
        hh, mm = int(t[8:10]), int(t[10:12])
        slot = (mm // 20) * 20
        key = t[:8] + f"{hh:02d}{slot:02d}00"
        g = buckets.setdefault(key, {"time": key, "open": b["open"], "high": b["high"], "low": b["low"], "close": b["close"], "volume": 0.0})
        g["high"] = max(g["high"], b["high"])
        g["low"] = min(g["low"], b["low"])
        g["close"] = b["close"]
        g["volume"] += _f(b.get("volume"))
    return [buckets[k] for k in sorted(buckets)][-target:]


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
            if cached and now - cached[0] < _TTL[tf]:
                return _merge(cached[1], live, target)
        try:
            official, source = (_kr_fetch(core, c, tf, target) if m == "KR" else _us_fetch(core, c, tf, target))
            merged = _merge(official, live, target)
            with _LOCK:
                _CACHE[key] = (now, merged, source)
                _ERRORS.pop(key, None)
            return merged
        except Exception as exc:
            with _LOCK:
                _ERRORS[key] = str(exc)[:260]
                cached = _CACHE.get(key)
            if cached:
                return _merge(cached[1], live, target)
            return _merge([], live, target)

    bars._namuh_official_intraday = True
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
                        raw = cf.chart(c, "5m", target * 4)
                        out[tf] = _aggregate_20m(raw, target)
                    else:
                        out[tf] = list(cf.chart(c, tf, target) or [])[-target:]
                except Exception:
                    out[tf] = []
            return {
                "market": m, "code": c, "bars": out,
                "counts": {k: len(v) for k, v in out.items()},
                "targets": dict(_TARGETS), "source": "Coinone official OHLCV",
            }
        out = {tf: list(feed.bars(m, c, tf) or [])[-target:] for tf, target in _TARGETS.items()}
        return {
            "market": m, "code": c, "bars": out,
            "counts": {k: len(v) for k, v in out.items()},
            "targets": dict(_TARGETS), "source": "NHPLUG official OHLCV",
            "errors": {tf: _ERRORS.get((m, c, tf), "") for tf in _TARGETS},
        }

    core.intraday_snapshot = intraday_snapshot
    if not any(getattr(r, "path", "") == "/api/v360/intraday/{market}/{code}" for r in core.app.router.routes):
        @core.app.get("/api/v360/intraday/{market}/{code}")
        def v360_intraday(market: str, code: str):
            return intraday_snapshot(market, code)

    _INSTALLED = True
    print("NAMUH OFFICIAL INTRADAY active: 1m=60, 3m/5m/20m=30", flush=True)
    return True
