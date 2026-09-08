from __future__ import annotations

import os
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

KST = timezone(timedelta(hours=9))
ROOT = Path(__file__).resolve().parent
_INSTALLED = False
_MASTER_LOCK = threading.RLock()
_MASTER_CODES: list[str] = []
_MASTER_REFRESHED = 0.0
_SCAN_STATS = {
    "hot_calls": 0,
    "master_calls": 0,
    "master_universe_count": 0,
    "master_cursor": 0,
    "scanner_errors": 0,
    "program_subscribe_attempts": 0,
    "program_reconnects": 0,
}

_FUND_PREFIXES = (
    "KODEX", "TIGER", "RISE", "ACE", "PLUS", "SOL", "KOSEF", "HANARO",
    "TIMEFOLIO", "KBSTAR", "ARIRANG", "FOCUS", "TREX", "SMART", "QV", "TRUE", "1Q",
)


def _f(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except Exception:
        return float(default)


def _fund_like(name: str) -> bool:
    s = re.sub(r"\s+", " ", str(name or "")).strip().upper()
    if not s:
        return False
    if " ETN" in f" {s}" or s.endswith("ETN") or " ETF" in f" {s}" or s.endswith("ETF"):
        return True
    return any(s.startswith(p) for p in _FUND_PREFIXES)


def _refresh_master_codes(core, force: bool = False) -> list[str]:
    global _MASTER_CODES, _MASTER_REFRESHED
    now = time.time()
    with _MASTER_LOCK:
        if _MASTER_CODES and not force and now - _MASTER_REFRESHED < 600:
            return list(_MASTER_CODES)
    try:
        core.feed._load_kr_master()
    except Exception:
        pass
    master = dict(getattr(core.feed, "kr_master_meta", {}) or {})
    rows: list[str] = []
    for code, meta in master.items():
        code = str(code or "").strip().upper()
        if len(code) != 6 or not code.isdigit():
            continue
        name = str((meta or {}).get("name") or "")
        if _fund_like(name):
            continue
        rows.append(code)
    rows = sorted(set(rows))
    with _MASTER_LOCK:
        _MASTER_CODES = rows
        _MASTER_REFRESHED = now
        _SCAN_STATS["master_universe_count"] = len(rows)
        return list(rows)


def _kr_scan_window() -> bool:
    now = datetime.now(KST)
    mins = now.hour * 60 + now.minute
    return now.weekday() < 5 and 8 * 60 <= mins < 20 * 60


def _krx_program_window() -> bool:
    now = datetime.now(KST)
    mins = now.hour * 60 + now.minute
    return now.weekday() < 5 and 9 * 60 <= mins < 15 * 60 + 30


def _install_program_guard(core) -> None:
    feed = core.feed
    if getattr(feed, "_namuh_v368_program_guard", False):
        return

    def program_loop_v368():
        delay = 5.0
        launched = False
        launched_at = 0.0
        while not feed._stop.is_set():
            if not _krx_program_window():
                launched = False
                feed.program_realtime["connected"] = False
                feed.program_realtime["error"] = "KRX 프로그램매매 장외 대기"
                feed._stop.wait(60.0)
                continue
            now = time.time()
            updated = _f(feed.program_realtime.get("updated_at"))
            fresh = bool(updated and now - updated <= 90.0)
            if launched and fresh:
                feed._stop.wait(20.0)
                continue
            if launched and now - launched_at < 120.0:
                feed._stop.wait(15.0)
                continue
            try:
                from nhplug.realtime import subscribe
                _SCAN_STATS["program_subscribe_attempts"] += 1
                if launched:
                    _SCAN_STATS["program_reconnects"] += 1
                subscribe(feed.fixed["KR"], feed._apply_program_message, tr_cd="mn", timeout=30)
                launched = True
                launched_at = time.time()
                delay = 5.0
                feed._stop.wait(15.0)
            except Exception as exc:
                launched = False
                feed.program_realtime["connected"] = False
                feed.program_realtime["error"] = str(exc)[:240]
                feed._stop.wait(delay)
                delay = min(90.0, delay * 2.0)

    feed.program_loop = program_loop_v368
    feed._namuh_v368_program_guard = True


def _install_full_kr_rotation(core) -> None:
    feed = core.feed
    if getattr(feed, "_namuh_v368_full_rotation", False):
        return
    try:
        import namuh_scalp_sector_final_0908 as final
    except Exception:
        return

    def kr_scanner_v368():
        from nhplug import call
        try:
            feed._load_kr_master()
        except Exception as exc:
            feed.errors["KR"] = f"국내 종목마스터: {exc}"[:300]
        try:
            final._refresh_discovery(core)
        except Exception:
            pass
        hot_idx = 0
        master_idx = 0
        cycle = 0
        while not feed._stop.is_set():
            try:
                final._soft_prune(core)
            except Exception:
                pass
            if not _kr_scan_window():
                feed._stop.wait(15.0)
                continue
            pool = final._scanner_pool(core)
            master = _refresh_master_codes(core)
            use_master = bool(master) and cycle % 4 == 3
            cycle += 1
            if use_master:
                code = master[master_idx % len(master)]
                master_idx += 1
                _SCAN_STATS["master_calls"] += 1
                _SCAN_STATS["master_cursor"] = master_idx % max(1, len(master))
            elif pool:
                code = pool[hot_idx % len(pool)]
                hot_idx += 1
                _SCAN_STATS["hot_calls"] += 1
            elif master:
                code = master[master_idx % len(master)]
                master_idx += 1
                _SCAN_STATS["master_calls"] += 1
                _SCAN_STATS["master_cursor"] = master_idx % max(1, len(master))
            else:
                feed._stop.wait(2.0)
                continue
            success = False
            last = ""
            for market_cd in feed._market_order():
                try:
                    data = call("/krstock/quote/v1/currentPrice", {"iem_cd": code, "market_cd": market_cd})
                    try:
                        final._STATS["scanner_calls"] += 1
                    except Exception:
                        pass
                    if final._queue_activate(core, code, data):
                        success = True
                    break
                except Exception as exc:
                    last = str(exc)[:220]
                    if "429" in last:
                        break
            if not success:
                _SCAN_STATS["scanner_errors"] += 1
                try:
                    final._STATS["scanner_fail"] += 1
                except Exception:
                    pass
                if last:
                    feed.errors["KR"] = f"{code}: {last}"[:300]
            else:
                feed.connected["KR"] = True
                feed.errors["KR"] = ""
            feed._stop.wait(0.70 if success else (3.0 if "429" in last else 1.2))

    feed.kr_scanner = kr_scanner_v368
    feed._namuh_v368_full_rotation = True
    _refresh_master_codes(core, force=True)


def _install_health(core) -> None:
    try:
        old = core.health_payload
    except Exception:
        return
    if getattr(old, "_namuh_v368", False):
        return

    def health():
        d = dict(old())
        try:
            store = core.store.status()
        except Exception:
            store = {}
        d["v368"] = {
            "active": True,
            "layout_unchanged": True,
            "display_top_n": 5,
            "kr_full_master_rotation": True,
            "kr_scan_mix": "3 hot : 1 full-master",
            "program_ws_guard": True,
            "store": store,
            "scan": dict(_SCAN_STATS),
        }
        return d

    health._namuh_v368 = True
    health._old = old
    core.health_payload = health


def _inject_js(asset: str) -> None:
    ver = (os.getenv("RENDER_GIT_COMMIT") or os.getenv("GY_BUILD_ID") or str(int(time.time())))[:12]
    for rel in ("static/index.html", "static/coin.html"):
        p = ROOT / rel
        try:
            text = p.read_text(encoding="utf-8")
            text = re.sub(rf'\s*<script\s+src=["\']/static/{re.escape(asset)}(?:\?[^"\']*)?["\']\s*></script>\s*', "\n", text, flags=re.I)
            tag = f'  <script src="/static/{asset}?v={ver}"></script>'
            text = text.replace("</body>", f"{tag}\n</body>")
            p.write_text(text, encoding="utf-8")
        except Exception:
            pass


def apply(ns=None):
    global _INSTALLED
    if _INSTALLED:
        return True
    core = ns.get("core") if isinstance(ns, dict) else None
    if core is None:
        return False
    _INSTALLED = True
    _install_program_guard(core)
    _install_full_kr_rotation(core)
    _install_health(core)
    _inject_js("v368_top5_runtime.js")
    try:
        @core.app.get("/api/v368/runtime")
        def v368_runtime():
            try:
                store = core.store.status()
            except Exception:
                store = {}
            out = {
                "ok": True,
                "version": "v368",
                "layout_unchanged": True,
                "display_top_n": 5,
                "kr_full_master_rotation": True,
                "store": store,
                "scan": dict(_SCAN_STATS),
                "program_realtime": dict(getattr(core.feed, "program_realtime", {}) or {}),
                "markets": {},
            }
            try:
                with core.cache_lock:
                    for m in ("KR", "US"):
                        c = dict(core.CACHE.get(m) or {})
                        rows = sorted(list(c.get("scalp") or []), key=lambda x: (_f(x.get("score")), _f(x.get("priority_score"))), reverse=True)
                        out["markets"][m] = {
                            "scored_count": len(rows),
                            "display_top5": [{"code": x.get("code"), "name": x.get("name"), "score": x.get("score")} for x in rows[:5]],
                            "leading_sector": (list(c.get("sectors") or []) or [None])[0],
                            "updated_at": _f(c.get("updated_at")),
                        }
            except Exception as exc:
                out["cache_error"] = str(exc)[:200]
            try:
                coins = sorted(list(core.coin_feed.candidates(80) or []), key=lambda x: _f(x.get("score")), reverse=True)
                out["markets"]["COIN"] = {
                    "scored_count": len(coins),
                    "display_top5": [{"code": x.get("code"), "name": x.get("name"), "score": x.get("score")} for x in coins[:5]],
                }
            except Exception as exc:
                out["markets"]["COIN"] = {"error": str(exc)[:160]}
            return out
    except Exception:
        pass
    print("NAMUH V368 FINAL active: UI unchanged + TOP5 display contract + full KR rolling scan + guarded program websocket", flush=True)
    return True
