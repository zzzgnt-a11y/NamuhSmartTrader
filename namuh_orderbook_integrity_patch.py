from __future__ import annotations

import threading
import time

_INSTALLED = False
_LOCK = threading.RLock()
_LAST: dict[str, float] = {}
_STATUS = {"ok": 0, "fail": 0, "last_error": "", "source": "NHPLUG currentPrice total_askp_rsqn/total_bidp_rsqn"}


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
                try:
                    return float(str(obj[k]).replace(",", "").replace("+", "").strip())
                except Exception:
                    pass
    return 0.0


def _apply(feed, code, data, source="currentPrice"):
    q = feed.q("KR", code)
    total_ask = _pick(data, ("total_askp_rsqn", "total_ask_qty", "ask_total_qty"))
    total_bid = _pick(data, ("total_bidp_rsqn", "total_bid_qty", "bid_total_qty"))
    ask1 = _pick(data, ("askp_rsqn1", "ask_rsqn", "ask_qty"))
    bid1 = _pick(data, ("bidp_rsqn1", "bid_rsqn", "bid_qty"))
    if total_ask > 0:
        q.total_ask_qty = total_ask
        q.ask_total_qty = total_ask
    if total_bid > 0:
        q.total_bid_qty = total_bid
        q.bid_total_qty = total_bid
    if ask1 > 0:
        q.askp_rsqn1 = ask1
    if bid1 > 0:
        q.bidp_rsqn1 = bid1
    q.orderbook_updated_at = time.time()
    q.orderbook_source = source
    return q, total_ask, total_bid


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

    def refresh(code, *, force=False):
        code = str(code or "").upper().strip()
        if not code:
            return feed.q("KR", code)
        now = time.time()
        with _LOCK:
            last = _LAST.get(code, 0.0)
            if not force and now - last < 1.5:
                return feed.q("KR", code)
            _LAST[code] = now
        try:
            from nhplug import call
            last_exc = None
            orders = list(getattr(feed, "_market_order", lambda: ["UNT", "KRX"])() or ["UNT", "KRX"])
            for market_cd in orders:
                try:
                    data = call("/krstock/quote/v1/currentPrice", {"iem_cd": code, "market_cd": market_cd})
                    q, ask, bid = _apply(feed, code, data, f"currentPrice:{market_cd}")
                    if ask > 0 and bid > 0:
                        with _LOCK:
                            _STATUS["ok"] += 1
                            _STATUS["last_error"] = ""
                        return q
                except Exception as exc:
                    last_exc = exc
            if last_exc:
                raise last_exc
        except Exception as exc:
            with _LOCK:
                _STATUS["fail"] += 1
                _STATUS["last_error"] = str(exc)[:180]
        return feed.q("KR", code)

    core.refresh_kr_orderbook_now = refresh

    # The stock detail score must use the same current orderbook that the user sees.
    old_detail = getattr(core, "stock_detail", None)
    if callable(old_detail) and not getattr(old_detail, "_namuh_orderbook_integrity", False):
        def stock_detail(*args, **kwargs):
            market = str(args[0] if args else kwargs.get("market", "")).upper()
            code = str(args[1] if len(args) > 1 else kwargs.get("code", "")).upper()
            if market == "KR" and code:
                refresh(code)
            d = old_detail(*args, **kwargs)
            if isinstance(d, dict) and market == "KR":
                q = feed.q("KR", code)
                ask = _f(getattr(q, "total_ask_qty", 0))
                bid = _f(getattr(q, "total_bid_qty", 0))
                d["live_orderbook_integrity"] = {
                    "ask_qty": ask, "bid_qty": bid,
                    "ratio": (ask / bid if ask > 0 and bid > 0 else None),
                    "source": str(getattr(q, "orderbook_source", "")),
                    "age_sec": round(max(0.0, time.time() - _f(getattr(q, "orderbook_updated_at", 0), time.time())), 2),
                }
            return d
        stock_detail._namuh_orderbook_integrity = True
        core.stock_detail = stock_detail

    # Restore the original currentPrice orderbook feed as a dedicated, bounded
    # background loop. Execution strength stays owned by currentExecution.
    def orderbook_loop():
        try:
            feed._load_kr_master()
        except Exception:
            pass
        idx = 0
        while not feed._stop.is_set():
            codes = feed.code_lists.get("KR") or feed.fixed.get("KR") or []
            if not codes:
                feed._stop.wait(1.0)
                continue
            code = codes[idx % len(codes)]
            idx += 1
            refresh(code, force=True)
            feed._stop.wait(0.35)

    threading.Thread(target=orderbook_loop, daemon=True, name="kr-orderbook-currentPrice").start()

    old_health = getattr(core, "health_payload", None)
    if callable(old_health):
        def health():
            d = dict(old_health())
            with _LOCK:
                d["kr_orderbook_integrity"] = dict(_STATUS)
            return d
        core.health_payload = health

    _INSTALLED = True
    print("NAMUH ORDERBOOK INTEGRITY active: currentPrice total queue quantities", flush=True)
    return True
