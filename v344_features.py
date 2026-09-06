from __future__ import annotations

import calendar
import threading
import time
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import requests

_INSTALLED = False
_core = None
_v343 = None
_runtime_ns = None
_LOCK = threading.RLock()
_DART_PAGE_CACHE: dict[tuple, tuple[float, dict]] = {}
_DART_STOCK_CACHE: dict[tuple, tuple[float, dict]] = {}
_STOCK_ATTEMPT: dict[str, float] = {}
_INVESTOR_ATTEMPT: dict[str, float] = {}
_INVESTOR_REFRESHING: set[str] = set()
_INDEX_ATTEMPT: dict[str, float] = {}


def _n(v: Any) -> float:
    try:
        return float(str(v or "0").replace(",", "").replace("+", "").strip())
    except Exception:
        return 0.0


def _iso_date(v: Any) -> str:
    s = "".join(ch for ch in str(v or "") if ch.isdigit())
    if len(s) >= 8:
        s = s[:8]
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    raw = str(v or "")
    return raw[:10] if len(raw) >= 10 and raw[4:5] == "-" and raw[7:8] == "-" else ""


def _months_ago(d, months: int):
    months = max(1, int(months or 1))
    y = d.year
    m = d.month - months
    while m <= 0:
        y -= 1
        m += 12
    day = min(d.day, calendar.monthrange(y, m)[1])
    return d.replace(year=y, month=m, day=day)


def _classify(title: str):
    try:
        from events import classify_event
        c = classify_event(title)
        sent = str(c.get("sentiment") or "neutral")
        blocked = bool(c.get("blocked"))
        return sent, str(c.get("label") or "중립"), (5.0 if sent == "positive" else -5.0 if sent == "negative" else 0.0), blocked
    except Exception:
        return "neutral", "중립", 0.0, False


def _dart_key() -> str:
    try:
        return str(getattr(_core.events, "api_key", "") or "").strip()
    except Exception:
        return ""


def _dart_get(params: dict) -> dict:
    key = _dart_key()
    if not key:
        return {"status": "NO_KEY", "message": "DART_API_KEY 미설정", "list": []}
    r = requests.get("https://opendart.fss.or.kr/api/list.json", params={"crtfc_key": key, **params}, timeout=18)
    r.raise_for_status()
    return r.json()


def _dart_row(x: dict, *, code_override: str = "") -> dict | None:
    code = str(code_override or x.get("stock_code") or "").strip()
    if not (len(code) == 6 and code.isdigit()):
        return None
    title = str(x.get("report_nm") or "").strip()
    sent, label, score, blocked = _classify(title)
    rcp = str(x.get("rcept_no") or "")
    return {
        "market": "KR",
        "code": code,
        "corp_name": str(x.get("corp_name") or code),
        "title": title,
        "date": _iso_date(x.get("rcept_dt")),
        "time": "",
        "source": "DART 공식",
        "url": f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcp}" if rcp else "",
        "sentiment": sent,
        "label": label,
        "score": score,
        "blocked": blocked,
        "form": str(x.get("corp_cls") or ""),
    }


def _dart_market_page(months: int, page: int, page_size: int) -> dict:
    months = max(1, min(3, int(months or 3)))
    page = max(1, int(page or 1))
    page_size = max(10, min(100, int(page_size or 50)))
    today = datetime.now(_core.KST).date()
    begin = _months_ago(today, months)
    key = (months, page, page_size, today.isoformat())
    now = time.time()
    cached = _DART_PAGE_CACHE.get(key)
    if cached and now - cached[0] < 60:
        return cached[1]
    j = _dart_get({
        "bgn_de": begin.strftime("%Y%m%d"),
        "end_de": today.strftime("%Y%m%d"),
        "page_no": str(page),
        "page_count": str(page_size),
        "sort": "date",
        "sort_mth": "desc",
    })
    status = str(j.get("status") or "")
    if status not in ("000", "013"):
        payload = {"ok": False, "market": "KR", "items": [], "status": j.get("message") or status, "source": "DART 공식"}
    else:
        items = []
        for x in j.get("list") or []:
            row = _dart_row(x)
            if row:
                items.append(row)
        payload = {
            "ok": True,
            "market": "KR",
            "months": months,
            "page": page,
            "page_size": page_size,
            "total_count": int(j.get("total_count") or 0),
            "total_page": int(j.get("total_page") or 1),
            "items": items,
            "source": "DART 공식 · 전종목",
            "updated_at": now,
        }
    _DART_PAGE_CACHE[key] = (now, payload)
    return payload


def _dart_stock_history(code: str, months: int = 3) -> dict:
    code = str(code or "").strip().upper()
    months = max(1, min(3, int(months or 3)))
    today = datetime.now(_core.KST).date()
    key = (code, months, today.isoformat())
    now = time.time()
    cached = _DART_STOCK_CACHE.get(key)
    if cached and now - cached[0] < 120:
        return cached[1]
    if not _dart_key():
        return {"ok": False, "market": "KR", "code": code, "items": [], "status": "DART_API_KEY 미설정"}
    try:
        _core.events._load_corp_map()
        corp = getattr(_core.events, "_corp_by_stock", {}).get(code)
    except Exception:
        corp = None
    if not corp:
        return {"ok": True, "market": "KR", "code": code, "items": [], "source": "DART 공식", "status": "DART 종목코드 매핑 없음"}
    begin = _months_ago(today, months)
    page = 1
    total_page = 1
    items = []
    while page <= total_page and page <= 10:
        j = _dart_get({
            "corp_code": corp[0],
            "bgn_de": begin.strftime("%Y%m%d"),
            "end_de": today.strftime("%Y%m%d"),
            "page_no": str(page),
            "page_count": "100",
            "sort": "date",
            "sort_mth": "desc",
        })
        status = str(j.get("status") or "")
        if status == "013":
            break
        if status != "000":
            raise RuntimeError(j.get("message") or status)
        total_page = int(j.get("total_page") or 1)
        for x in j.get("list") or []:
            row = _dart_row(x, code_override=code)
            if row:
                items.append(row)
        page += 1
        if page <= total_page:
            time.sleep(0.04)
    uniq = {(x.get("date"), x.get("title"), x.get("url")): x for x in items}
    rows = sorted(uniq.values(), key=lambda x: (x.get("date") or "", x.get("title") or ""), reverse=True)
    payload = {
        "ok": True,
        "market": "KR",
        "code": code,
        "corp_name": corp[1],
        "months": months,
        "items": rows,
        "count": len(rows),
        "source": "DART 공식 · 종목별 3개월",
        "updated_at": now,
    }
    _DART_STOCK_CACHE[key] = (now, payload)
    return payload


def _us_stock_history(code: str, months: int = 3) -> dict:
    cutoff = (datetime.now(_core.KST).date() - timedelta(days=max(1, months) * 31)).isoformat()
    try:
        rows = list(_v343._sec_history_symbol(str(code or "").upper(), cutoff) or [])
    except Exception:
        rows = []
    rows = [x for x in rows if str(x.get("date") or "") >= cutoff]
    rows.sort(key=lambda x: str(x.get("date") or ""), reverse=True)
    return {"ok": True, "market": "US", "code": str(code or "").upper(), "months": months, "items": rows, "count": len(rows), "source": "SEC EDGAR"}


def _load_saved_stock_bars(market: str, code: str) -> list[dict]:
    try:
        raw = _core.store.load_json(f"v344_stock_daily:{market}:{code}", {}) or {}
        rows = raw.get("bars") if isinstance(raw, dict) else []
        return list(rows or [])[-120:]
    except Exception:
        return []


def _save_stock_bars(market: str, code: str, bars: list[dict]):
    try:
        _core.store.save_json(f"v344_stock_daily:{market}:{code}", {"version": 1, "saved_at": time.time(), "bars": list(bars or [])[-120:]})
    except Exception:
        pass


def _normalized_daily(rows: list[dict]) -> list[dict]:
    out = []
    seen = set()
    for b in rows or []:
        raw = str(b.get("date") or b.get("time") or "").replace("-", "").replace("/", "")
        if len(raw) != 8 or not raw.isdigit() or raw in seen:
            continue
        close = _n(b.get("close"))
        o = _n(b.get("open")); h = _n(b.get("high")); l = _n(b.get("low"))
        # A candle is chartable only when the upstream supplied real O/H/L/C.
        # Never turn close-only history into a fake flat candle.
        if min(o, h, l, close) <= 0 or h < max(o, close) or l > min(o, close):
            continue
        seen.add(raw)
        out.append({"time": raw, "open": o, "high": h, "low": l, "close": close, "volume": _n(b.get("volume"))})
    out.sort(key=lambda x: x["time"])
    return out


def _previous_weekday(d):
    d = d - timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def _expected_trade_date(market: str) -> str:
    """Expected date for an in-progress official daily candle.

    v34.5 switched KR to today's date at 08:00 because NXT had opened.  That
    mixed an alternative-trading-system quote into a KRX-style daily candle.
    Daily candles now follow the regular cash session only.
    """
    market = "US" if str(market).upper() == "US" else "KR"
    now_kst = datetime.now(_core.KST)
    if market == "KR":
        d = now_kst.date()
        if d.weekday() >= 5:
            while d.weekday() >= 5:
                d -= timedelta(days=1)
        elif now_kst.hour * 60 + now_kst.minute < 9 * 60:
            d = _previous_weekday(d)
        return d.strftime("%Y%m%d")

    ny = now_kst.astimezone(ZoneInfo("America/New_York"))
    d = ny.date()
    if d.weekday() >= 5:
        while d.weekday() >= 5:
            d -= timedelta(days=1)
    elif ny.hour * 60 + ny.minute < 9 * 60 + 30:
        d = _previous_weekday(d)
    return d.strftime("%Y%m%d")


def _regular_cash_open(market: str) -> bool:
    market = "US" if str(market).upper() == "US" else "KR"
    now = datetime.now(_core.KST)
    if market == "KR":
        mins = now.hour * 60 + now.minute
        return now.weekday() < 5 and 9 * 60 <= mins <= 15 * 60 + 30
    ny = now.astimezone(ZoneInfo("America/New_York"))
    mins = ny.hour * 60 + ny.minute
    return ny.weekday() < 5 and 9 * 60 + 30 <= mins <= 16 * 60


def _daily_bars(market: str, code: str, days: int = 30) -> tuple[list[dict], str]:
    market = "US" if str(market).upper() == "US" else "KR"
    code = str(code or "").upper().strip()
    days = max(20, min(60, int(days or 30)))
    q = _core.feed.q(market, code)
    saved = _normalized_daily(_load_saved_stock_bars(market, code))
    if saved and not list(getattr(q, "daily_bars", []) or []):
        try:
            q.set_daily_bars([{"date": x["time"], **{k: x[k] for k in ("open", "high", "low", "close", "volume")}} for x in saved])
        except Exception:
            pass
    source = "NH 일봉 캐시"
    key = f"{market}:{code}"
    now = time.time()
    current = _normalized_daily(list(getattr(q, "daily_bars", []) or []))
    latest = current[-1]["time"] if current else ""
    expected = _expected_trade_date(market)
    if (len(current) < days or latest < expected) and now - _STOCK_ATTEMPT.get(key, 0) >= 90:
        _STOCK_ATTEMPT[key] = now
        try:
            fetched = _core.feed.ensure_daily_bars(market, code, max(days, 30), force=True)
            current = _normalized_daily(fetched)
            if current:
                source = "NH 공식 일봉"
        except Exception:
            pass
    if not current:
        current = saved
        source = "저장된 NH 일봉"

    # Only the regular cash session may update today's provisional candle.
    # NXT pre/after-market and US extended-hours quotes stay out of official 1D.
    quote_day = ""
    try:
        if float(getattr(q, "updated_at", 0) or 0) > 0:
            quote_day = datetime.fromtimestamp(float(q.updated_at), _core.KST)
            if market == "US":
                quote_day = quote_day.astimezone(ZoneInfo("America/New_York"))
            quote_day = quote_day.strftime("%Y%m%d")
    except Exception:
        quote_day = ""
    if _regular_cash_open(market) and quote_day == expected and _n(getattr(q, "price", 0)) > 0 and _n(getattr(q, "open", 0)) > 0:
        lows = [x for x in (_n(q.low), _n(q.open), _n(q.price)) if x > 0]
        live = {
            "time": expected,
            "open": _n(q.open),
            "high": max(_n(q.high), _n(q.open), _n(q.price)),
            "low": min(lows) if lows else _n(q.price),
            "close": _n(q.price),
            "volume": _n(q.volume),
        }
        by = {x["time"]: x for x in current}
        by[expected] = live
        current = [by[k] for k in sorted(by)]
        source = source + " + 정규장 현재값"
    current = current[-days:]
    if current:
        _save_stock_bars(market, code, current)
    return current, source


def _apply_stock_meta(market: str, code: str):
    q = _core.feed.q(market, code)
    try:
        fn = (_runtime_ns or {}).get("_ensure_search_catalog")
        catalog = fn(market) if callable(fn) else {}
        meta = catalog.get(code) or {}
        if meta:
            q.name = str(meta.get("name") or q.name or code)
            q.sector = str(meta.get("sector") or q.sector or "")
    except Exception:
        pass
    return q


def _stock_payload(market: str, code: str, timeframe: str, days: int = 30) -> dict:
    market = "US" if str(market).upper() == "US" else "KR"
    code = str(code or "").upper().strip()
    tf = str(timeframe or "1d").lower()
    q = _apply_stock_meta(market, code)
    try:
        d = dict(_core.stock_detail(market, code, timeframe=tf))
    except Exception:
        d = {"market": market, "code": code, "name": q.name or code, "sector": q.sector or "", "price": q.price, "scores": {}, "analysis": None, "flow": {}, "events": []}
    d["name"] = q.name or d.get("name") or code
    d["sector"] = q.sector or d.get("sector") or ""
    if tf in ("1d", "d", "day", "일봉"):
        bars, source = _daily_bars(market, code, days)
        d["bars"] = bars
        d["chart_source"] = source
        d["chart_days"] = len(bars)
        d["default_timeframe"] = "1d"
        d["chart_last_date"] = bars[-1]["time"] if bars else ""
        d["chart_expected_date"] = _expected_trade_date(market)
        d["chart_regular_session_only"] = True
        if _n(d.get("price")) <= 0 and bars:
            d["price"] = bars[-1]["close"]
            d["price_display_source"] = "최근 공식 종가"
        else:
            d["price_display_source"] = "현재가"
    try:
        hist = _dart_stock_history(code, 3) if market == "KR" else _us_stock_history(code, 3)
        d["events"] = list(hist.get("items") or [])
        d["event_history_months"] = 3
        d["event_history_source"] = hist.get("source")
        d["event_history_status"] = hist.get("status") or ""
    except Exception as exc:
        d["event_history_error"] = str(exc)[:180]
    return d


def _investor_rows(code: str) -> list[dict]:
    q = _core.feed.q("KR", str(code or "").upper().strip())
    rows = list(getattr(q, "investor_daily", []) or [])[-20:]
    clean = []
    seen = set()
    for r in rows:
        date = _iso_date(r.get("date"))
        if not date or date in seen:
            continue
        seen.add(date)
        clean.append({
            "date": date,
            "foreign": _n(r.get("foreign")),
            "institution": _n(r.get("institution")),
            "person": _n(r.get("person")),
            "program": _n(r.get("program")),
        })
    clean.sort(key=lambda x: x["date"])
    return clean[-20:]


def _refresh_investor(code: str):
    code = str(code or "").upper().strip()
    if not code:
        return
    with _LOCK:
        if code in _INVESTOR_REFRESHING:
            return
        _INVESTOR_REFRESHING.add(code)
        _INVESTOR_ATTEMPT[code] = time.time()
    try:
        from nhplug import call
        last = None
        for market_cd in _core.feed._market_order():
            try:
                data = call("/krstock/quote/v1/currentInvestor", {
                    "market_cd": market_cd, "iem_cd": code, "array_cnt": "20"
                })
                _core.feed._apply_investor(code, data)
                _core.feed.investor_updated_at = time.time()
                last = None
                break
            except Exception as exc:
                last = exc
        if last is not None:
            raise last
    except Exception:
        pass
    finally:
        with _LOCK:
            _INVESTOR_REFRESHING.discard(code)


def _investor_payload(code: str) -> dict:
    code = str(code or "").upper().strip()
    rows = _investor_rows(code)
    now = time.time()
    with _LOCK:
        refreshing = code in _INVESTOR_REFRESHING
        last_attempt = float(_INVESTOR_ATTEMPT.get(code, 0) or 0)
    if len(rows) < 20 and not refreshing and now - last_attempt >= 60:
        threading.Thread(target=_refresh_investor, args=(code,), daemon=True).start()
        refreshing = True
    sums = {k: sum(_n(r.get(k)) for r in rows) for k in ("foreign", "institution", "person", "program")}
    denom = sum(abs(sums[k]) for k in ("foreign", "institution", "person")) or 0.0
    shares = {k: (sums[k] / denom * 100.0 if denom else 0.0) for k in ("foreign", "institution", "person")}
    return {
        "ok": True, "market": "KR", "code": code, "days": len(rows), "items": rows,
        "sums": sums, "share_pct": shares, "source": "NHPLUG currentInvestor",
        "window": "최근 20거래일", "refreshing": refreshing,
        "updated_at": float(getattr(_core.feed, "investor_updated_at", 0) or 0),
    }


def _index_status_label(key: str, open_now: bool) -> str:
    key = str(key or "").lower()
    if open_now:
        return "정규장 거래중" if key in ("kospi", "kosdaq", "sp500", "nasdaq", "sox") else "선물 거래중"
    if key in ("kospi", "kosdaq"):
        return "KRX 정규장 종료/휴장"
    if key in ("sp500", "nasdaq", "sox"):
        return "미국 정규장 종료/휴장"
    return "선물 휴장/정산시간"


def _index_payload(market: str, key: str, days: int = 60) -> dict:
    market = "US" if str(market or "KR").upper() == "US" else "KR"
    key = str(key or "").lower().strip()
    allowed = {
        "KR": {"kospi", "kosdaq", "kospi_night", "nasdaq_future", "sox"},
        "US": {"sp500", "nasdaq", "nasdaq_future", "sox"},
    }
    if key not in allowed[market]:
        return {"ok": False, "market": market, "key": key, "error": "index not available in this market mode", "bars": []}
    item = dict(_core.feed.market_item(key) or {})
    bars = _normalized_daily(list(_core.feed.market_bars(key, "1d") or []))[-max(20, min(120, int(days or 60))):]
    now = time.time()
    if key in ("kospi", "kosdaq") and (not bars or now - float(getattr(_core.feed, "market_daily_updated_at", {}).get(key, 0) or 0) > 900):
        if now - _INDEX_ATTEMPT.get(key, 0) >= 60:
            _INDEX_ATTEMPT[key] = now
            try:
                _core.feed.refresh_market_daily(key, force=not bool(bars))
            except Exception:
                pass
    daily_source = str(getattr(_core.feed, "market_daily_source", {}).get(key, "") or "")
    daily_error = str(getattr(_core.feed, "market_daily_error", {}).get(key, "") or "")
    quote_source = str(item.get("source") or "")
    open_now = bool(_core.feed.market_open_for_key(key))
    valid = bool(bars) and all(min(_n(x.get("open")), _n(x.get("high")), _n(x.get("low")), _n(x.get("close"))) > 0 for x in bars)
    last_date = bars[-1]["time"] if bars else ""
    last_close = bars[-1]["close"] if bars else None
    label = item.get("label") or {
        "kospi": "코스피", "kosdaq": "코스닥", "sp500": "S&P500", "nasdaq": "나스닥",
        "sox": "필라델피아 반도체지수", "kospi_night": "코스피 야간선물", "nasdaq_future": "나스닥 선물",
    }.get(key, key)
    return {
        "ok": True, "market": market, "key": key, "label": label,
        "value": item.get("value"), "change": item.get("change"), "change_pct": item.get("change_pct"),
        "quote_status": item.get("status") or "", "quote_source": quote_source, "quote_asof": item.get("asof") or "",
        "market_open": open_now, "market_status": _index_status_label(key, open_now),
        "bars": bars, "bar_count": len(bars), "chart_valid_ohlc": valid,
        "chart_source": daily_source or quote_source or "공식 데이터", "chart_error": daily_error,
        "chart_last_date": last_date, "chart_last_close": last_close,
        "chart_is_live_quote": False,
        "note": "현재 지수값과 일봉 OHLC는 분리 표시합니다. 일봉은 실제 O/H/L/C가 있는 공식 데이터만 사용합니다.",
        "flow_supported": market == "KR" and key in ("kospi", "kosdaq", "kospi_night"),
    }


def _session_payload() -> dict:
    now = datetime.now(_core.KST)
    default = _core.default_view_market(now)
    nxt = _core.feed.session_state("KR") or {}
    return {
        "ok": True,
        "kst": now.isoformat(),
        "default_view": default,
        "kr_active": bool(_core.trading_window(now) == "KR"),
        "us_active": bool(_core.trading_window(now) == "US"),
        "nxt": nxt,
        "kr_close_label": "장 종료 · NXT 거래 종료",
    }


def install(ns: dict):
    global _INSTALLED, _core, _v343, _runtime_ns
    if _INSTALLED:
        return
    _INSTALLED = True
    _core = ns["core"]
    _runtime_ns = ns
    import v343_features as _v343_mod
    _v343 = _v343_mod

    @_core.app.get("/api/v344/session")
    def v344_session():
        return _session_payload()

    @_core.app.get("/api/v344/disclosures")
    def v344_disclosures(market: str = "KR", months: int = 3, page: int = 1, page_size: int = 50):
        market = str(market or "KR").upper()
        if market == "US":
            try:
                d = dict(_v343._us_history_page(max(1, int(page)), max(10, min(100, int(page_size)))))
                cutoff = (datetime.now(_core.KST).date() - timedelta(days=max(1, min(3, int(months))) * 31)).isoformat()
                rows = [x for x in list(d.get("items") or []) if str(x.get("date") or "") >= cutoff]
                d.update({"items": rows, "months": min(3, int(months or 3)), "source": "SEC EDGAR", "scope": d.get("scope") or "현재 추적 종목"})
                return d
            except Exception as exc:
                return {"ok": False, "market": "US", "items": [], "status": str(exc)[:180]}
        try:
            return _dart_market_page(months, page, page_size)
        except Exception as exc:
            return {"ok": False, "market": "KR", "items": [], "status": str(exc)[:180], "source": "DART 공식"}

    @_core.app.get("/api/v344/disclosures/{market}/{code}")
    def v344_stock_disclosures(market: str, code: str, months: int = 3):
        try:
            return _dart_stock_history(code, months) if str(market).upper() == "KR" else _us_stock_history(code, months)
        except Exception as exc:
            return {"ok": False, "market": str(market).upper(), "code": str(code).upper(), "items": [], "status": str(exc)[:180]}

    @_core.app.get("/api/v344/stock/{market}/{code}")
    def v344_stock(market: str, code: str, timeframe: str = "1d", days: int = 30):
        return _stock_payload(market, code, timeframe, days)

    @_core.app.get("/api/v344/investor-stock/{code}")
    def v344_investor_stock(code: str):
        return _investor_payload(code)

    @_core.app.get("/api/v344/index/{market}/{key}")
    def v344_index(market: str, key: str, days: int = 60):
        return _index_payload(market, key, days)

    @_core.app.get("/api/v344/diagnostics/{market}/{code}")
    def v344_diagnostics(market: str, code: str):
        market2 = "US" if str(market).upper() == "US" else "KR"
        code2 = str(code or "").upper().strip()
        q = _core.feed.q(market2, code2)
        rows = _normalized_daily(list(getattr(q, "daily_bars", []) or []))
        saved = _normalized_daily(_load_saved_stock_bars(market2, code2))
        return {
            "ok": True, "market": market2, "code": code2,
            "memory_daily_bars": len(rows), "saved_daily_bars": len(saved),
            "memory_last": rows[-1]["time"] if rows else "",
            "saved_last": saved[-1]["time"] if saved else "",
            "expected": _expected_trade_date(market2),
            "dart_key": bool(_dart_key()),
            "dart_market_cache": len(_DART_PAGE_CACHE),
            "dart_stock_cache": len(_DART_STOCK_CACHE),
        }


def status_snapshot() -> dict:
    return {
        "installed": _INSTALLED,
        "dart_market_cache": len(_DART_PAGE_CACHE),
        "dart_stock_cache": len(_DART_STOCK_CACHE),
        "stock_daily_attempts": len(_STOCK_ATTEMPT),
        "investor_attempts": len(_INVESTOR_ATTEMPT),
        "investor_refreshing": len(_INVESTOR_REFRESHING),
        "index_refresh_attempts": len(_INDEX_ATTEMPT),
    }
