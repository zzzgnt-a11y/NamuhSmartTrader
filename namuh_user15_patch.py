from __future__ import annotations

import math
import re
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

import requests

_INSTALLED = False
_KOSPI_FORECAST_KEY = "namuh_kospi_5y_forecast_v1"


def _n(v, default=0.0):
    try:
        if isinstance(v, (int, float)):
            return float(v)
        s = str(v or "").strip().replace(",", "").replace("−", "-").replace("+", "")
        m = re.search(r"-?\d+(?:\.\d+)?", s)
        if not m:
            return float(default)
        x = float(m.group(0))
        a = abs(x)
        if "조" in s:
            x = (1 if x >= 0 else -1) * a * 1e12
        elif "억" in s:
            x = (1 if x >= 0 else -1) * a * 1e8
        elif "만" in s:
            x = (1 if x >= 0 else -1) * a * 1e4
        return x
    except Exception:
        return float(default)


def _digits(v):
    return "".join(ch for ch in str(v or "") if ch.isdigit())


def _walk(v):
    if isinstance(v, dict):
        yield v
        for x in v.values():
            yield from _walk(x)
    elif isinstance(v, list):
        for x in v:
            yield from _walk(x)


def _patch_text(path: str, replacements):
    p = Path(path)
    if not p.exists():
        return False
    try:
        text = p.read_text(encoding="utf-8")
        old = text
        for a, b in replacements:
            text = text.replace(a, b)
        if text != old:
            p.write_text(text, encoding="utf-8")
            return True
    except Exception as exc:
        print("NAMUH USER15 STATIC PATCH ERROR", path, str(exc)[:180], flush=True)
    return False


def _replace_route(core, path: str, func):
    for route in core.app.router.routes:
        if getattr(route, "path", "") != path:
            continue
        try:
            route.endpoint = func
            if getattr(route, "dependant", None) is not None:
                route.dependant.call = func
        except Exception:
            pass
        return True
    return False


def _mean(vals):
    vals = list(vals or [])
    return sum(vals) / len(vals) if vals else 0.0


def _std(vals):
    vals = list(vals or [])
    if len(vals) < 2:
        return 0.0
    m = _mean(vals)
    return math.sqrt(sum((x - m) ** 2 for x in vals) / (len(vals) - 1))


def apply(ns):
    global _INSTALLED
    if _INSTALLED:
        return
    core = ns.get("core") if isinstance(ns, dict) else None
    if core is None:
        return
    _INSTALLED = True

    # ------------------------------------------------------------------
    # Frontend performance: remove high-frequency DOM ownership loops and
    # duplicate network polling. Trading/background engine cadence is untouched.
    # ------------------------------------------------------------------
    _patch_text("static/app.js", [
        ("setInterval(refresh,5000)", "setInterval(refresh,8000)"),
    ])
    _patch_text("static/v352.js", [
        ("setInterval(()=>loadUniverse(false),8000);setInterval(()=>{renderAllScores();if(!$('#v34SearchBox')?.dataset.v352)installSearch()},1000)",
         "setInterval(()=>loadUniverse(false),15000)"),
    ])
    _patch_text("static/v355_unified_ui.js", [
        ("setInterval(apply,400);document.addEventListener('DOMContentLoaded',apply,{once:true});setTimeout(apply,100);",
         "document.addEventListener('DOMContentLoaded',apply,{once:true});"),
    ])
    _patch_text("static/v356_strategy_ui.js", [
        ("if(scalp)new MutationObserver(schedule).observe(scalp,opts);", ""),
        ("if(positions)new MutationObserver(schedule).observe(positions,opts);", ""),
        ("setInterval(schedule,2000);", ""),
    ])
    _patch_text("static/index.js", [
        ("load();setInterval(load,30000);setInterval(()=>{if(DATA?.flow_supported)loadFlow()},60000);",
         "load();setInterval(load,45000);"),
    ])

    # sitecustomize_legacy creates this runtime asset. Disable the top chart
    # disclosure strip and its duplicate data fetches, while keeping the normal
    # disclosure section below the chart intact.
    _patch_text("static/stock-fix.js", [
        ("function installDisclosureUI(){\n const wrap=", "function installDisclosureUI(){return;\n const wrap="),
        ("async function refreshDisclosures(){\n installDisclosureUI();", "async function refreshDisclosures(){return;\n installDisclosureUI();"),
        ("setInterval(refreshDisclosures,120000);", ""),
    ])

    # Historical minute candles are immutable; live ticks are merged separately.
    # A longer cache drastically cuts repeated NH requests on stock detail pages.
    try:
        import namuh_minute_data_patch as minute_patch
        minute_patch._TTL.update({"1m": 180.0, "3m": 180.0, "5m": 180.0, "20m": 300.0})
    except Exception:
        pass

    # ------------------------------------------------------------------
    # KR sector breadth: when a formal KRX OpenAPI key is absent, use the
    # official KRX public Information Data System all-stock daily snapshot to
    # choose a liquid 80-name scan universe instead of only the fixed ~15 names.
    # ------------------------------------------------------------------
    feed = core.feed
    old_refresh_sector = getattr(feed, "_refresh_sector_scan_universe", None)

    def refresh_sector_scan_universe():
        if getattr(feed, "krx_openapi_key", ""):
            return old_refresh_sector() if callable(old_refresh_sector) else None
        try:
            for d in feed._recent_trade_dates(8):
                j = feed._krx_post({
                    "bld": "dbms/MDC/STAT/standard/MDCSTAT01501",
                    "mktId": "ALL",
                    "trdDd": d,
                })
                rows = j.get("OutBlock_1") or j.get("output") or j.get("output1") or []
                ranked = []
                for r in rows:
                    if not isinstance(r, dict):
                        continue
                    raw = str(r.get("ISU_SRT_CD") or r.get("ISU_CD") or "")
                    m = re.search(r"(\d{6})", raw)
                    if not m:
                        continue
                    code = m.group(1)
                    if code not in getattr(feed, "kr_master_meta", {}):
                        continue
                    value = _n(r.get("ACC_TRDVAL"))
                    if value > 0:
                        ranked.append((value, code))
                if ranked:
                    ranked.sort(reverse=True)
                    top = [c for _, c in ranked[:80]]
                    feed.sector_scan_codes = list(dict.fromkeys(list(feed.fixed.get("KR") or []) + top))
                    feed.sector_universe_asof = d
                    feed.market_errors.pop("sector_universe", None)
                    print(f"NAMUH KR SECTOR universe={len(feed.sector_scan_codes)} KRX public {d}", flush=True)
                    return
        except Exception as exc:
            feed.market_errors["sector_universe"] = str(exc)[:220]
        if callable(old_refresh_sector):
            return old_refresh_sector()

    if callable(old_refresh_sector):
        feed._refresh_sector_scan_universe = refresh_sector_scan_universe

    # ------------------------------------------------------------------
    # Fast KOSPI/KOSDAQ market investor flow. KRX remains the primary owner;
    # Naver's public index integration data supplies an immediate numeric
    # fallback/latest row while KRX refreshes in the background.
    # ------------------------------------------------------------------
    flow_lock = threading.RLock()
    fast_flow = {}
    fast_flow_at = 0.0
    http = requests.Session()
    http.headers.update({"User-Agent": "Mozilla/5.0 GY-Trading-OS/36.1", "Accept": "application/json,*/*"})

    def naver_flow_one(key):
        code = "KOSPI" if key == "kospi" else "KOSDAQ"
        url = f"https://stock.naver.com/api/securityFe/api/index/{code}/integration"
        r = http.get(url, timeout=5)
        r.raise_for_status()
        payload = r.json()
        by_date = {}
        for x in _walk(payload):
            if not isinstance(x, dict):
                continue
            if not any(k in x for k in ("personalValue", "foreignValue", "institutionalValue")):
                continue
            ds = _digits(x.get("bizdate") or x.get("localDate") or x.get("date"))[:8]
            if len(ds) != 8:
                continue
            date = f"{ds[:4]}-{ds[4:6]}-{ds[6:8]}"
            by_date[date] = {
                "date": date,
                "person": _n(x.get("personalValue")),
                "foreign": _n(x.get("foreignValue")),
                "institution": _n(x.get("institutionalValue")),
            }
        daily = [by_date[k] for k in sorted(by_date)][-31:]
        latest = daily[-1] if daily else {}
        return {
            "key": key,
            "label": code,
            "source": "Naver 증권 지수 투자자 동향",
            "asof": latest.get("date") or "",
            "latest": {k: latest.get(k) for k in ("foreign", "institution", "person")} if latest else {},
            "daily": daily,
            "days": len(daily),
            "ok": bool(daily),
        }

    def refresh_fast_flow():
        nonlocal fast_flow_at
        new = {}
        for key in ("kospi", "kosdaq"):
            try:
                x = naver_flow_one(key)
                if x.get("ok"):
                    new[key] = x
            except Exception as exc:
                print("NAMUH FAST FLOW", key, str(exc)[:140], flush=True)
        if new:
            with flow_lock:
                fast_flow.update(new)
                fast_flow_at = time.time()

    def flow_worker():
        while True:
            refresh_fast_flow()
            time.sleep(120)

    threading.Thread(target=flow_worker, daemon=True, name="namuh-fast-flow").start()

    old_flow_endpoint = None
    for route in core.app.router.routes:
        if getattr(route, "path", "") == "/api/v343/market-flow":
            old_flow_endpoint = route.endpoint
            break

    def market_flow_endpoint():
        try:
            base = old_flow_endpoint() if callable(old_flow_endpoint) else {}
            if not isinstance(base, dict):
                base = {}
        except Exception:
            base = {}
        items = dict(base.get("items") or {})
        with flow_lock:
            ff = dict(fast_flow)
            ff_at = fast_flow_at
        try:
            import v343_features as v343
            enrich = getattr(v343, "_flow_enrich", None)
        except Exception:
            enrich = None
        for key in ("kospi", "kosdaq"):
            fallback = ff.get(key)
            if not fallback:
                continue
            current = dict(items.get(key) or {})
            if not current.get("daily"):
                current = dict(fallback)
            else:
                current["latest"] = dict(fallback.get("latest") or current.get("latest") or {})
                current["fast_latest_source"] = fallback.get("source")
            if callable(enrich):
                try:
                    current = enrich(current)
                except Exception:
                    pass
            items[key] = current
        base["items"] = items
        base["fast_flow_updated_at"] = ff_at
        return base

    if old_flow_endpoint:
        _replace_route(core, "/api/v343/market-flow", market_flow_endpoint)

    # ------------------------------------------------------------------
    # Smart Money: five-year KOSPI regime analysis. This is an empirical
    # nearest-regime estimate, not a guaranteed prediction. It reports the
    # 5-trading-day positive frequency and expected index price/return.
    # ------------------------------------------------------------------
    forecast_lock = threading.RLock()
    saved = core.store.load_json(_KOSPI_FORECAST_KEY, {}) or {}
    forecast = dict(saved.get("forecast") or {}) if isinstance(saved, dict) else {}
    forecast_updated = _n(saved.get("updated_at")) if isinstance(saved, dict) else 0.0

    def compute_forecast(rows):
        clean = []
        for x in list(rows or []):
            c = _n(x.get("close"))
            if c > 0:
                clean.append({"date": str(x.get("date") or x.get("time") or ""), "close": c})
        clean.sort(key=lambda x: x["date"])
        if len(clean) < 650:
            return {"ready": False, "reason": f"KOSPI 5년 데이터 부족 {len(clean)}개", "sample_days": len(clean)}
        closes = [x["close"] for x in clean]
        rets = [0.0] + [closes[i] / closes[i - 1] - 1.0 for i in range(1, len(closes))]
        cur_ret20 = closes[-1] / closes[-21] - 1.0
        cur_vol20 = _std(rets[-20:])
        feats = []
        for i in range(40, len(closes) - 5):
            ret20 = closes[i] / closes[i - 20] - 1.0
            vol20 = _std(rets[i - 19:i + 1])
            fwd5 = closes[i + 5] / closes[i] - 1.0
            feats.append((ret20, vol20, fwd5))
        if len(feats) < 300:
            return {"ready": False, "reason": "유사국면 표본 부족", "sample_days": len(clean)}
        sr = _std([x[0] for x in feats]) or 0.01
        sv = _std([x[1] for x in feats]) or 0.005
        nearest = sorted(feats, key=lambda x: ((x[0] - cur_ret20) / sr) ** 2 + ((x[1] - cur_vol20) / sv) ** 2)[:80]
        fwds = sorted(x[2] for x in nearest)
        trim = max(2, len(fwds) // 10)
        core_fwds = fwds[trim:-trim] if len(fwds) > trim * 2 else fwds
        exp = _mean(core_fwds)
        prob = sum(x > 0 for x in fwds) / len(fwds) * 100.0
        last = closes[-1]
        return {
            "ready": True,
            "basis": "KOSPI 최근 5년 · 현재 20일 수익률/변동성과 유사한 80개 국면",
            "horizon": "5거래일",
            "sample_days": len(clean),
            "similar_samples": len(fwds),
            "asof": clean[-1]["date"],
            "current_index": round(last, 2),
            "up_probability_pct": round(prob, 1),
            "expected_return_pct": round(exp * 100.0, 2),
            "expected_index": round(last * (1.0 + exp), 2),
            "current_20d_return_pct": round(cur_ret20 * 100.0, 2),
            "current_20d_vol_pct": round(cur_vol20 * 100.0, 2),
            "method": "empirical nearest-regime statistics",
        }

    def refresh_forecast(force=False):
        nonlocal forecast, forecast_updated
        with forecast_lock:
            if not force and forecast.get("ready") and time.time() - forecast_updated < 21600:
                return
        try:
            now = datetime.now(core.KST)
            end = now.strftime("%Y%m%d")
            start = (now - timedelta(days=1900)).strftime("%Y%m%d")
            j = feed._krx_post({
                "bld": "dbms/MDC/STAT/standard/MDCSTAT00301",
                "indIdx": "1",
                "indIdx2": "001",
                "strtDd": start,
                "endDd": end,
            })
            raw = j.get("output") or j.get("OutBlock_1") or j.get("output1") or []
            rows = feed._parse_krx_index_rows(raw)
            result = compute_forecast(rows)
            with forecast_lock:
                forecast = result
                forecast_updated = time.time()
            core.store.save_json(_KOSPI_FORECAST_KEY, {"updated_at": forecast_updated, "forecast": result})
            print("NAMUH SMART 5Y", result.get("ready"), result.get("sample_days"), flush=True)
        except Exception as exc:
            with forecast_lock:
                if not forecast:
                    forecast = {"ready": False, "reason": str(exc)[:180]}

    def forecast_worker():
        time.sleep(1)
        while True:
            refresh_forecast(False)
            time.sleep(21600)

    threading.Thread(target=forecast_worker, daemon=True, name="namuh-kospi-5y").start()

    # ------------------------------------------------------------------
    # Timeframe score reliability: never drop the five requested score keys.
    # Missing minute scores are warmed in a background thread so the detail page
    # remains responsive; subsequent refreshes receive the real computed score.
    # ------------------------------------------------------------------
    old_stock_detail = core.stock_detail
    score_lock = threading.RLock()
    score_cache = {}
    score_warming = set()

    def warm_scores(market, code):
        key = (market, code)
        out = {}
        try:
            q = feed.q(market, code)
            for tf in ("1m", "3m", "5m", "20m", "1d"):
                try:
                    if tf == "1d":
                        feed.ensure_daily_bars(market, code, 60)
                    bars = list(feed.bars(market, code, tf) or [])
                    a = core._analysis_for_bars(q, market, bars) if len(bars) >= 20 else None
                    out[tf] = a.get("score") if isinstance(a, dict) else None
                except Exception:
                    out[tf] = None
            with score_lock:
                score_cache[key] = (time.time(), out)
        finally:
            with score_lock:
                score_warming.discard(key)

    def stock_detail(market, code, timeframe="1d"):
        d = dict(old_stock_detail(market, code, timeframe))
        m = "US" if str(market).upper() == "US" else "KR"
        c = str(code or "").upper()
        scores = dict(d.get("scores") or {})
        for tf in ("1m", "3m", "5m", "20m", "1d"):
            scores.setdefault(tf, None)
        key = (m, c)
        with score_lock:
            cached = score_cache.get(key)
            if cached and time.time() - cached[0] < 300:
                for tf, val in cached[1].items():
                    if scores.get(tf) is None and val is not None:
                        scores[tf] = val
            need = any(scores.get(tf) is None for tf in ("1m", "3m", "5m", "20m", "1d"))
            if need and key not in score_warming:
                score_warming.add(key)
                threading.Thread(target=warm_scores, args=(m, c), daemon=True, name=f"score-{m}-{c}").start()
        d["scores"] = scores
        return d

    core.stock_detail = stock_detail
    _replace_route(core, "/api/stock/{market}/{code}", stock_detail)

    # Attach forecast to KR state without mixing it into US/COIN calendars.
    old_state = core.state

    def state(market="KR"):
        d = dict(old_state(market))
        m = str(d.get("mode") or market or "KR").upper()
        if m == "KR":
            with forecast_lock:
                f = dict(forecast)
                f["updated_at"] = forecast_updated
            d["smart_money_forecast"] = f
        else:
            d["smart_money_forecast"] = None
        return d

    core.state = state
    _replace_route(core, "/api/state", state)

    # Final lightweight UI owners. They do not add polling; they piggyback on
    # the page's existing fetches/DOM updates.
    try:
        inject = ns.get("_inject")
        if callable(inject):
            inject("static/index.html", css=False, scripts=("/static/v361_user15.js",))
            inject("static/index-detail.html", css=False, head_scripts=("/static/index-v361.js",))
            inject("static/stock.html", css=False, head_scripts=("/static/stock-v361.js",))
            inject("static/coin-detail.html", css=False, scripts=("/static/coin-detail-v361.js",))
    except Exception as exc:
        print("NAMUH USER15 UI INJECT", str(exc)[:180], flush=True)

    print("NAMUH USER15 PATCH active: 15 fixes + frontend performance", flush=True)
