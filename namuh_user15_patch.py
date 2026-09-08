from __future__ import annotations

import statistics
import threading
import time
from collections import defaultdict

_INSTALLED = False


def _f(v, default=0.0):
    try:
        return float(str(v or "0").replace(",", "").replace("+", "").strip())
    except Exception:
        return float(default)


def _walk(v):
    if isinstance(v, dict):
        yield v
        for x in v.values():
            yield from _walk(x)
    elif isinstance(v, list):
        for x in v:
            yield from _walk(x)


def _date(v):
    s = "".join(ch for ch in str(v or "") if ch.isdigit())
    return s[:8] if len(s) >= 8 else ""


def apply(ns):
    global _INSTALLED
    if _INSTALLED:
        return
    core = ns.get("core") if isinstance(ns, dict) else None
    if core is None:
        return
    _INSTALLED = True
    feed = core.feed

    # Final lightweight owner. It only removes/repairs the requested UI pieces.
    try:
        inject = ns.get("_inject")
        if callable(inject):
            for rel in ("static/index.html", "static/stock.html", "static/index-detail.html", "static/coin.html", "static/coin-detail.html"):
                inject(rel, css=False, scripts=("/static/v361_user15.js",))
    except Exception as exc:
        print("NAMUH USER15 UI INJECT:", str(exc)[:180], flush=True)

    old_apply_investor = getattr(feed, "_apply_investor", None)
    if callable(old_apply_investor):
        def apply_investor(code, data):
            old_apply_investor(code, data)
            dated = []
            for o in _walk(data):
                if not isinstance(o, dict):
                    continue
                d = _date(o.get("bsop_date") or o.get("stck_bsop_date") or o.get("trade_date") or o.get("date") or o.get("xymd") or o.get("trd_dd"))
                if not d:
                    continue
                row = {"date": d}
                found = False
                fields = {
                    "foreign": ("frgn_ntby_qty", "invest", "foreignerPureBuyQuant"),
                    "institution": ("gigwan", "orgn_ntby_qty", "organPureBuyQuant"),
                    "person": ("person", "prsn_ntby_qty", "individualPureBuyQuant"),
                    "program": ("program", "prgm_ntby_qty"),
                }
                for name, keys in fields.items():
                    for k in keys:
                        if k in o and o.get(k) not in (None, ""):
                            row[name] = _f(o.get(k))
                            found = True
                            break
                if found:
                    dated.append(row)
            if not dated:
                return
            latest = max(dated, key=lambda x: x["date"])
            q = feed.q("KR", code)
            if any(k in latest for k in ("foreign", "institution", "program")):
                q.update_flow(
                    latest.get("foreign") if "foreign" in latest else None,
                    latest.get("institution") if "institution" in latest else None,
                    latest.get("program") if "program" in latest else None,
                )
            if "person" in latest:
                q.person_net = latest["person"]
            if "program" in latest:
                q.program_net = latest["program"]
        feed._apply_investor = apply_investor

    old_refresh_universe = getattr(feed, "_refresh_sector_scan_universe", None)
    if callable(old_refresh_universe):
        def refresh_sector_scan_universe():
            if getattr(feed, "krx_openapi_key", ""):
                return old_refresh_universe()
            meta = dict(getattr(feed, "kr_master_meta", {}) or {})
            if not meta:
                feed.sector_scan_codes = list(feed.fixed.get("KR") or [])
                return
            groups = defaultdict(list)
            for code, row in meta.items():
                sec = str((row or {}).get("sector") or "기타")
                groups[sec].append(str(code))
            for sec in groups:
                groups[sec].sort()
            selected = list(dict.fromkeys(list(feed.fixed.get("KR") or [])))
            limit = min(max(48, int(getattr(feed, "sector_scan_limit", 160) or 160)), 72)
            depth = 0
            sectors = sorted(groups)
            while len(selected) < limit:
                added = False
                for sec in sectors:
                    arr = groups[sec]
                    if depth < len(arr):
                        c = arr[depth]
                        if c not in selected:
                            selected.append(c)
                            added = True
                            if len(selected) >= limit:
                                break
                if not added:
                    break
                depth += 1
            feed.sector_scan_codes = selected
            feed.sector_universe_asof = ""
        feed._refresh_sector_scan_universe = refresh_sector_scan_universe

    old_program_loop = getattr(feed, "program_loop", None)
    if callable(old_program_loop):
        def program_loop():
            delay = 1
            feed._stop.wait(4)
            while not feed._stop.is_set():
                try:
                    from nhplug.realtime import subscribe
                    codes = list(getattr(feed, "sector_scan_codes", []) or feed.fixed.get("KR") or [])[:60]
                    subscribe(codes, feed._apply_program_message, tr_cd="mn", timeout=30)
                    delay = 1
                    if not feed.program_realtime.get("connected"):
                        feed.program_realtime["error"] = "실시간 프로그램매매 수신 대기"
                except Exception as exc:
                    feed.program_realtime["connected"] = False
                    feed.program_realtime["error"] = str(exc)[:240]
                    feed._stop.wait(delay)
                    delay = min(30, delay * 2)
        feed.program_loop = program_loop

    forecast_lock = threading.RLock()
    forecast = {"ready": False, "loading": False, "updated_at": 0.0, "history_days": 0}

    def build_forecast():
        nonlocal forecast
        with forecast_lock:
            if forecast.get("loading"):
                return
            forecast = {**forecast, "loading": True}
        try:
            bars = list(feed._fetch_krx_index_daily_web("kospi", 1260) or [])
            closes = [_f(x.get("close")) for x in bars if _f(x.get("close")) > 0]
            if len(closes) < 800:
                raise RuntimeError(f"KOSPI 5Y history short: {len(closes)}")
            lookback, horizon = 20, 20
            current_mom = closes[-1] / closes[-1 - lookback] - 1.0
            samples = []
            for i in range(lookback, len(closes) - horizon):
                if closes[i - lookback] <= 0 or closes[i] <= 0:
                    continue
                mom = closes[i] / closes[i - lookback] - 1.0
                future = closes[i + horizon] / closes[i] - 1.0
                samples.append((abs(mom - current_mom), future))
            samples.sort(key=lambda x: x[0])
            analog = [x[1] for x in samples[: min(160, len(samples))]]
            if len(analog) < 40:
                raise RuntimeError("KOSPI analogue sample short")
            up = sum(x > 0 for x in analog) / len(analog) * 100.0
            expected = statistics.median(analog) * 100.0
            current_index = _f((feed.market_item("kospi") or {}).get("value")) or closes[-1]
            result = {
                "ready": True, "loading": False, "updated_at": time.time(),
                "history_days": len(closes), "history_years": round(len(closes) / 250.0, 1),
                "analogue_count": len(analog), "lookback_days": lookback, "forecast_days": horizon,
                "up_probability_pct": round(up, 1), "expected_change_pct": round(expected, 2),
                "current_kospi": round(current_index, 2),
                "expected_kospi": round(current_index * (1.0 + expected / 100.0), 2),
                "method": "KOSPI 5년 · 최근20일 모멘텀 유사구간 → 향후20일 중앙값",
                "source": "KRX 정보데이터시스템",
            }
            with forecast_lock:
                forecast = result
        except Exception as exc:
            with forecast_lock:
                forecast = {"ready": False, "loading": False, "updated_at": time.time(), "history_days": 0, "error": str(exc)[:180]}

    threading.Thread(target=build_forecast, daemon=True, name="kospi-5y-forecast").start()

    old_candidate = core.candidate

    def candidate(q, market, smart=False, secmap=None, stockmap=None, leadermap=None, sector_rankmap=None, now=None):
        out = old_candidate(q, market, smart, secmap, stockmap, leadermap, sector_rankmap, now)
        if not (smart and str(market or "").upper() == "KR" and isinstance(out, dict)):
            return out
        with forecast_lock:
            fc = dict(forecast)
        if fc.get("ready"):
            px = _f(out.get("price") or getattr(q, "price", 0))
            fc["expected_price"] = round(px * (1.0 + _f(fc.get("expected_change_pct")) / 100.0)) if px > 0 else None
        out["smart_money_5y"] = fc
        return out

    core.candidate = candidate

    try:
        import v343_features as v343
        threading.Thread(target=v343._refresh_market_flow, kwargs={"force": False}, daemon=True, name="market-flow-warm").start()
    except Exception:
        pass

    old_health = getattr(core, "health_payload", None)
    if callable(old_health):
        def health():
            d = dict(old_health())
            with forecast_lock:
                d["smart_money_kospi_5y"] = {k: forecast.get(k) for k in ("ready", "loading", "history_days", "updated_at", "error")}
            d["sector_balanced_scan_limit"] = len(getattr(feed, "sector_scan_codes", []) or [])
            return d
        core.health_payload = health

    print("NAMUH USER15 active: investor latest-row + balanced sectors + KOSPI 5Y smart money + UI361", flush=True)
