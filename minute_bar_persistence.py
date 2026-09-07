from __future__ import annotations

import threading
import time
from collections import OrderedDict
from typing import Any

_INSTALLED = False
_LOCK = threading.RLock()
_CACHE: OrderedDict[str, list[dict]] = OrderedDict()
_LAST_SAVE: dict[str, tuple[int, str]] = {}
_MAX_KEYS = 120
_MAX_BARS = 20


def _bar_key(b: dict) -> str:
    for k in ("timestamp", "datetime", "time", "date", "dt", "ts"):
        v = b.get(k)
        if v not in (None, ""):
            return f"{k}:{v}"
    return "|".join(str(b.get(k, "")) for k in ("open", "high", "low", "close", "volume"))


def _merge(old: list[dict], live: list[dict]) -> list[dict]:
    merged: OrderedDict[str, dict] = OrderedDict()
    for b in list(old or []) + list(live or []):
        if isinstance(b, dict):
            merged[_bar_key(b)] = dict(b)
    return list(merged.values())[-_MAX_BARS:]


def install(core: Any) -> bool:
    global _INSTALLED
    if _INSTALLED:
        return True
    feed = getattr(core, "feed", None)
    store = getattr(core, "store", None)
    if feed is None or store is None or not hasattr(feed, "bars"):
        return False

    original = feed.bars

    def wrapped_bars(market, code, timeframe="1m", *args, **kwargs):
        live = list(original(market, code, timeframe, *args, **kwargs) or [])
        if str(timeframe).lower() not in ("1m", "1min", "minute"):
            return live
        m = str(market or "").upper()
        c = str(code or "").upper()
        if m not in ("KR", "US") or not c:
            return live
        skey = f"minute_bars_v1:{m}:{c}"
        with _LOCK:
            persisted = _CACHE.get(skey)
            if persisted is None:
                try:
                    raw = store.load_json(skey, {}) or {}
                    persisted = list(raw.get("bars") or []) if isinstance(raw, dict) else []
                except Exception:
                    persisted = []
                _CACHE[skey] = persisted[-_MAX_BARS:]
            merged = _merge(persisted, live)
            _CACHE[skey] = merged
            _CACHE.move_to_end(skey)
            while len(_CACHE) > _MAX_KEYS:
                _CACHE.popitem(last=False)

            if merged:
                newest = _bar_key(merged[-1])
                sig = (len(merged), newest)
                if _LAST_SAVE.get(skey) != sig:
                    _LAST_SAVE[skey] = sig
                    try:
                        store.save_json(skey, {
                            "version": 1,
                            "market": m,
                            "code": c,
                            "updated_at": time.time(),
                            "bars": merged[-_MAX_BARS:],
                        })
                    except Exception:
                        pass
        return merged

    feed.bars = wrapped_bars
    _INSTALLED = True
    print("MINUTE_PERSIST installed max_bars=20", flush=True)
    return True
