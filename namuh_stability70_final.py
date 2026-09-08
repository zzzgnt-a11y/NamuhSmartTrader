from __future__ import annotations

import re
import threading
import time
from collections import OrderedDict
from pathlib import Path

_INSTALLED = False
ROOT = Path(__file__).resolve().parent
C1_THRESHOLD = 70.0

_STATS = {
    "investor_ok": 0,
    "investor_fail": 0,
    "investor_queue": 0,
    "investor_last_error": "",
    "investor_last_code": "",
    "scanner_hot": 0,
    "scanner_promoted": 0,
    "scanner_discovery_checked": 0,
    "scanner_discovery_promoted": 0,
    "scanner_last_error": "",
    "sticky_scalp_uses": 0,
    "sticky_sector_uses": 0,
}
_PROMOTED = OrderedDict()
_PROMOTED_LOCK = threading.RLock()
_LAST_GOOD = {"KR": {"scalp": [], "sectors": [], "ts": 0.0}, "US": {"scalp": [], "sectors": [], "ts": 0.0}}


def _f(v, default=0.0):
    try:
        return float(v)
    except Exception:
        return float(default)


def _dedupe_rows(rows):
    out = []
    seen = set()
    for x in list(rows or []):
        if not isinstance(x, dict):
            continue
        code = str(x.get("code") or "").upper().strip()
        key = code or (str(x.get("name") or ""), str(x.get("price") or ""))
        if key in seen:
            continue
        seen.add(key)
        out.append(x)
    return out


def _hard_gate(c1):
    g = dict(c1.get("gates") or {})
    return bool(g.get("daily") and g.get("minute1m") and g.get("execution") and g.get("orderbook"))


def _install_threshold70(core):
    old = core.candidate
    if getattr(old, "_namuh_threshold70_final", False):
        return

    def candidate(*args, **kwargs):
        out = old(*args, **kwargs)
        if not isinstance(out, dict):
            return out
        try:
            market = str(args[1] if len(args) > 1 else kwargs.get("market", "")).upper()
            smart = bool(args[2] if len(args) > 2 else kwargs.get("smart", False))
            if smart or market not in ("KR", "US"):
                return out
            c1 = dict(out.get("condition1") or {})
            if not c1:
                return out
            gates = dict(c1.get("gates") or {})
            total = _f(c1.get("score"), _f(out.get("score")))
            blocked = bool(gates.get("event_block", False))
            gate = bool(not blocked and _hard_gate(c1) and total >= C1_THRESHOLD)
            gates["total70"] = total >= C1_THRESHOLD
            gates["total_threshold"] = total >= C1_THRESHOLD
            gates.pop("total75", None)
            c1.update({
                "entry_threshold": C1_THRESHOLD,
                "gate": gate,
                "gates": gates,
                "threshold_owner": "condition1 final 70",
            })
            out["condition1"] = c1
            out["condition1_gate_pass"] = gate
            labels = [x for x in list(out.get("condition_labels") or []) if str(x) != "조건1"]
            if gate:
                labels.insert(0, "조건1")
            out["condition_labels"] = list(dict.fromkeys(labels))
            out["condition_display"] = (
                "복합조건" if len([x for x in out["condition_labels"] if str(x).startswith("조건")]) > 1
                else (out["condition_labels"][0] if out["condition_labels"] else "")
            )
        except Exception as exc:
            out["threshold70_final_error"] = str(exc)[:180]
        return out

    candidate._namuh_threshold70_final = True
    core.candidate = candidate


def _iter_dicts(v):
    if isinstance(v, dict):
        yield v
        for x in v.values():
            yield from _iter_dicts(x)
    elif isinstance(v, (list, tuple)):
        for x in v:
            yield from _iter_dicts(x)


def _install_investor_field_tracking(core):
    feed = core.feed
    old = getattr(feed, "_apply_investor", None)
    if not callable(old) or getattr(old, "_namuh_field_tracking", False):
        return

    def apply_investor(code, data):
        result = old(code, data)
        try:
            flags = {"foreign": False, "institution": False, "person": False, "program": False}
            for o in _iter_dicts(data):
                if not isinstance(o, dict):
                    continue
                if any(k in o and o.get(k) not in (None, "") for k in ("frgn_ntby_qty", "invest")):
                    flags["foreign"] = True
                if any(k in o and o.get(k) not in (None, "") for k in ("orgn_ntby_qty", "gigwan")):
                    flags["institution"] = True
                if any(k in o and o.get(k) not in (None, "") for k in ("prsn_ntby_qty", "person")):
                    flags["person"] = True
                if any(k in o and o.get(k) not in (None, "") for k in ("prgm_ntby_qty", "pgtr_ntby_qty", "program")):
                    flags["program"] = True
            q = feed.q("KR", code)
            prev = dict(getattr(q, "investor_field_ready", {}) or {})
            q.investor_field_ready = {k: bool(prev.get(k) or flags[k]) for k in flags}
            q.investor_field_updated_at = time.time()
        except Exception:
            pass
        return result

    apply_investor._namuh_field_tracking = True
    apply_investor._old = old
    feed._apply_investor = apply_investor


def _priority_investor_codes(core):
    feed = core.feed
    out = []
    try:
        sectors = list((core.CACHE.get("KR") or {}).get("sectors") or [])[:5]
    except Exception:
        sectors = []
    qmap = feed.quotes_for("KR")
    # Leading-sector members first. Only live members are useful for current sector flow,
    # so do not walk the whole 3,919-name catalog here.
    for s in sectors:
        leader = str(s.get("leader_code") or "").strip()
        if leader:
            out.append(leader)
        sec = str(s.get("sector") or "").strip()
        if sec:
            for code, q in list(qmap.items()):
                try:
                    if _f(getattr(q, "price", 0)) > 0 and str(core.sector_name(q, "KR")) == sec:
                        out.append(str(code))
                except Exception:
                    pass
    try:
        for x in list((core.CACHE.get("KR") or {}).get("scalp") or [])[:30]:
            c = str(x.get("code") or "").strip()
            if c:
                out.append(c)
    except Exception:
        pass
    try:
        out.extend([str(x) for x in list(feed.fixed.get("KR", []) or []) if str(x)])
    except Exception:
        pass
    try:
        for p in list(core.paper.positions.values()):
            if str(getattr(p, "market", "")).upper() == "KR":
                out.append(str(getattr(p, "code", "")))
    except Exception:
        pass
    with _PROMOTED_LOCK:
        out.extend(list(_PROMOTED.keys()))
    clean = []
    seen = set()
    for c in out:
        c = str(c or "").upper().strip()
        if len(c) == 6 and c.isdigit() and c not in seen:
            seen.add(c)
            clean.append(c)
    # Bounded hot queue prevents a 3,919-name investor loop while keeping the
    # names that actually contribute to leading-sector/scalp calculations fresh.
    return clean[:80]


def _install_bounded_investor_loop(core):
    feed = core.feed

    def investor_loop():
        from nhplug import call
        idx = 0
        while not feed._stop.is_set():
            codes = _priority_investor_codes(core)
            _STATS["investor_queue"] = len(codes)
            if not codes:
                feed._stop.wait(1.0)
                continue
            code = codes[idx % len(codes)]
            idx += 1
            ok = False
            last = ""
            for market_cd in feed._market_order():
                try:
                    data = call("/krstock/quote/v1/currentInvestor", {
                        "market_cd": market_cd, "iem_cd": code, "array_cnt": "14"
                    })
                    feed._apply_investor(code, data)
                    feed.investor_updated_at = time.time()
                    _STATS["investor_ok"] += 1
                    _STATS["investor_last_code"] = code
                    _STATS["investor_last_error"] = ""
                    ok = True
                    break
                except Exception as exc:
                    last = str(exc)[:180]
                    if "429" in last:
                        break
            if not ok:
                _STATS["investor_fail"] += 1
                _STATS["investor_last_error"] = last
            # Adaptive backoff: currentInvestor is enrichment, never worth taking
            # down quote/scoring transport. Keep it deliberately gentler.
            wait = 1.25 if ok else (5.0 if "429" in last else 3.0)
            feed._stop.wait(wait)

    feed.investor_loop = investor_loop


def _cleanup_promoted(now):
    with _PROMOTED_LOCK:
        dead = [c for c, x in _PROMOTED.items() if _f(x.get("until")) < now]
        for c in dead:
            _PROMOTED.pop(c, None)
        while len(_PROMOTED) > 20:
            _PROMOTED.popitem(last=False)


def _promote(code, strength, change_pct):
    now = time.time()
    with _PROMOTED_LOCK:
        _PROMOTED.pop(code, None)
        _PROMOTED[code] = {
            "until": now + 900.0,
            "strength": round(_f(strength), 1),
            "change_pct": round(_f(change_pct), 2),
        }
        while len(_PROMOTED) > 20:
            _PROMOTED.popitem(last=False)
    _STATS["scanner_discovery_promoted"] += 1


def _scanner_hot_codes(core):
    feed = core.feed
    out = []
    try:
        out.extend(list(feed.fixed.get("KR", []) or []))
    except Exception:
        pass
    try:
        out.extend(str(x.get("code") or "") for x in list((core.CACHE.get("KR") or {}).get("scalp") or [])[:25])
        out.extend(str(x.get("leader_code") or "") for x in list((core.CACHE.get("KR") or {}).get("sectors") or [])[:5])
    except Exception:
        pass
    try:
        out.extend(str(getattr(p, "code", "")) for p in list(core.paper.positions.values()) if str(getattr(p, "market", "")).upper() == "KR")
    except Exception:
        pass
    with _PROMOTED_LOCK:
        out.extend(list(_PROMOTED.keys()))
    clean = []
    seen = set()
    for c in out:
        c = str(c or "").upper().strip()
        if len(c) == 6 and c.isdigit() and c not in seen:
            seen.add(c)
            clean.append(c)
    return clean[:45]


def _install_adaptive_kr_scanner(core):
    feed = core.feed

    def kr_scanner():
        from nhplug import call
        from nhfeed import pick
        try:
            feed._load_kr_master()
        except Exception as exc:
            feed.errors["KR"] = f"국내 종목마스터: {exc}"[:300]
        master = [str(x) for x in list((getattr(feed, "kr_master_meta", {}) or {}).keys()) if str(x)]
        if not master:
            master = [str(x) for x in list(feed.fixed.get("KR", []) or []) if str(x)]
        hot_idx = 0
        disc_idx = 0
        turn = 0
        while not feed._stop.is_set():
            now = time.time()
            _cleanup_promoted(now)
            hot = _scanner_hot_codes(core)
            _STATS["scanner_hot"] = len(hot)
            _STATS["scanner_promoted"] = len(_PROMOTED)
            # Two hot refreshes for each discovery request. This preserves ~25s
            # freshness for the actual trading set while continuously checking
            # the full KR master without putting all 3,919 names into CACHE.
            discovery = bool(master and turn % 3 == 2)
            turn += 1
            if discovery:
                code = master[disc_idx % len(master)]
                disc_idx += 1
            else:
                if not hot:
                    feed._stop.wait(.5)
                    continue
                code = hot[hot_idx % len(hot)]
                hot_idx += 1
            last = ""
            success = False
            for market_cd in feed._market_order():
                try:
                    data = call("/krstock/quote/v1/currentPrice", {"iem_cd": code, "market_cd": market_cd})
                    if discovery and code not in hot:
                        # Lightweight discovery first; only promote a moving/strong
                        # stock into the heavy scoring universe. This fixes the
                        # old fixed-name bias without making every master symbol a
                        # 5-second scoring/API workload.
                        px = pick(data, ("stck_prpr", "prpr", "price", "cur_pr", "now_pr"))
                        op = pick(data, ("stck_oprc", "open"))
                        st = pick(data, ("cttr", "volpower", "execution_strength"))
                        ch = ((px / op) - 1.0) * 100.0 if px > 0 and op > 0 else 0.0
                        _STATS["scanner_discovery_checked"] += 1
                        if px > 0 and op > 0 and (abs(ch) >= 0.8 or st >= 100.0):
                            feed._apply_kr(code, data)
                            _promote(code, st, ch)
                    else:
                        feed._apply_kr(code, data)
                    q = feed.quotes_for("KR").get(code)
                    if q is not None and _f(getattr(q, "price", 0)) > 0:
                        feed.connected["KR"] = True
                        feed.errors["KR"] = ""
                    success = True
                    break
                except Exception as exc:
                    last = str(exc)[:220]
                    if "429" in last:
                        break
            if not success:
                _STATS["scanner_last_error"] = last
                if last:
                    feed.errors["KR"] = f"{code}: {last}"[:300]
            else:
                _STATS["scanner_last_error"] = ""
            # Keep total quote pressure below the previous .35s loop.
            feed._stop.wait(.55 if success else (3.0 if "429" in last else 1.2))

    feed.kr_scanner = kr_scanner


def _install_sticky_cache(core):
    old = core.rebuild_cache
    if getattr(old, "_namuh_sticky_stability", False):
        return

    def rebuild_cache(market, now=None):
        scalp, smart = old(market, now)
        m = str(market or "").upper()
        if m not in ("KR", "US"):
            return scalp, smart
        t = time.time()
        clean = _dedupe_rows(scalp)
        try:
            with core.cache_lock:
                cache = core.CACHE[m]
                sectors = list(cache.get("sectors") or [])
                if clean:
                    cache["scalp"] = clean[:50]
                    _LAST_GOOD[m]["scalp"] = [dict(x) for x in clean[:50]]
                    _LAST_GOOD[m]["ts"] = t
                elif _LAST_GOOD[m]["scalp"] and t - _LAST_GOOD[m]["ts"] <= 120:
                    # UI/cache only. Returned candidates remain the real current
                    # empty result, so stale data can never trigger a new buy.
                    cache["scalp"] = [dict(x) for x in _LAST_GOOD[m]["scalp"]]
                    cache["stale_scalp"] = True
                    _STATS["sticky_scalp_uses"] += 1
                if sectors:
                    _LAST_GOOD[m]["sectors"] = [dict(x) for x in sectors]
                    _LAST_GOOD[m]["ts"] = t
                elif _LAST_GOOD[m]["sectors"] and t - _LAST_GOOD[m]["ts"] <= 120:
                    cache["sectors"] = [dict(x) for x in _LAST_GOOD[m]["sectors"]]
                    cache["stale_sectors"] = True
                    _STATS["sticky_sector_uses"] += 1
        except Exception:
            pass
        return clean, smart

    rebuild_cache._namuh_sticky_stability = True
    core.rebuild_cache = rebuild_cache


def _patch_route_entry_score(core):
    try:
        for route in list(core.app.routes):
            if getattr(route, "path", "") != "/api/v352/universe":
                continue
            old = route.endpoint
            if getattr(old, "_namuh_entry70", False):
                continue
            def endpoint(*args, __old=old, **kwargs):
                d = __old(*args, **kwargs)
                if isinstance(d, dict):
                    d["entry_score"] = 70
                    d["entry_threshold"] = 70
                return d
            endpoint._namuh_entry70 = True
            route.endpoint = endpoint
    except Exception:
        pass


def _patch_ai_threshold70(core):
    try:
        import namuh_final_runtime_0908 as rt
        def record_ai(c, market):
            rows = list((c.CACHE.get(market) or {}).get("scalp") or [])
            if not rows:
                return
            now = rt._market_now(c, market)
            mins = now.hour * 60 + now.minute
            active = (now.weekday() < 5 and 9 * 60 <= mins <= 15 * 60 + 30) if market == "KR" else (now.weekday() < 5 and 9 * 60 + 30 <= mins <= 16 * 60)
            if not active:
                return
            bucket = f"{now.hour:02d}:{(now.minute // 10) * 10:02d}"
            ranked = sorted(rows, key=lambda x: rt._f(x.get("score")), reverse=True)
            top = ranked[:10]
            item = {
                "time": bucket,
                "score": round(rt._f(ranked[0].get("score")), 1),
                "name": str(ranked[0].get("name") or ranked[0].get("code") or ""),
                "avg": round(sum(rt._f(x.get("score")) for x in top) / max(1, len(top)), 1),
                "ready": sum(1 for x in ranked if rt._f(x.get("score")) >= 70.0),
                "count": len(ranked),
                "threshold": 70,
                "ts": time.time(),
            }
            with rt._AI_LOCK:
                h = [x for x in rt._AI_HISTORY.get(market, []) if x.get("time") != bucket]
                h.append(item)
                rt._AI_HISTORY[market] = h[-96:]
                try:
                    c.store.save_json(rt._ai_key(market), rt._AI_HISTORY[market])
                except Exception:
                    pass
        rt._record_ai = record_ai
    except Exception:
        pass


def _patch_frontend():
    # Main AI score panel: 70-point entry label and gentler polling.
    p = ROOT / "static" / "v364_main.js"
    if p.exists():
        text = p.read_text(encoding="utf-8")
        text = text.replace(">=75).length", ">=70).length")
        text = text.replace("75↑", "70↑")
        text = text.replace("72↑", "70↑")
        text = re.sub(r"setInterval\(loadScores,\s*(?:5000|10000|20000)\)", "setInterval(loadScores,20000)", text)
        p.write_text(text, encoding="utf-8")

    # Main state polling was 5s. 8s is still live enough but removes a large
    # share of browser-triggered traffic during upstream instability.
    p = ROOT / "static" / "app.js"
    if p.exists():
        text = p.read_text(encoding="utf-8")
        text = re.sub(r"setInterval\(refresh,\s*(?:3000|5000|8000|10000)\)", "setInterval(refresh,8000)", text)
        p.write_text(text, encoding="utf-8")

    # Index detail used to fetch the same market-flow payload from render() every
    # 30s AND from its own 60s timer. Keep one initial fetch + one 60s refresh.
    p = ROOT / "static" / "index.js"
    if p.exists():
        text = p.read_text(encoding="utf-8")
        text = text.replace("if(d.flow_supported)loadFlow();else $('indexFlowPanel').classList.add('hide')", "if(d.flow_supported){if(!flowRows.length)loadFlow()}else $('indexFlowPanel').classList.add('hide')")
        p.write_text(text, encoding="utf-8")


def _install_health(core):
    old = getattr(core, "health_payload", None)
    if not callable(old):
        return
    def health():
        d = dict(old())
        fields = {"foreign": 0, "institution": 0, "person": 0, "program": 0}
        try:
            qs = list(core.feed.quotes_for("KR").values())
            for q in qs:
                f = dict(getattr(q, "investor_field_ready", {}) or {})
                for k in fields:
                    fields[k] += 1 if f.get(k) else 0
        except Exception:
            qs = []
        d["stability70_final"] = {
            "active": True,
            "condition1_threshold": 70,
            "hard_gates_unchanged": True,
            "kr_quote_count": len(qs),
            "investor_field_ready": fields,
            "stats": dict(_STATS),
            "promoted_hot": list(_PROMOTED.keys()),
            "sticky_cache_seconds": 120,
            "main_state_poll_seconds": 8,
            "ai_poll_seconds": 20,
            "index_flow_poll_seconds": 60,
        }
        return d
    core.health_payload = health


def apply(ns=None):
    global _INSTALLED
    if _INSTALLED:
        return True
    core = ns.get("core") if isinstance(ns, dict) else None
    if core is None:
        return False
    _install_threshold70(core)
    _install_investor_field_tracking(core)
    _install_bounded_investor_loop(core)
    _install_adaptive_kr_scanner(core)
    _install_sticky_cache(core)
    _patch_route_entry_score(core)
    _patch_ai_threshold70(core)
    _patch_frontend()
    _install_health(core)
    _INSTALLED = True
    print("NAMUH STABILITY70 FINAL active: C1>=70 + bounded investor + adaptive KR discovery + sticky UI cache + lighter polling", flush=True)
    return True
