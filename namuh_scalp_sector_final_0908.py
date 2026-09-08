from __future__ import annotations

import re
import threading
import time
from collections import OrderedDict
from queue import Queue, Empty, Full

import requests

_INSTALLED = False
_LOCK = threading.RLock()
_DISCOVERY: list[str] = []
_DISCOVERY_SOURCE = "waiting"
_DISCOVERY_UPDATED = 0.0
_OWNED: OrderedDict[str, float] = OrderedDict()
_ACTIVATE_Q: Queue = Queue(maxsize=40)
_ACTIVATE_PENDING: set[str] = set()
_WORKERS_STARTED = False
_LAST_PRUNE = 0.0
_STATS = {
    "discovery_refresh": 0,
    "discovery_fail": 0,
    "discovery_count": 0,
    "minute_sync_codes": 0,
    "public_rank_codes": 0,
    "nh_verified": 0,
    "activate_queued": 0,
    "activate_ok": 0,
    "activate_fail": 0,
    "scanner_calls": 0,
    "scanner_fail": 0,
    "sector_fallback_sectors": 0,
    "sector_foreign_fallback_members": 0,
    "sector_person_fallback_members": 0,
}
_SESSION = requests.Session()
_SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131 Safari/537.36",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.7,en;q=0.6",
})


def _f(v, default=0.0):
    try:
        return float(v)
    except Exception:
        return float(default)


def _date(v):
    s = "".join(ch for ch in str(v or "") if ch.isdigit())
    return s[:8] if len(s) >= 8 else ""


def _dedupe(codes, limit=80):
    out = []
    seen = set()
    for c in codes:
        c = str(c or "").strip().upper()
        if len(c) == 6 and c.isdigit() and c not in seen:
            seen.add(c)
            out.append(c)
            if len(out) >= limit:
                break
    return out


def _minute_sync_codes(core, limit=30):
    try:
        with core.MINUTE_SYNC_LOCK:
            rows = [dict(x) for x in (core.MINUTE_SYNC.get("rows") or {}).values() if isinstance(x, dict)]
        now = time.time()
        ttl = _f(getattr(core, "MINUTE_SYNC_TTL", 180), 180)
        rows = [x for x in rows if now - _f(x.get("_received_at"), core.MINUTE_SYNC.get("updated_at", 0)) <= ttl]
        rows.sort(key=lambda x: (
            _f(x.get("score")), _f(x.get("probability_up_20m")),
            _f(x.get("probability_surge_20m"))
        ), reverse=True)
        return _dedupe([x.get("code") for x in rows], limit)
    except Exception:
        return []


def _public_rank_codes(core, limit=60):
    """Broad discovery only. Every returned code is re-read from NH before scoring.

    The site used to discover one KR master symbol per ~3 quote calls, which makes
    a 3k+ name universe take far too long and leaves the detector dominated by the
    fixed seed names. These pages provide a cheap cross-sectional list of active
    names; no price, score, flow, or trade decision is ever accepted from them.
    """
    urls = (
        "https://finance.naver.com/sise/sise_quant.naver?sosok=0",
        "https://finance.naver.com/sise/sise_rise.naver?sosok=0",
        "https://finance.naver.com/sise/sise_quant.naver?sosok=1",
        "https://finance.naver.com/sise/sise_rise.naver?sosok=1",
    )
    got = []
    for url in urls:
        try:
            r = _SESSION.get(url, timeout=5)
            r.raise_for_status()
            got.extend(re.findall(r"(?:code=|/item/main\.naver\?code=)(\d{6})", r.text))
        except Exception:
            continue
    master = getattr(core.feed, "kr_master_meta", {}) or {}
    clean = _dedupe(got, 200)
    if master:
        clean = [c for c in clean if c in master]
    return clean[:limit]


def _refresh_discovery(core):
    global _DISCOVERY, _DISCOVERY_SOURCE, _DISCOVERY_UPDATED
    minute = _minute_sync_codes(core, 30)
    public = _public_rank_codes(core, 60)
    codes = _dedupe(minute + public, 70)
    source = "+".join(x for x, ok in (("pc_minute", bool(minute)), ("public_rank_nh_verify", bool(public))) if ok) or "master_fallback"
    if not codes:
        try:
            master = list((getattr(core.feed, "kr_master_meta", {}) or {}).keys())
            # Spread across the master instead of always starting at index zero.
            step = max(1, len(master) // 60) if master else 1
            codes = _dedupe(master[::step], 60)
        except Exception:
            codes = []
    with _LOCK:
        _DISCOVERY = codes
        _DISCOVERY_SOURCE = source
        _DISCOVERY_UPDATED = time.time()
        _STATS["discovery_refresh"] += 1
        _STATS["discovery_count"] = len(codes)
        _STATS["minute_sync_codes"] = len(minute)
        _STATS["public_rank_codes"] = len(public)
    return codes


def _discovery_loop(core):
    while True:
        try:
            _refresh_discovery(core)
        except Exception:
            with _LOCK:
                _STATS["discovery_fail"] += 1
        time.sleep(45)


def _queue_activate(core, code, data):
    q = core.feed.quotes_for("KR").get(code)
    if q is not None and len(list(getattr(q, "daily_bars", []) or [])) >= 10:
        try:
            core.feed._apply_kr(code, data)
            with _LOCK:
                _OWNED.pop(code, None)
                _OWNED[code] = time.time()
                _STATS["nh_verified"] += 1
            return True
        except Exception:
            return False
    with _LOCK:
        if code in _ACTIVATE_PENDING:
            return True
        if _ACTIVATE_Q.full():
            return False
        _ACTIVATE_PENDING.add(code)
        _STATS["activate_queued"] += 1
    try:
        _ACTIVATE_Q.put_nowait((core, code, data, time.time()))
        return True
    except Full:
        with _LOCK:
            _ACTIVATE_PENDING.discard(code)
        return False


def _activate_worker():
    while True:
        try:
            core, code, data, queued_at = _ACTIVATE_Q.get(timeout=1)
        except Empty:
            continue
        try:
            # Persist history before the quote becomes scoreable. This prevents
            # the score path from issuing the same daily-history request every 5s.
            try:
                core.feed.ensure_daily_bars("KR", code, 30)
            except Exception:
                pass
            q = core.feed.quotes_for("KR").get(code)
            if q is not None and len(list(getattr(q, "daily_bars", []) or [])) >= 10:
                core.feed._apply_kr(code, data)
                with _LOCK:
                    _OWNED.pop(code, None)
                    _OWNED[code] = time.time()
                    while len(_OWNED) > 70:
                        _OWNED.popitem(last=False)
                    _STATS["activate_ok"] += 1
                    _STATS["nh_verified"] += 1
            else:
                with _LOCK:
                    _STATS["activate_fail"] += 1
        except Exception:
            with _LOCK:
                _STATS["activate_fail"] += 1
        finally:
            with _LOCK:
                _ACTIVATE_PENDING.discard(code)
            _ACTIVATE_Q.task_done()
            time.sleep(1.7)


def _start_workers(core):
    global _WORKERS_STARTED
    if _WORKERS_STARTED:
        return
    _WORKERS_STARTED = True
    threading.Thread(target=_activate_worker, daemon=True, name="namuh-scan-activate").start()
    threading.Thread(target=_discovery_loop, args=(core,), daemon=True, name="namuh-broad-discovery").start()


def _scanner_pool(core):
    out = []
    try:
        out.extend(str(getattr(p, "code", "")) for p in core.paper.positions.values() if str(getattr(p, "market", "")).upper() == "KR")
    except Exception:
        pass
    try:
        cache = core.CACHE.get("KR") or {}
        out.extend(str(x.get("code") or "") for x in list(cache.get("scalp") or [])[:20])
        out.extend(str(x.get("leader_code") or "") for x in list(cache.get("sectors") or [])[:5])
    except Exception:
        pass
    with _LOCK:
        out.extend(_DISCOVERY[:55])
        out.extend(reversed(list(_OWNED.keys())[-20:]))
    try:
        out.extend(list(core.feed.fixed.get("KR", []) or []))
    except Exception:
        pass
    return _dedupe(out, 85)


def _position_codes(core):
    try:
        return {str(getattr(p, "code", "")) for p in core.paper.positions.values() if str(getattr(p, "market", "")).upper() == "KR"}
    except Exception:
        return set()


def _soft_prune(core):
    global _LAST_PRUNE
    now = time.time()
    if now - _LAST_PRUNE < 60:
        return
    _LAST_PRUNE = now
    with _LOCK:
        current = set(_DISCOVERY)
        owned = list(_OWNED.items())
    try:
        fixed = set(core.feed.fixed.get("KR", []) or [])
    except Exception:
        fixed = set()
    keep = current | fixed | _position_codes(core)
    # Do not mutate the quote dict while rebuild_cache may be iterating it.
    # Mark old patch-owned names inactive by price=0; the object/history remains
    # available and can be reactivated cheaply if the name becomes hot again.
    for code, ts in owned:
        if code in keep or now - ts <= 900:
            continue
        try:
            q = core.feed.quotes_for("KR").get(code)
            if q is not None:
                q.price = 0.0
        except Exception:
            pass
        with _LOCK:
            _OWNED.pop(code, None)


def _install_scanner(core):
    feed = core.feed

    def kr_scanner():
        from nhplug import call
        try:
            feed._load_kr_master()
        except Exception as exc:
            feed.errors["KR"] = f"국내 종목마스터: {exc}"[:300]
        try:
            _refresh_discovery(core)
        except Exception:
            pass
        idx = 0
        while not feed._stop.is_set():
            _soft_prune(core)
            pool = _scanner_pool(core)
            if not pool:
                feed._stop.wait(1.0)
                continue
            code = pool[idx % len(pool)]
            idx += 1
            success = False
            last = ""
            for market_cd in feed._market_order():
                try:
                    data = call("/krstock/quote/v1/currentPrice", {"iem_cd": code, "market_cd": market_cd})
                    _STATS["scanner_calls"] += 1
                    if _queue_activate(core, code, data):
                        success = True
                    break
                except Exception as exc:
                    last = str(exc)[:220]
                    if "429" in last:
                        break
            if not success:
                _STATS["scanner_fail"] += 1
                if last:
                    feed.errors["KR"] = f"{code}: {last}"[:300]
            else:
                feed.connected["KR"] = True
                feed.errors["KR"] = ""
            # Quote + investor + history workers share the same NH app limit.
            # ~1.4 quote calls/s here leaves headroom for those other channels.
            feed._stop.wait(0.70 if success else (3.0 if "429" in last else 1.2))

    feed.kr_scanner = kr_scanner


def _explicit_field_tracking(core):
    feed = core.feed
    old = getattr(feed, "_apply_investor", None)
    if not callable(old) or getattr(old, "_namuh_explicit_field_tracking", False):
        return

    def apply_investor(code, data):
        result = old(code, data)
        try:
            flags = {"foreign": False, "institution": False, "person": False, "program": False}
            def walk(v):
                if isinstance(v, dict):
                    yield v
                    for z in v.values():
                        yield from walk(z)
                elif isinstance(v, (list, tuple)):
                    for z in v:
                        yield from walk(z)
            for o in walk(data):
                if not isinstance(o, dict):
                    continue
                flags["foreign"] |= any(k in o and o.get(k) not in (None, "") for k in ("frgn_ntby_qty", "foreign"))
                flags["institution"] |= any(k in o and o.get(k) not in (None, "") for k in ("orgn_ntby_qty", "gigwan"))
                flags["person"] |= any(k in o and o.get(k) not in (None, "") for k in ("prsn_ntby_qty", "person"))
                flags["program"] |= any(k in o and o.get(k) not in (None, "") for k in ("prgm_ntby_qty", "pgtr_ntby_qty", "program"))
            q = feed.q("KR", code)
            q.investor_field_ready = flags
            q.investor_field_updated_at = time.time()
        except Exception:
            pass
        return result

    apply_investor._namuh_explicit_field_tracking = True
    feed._apply_investor = apply_investor


def _completed5(q, key, today):
    rows = []
    for r in list(getattr(q, "investor_daily", []) or []):
        if not isinstance(r, dict):
            continue
        d = _date(r.get("date"))
        if d and d < today:
            rows.append((d, _f(r.get(key))))
    rows.sort(key=lambda x: x[0])
    vals = [v for _, v in rows[-5:]]
    return (sum(vals), len(vals)) if vals else (0.0, 0)


def _effective_flow(q, key, today):
    current = _f(getattr(q, "foreign_net", 0)) if key == "foreign" else _f(getattr(q, "person_net", 0))
    # Use live currentInvestor when it carries a non-zero value. NH can publish
    # literal 0 for foreign/person during the current session while completed
    # historical rows are populated; in that case preserve visibility using the
    # most recent five completed sessions and label it explicitly as fallback.
    if current != 0:
        return current, False, 0
    hist, days = _completed5(q, key, today)
    if days and hist != 0:
        return hist, True, days
    return current, False, days


def _install_sector_flow(core):
    old = core.build_sector_context
    if getattr(old, "_namuh_sector_flow_completed5", False):
        return

    def build_sector_context(market):
        sectors, secmap, stock_strength = old(market)
        if str(market).upper() != "KR" or not sectors:
            return sectors, secmap, stock_strength
        today = core.datetime.now(core.KST).strftime("%Y%m%d")
        groups = {}
        for q in list(core.feed.quotes_for("KR").values()):
            try:
                if _f(getattr(q, "price", 0)) <= 0 or _f(getattr(q, "open", 0)) <= 0:
                    continue
                groups.setdefault(str(core.sector_name(q, "KR")), []).append(q)
            except Exception:
                continue
        foreign_fb = 0
        person_fb = 0
        fallback_sectors = 0
        for x in sectors:
            qs = groups.get(str(x.get("sector") or ""), [])
            if not qs:
                continue
            raw_f = sum(_f(getattr(q, "foreign_net", 0)) for q in qs)
            raw_person = sum(_f(getattr(q, "person_net", 0)) for q in qs)
            eff_f = 0.0
            eff_person = 0.0
            fval = 0.0
            person_exit = 0.0
            ff = 0
            pf = 0
            fdays = 0
            pdays = 0
            for q in qs:
                ef, used_f, days_f = _effective_flow(q, "foreign", today)
                ep, used_p, days_p = _effective_flow(q, "person", today)
                eff_f += ef
                eff_person += ep
                fval += _f(getattr(q, "price", 0)) * max(0.0, ef)
                person_exit += _f(getattr(q, "price", 0)) * max(0.0, -ep)
                ff += 1 if used_f else 0
                pf += 1 if used_p else 0
                fdays = max(fdays, days_f)
                pdays = max(pdays, days_p)
            fv = dict(x.get("flow_value") or {})
            fv["foreign"] = fval
            fv["person_exit"] = person_exit
            x["flow_value"] = fv
            x["foreign_net_raw"] = raw_f
            x["person_net_raw"] = raw_person
            x["foreign_net"] = eff_f
            x["person_net"] = eff_person
            x["flow_source"] = {
                "foreign": "recent5_completed" if ff else "current",
                "person_exit": "recent5_completed" if pf else "current",
                "institution": "current",
                "program": "current",
                "foreign_fallback_members": ff,
                "person_fallback_members": pf,
                "foreign_history_days": fdays,
                "person_history_days": pdays,
            }
            if ff or pf:
                fallback_sectors += 1
            foreign_fb += ff
            person_fb += pf

        totals = {k: sum(max(0.0, _f((x.get("flow_value") or {}).get(k))) for x in sectors)
                  for k in ("foreign", "institution", "program", "person_exit")}
        for x in sectors:
            fv = x.get("flow_value") or {}
            shares = {k: (_f(fv.get(k)) / totals[k] * 100.0 if totals[k] > 0 else 0.0) for k in totals}
            raw = shares["foreign"] * 0.35 + shares["institution"] * 0.35 + shares["program"] * 0.20 + shares["person_exit"] * 0.10
            x["flow_share"] = {**{k: round(v, 1) for k, v in shares.items()}, "_composite_raw": raw}
        comp = sum(_f((x.get("flow_share") or {}).get("_composite_raw")) for x in sectors)
        for x in sectors:
            sh = x.get("flow_share") or {}
            raw = _f(sh.pop("_composite_raw", 0))
            sh["composite"] = round(raw / comp * 100.0, 1) if comp > 0 else 0.0
            x["flow_share"] = sh
        sectors.sort(key=lambda x: (_f((x.get("flow_share") or {}).get("composite")), _f(x.get("score"))), reverse=True)
        with _LOCK:
            _STATS["sector_fallback_sectors"] = fallback_sectors
            _STATS["sector_foreign_fallback_members"] = foreign_fb
            _STATS["sector_person_fallback_members"] = person_fb
        return sectors, {str(x.get("sector") or ""): _f(x.get("score")) for x in sectors}, stock_strength

    build_sector_context._namuh_sector_flow_completed5 = True
    core.build_sector_context = build_sector_context


def _install_health(core):
    old = getattr(core, "health_payload", None)
    if not callable(old):
        return

    def health():
        d = dict(old())
        with _LOCK:
            disc = list(_DISCOVERY)
            source = _DISCOVERY_SOURCE
            updated = _DISCOVERY_UPDATED
            stats = dict(_STATS)
            active = list(_OWNED.keys())
            pending = len(_ACTIVATE_PENDING)
        d["scalp_sector_final"] = {
            "active": True,
            "discovery_source": source,
            "discovery_count": len(disc),
            "discovery_updated_at": updated,
            "discovery_sample": disc[:20],
            "nh_verified_active": active[-30:],
            "activation_pending": pending,
            "activation_queue": _ACTIVATE_Q.qsize(),
            "stats": stats,
            "sector_flow_policy": "current explicit field; if literal zero, recent 5 completed sessions fallback with source label",
            "foreign_field": "frgn_ntby_qty only (invest is not foreign)",
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
    _explicit_field_tracking(core)
    _install_sector_flow(core)
    _install_scanner(core)
    _install_health(core)
    _start_workers(core)
    _INSTALLED = True
    print("NAMUH SCALP/SECTOR FINAL 0908 active: broad discovery + NH verify + completed5 foreign/person fallback", flush=True)
    return True
