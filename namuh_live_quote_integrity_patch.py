from __future__ import annotations

import threading
import time

_INSTALLED = False
_LOCK = threading.RLock()
_REFRESH_AT: dict[str, float] = {}
_STATUS = {
    "scanner_source": "currentExecution",
    "realtime": False,
    "realtime_error": "",
    "realtime_updated_at": 0.0,
    "direct_refresh_ok": 0,
    "direct_refresh_fail": 0,
}


def _f(v, default=0.0):
    try:
        return float(str(v).replace(",", "").replace("+", "").strip())
    except Exception:
        return float(default)


def _walk(v):
    if isinstance(v, dict):
        yield v
        for x in v.values():
            yield from _walk(x)
    elif isinstance(v, (list, tuple)):
        for x in v:
            yield from _walk(x)


def _pick(data, keys):
    for obj in _walk(data):
        if not isinstance(obj, dict):
            continue
        for k in keys:
            if k in obj and obj[k] not in (None, ""):
                v = _f(obj[k])
                if v != 0:
                    return v
    return 0.0


def _pick_text(data, keys):
    for obj in _walk(data):
        if not isinstance(obj, dict):
            continue
        for k in keys:
            if k in obj and obj[k] not in (None, ""):
                return str(obj[k]).strip()
    return ""


def _apply_execution(feed, code, data, *, source="currentExecution"):
    """Apply only fields guaranteed by NHPLUG currentExecution/realtime execution.

    currentPrice does NOT expose cttr. currentExecution Output_0/Output_1 and
    realtime execution expose the actual execution-strength field.
    """
    q = feed.q("KR", code)
    price = _pick(data, ("stck_prpr", "price", "prpr"))
    volume = _pick(data, ("acml_vol", "volume", "new_volume"))
    strength = _pick(data, ("cttr", "volpower", "execution_strength"))
    open_ = _pick(data, ("stck_oprc", "open"))
    high = _pick(data, ("stck_hgpr", "high"))
    low = _pick(data, ("stck_lwpr", "low"))
    ask = _pick(data, ("askp", "offer", "best_ask"))
    bid = _pick(data, ("bidp", "bid", "best_bid"))
    name = _pick_text(data, ("iem_nm", "name"))
    now = time.time()

    if name:
        q.name = name
    if price > 0:
        q.mark(price, volume, now)
    elif volume > 0:
        q.volume = max(_f(getattr(q, "volume", 0)), volume)
    if open_ > 0:
        q.open = open_
    if high > 0:
        q.high = high
    if low > 0:
        q.low = low
    if ask > 0:
        q.best_ask = ask
    if bid > 0:
        q.best_bid = bid
    if strength > 0:
        q.update_execution(strength, now)
        q.execution_updated_at = now
        q.execution_source = source
    return q, strength


def apply(ns=None):
    global _INSTALLED
    if _INSTALLED:
        return True
    core = ns.get("core") if isinstance(ns, dict) else None
    if core is None:
        return False
    feed = getattr(core, "feed", None)
    if feed is None:
        return False

    # 1) Replace the KR quote scanner's currentPrice call with currentExecution.
    # currentExecution supplies current price/OHLC/volume AND the real cttr in one
    # official NHPLUG call, so this does not double REST traffic.
    def kr_scanner_execution():
        try:
            feed._load_kr_master()
        except Exception:
            pass
        codes = feed.code_lists.get("KR") or feed.fixed.get("KR") or []
        if not codes:
            return
        from nhplug import call
        while not feed._stop.is_set():
            code = codes[feed.scan_index["KR"] % len(codes)]
            feed.scan_index["KR"] = (feed.scan_index["KR"] + 1) % len(codes)
            err = ""
            orders = list(getattr(feed, "_market_order", lambda: ["UNT", "KRX"])() or ["UNT", "KRX"])
            for market_cd in orders:
                try:
                    data = call("/krstock/quote/v1/currentExecution", {
                        "iem_cd": code,
                        "market_cd": market_cd,
                        "array_cnt": "0001",
                    })
                    q, strength = _apply_execution(feed, code, data, source=f"currentExecution:{market_cd}")
                    if _f(getattr(q, "price", 0)) > 0:
                        feed.connected["KR"] = True
                        feed.errors["KR"] = ""
                        break
                except Exception as exc:
                    err = f"{market_cd} {code}: {exc}"[:300]
                    if "429" in err:
                        time.sleep(1.0)
                        break
            if err and _f(getattr(feed.q("KR", code), "price", 0)) <= 0:
                feed.errors["KR"] = err
            feed._stop.wait(0.05)

    feed.kr_scanner = kr_scanner_execution

    # 2) Exact on-demand currentExecution refresh for the stock detail path.
    # Detail polling is 15 s, so a direct refresh here is cheap and guarantees the
    # score shown for the opened stock uses the latest NH execution-strength value.
    def refresh_now(code: str, *, force=False):
        code = str(code or "").upper().strip()
        if not code:
            return None
        now = time.time()
        with _LOCK:
            last = _REFRESH_AT.get(code, 0.0)
            if not force and now - last < 1.5:
                return feed.q("KR", code)
            _REFRESH_AT[code] = now
        try:
            from nhplug import call
            last_exc = None
            orders = list(getattr(feed, "_market_order", lambda: ["UNT", "KRX"])() or ["UNT", "KRX"])
            for market_cd in orders:
                try:
                    data = call("/krstock/quote/v1/currentExecution", {
                        "iem_cd": code,
                        "market_cd": market_cd,
                        "array_cnt": "0001",
                    })
                    q, strength = _apply_execution(feed, code, data, source=f"detail-currentExecution:{market_cd}")
                    if strength > 0:
                        with _LOCK:
                            _STATUS["direct_refresh_ok"] += 1
                        return q
                except Exception as exc:
                    last_exc = exc
            if last_exc:
                raise last_exc
        except Exception:
            with _LOCK:
                _STATUS["direct_refresh_fail"] += 1
        return feed.q("KR", code)

    core.refresh_kr_execution_now = refresh_now

    old_detail = getattr(core, "stock_detail", None)
    if callable(old_detail) and not getattr(old_detail, "_namuh_live_quote_integrity", False):
        def stock_detail(*args, **kwargs):
            market = str(args[0] if args else kwargs.get("market", "")).upper()
            code = str(args[1] if len(args) > 1 else kwargs.get("code", "")).upper()
            if market == "KR" and code:
                refresh_now(code)
            d = old_detail(*args, **kwargs)
            if isinstance(d, dict) and market == "KR":
                q = feed.q("KR", code)
                d["price"] = _f(getattr(q, "price", d.get("price", 0)))
                flow = dict(d.get("flow") or {})
                flow["execution_strength"] = round(_f(getattr(q, "execution_strength", 0)), 2)
                flow["execution_source"] = str(getattr(q, "execution_source", ""))
                flow["execution_age_sec"] = round(max(0.0, time.time() - _f(getattr(q, "execution_updated_at", 0), time.time())), 2)
                d["flow"] = flow
                d["live_quote_integrity"] = {
                    "source": str(getattr(q, "execution_source", "")),
                    "execution_strength": round(_f(getattr(q, "execution_strength", 0)), 2),
                    "execution_updated_at": _f(getattr(q, "execution_updated_at", 0)),
                }
            return d
        stock_detail._namuh_live_quote_integrity = True
        core.stock_detail = stock_detail

    # 3) Keep Samsung + the nine highest-priority fixed KR codes on the official
    # integrated realtime execution channel. The other WebSocket slot remains for
    # the existing program-flow channel; the full universe still uses currentExecution.
    def realtime_loop():
        hot = list(dict.fromkeys(list(feed.fixed.get("KR") or [])))[:10]
        if not hot:
            return
        while not feed._stop.is_set():
            try:
                from nhplug.realtime import subscribe
                def on_msg(msg):
                    if not isinstance(msg, dict):
                        return
                    h = msg.get("header") if isinstance(msg.get("header"), dict) else {}
                    b = msg.get("body") if isinstance(msg.get("body"), dict) else {}
                    code = str(b.get("code") or h.get("tr_key") or "").strip()
                    if len(code) != 6:
                        return
                    _apply_execution(feed, code, b, source="realtime:mc")
                    with _LOCK:
                        _STATUS["realtime"] = True
                        _STATUS["realtime_error"] = ""
                        _STATUS["realtime_updated_at"] = time.time()
                subscribe(hot, on_msg, tr_cd="mc", timeout=30)
            except Exception as exc:
                with _LOCK:
                    _STATUS["realtime"] = False
                    _STATUS["realtime_error"] = str(exc)[:180]
                feed._stop.wait(2.0)

    threading.Thread(target=realtime_loop, daemon=True, name="kr-live-execution-hot10").start()

    old_health = getattr(core, "health_payload", None)
    if callable(old_health):
        def health():
            d = dict(old_health())
            with _LOCK:
                d["kr_live_quote_integrity"] = dict(_STATUS)
            q = feed.q("KR", "005930")
            d["samsung_execution"] = {
                "value": round(_f(getattr(q, "execution_strength", 0)), 2),
                "source": str(getattr(q, "execution_source", "")),
                "age_sec": round(max(0.0, time.time() - _f(getattr(q, "execution_updated_at", 0), time.time())), 2),
            }
            return d
        core.health_payload = health

    _INSTALLED = True
    print("NAMUH LIVE QUOTE INTEGRITY active: KR currentExecution + hot10 realtime mc + detail refresh", flush=True)
    return True
