from __future__ import annotations

import inspect
import os
import re
import threading
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
_INSTALLED = False
_HEALTH_LOCK = threading.RLock()
_HEALTH_CACHE = {"ts": 0.0, "data": None}
_STATS = {
    "sector_base_unwrap": "",
    "sector_quotes": 0,
    "health_cache_hit": 0,
    "health_cache_miss": 0,
    "kr_rebuilds": 0,
    "us_rebuilds": 0,
    "inactive_rebuilds_skipped": 0,
    "route_cache_hits": 0,
    "route_cache_misses": 0,
}


def _f(v, default=0.0):
    try:
        return float(v)
    except Exception:
        return float(default)


def _digits(v):
    return "".join(ch for ch in str(v or "") if ch.isdigit())[:8]


def _find_closure_old(fn):
    try:
        for cell in list(fn.__closure__ or []):
            try:
                obj = cell.cell_contents
            except Exception:
                continue
            if callable(obj) and obj is not fn and getattr(obj, "__name__", "") == "build_sector_context":
                return obj
    except Exception:
        pass
    return None


def _sector_base(core):
    fn = core.build_sector_context
    chain = []
    seen = set()
    while callable(fn) and id(fn) not in seen:
        seen.add(id(fn))
        chain.append(getattr(fn, "__name__", "build_sector_context"))
        if getattr(fn, "_namuh_v371_today_only", False) or getattr(fn, "_namuh_v370_institution", False):
            old = getattr(fn, "_old", None)
            if callable(old):
                fn = old
                continue
        if getattr(fn, "_namuh_sector_flow_completed5", False):
            old = getattr(fn, "_old", None) or _find_closure_old(fn)
            if callable(old):
                fn = old
                continue
        break
    _STATS["sector_base_unwrap"] = " > ".join(chain[-6:])
    return fn


def _today_row(q, today):
    try:
        rows = list(getattr(q, "investor_daily", []) or [])
    except Exception:
        rows = []
    for r in reversed(rows):
        if isinstance(r, dict) and _digits(r.get("date")) == today:
            return r
    return None


def _install_fast_today_sector(core):
    base = _sector_base(core)
    if not callable(base):
        return

    def build_sector_context(market):
        sectors, secmap, stock_strength = base(market)
        if str(market).upper() != "KR" or not sectors:
            return sectors, secmap, stock_strength

        today = datetime.now(core.KST).strftime("%Y%m%d")
        grouped = {}
        qvals = list(core.feed.quotes_for("KR").values())
        _STATS["sector_quotes"] = len(qvals)
        for q in qvals:
            try:
                price = _f(getattr(q, "price", 0))
                if price <= 0:
                    continue
                sec = str(core.sector_name(q, "KR"))
                r = _today_row(q, today)
                asof_today = _digits(getattr(q, "investor_asof", "")) == today
                if r is not None:
                    foreign = _f(r.get("foreign"))
                    institution = _f(r.get("institution"))
                    person = _f(r.get("person"))
                    program = _f(r.get("program"))
                    source = "today_row"
                elif asof_today:
                    foreign = _f(getattr(q, "foreign_net", 0))
                    institution = _f(getattr(q, "institution_net", 0))
                    person = _f(getattr(q, "person_net", 0))
                    program = _f(getattr(q, "program_net", 0))
                    source = "today_current"
                else:
                    foreign = institution = person = program = 0.0
                    source = "today_waiting"
                g = grouped.setdefault(sec, {
                    "foreign": 0.0, "institution": 0.0, "program": 0.0, "person": 0.0,
                    "foreign_value": 0.0, "institution_value": 0.0,
                    "program_value": 0.0, "person_exit_value": 0.0,
                    "today_members": 0, "waiting_members": 0,
                })
                g["foreign"] += foreign
                g["institution"] += institution
                g["program"] += program
                g["person"] += person
                g["foreign_value"] += price * max(0.0, foreign)
                g["institution_value"] += price * max(0.0, institution)
                g["program_value"] += price * max(0.0, program)
                g["person_exit_value"] += price * max(0.0, -person)
                if source == "today_waiting":
                    g["waiting_members"] += 1
                else:
                    g["today_members"] += 1
            except Exception:
                continue

        for x in sectors:
            g = grouped.get(str(x.get("sector") or ""), {})
            x["foreign_net"] = _f(g.get("foreign"))
            x["institution_net"] = _f(g.get("institution"))
            x["program_net"] = _f(g.get("program"))
            x["person_net"] = _f(g.get("person"))
            x["flow_value"] = {
                "foreign": _f(g.get("foreign_value")),
                "institution": _f(g.get("institution_value")),
                "program": _f(g.get("program_value")),
                "person_exit": _f(g.get("person_exit_value")),
            }
            x["flow_source"] = {
                "foreign": "today_only", "institution": "today_only",
                "program": "today_only", "person_exit": "today_only",
                "historical_fallback": False,
                "today_members": int(g.get("today_members") or 0),
                "waiting_members": int(g.get("waiting_members") or 0),
            }

        keys = ("foreign", "institution", "program", "person_exit")
        totals = {k: sum(max(0.0, _f((x.get("flow_value") or {}).get(k))) for x in sectors) for k in keys}
        comp_total = 0.0
        for x in sectors:
            fv = x.get("flow_value") or {}
            sh = {k: (_f(fv.get(k)) / totals[k] * 100.0 if totals[k] > 0 else 0.0) for k in keys}
            raw = sh["foreign"] * 0.35 + sh["institution"] * 0.35 + sh["program"] * 0.20 + sh["person_exit"] * 0.10
            x["flow_share"] = {**{k: round(v, 1) for k, v in sh.items()}, "_raw": raw}
            comp_total += raw
        for x in sectors:
            sh = x.get("flow_share") or {}
            raw = _f(sh.pop("_raw", 0))
            sh["composite"] = round(raw / comp_total * 100.0, 1) if comp_total > 0 else 0.0
            x["flow_share"] = sh
        sectors.sort(key=lambda x: (_f((x.get("flow_share") or {}).get("composite")), _f(x.get("score"))), reverse=True)
        core._NAMUH_V372_SECTOR = {"today": today, "totals": {k: round(v, 2) for k, v in totals.items()}}
        return sectors, {str(x.get("sector") or ""): _f(x.get("score")) for x in sectors}, stock_strength

    build_sector_context._namuh_v372_fast_today = True
    build_sector_context._old = base
    core.build_sector_context = build_sector_context


def _install_cached_health(core):
    old = core.health_payload
    if getattr(old, "_namuh_v372_cached", False):
        return

    def health_payload():
        now = time.monotonic()
        data = _HEALTH_CACHE.get("data")
        if data is not None and now - _f(_HEALTH_CACHE.get("ts")) < 2.0:
            _STATS["health_cache_hit"] += 1
            return dict(data)
        with _HEALTH_LOCK:
            now = time.monotonic()
            data = _HEALTH_CACHE.get("data")
            if data is not None and now - _f(_HEALTH_CACHE.get("ts")) < 2.0:
                _STATS["health_cache_hit"] += 1
                return dict(data)
            out = dict(old())
            _HEALTH_CACHE["data"] = out
            _HEALTH_CACHE["ts"] = now
            _STATS["health_cache_miss"] += 1
            return dict(out)

    health_payload._namuh_v372_cached = True
    health_payload._old = old
    core.health_payload = health_payload

    try:
        static_macro = list(core.macro_calendar_payload() or [])
        core.macro_calendar_payload = lambda: static_macro
    except Exception:
        pass


def _latest_lists(core, market):
    try:
        with core.cache_lock:
            c = core.CACHE.get(market) or {}
            return list(c.get("scalp") or []), list(c.get("smart") or [])
    except Exception:
        return [], []


def _install_staggered_ai_loop(core):
    def ai_loop_v372():
        core.LOOP_STATE["started_at"] = time.time()
        last_build = {"KR": 0.0, "US": 0.0}
        last_trade = 0.0
        last_persist = 0.0
        latest = {"KR": ([], []), "US": ([], [])}
        while True:
            core.LOOP_STATE["last_tick"] = time.time()
            core.LOOP_STATE["iterations"] += 1
            try:
                now_dt = datetime.now(core.KST)
                active = core.trading_window(now_dt)
                mono = time.monotonic()
                for market in ("KR", "US"):
                    interval = 4.0 if active == market else (18.0 if active else 12.0)
                    if mono - last_build[market] < interval:
                        if active and market != active:
                            _STATS["inactive_rebuilds_skipped"] += 1
                        continue
                    latest[market] = core.rebuild_cache(market, now_dt)
                    last_build[market] = mono
                    _STATS["kr_rebuilds" if market == "KR" else "us_rebuilds"] += 1

                if core.AUTO_TRADING_ENABLED and active in ("KR", "US") and mono - last_trade >= 3.5:
                    scalp, smart = latest.get(active) or ([], [])
                    if not scalp:
                        scalp, smart = _latest_lists(core, active)
                    if active == "KR":
                        core.mark_and_sell("KR", scalp, smart, now_dt)
                        core.trade_scalp("KR", scalp, now_dt)
                        core.trade_smart_kr(smart, now_dt)
                    else:
                        core.mark_and_sell("US", scalp, [], now_dt)
                        core.trade_scalp("US", scalp, now_dt)
                    last_trade = mono

                if time.time() - last_persist >= 60.0:
                    core._persist_paper()
                    last_persist = time.time()
                core.LOOP_STATE["last_ok"] = time.time()
                core.LOOP_STATE["last_error"] = ""
            except Exception as exc:
                core.LOOP_STATE["last_error"] = str(exc)[:300]
                print("AI LOOP V372 ERROR:", str(exc)[:220], flush=True)
            time.sleep(0.75)

    core.ai_loop = ai_loop_v372


def _route_cache(app, path, ttl):
    try:
        route = next((r for r in app.routes if getattr(r, "path", None) == path and hasattr(r, "dependant")), None)
        if route is None or getattr(route, "_namuh_v372_cached", False):
            return
        old = route.dependant.call
        lock = threading.RLock()
        cache = {}

        def key_for(kwargs):
            return tuple(sorted((str(k), repr(v)) for k, v in kwargs.items()))

        if inspect.iscoroutinefunction(old):
            async def wrapped(**kwargs):
                key = key_for(kwargs); now = time.monotonic()
                with lock:
                    item = cache.get(key)
                    if item and now - item[0] < ttl:
                        _STATS["route_cache_hits"] += 1
                        return item[1]
                out = await old(**kwargs)
                with lock:
                    cache[key] = (time.monotonic(), out)
                _STATS["route_cache_misses"] += 1
                return out
        else:
            def wrapped(**kwargs):
                key = key_for(kwargs); now = time.monotonic()
                with lock:
                    item = cache.get(key)
                    if item and now - item[0] < ttl:
                        _STATS["route_cache_hits"] += 1
                        return item[1]
                out = old(**kwargs)
                with lock:
                    cache[key] = (time.monotonic(), out)
                _STATS["route_cache_misses"] += 1
                return out
        route.dependant.call = wrapped
        route.endpoint = wrapped
        route._namuh_v372_cached = True
    except Exception as exc:
        print("V372 route cache skip", path, str(exc)[:120], flush=True)


def _trim_state_routes(core):
    try:
        route = next((r for r in core.app.routes if getattr(r, "path", None) == "/api/state" and hasattr(r, "dependant")), None)
        if route is not None and not getattr(route, "_namuh_v372_trim", False):
            old = route.dependant.call
            def state_fast(**kwargs):
                out = old(**kwargs)
                if isinstance(out, dict) and str(out.get("mode")) in ("KR", "US"):
                    rows = list(out.get("scalp") or [])
                    rows.sort(key=lambda x: _f(x.get("score")), reverse=True)
                    out["scalp"] = rows[:5]
                elif isinstance(out, dict) and str(out.get("mode")) == "COIN":
                    rows = list(out.get("scalp") or [])
                    rows.sort(key=lambda x: _f(x.get("score")), reverse=True)
                    out["scalp"] = rows[:5]
                return out
            route.dependant.call = state_fast
            route.endpoint = state_fast
            route._namuh_v372_trim = True
    except Exception as exc:
        print("V372 state trim skip", str(exc)[:140], flush=True)

    try:
        route = next((r for r in core.app.routes if getattr(r, "path", None) == "/api/coin/state" and hasattr(r, "dependant")), None)
        if route is not None and not getattr(route, "_namuh_v372_trim", False):
            old = route.dependant.call
            def coin_state_fast(**kwargs):
                out = old(**kwargs)
                if isinstance(out, dict):
                    rows = list(out.get("candidates") or [])
                    rows.sort(key=lambda x: _f(x.get("score")), reverse=True)
                    out["candidates"] = rows[:5]
                return out
            route.dependant.call = coin_state_fast
            route.endpoint = coin_state_fast
            route._namuh_v372_trim = True
    except Exception:
        pass


def _patch_text(path, fn):
    p = ROOT / path
    if not p.exists():
        return
    try:
        text = p.read_text(encoding="utf-8")
        new = fn(text)
        if new != text:
            p.write_text(new, encoding="utf-8")
    except Exception:
        pass


def _patch_frontend(build):
    def app_js(text):
        text = text.replace("async function refresh(force=false){if(refreshing&&!force)return;", "async function refresh(force=false){if(document.hidden&&!force)return;if(refreshing&&!force)return;")
        text = re.sub(r"setInterval\(refresh,\s*(?:1000|3000|4000|5000|10000)\)", "setInterval(refresh,5000)", text)
        return text
    _patch_text("static/app.js", app_js)

    def coin_js(text):
        text = text.replace("async function refresh(force=false){", "async function refresh(force=false){if(document.hidden&&!force)return;")
        text = re.sub(r"setInterval\(refresh,\s*(?:1000|3000|4000|5000|10000)\)", "setInterval(refresh,5000)", text)
        return text
    _patch_text("static/coin.js", coin_js)

    def v34_js(text):
        text = re.sub(r"setInterval\(loadAuto,\s*12000\)", "setInterval(loadAuto,20000)", text)
        text = re.sub(r"setInterval\(loadDisclosureAlerts,\s*7000\)", "setInterval(loadDisclosureAlerts,15000)", text)
        text = re.sub(r"setInterval\(loadFlowAlerts,\s*4000\)", "setInterval(loadFlowAlerts,8000)", text)
        return text
    _patch_text("static/v34.js", v34_js)

    def v370_js(text):
        text = text.replace("function tick(){if(busy)return;", "function tick(){if(document.hidden||busy)return;")
        text = re.sub(r"setInterval\(tick,\s*1200\)", "setInterval(tick,5000)", text)
        return text
    _patch_text("static/v370_userfix.js", v370_js)

    guard = f"""<script id=\"gyBuildGuard\">(()=>{{const b='{build}';try{{const k='GY_BUILD_ACTIVE';if(localStorage.getItem(k)!==b){{for(let i=localStorage.length-1;i>=0;i--){{const x=localStorage.key(i)||'';if(x.startsWith('GY_FAST_STATE_V1_')||x.startsWith('GY_FAST_STOCK_V1_')||x.startsWith('GY_AI_TIME_V364_'))localStorage.removeItem(x)}}localStorage.setItem(k,b);if('serviceWorker'in navigator)navigator.serviceWorker.getRegistrations().then(a=>a.forEach(r=>r.unregister())).catch(()=>{{}});if(window.caches)caches.keys().then(a=>a.forEach(x=>caches.delete(x))).catch(()=>{{}})}}}}catch(_){{}}}})();</script>"""
    for rel in ("static/index.html", "static/coin.html", "static/stock.html", "static/index-detail.html", "static/coin-detail.html"):
        p = ROOT / rel
        if not p.exists():
            continue
        try:
            text = p.read_text(encoding="utf-8")
            text = re.sub(r"<script id=[\"']gyBuildGuard[\"']>.*?</script>", "", text, flags=re.S)
            text = re.sub(r"([\"']/static/[^\"'?]+\.(?:js|css))\?v=[^\"']*", lambda m: f"{m.group(1)}?v={build}", text)
            text = text.replace("</head>", guard + "\n</head>")
            p.write_text(text, encoding="utf-8")
        except Exception:
            pass


def _install_health_marker(core):
    old = core.health_payload
    if getattr(old, "_namuh_v372_marker", False):
        return
    def health():
        d = dict(old())
        d["v372"] = {
            "active": True,
            "speed_only": True,
            "layout_unchanged": True,
            "normal_browser_cache_guard": True,
            "state_top5_payload": True,
            "static_build_version": True,
            "health_ttl_sec": 2,
            "active_market_rebuild_sec": 4,
            "inactive_market_rebuild_sec": 18,
            "state_poll_sec": 5,
            "sector_window": "today only; no historical fallback",
            "stats": dict(_STATS),
            "sector": getattr(core, "_NAMUH_V372_SECTOR", {}),
        }
        return d
    health._namuh_v372_marker = True
    health._old = old
    core.health_payload = health


def apply(ns=None):
    global _INSTALLED
    if _INSTALLED:
        return True
    core = ns.get("core") if isinstance(ns, dict) else None
    if core is None:
        return False
    _INSTALLED = True

    _install_fast_today_sector(core)
    _install_cached_health(core)
    _install_staggered_ai_loop(core)
    _trim_state_routes(core)
    for path, ttl in (("/api/v352/universe", 3.0), ("/api/v364/ai-time", 5.0), ("/api/v34/flow-alerts", 4.0), ("/api/v34/disclosure-alerts", 5.0), ("/api/health", 2.0)):
        _route_cache(core.app, path, ttl)
    build = (os.getenv("RENDER_GIT_COMMIT") or os.getenv("GY_BUILD_ID") or str(int(time.time())))[:12]
    _patch_frontend(build)
    _install_health_marker(core)
    print("NAMUH V372 SPEED active: low-CPU stagger + cached health + lean TOP5 state + today-sector fast path + normal-browser cache guard", flush=True)
    return True
