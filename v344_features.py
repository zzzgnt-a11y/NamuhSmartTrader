from __future__ import annotations

import calendar
import threading
import time
from datetime import datetime, timedelta
from typing import Any

import requests

_INSTALLED = False
_core = None
_v343 = None
_LOCK = threading.RLock()
_DART_PAGE_CACHE: dict[tuple, tuple[float, dict]] = {}
_DART_STOCK_CACHE: dict[tuple, tuple[float, dict]] = {}
_STOCK_ATTEMPT: dict[str, float] = {}


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
        if close <= 0:
            continue
        o = _n(b.get("open")) or close
        h = _n(b.get("high")) or close
        l = _n(b.get("low")) or close
        if min(o, h, l, close) <= 0:
            continue
        seen.add(raw)
        out.append({"time": raw, "open": o, "high": max(h, o, close), "low": min(l, o, close), "close": close, "volume": _n(b.get("volume"))})
    out.sort(key=lambda x: x["time"])
    return out


def _expected_trade_date(market: str) -> str:
    now = datetime.now(_core.KST)
    if market == "US":
        try:
            return str(_core.feed._expected_us_trade_date(now) or "").replace("-", "")[:8]
        except Exception:
            if now.hour < 6:
                now -= timedelta(days=1)
    else:
        # Before NXT opens, the latest completed KR candle is the previous
        # trading weekday. Weekends also resolve to the most recent Friday.
        if now.weekday() < 5 and now.hour * 60 + now.minute < 480:
            now -= timedelta(days=1)
    while now.weekday() >= 5:
        now -= timedelta(days=1)
    return now.strftime("%Y%m%d")


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
    # Merge the latest NH quote into today's candle when available. This makes
    # the closed-session chart include the final known value even if the daily
    # history endpoint has not rolled over yet.
    quote_day = ""
    try:
        if float(getattr(q, "updated_at", 0) or 0) > 0:
            quote_day = datetime.fromtimestamp(float(q.updated_at), _core.KST).strftime("%Y%m%d")
    except Exception:
        quote_day = ""
    if quote_day == expected and _n(getattr(q, "price", 0)) > 0 and _n(getattr(q, "open", 0)) > 0:
        d = expected
        live = {
            "time": d,
            "open": _n(q.open),
            "high": max(_n(q.high), _n(q.open), _n(q.price)),
            "low": min(x for x in (_n(q.low), _n(q.open), _n(q.price)) if x > 0),
            "close": _n(q.price),
            "volume": _n(q.volume),
        }
        by = {x["time"]: x for x in current}
        by[d] = live
        current = [by[k] for k in sorted(by)]
        source = source + " + 최신 NH 값"
    current = current[-days:]
    if current:
        _save_stock_bars(market, code, current)
    return current, source


def _stock_payload(market: str, code: str, timeframe: str, days: int = 30) -> dict:
    market = "US" if str(market).upper() == "US" else "KR"
    code = str(code or "").upper().strip()
    tf = str(timeframe or "1d").lower()
    _core.feed.q(market, code)  # detail page can warm an on-demand symbol
    try:
        d = dict(_core.stock_detail(market, code, timeframe=tf))
    except Exception:
        q = _core.feed.q(market, code)
        d = {"market": market, "code": code, "name": q.name or code, "sector": q.sector or "", "price": q.price, "scores": {}, "analysis": None, "flow": {}, "events": []}
    if tf in ("1d", "d", "day", "일봉"):
        bars, source = _daily_bars(market, code, days)
        d["bars"] = bars
        d["chart_source"] = source
        d["chart_days"] = len(bars)
        d["default_timeframe"] = "1d"
    try:
        hist = _dart_stock_history(code, 3) if market == "KR" else _us_stock_history(code, 3)
        d["events"] = list(hist.get("items") or [])
        d["event_history_months"] = 3
        d["event_history_source"] = hist.get("source")
    except Exception as exc:
        d["event_history_error"] = str(exc)[:180]
    return d


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
    global _INSTALLED, _core, _v343
    if _INSTALLED:
        return
    _INSTALLED = True
    _core = ns["core"]
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


def status_snapshot() -> dict:
    return {
        "installed": _INSTALLED,
        "dart_market_cache": len(_DART_PAGE_CACHE),
        "dart_stock_cache": len(_DART_STOCK_CACHE),
        "stock_daily_attempts": len(_STOCK_ATTEMPT),
    }
