from __future__ import annotations

import threading
import time

_INSTALLED = False
_LOCK = threading.RLock()
_CACHE = {}
_STATS = {
    "suppressed_orderbook_fullscan": 0,
    "suppressed_volume_backfill": 0,
    "suppressed_sync_minute_fetch": 0,
    "minute_bg_busy_skip": 0,
    "hot_orderbook_ok": 0,
    "hot_orderbook_fail": 0,
}
_MINUTE_NET_LOCK = threading.Lock()


def _key(path, params):
    p = params or {}
    return (
        str(path), str(p.get("iem_cd") or ""), str(p.get("market_cd") or ""),
        str(p.get("edate") or ""), str(p.get("gubun") or ""), str(p.get("xtick") or ""),
    )


def apply(ns=None):
    global _INSTALLED
    if _INSTALLED:
        return True
    core = ns.get("core") if isinstance(ns, dict) else None
    if core is None:
        return False

    try:
        import nhplug
    except Exception:
        return False

    old_call = getattr(nhplug, "call", None)
    if not callable(old_call) or getattr(old_call, "_namuh_traffic_guard", False):
        _INSTALLED = True
        return True

    fixed = list(dict.fromkeys(list(getattr(core.feed, "fixed", {}).get("KR", []) or [])))
    hot = ["005930", *[str(x).upper() for x in fixed if str(x).upper() != "005930"]]
    hot = list(dict.fromkeys(hot))[:24]
    hotset = set(hot)

    def guarded_call(path, params=None, *args, **kwargs):
        name = threading.current_thread().name
        p = params or {}
        code = str(p.get("iem_cd") or "").upper()
        path_s = str(path or "")

        # The orderbook integrity patch accidentally added a SECOND scanner over
        # the entire ~4k KR catalog. Kill only that duplicate scanner. The main
        # currentExecution scanner remains untouched.
        if name == "kr-orderbook-currentPrice":
            with _LOCK:
                _STATS["suppressed_orderbook_fullscan"] += 1
            raise SystemExit("duplicate full-universe orderbook scanner disabled by traffic guard")

        # The 15-session backfill had three workers and candidate-time scheduling.
        # Keep one worker for fixed/hot symbols only; arbitrary universe symbols
        # are not allowed to saturate the quote transport.
        if name.startswith("volume15-curve-"):
            if name not in ("volume15-curve-1",) or (code and code not in hotset):
                with _LOCK:
                    _STATS["suppressed_volume_backfill"] += 1
                if name not in ("volume15-curve-1",):
                    raise SystemExit("extra volume backfill worker disabled by traffic guard")
                raise RuntimeError("non-hot volume backfill deferred by traffic guard")

        # Minute-history cache misses used to make web/candidate threads perform
        # multi-day REST fetches synchronously. Never block those threads. They
        # immediately fall back to the already collected live/persisted 1m data.
        is_minute_period = (
            path_s.endswith("/krstock/quote/v1/period")
            and str(p.get("gubun") or "") == "5"
            and str(p.get("xtick") or "") == "001"
        )
        if is_minute_period:
            k = _key(path_s, p)
            with _LOCK:
                cached = _CACHE.get(k)
            if cached is not None and not name.startswith(("minute-", "volume15-curve-")):
                return cached
            if not name.startswith(("minute-", "volume15-curve-")):
                with _LOCK:
                    _STATS["suppressed_sync_minute_fetch"] += 1
                return {}
            if name.startswith("minute-"):
                if not _MINUTE_NET_LOCK.acquire(blocking=False):
                    with _LOCK:
                        _STATS["minute_bg_busy_skip"] += 1
                    return {}
                try:
                    data = old_call(path, params, *args, **kwargs)
                    if data:
                        with _LOCK:
                            _CACHE[k] = data
                    return data
                finally:
                    _MINUTE_NET_LOCK.release()

        data = old_call(path, params, *args, **kwargs)
        if is_minute_period and data:
            with _LOCK:
                _CACHE[_key(path_s, p)] = data
        return data

    guarded_call._namuh_traffic_guard = True
    guarded_call._namuh_traffic_guard_old = old_call
    nhplug.call = guarded_call

    # Replace the killed full-catalog orderbook scanner with a bounded hot-list
    # refresher. This keeps actual total queue quantities fresh where scores are
    # actively used, without a second 4k-symbol REST sweep.
    refresh_book = getattr(core, "refresh_kr_orderbook_now", None)
    if callable(refresh_book) and hot:
        def hot_orderbook_loop():
            idx = 0
            stop = getattr(core.feed, "_stop", None)
            while stop is None or not stop.is_set():
                code = hot[idx % len(hot)]
                idx += 1
                try:
                    refresh_book(code, force=True)
                    with _LOCK:
                        _STATS["hot_orderbook_ok"] += 1
                except Exception:
                    with _LOCK:
                        _STATS["hot_orderbook_fail"] += 1
                if stop is not None:
                    stop.wait(1.0)
                else:
                    time.sleep(1.0)
        threading.Thread(target=hot_orderbook_loop, daemon=True, name="kr-orderbook-hot-guard").start()

    old_health = getattr(core, "health_payload", None)
    if callable(old_health):
        def health():
            d = dict(old_health())
            with _LOCK:
                d["runtime_traffic_guard"] = {**_STATS, "hot_symbols": len(hot), "active": True}
            return d
        core.health_payload = health

    _INSTALLED = True
    print("NAMUH TRAFFIC GUARD active: no sync minute fetch + no duplicate 4k orderbook scan + bounded volume backfill", flush=True)
    return True
