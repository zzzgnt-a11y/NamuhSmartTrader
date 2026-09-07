from __future__ import annotations

import json
import os
import threading
import time
from collections import OrderedDict
from datetime import datetime, timezone, timedelta
from typing import Any

_INSTALLED = False
_LOCK = threading.RLock()
_CACHE: OrderedDict[str, list[dict]] = OrderedDict()
_LAST_SAVE: dict[str, tuple[int, str]] = {}
_MAX_KEYS = 240
_MAX_BARS = 20
_KST = timezone(timedelta(hours=9))
_DB_READY = False


def _session_date() -> str:
    return datetime.now(_KST).strftime("%Y-%m-%d")


def _bar_key(b: dict) -> str:
    for k in ("timestamp", "datetime", "time", "date", "dt", "ts", "t"):
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


def _pg_connect():
    url = os.getenv("DATABASE_URL") or os.getenv("POSTGRES_URL")
    if not url:
        return None
    try:
        import psycopg
        return psycopg.connect(url, connect_timeout=5)
    except Exception:
        return None


def _pg_ensure() -> bool:
    global _DB_READY
    if _DB_READY:
        return True
    con = _pg_connect()
    if con is None:
        return False
    try:
        with con:
            with con.cursor() as cur:
                cur.execute("""
                    create table if not exists namuh_minute_bar_cache (
                        market text not null,
                        code text not null,
                        timeframe text not null,
                        session_date text not null,
                        bars_json text not null,
                        updated_at timestamptz not null default now(),
                        primary key (market, code, timeframe, session_date)
                    )
                """)
        _DB_READY = True
        return True
    except Exception:
        return False
    finally:
        try: con.close()
        except Exception: pass


def _pg_load(market: str, code: str, timeframe: str) -> list[dict]:
    if not _pg_ensure():
        return []
    con = _pg_connect()
    if con is None:
        return []
    try:
        with con.cursor() as cur:
            cur.execute("""
                select bars_json
                from namuh_minute_bar_cache
                where market=%s and code=%s and timeframe=%s and session_date=%s
                  and updated_at > now() - interval '8 hours'
            """, (market, code, timeframe, _session_date()))
            row = cur.fetchone()
        if not row:
            return []
        raw = json.loads(row[0])
        return [dict(x) for x in raw if isinstance(x, dict)][-_MAX_BARS:]
    except Exception:
        return []
    finally:
        try: con.close()
        except Exception: pass


def _pg_save(market: str, code: str, timeframe: str, bars: list[dict]) -> None:
    if not bars or not _pg_ensure():
        return
    con = _pg_connect()
    if con is None:
        return
    try:
        payload = json.dumps(bars[-_MAX_BARS:], ensure_ascii=False, default=str, separators=(",", ":"))
        with con:
            with con.cursor() as cur:
                cur.execute("""
                    insert into namuh_minute_bar_cache
                        (market, code, timeframe, session_date, bars_json, updated_at)
                    values (%s,%s,%s,%s,%s,now())
                    on conflict (market, code, timeframe, session_date)
                    do update set bars_json=excluded.bars_json, updated_at=now()
                """, (market, code, timeframe, _session_date(), payload))
    except Exception:
        pass
    finally:
        try: con.close()
        except Exception: pass


def install(core: Any) -> bool:
    global _INSTALLED
    if _INSTALLED:
        return True
    feed = getattr(core, "feed", None)
    store = getattr(core, "store", None)
    if feed is None or not hasattr(feed, "bars"):
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

        skey = f"minute_bars_v2:{_session_date()}:{m}:{c}"
        with _LOCK:
            persisted = _CACHE.get(skey)
            if persisted is None:
                persisted = []
                # First try the app's normal persistent store for compatibility.
                if store is not None:
                    try:
                        raw = store.load_json(skey, {}) or {}
                        if isinstance(raw, dict) and str(raw.get("session_date") or "") == _session_date():
                            persisted = list(raw.get("bars") or [])
                    except Exception:
                        persisted = []
                # Direct Postgres is the restart-safe fallback when store setup/order
                # changes during a Render deploy.
                if not persisted:
                    persisted = _pg_load(m, c, "1m")
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
                    payload = {
                        "version": 2,
                        "market": m,
                        "code": c,
                        "session_date": _session_date(),
                        "updated_at": time.time(),
                        "bars": merged[-_MAX_BARS:],
                    }
                    if store is not None:
                        try:
                            store.save_json(skey, payload)
                        except Exception:
                            pass
                    # Never block the quote/scalp path on database I/O.
                    threading.Thread(target=_pg_save, args=(m, c, "1m", merged), daemon=True).start()

        return merged

    wrapped_bars._namuh_minute_persist = True
    feed.bars = wrapped_bars
    _INSTALLED = True
    print("MINUTE_PERSIST installed version=2 max_bars=20 direct_pg=1", flush=True)
    return True
