from __future__ import annotations

import re
import threading
import os
import time
from collections import deque
from datetime import datetime, timedelta
from types import MethodType
from typing import Any

import requests

_INSTALLED = False
_core = None
_ns = None

_LOCK = threading.RLock()
_FLOW_STATE_KEY = "v343_market_flow"
_US_HISTORY_KEY = "v343_us_disclosure_history"

_MARKET_FLOW: dict[str, dict] = {}
_MARKET_FLOW_UPDATED = 0.0
_MARKET_FLOW_REFRESHING = False

_DART_PAGE_CACHE: dict[tuple, tuple[float, dict]] = {}
_DART_EARN_CACHE: dict[str, tuple[float, dict]] = {}
_DART_EARN_REFRESHING: set[str] = set()

_US_HISTORY: list[dict] = []
_US_HISTORY_UPDATED = 0.0
_US_HISTORY_REFRESHING = False

_BG_STARTED = False
_BG_LOCK = threading.Lock()

_EARN_RE_KR = re.compile(r"(사업보고서|반기보고서|분기보고서|영업\s*\(잠정\)\s*실적|잠정실적|매출액\s*또는\s*손익구조)", re.I)
_US_EARN_FORMS = {"10-Q", "10-K", "20-F", "40-F"}


def _n(v: Any) -> float:
    try:
        return float(str(v or "0").replace(",", "").replace("+", "").strip())
    except Exception:
        return 0.0


def _digits_date(v: Any) -> str:
    s = re.sub(r"\D", "", str(v or ""))
    if len(s) >= 8:
        return s[:8]
    return ""


def _iso_date(v: Any) -> str:
    s = _digits_date(v)
    if len(s) == 8:
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    raw = str(v or "")
    if len(raw) >= 10 and raw[4:5] == "-" and raw[7:8] == "-":
        return raw[:10]
    return ""


def _latest_trade_date(rows: list[dict]) -> str:
    dates = [str(x.get("date") or "") for x in rows if x.get("date")]
    return max(dates) if dates else ""


def _load_persisted():
    global _MARKET_FLOW, _MARKET_FLOW_UPDATED, _US_HISTORY, _US_HISTORY_UPDATED
    try:
        raw = _core.store.load_json(_FLOW_STATE_KEY, {}) or {}
        if isinstance(raw, dict):
            data = raw.get("markets")
            if isinstance(data, dict):
                _MARKET_FLOW = data
                _MARKET_FLOW_UPDATED = float(raw.get("updated_at") or 0)
    except Exception:
        pass
    try:
        raw = _core.store.load_json(_US_HISTORY_KEY, {}) or {}
        if isinstance(raw, dict) and isinstance(raw.get("items"), list):
            _US_HISTORY = list(raw.get("items") or [])[:5000]
            _US_HISTORY_UPDATED = float(raw.get("updated_at") or 0)
    except Exception:
        pass


def _save_market_flow():
    try:
        _core.store.save_json(_FLOW_STATE_KEY, {
            "version": 1,
            "updated_at": _MARKET_FLOW_UPDATED,
            "markets": _MARKET_FLOW,
        })
    except Exception:
        pass


def _save_us_history():
    try:
        _core.store.save_json(_US_HISTORY_KEY, {
            "version": 1,
            "updated_at": _US_HISTORY_UPDATED,
            "items": _US_HISTORY[:5000],
        })
    except Exception:
        pass


def _parse_market_flow_output(rows: list[dict]) -> list[dict]:
    out = []
    for r in rows or []:
        d = _iso_date(r.get("TRD_DD") or r.get("BAS_DD") or r.get("date"))
        if not d:
            continue
        # KRX MDCSTAT02202 general view: 기관합계, 기타법인, 개인, 외국인합계, 전체
        out.append({
            "date": d,
            "institution": _n(r.get("TRDVAL1") or r.get("institution")),
            "other_corp": _n(r.get("TRDVAL2") or r.get("other_corp")),
            "person": _n(r.get("TRDVAL3") or r.get("person")),
            "foreign": _n(r.get("TRDVAL4") or r.get("foreign")),
            "total": _n(r.get("TRDVAL_TOT") or r.get("total")),
        })
    by_date = {x["date"]: x for x in out}
    return [by_date[k] for k in sorted(by_date)][-31:]


def _fetch_market_flow_one(key: str, mkt_id: str) -> dict:
    end = datetime.now(_core.KST).date()
    start = end - timedelta(days=45)
    payload = {
        "bld": "dbms/MDC/STAT/standard/MDCSTAT02202",
        "strtDd": start.strftime("%Y%m%d"),
        "endDd": end.strftime("%Y%m%d"),
        "mktId": mkt_id,
        "etf": "",
        "etn": "",
        "elw": "",
        "inqTpCd": "2",
        "trdVolVal": "2",  # 거래대금
        "askBid": "3",     # 순매수
        "money": "1",
        "csvxls_isNo": "false",
    }
    j = _core.feed._krx_post(payload)
    rows = j.get("output") or j.get("OutBlock_1") or j.get("output1") or []
    daily = _parse_market_flow_output(rows)
    latest = daily[-1] if daily else {}
    return {
        "key": key,
        "label": "KOSPI" if key == "kospi" else "KOSDAQ",
        "source": "KRX 투자자별 순매수 거래대금",
        "asof": latest.get("date") or "",
        "latest": {
            "foreign": latest.get("foreign"),
            "institution": latest.get("institution"),
            "person": latest.get("person"),
        } if latest else {},
        "daily": daily,
        "days": len(daily),
        "ok": bool(daily),
    }


def _refresh_market_flow(force: bool = False):
    global _MARKET_FLOW, _MARKET_FLOW_UPDATED, _MARKET_FLOW_REFRESHING
    with _LOCK:
        if _MARKET_FLOW_REFRESHING:
            return
        if not force and _MARKET_FLOW_UPDATED and time.time() - _MARKET_FLOW_UPDATED < 120:
            return
        _MARKET_FLOW_REFRESHING = True
    try:
        new = {}
        errors = {}
        for key, mkt in (("kospi", "STK"), ("kosdaq", "KSQ")):
            try:
                row = _fetch_market_flow_one(key, mkt)
                if row.get("ok"):
                    new[key] = row
                else:
                    errors[key] = "KRX 수급 응답 없음"
            except Exception as exc:
                errors[key] = str(exc)[:180]
        with _LOCK:
            if new:
                merged = dict(_MARKET_FLOW)
                merged.update(new)
                for k, err in errors.items():
                    if k in merged:
                        merged[k] = {**merged[k], "error": err}
                _MARKET_FLOW = merged
                _MARKET_FLOW_UPDATED = time.time()
                _save_market_flow()
            elif errors:
                for k, err in errors.items():
                    if k in _MARKET_FLOW:
                        _MARKET_FLOW[k] = {**_MARKET_FLOW[k], "error": err}
    finally:
        with _LOCK:
            _MARKET_FLOW_REFRESHING = False


def _dart_key() -> str:
    try:
        return str(getattr(_core.events, "api_key", "") or "").strip()
    except Exception:
        return ""


def _dart_list_request(params: dict) -> dict:
    key = _dart_key()
    if not key:
        return {"status": "NO_KEY", "message": "DART_API_KEY 미설정", "list": []}
    p = {"crtfc_key": key, **params}
    r = requests.get("https://opendart.fss.or.kr/api/list.json", params=p, timeout=18)
    r.raise_for_status()
    return r.json()


def _classify_history_title(title: str) -> tuple[str, str, float, bool]:
    try:
        from events import classify_event
        c = classify_event(title)
        sent = str(c.get("sentiment") or "neutral")
        blocked = bool(c.get("blocked"))
        score = 5.0 if sent == "positive" else -5.0 if sent == "negative" else 0.0
        return sent, str(c.get("label") or "중립"), score, blocked
    except Exception:
        return "neutral", "중립", 0.0, False


def _dart_history_page(page: int, page_size: int, months: int = 6) -> dict:
    """Return a single logical six-month DART stream.

    OpenDART limits searches without corp_code to at most three months, so the
    six-month window is split into two official requests and paginated as one
    logical list.  This prevents the old >3-month request from silently failing.
    """
    today = datetime.now(_core.KST).date()
    months = max(1, min(6, int(months or 6)))
    oldest = today - timedelta(days=months * 31)
    split = today - timedelta(days=92)
    windows = [(max(split + timedelta(days=1), oldest), today)]
    if oldest <= split:
        windows.append((oldest, split))
    size = max(10, min(100, int(page_size or 50)))
    p = max(1, int(page or 1))
    now = time.time()
    cache_key = ("six", p, size, oldest.isoformat(), today.isoformat())
    cached = _DART_PAGE_CACHE.get(cache_key)
    if cached and now - cached[0] < 600:
        return cached[1]

    metas = []
    for ws, we in windows:
        meta_key = ("meta", size, ws.isoformat(), we.isoformat())
        mc = _DART_PAGE_CACHE.get(meta_key)
        if mc and now - mc[0] < 600:
            meta = mc[1]
        else:
            j = _dart_list_request({
                "bgn_de": ws.strftime("%Y%m%d"), "end_de": we.strftime("%Y%m%d"),
                "page_no": "1", "page_count": str(size), "sort": "date", "sort_mth": "desc",
            })
            status = str(j.get("status") or "")
            if status not in ("000", "013"):
                meta = {"ok": False, "total_page": 0, "total_count": 0, "status": j.get("message") or status}
            else:
                meta = {"ok": True, "total_page": int(j.get("total_page") or 1),
                        "total_count": int(j.get("total_count") or 0), "first_json": j}
            _DART_PAGE_CACHE[meta_key] = (now, meta)
        metas.append((ws, we, meta))

    total_pages = sum(int(x[2].get("total_page") or 0) for x in metas) or 1
    total_count = sum(int(x[2].get("total_count") or 0) for x in metas)
    target = p
    chosen = None
    local_page = 1
    passed = 0
    for ws, we, meta in metas:
        pages = int(meta.get("total_page") or 0)
        if target <= passed + pages:
            chosen = (ws, we, meta)
            local_page = target - passed
            break
        passed += pages
    if chosen is None:
        payload = {"ok": True, "market": "KR", "months": months, "page": p, "page_size": size,
                   "total_count": total_count, "total_page": total_pages, "items": [],
                   "source": "DART 공식", "updated_at": now}
        _DART_PAGE_CACHE[cache_key] = (now, payload)
        return payload

    ws, we, meta = chosen
    if local_page == 1 and isinstance(meta.get("first_json"), dict):
        j = meta["first_json"]
    else:
        j = _dart_list_request({
            "bgn_de": ws.strftime("%Y%m%d"), "end_de": we.strftime("%Y%m%d"),
            "page_no": str(local_page), "page_count": str(size), "sort": "date", "sort_mth": "desc",
        })
    items = []
    for x in j.get("list") or []:
        stock_code = str(x.get("stock_code") or "").strip()
        if not (len(stock_code) == 6 and stock_code.isdigit()):
            continue
        title = str(x.get("report_nm") or "").strip()
        sent, label, score, blocked = _classify_history_title(title)
        rcp = str(x.get("rcept_no") or "")
        items.append({
            "market": "KR", "code": stock_code, "corp_name": str(x.get("corp_name") or stock_code),
            "title": title, "date": _iso_date(x.get("rcept_dt")), "time": "", "source": "DART 공식",
            "url": f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcp}" if rcp else "",
            "sentiment": sent, "label": label, "score": score, "blocked": blocked,
            "form": str(x.get("corp_cls") or ""),
        })
    payload = {"ok": True, "market": "KR", "months": months, "page": p, "page_size": size,
               "total_count": total_count, "total_page": total_pages, "items": items,
               "source": "DART 공식", "updated_at": now, "window_split": "3개월 + 이전 3개월"}
    _DART_PAGE_CACHE[cache_key] = (now, payload)
    return payload

def _tracked_us_codes() -> list[str]:
    out = []
    try:
        out.extend(list(_core.feed.fixed.get("US") or []))
    except Exception:
        pass
    try:
        out.extend(list(_core.feed.code_lists.get("US") or []))
    except Exception:
        pass
    try:
        out.extend(list(_core.feed.quotes_for("US").keys()))
    except Exception:
        pass
    try:
        with _core.cache_lock:
            for row in list((_core.CACHE.get("US") or {}).get("scalp") or [])[:30]:
                out.append(str(row.get("code") or ""))
    except Exception:
        pass
    clean = []
    seen = set()
    for c in out:
        c = str(c or "").upper().strip()
        if c and c not in seen:
            seen.add(c)
            clean.append(c)
    return clean[:60]


def _sec_meta():
    try:
        _ns["_load_sec_tickers"]()
        return _ns.get("_SEC_TICKERS") or {}
    except Exception:
        return {}


def _sec_history_symbol(symbol: str, cutoff: str) -> list[dict]:
    meta = _sec_meta().get(symbol.upper())
    if not meta or not meta.get("cik"):
        return []
    cik = int(meta["cik"])
    sess = _ns.get("_SEC_SESSION")
    if sess is None:
        return []
    url = f"https://data.sec.gov/submissions/CIK{cik:010d}.json"
    r = sess.get(url, timeout=18)
    r.raise_for_status()
    recent = (r.json().get("filings") or {}).get("recent") or {}
    forms = recent.get("form") or []
    dates = recent.get("filingDate") or []
    accs = recent.get("accessionNumber") or []
    docs = recent.get("primaryDocument") or []
    descs = recent.get("primaryDocDescription") or []
    out = []
    n = max(len(forms), len(dates))
    for i in range(n):
        date = str(dates[i] if i < len(dates) else "")
        if not date or date < cutoff:
            continue
        form = str(forms[i] if i < len(forms) else "")
        acc = str(accs[i] if i < len(accs) else "")
        doc = str(docs[i] if i < len(docs) else "")
        desc = str(descs[i] if i < len(descs) else "")
        archive = ""
        if acc and doc:
            archive = f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc.replace('-', '')}/{doc}"
        out.append({
            "market": "US", "code": symbol.upper(), "corp_name": meta.get("name") or symbol.upper(),
            "title": desc or f"SEC {form}", "form": form, "date": date, "time": "",
            "source": "SEC EDGAR", "url": archive or url, "sentiment": "neutral",
            "label": form or "SEC", "score": 0.0, "blocked": False,
        })
    return out


def _refresh_us_history(force: bool = False):
    global _US_HISTORY, _US_HISTORY_UPDATED, _US_HISTORY_REFRESHING
    with _LOCK:
        if _US_HISTORY_REFRESHING:
            return
        if not force and _US_HISTORY_UPDATED and time.time() - _US_HISTORY_UPDATED < 900:
            return
        _US_HISTORY_REFRESHING = True
    try:
        cutoff = (datetime.now(_core.KST).date() - timedelta(days=186)).isoformat()
        rows = []
        for symbol in _tracked_us_codes():
            try:
                rows.extend(_sec_history_symbol(symbol, cutoff))
            except Exception:
                pass
            time.sleep(0.12)
        rows.sort(key=lambda e: (str(e.get("date") or ""), str(e.get("code") or "")), reverse=True)
        if rows:
            with _LOCK:
                _US_HISTORY = rows[:5000]
                _US_HISTORY_UPDATED = time.time()
                _save_us_history()
    finally:
        with _LOCK:
            _US_HISTORY_REFRESHING = False


def _us_history_page(page: int, page_size: int) -> dict:
    if not _US_HISTORY_UPDATED or time.time() - _US_HISTORY_UPDATED > 900:
        threading.Thread(target=_refresh_us_history, daemon=True).start()
    with _LOCK:
        rows = list(_US_HISTORY)
        updated = _US_HISTORY_UPDATED
        refreshing = _US_HISTORY_REFRESHING
    p = max(1, page)
    size = max(10, min(100, page_size))
    start = (p - 1) * size
    return {
        "ok": True,
        "market": "US",
        "months": 6,
        "page": p,
        "page_size": size,
        "total_count": len(rows),
        "total_page": max(1, (len(rows) + size - 1) // size),
        "items": rows[start:start + size],
        "source": "SEC EDGAR",
        "updated_at": updated,
        "refreshing": refreshing,
        "scope": "현재 추적/분석 종목",
    }


def _build_kr_earnings_month(year: int, month: int) -> dict:
    key = f"{year:04d}-{month:02d}"
    start = datetime(year, month, 1).date()
    end = (datetime(year + (month == 12), 1 if month == 12 else month + 1, 1).date() - timedelta(days=1))
    items = []
    # A = periodic reports, I = exchange disclosures (includes many preliminary earnings notices).
    for ptype in ("A", "I"):
        page = 1
        total_page = 1
        while page <= min(total_page, 10):
            j = _dart_list_request({
                "bgn_de": start.strftime("%Y%m%d"), "end_de": end.strftime("%Y%m%d"),
                "pblntf_ty": ptype, "page_no": str(page), "page_count": "100",
                "sort": "date", "sort_mth": "desc",
            })
            status = str(j.get("status") or "")
            if status not in ("000", "013"):
                break
            total_page = int(j.get("total_page") or 1)
            for x in j.get("list") or []:
                code = str(x.get("stock_code") or "").strip()
                title = str(x.get("report_nm") or "")
                if not (len(code) == 6 and code.isdigit()) or not _EARN_RE_KR.search(title):
                    continue
                rcp = str(x.get("rcept_no") or "")
                items.append({
                    "market": "KR", "code": code, "name": str(x.get("corp_name") or code),
                    "date": _iso_date(x.get("rcept_dt")), "time": "", "title": title,
                    "source": "DART 공식", "kind": "earnings_filing",
                    "url": f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcp}" if rcp else "",
                })
            page += 1
            time.sleep(0.06)
    uniq = {(x["code"], x["date"], x["title"]): x for x in items}
    items = sorted(uniq.values(), key=lambda x: (x.get("date", ""), x.get("name", "")))
    return {"ok": True, "market": "KR", "year": year, "month": month, "items": items,
            "source": "DART 정기/거래소 실적공시", "official_actual_dates_only": True,
            "updated_at": time.time(), "refreshing": False,
            "scope_note": "공식 실적 관련 공시일 · 미래 발표예정일을 임의 생성하지 않음"}


def _kr_earnings_worker(year: int, month: int):
    key = f"{year:04d}-{month:02d}"
    try:
        payload = _build_kr_earnings_month(year, month)
        _DART_EARN_CACHE[key] = (time.time(), payload)
    except Exception:
        pass
    finally:
        _DART_EARN_REFRESHING.discard(key)


def _kr_earnings_month(year: int, month: int) -> dict:
    key = f"{year:04d}-{month:02d}"
    now = time.time()
    cached = _DART_EARN_CACHE.get(key)
    if cached and now - cached[0] < 3600:
        return cached[1]
    if key not in _DART_EARN_REFRESHING:
        _DART_EARN_REFRESHING.add(key)
        threading.Thread(target=_kr_earnings_worker, args=(year, month), daemon=True).start()
    if cached:
        return {**cached[1], "refreshing": True}
    return {"ok": True, "market": "KR", "year": year, "month": month, "items": [],
            "source": "DART 정기/거래소 실적공시", "official_actual_dates_only": True,
            "updated_at": 0.0, "refreshing": True}

def _us_earnings_month(year: int, month: int) -> dict:
    if not _US_HISTORY_UPDATED or time.time() - _US_HISTORY_UPDATED > 900:
        threading.Thread(target=_refresh_us_history, daemon=True).start()
    prefix = f"{year:04d}-{month:02d}-"
    with _LOCK:
        rows = [x for x in _US_HISTORY if str(x.get("date") or "").startswith(prefix)
                and str(x.get("form") or "").upper() in _US_EARN_FORMS]
        updated = _US_HISTORY_UPDATED
        refreshing = _US_HISTORY_REFRESHING
    items = [{
        "market": "US", "code": x.get("code"), "name": x.get("corp_name") or x.get("code"),
        "date": x.get("date"), "time": "", "title": x.get("title") or x.get("form"),
        "source": "SEC EDGAR", "kind": "earnings_filing", "url": x.get("url") or "",
    } for x in rows]
    return {"ok": True, "market": "US", "year": year, "month": month, "items": items,
            "source": "SEC 10-Q/10-K", "official_actual_dates_only": True,
            "updated_at": updated, "refreshing": refreshing}


def _patch_investor_20d():
    feed = _core.feed
    try:
        import nhfeed as nhmod
    except Exception:
        return

    original_apply = feed._apply_investor

    def apply_20d(self, code, data):
        original_apply(code, data)
        try:
            q = self.q("KR", code)
            objs = list(nhmod.walk(data))
            rows = []
            seen = set()
            for o in objs:
                if not isinstance(o, dict):
                    continue
                if not any(k in o for k in ("frgn_ntby_qty", "invest", "gigwan", "orgn_ntby_qty", "person", "prsn_ntby_qty")):
                    continue
                d = nhmod.normalize_date(o.get("bsop_date1") or o.get("bsop_date") or o.get("date"))
                if not d or d in seen:
                    continue
                seen.add(d)
                rows.append({
                    "date": d,
                    "foreign": nhmod.num(o.get("frgn_ntby_qty") if "frgn_ntby_qty" in o else o.get("invest")),
                    "institution": nhmod.num(o.get("gigwan") if "gigwan" in o else o.get("orgn_ntby_qty")),
                    "person": nhmod.num(o.get("person") if "person" in o else o.get("prsn_ntby_qty")),
                    "program": nhmod.num(o.get("program") if "program" in o else o.get("prgm_ntby_qty")),
                })
            if rows:
                rows.sort(key=lambda x: x["date"])
                q.investor_daily = deque(rows[-20:], maxlen=20)
        except Exception:
            pass

    def investor_loop_20d(self):
        from nhplug import call
        idx = 0
        while not self._stop.is_set():
            codes = self.code_lists["KR"] or self.fixed["KR"]
            if not codes:
                self._stop.wait(1.0)
                continue
            code = codes[idx % len(codes)]
            idx += 1
            err = ""
            for market_cd in self._market_order():
                try:
                    data = call("/krstock/quote/v1/currentInvestor", {
                        "market_cd": market_cd, "iem_cd": code, "array_cnt": "20"
                    })
                    self._apply_investor(code, data)
                    self.investor_updated_at = time.time()
                    err = ""
                    break
                except Exception as exc:
                    err = str(exc)[:200]
                    if "429" in err:
                        time.sleep(1.5)
                        break
            self._stop.wait(.75)

    feed._apply_investor = MethodType(apply_20d, feed)
    feed.investor_loop = MethodType(investor_loop_20d, feed)


def _index_diagnostics() -> dict:
    out = {}
    for key in ("kospi", "kosdaq", "kospi_night"):
        try:
            bars = list(_core.feed.market_bars(key, "1d") or [])
        except Exception:
            bars = []
        valid = 0
        for b in bars:
            if min(_n(b.get("open")), _n(b.get("high")), _n(b.get("low")), _n(b.get("close"))) > 0:
                valid += 1
        source = str(getattr(_core.feed, "market_daily_source", {}).get(key, "") or "")
        error = str(getattr(_core.feed, "market_daily_error", {}).get(key, "") or "")
        item = _core.feed.market_item(key) or {}
        out[key] = {
            "bar_count": len(bars), "valid_ohlc": valid, "ready": bool(bars) and valid == len(bars),
            "first": str(bars[0].get("time") or "") if bars else "",
            "last": str(bars[-1].get("time") or "") if bars else "",
            "daily_source": source, "item_source": item.get("source") or "", "error": error,
        }
    return out


def _flow_loop():
    time.sleep(4)
    while True:
        try:
            _refresh_market_flow()
        except Exception:
            pass
        now = datetime.now(_core.KST)
        mins = now.hour * 60 + now.minute
        active = now.weekday() < 5 and 8 * 60 <= mins <= 16 * 60
        time.sleep(120 if active else 900)


def _us_loop():
    time.sleep(8)
    while True:
        try:
            _refresh_us_history()
        except Exception:
            pass
        time.sleep(900)



# ---------------------------------------------------------------------------
# v34.3 fast caches: persistent index OHLC, cached Coinone candles/BTC,
# NH overseas-futures commodity context, and optional domestic-night investor
# flow discovery.  Every network collector runs outside request/score paths.
# ---------------------------------------------------------------------------

_INDEX_STATE_KEY = "v343_index_daily_bars"
_COMMODITY_STATE_KEY = "v343_commodities"
_NIGHT_FLOW_STATE_KEY = "v343_night_investor_flow"

_COMMODITY_LOCK = threading.RLock()
_COMMODITIES: dict[str, dict] = {}
_COMMODITY_UPDATED = 0.0
_COMMODITY_REFRESHING = False
_COMMODITY_LAST_ATTEMPT = 0.0
_COMMODITY_SYMBOLS: dict[str, dict] = {}
_COMMODITY_SYMBOLS_AT = 0.0

_NIGHT_FLOW: dict = {}
_NIGHT_FLOW_UPDATED = 0.0
_NIGHT_FLOW_REFRESHING = False
_NIGHT_FLOW_LAST_ATTEMPT = 0.0
_NIGHT_SPEC_CACHE: tuple[float, dict] | None = None

_COIN_CHART_LOCK = threading.RLock()
_COIN_CHART_CACHE: dict[tuple[str, str, int], tuple[float, list[dict]]] = {}
_BTC_CACHE: dict = {}
_BTC_UPDATED = 0.0


def _serialize_index_bars() -> dict:
    rows = {}
    for key in ("kospi", "kosdaq", "kospi_night", "nasdaq_future", "sp500", "nasdaq", "sox"):
        try:
            bars = list(_core.feed.market_daily_bars.get(key, []) or [])[-120:]
        except Exception:
            bars = []
        if bars:
            rows[key] = bars
    return rows


def _save_index_bars():
    try:
        _core.store.save_json(_INDEX_STATE_KEY, {
            "version": 1,
            "saved_at": time.time(),
            "bars": _serialize_index_bars(),
            "sources": dict(getattr(_core.feed, "market_daily_source", {}) or {}),
        })
    except Exception:
        pass


def _restore_index_bars():
    try:
        raw = _core.store.load_json(_INDEX_STATE_KEY, {}) or {}
        bars_map = raw.get("bars") if isinstance(raw, dict) else None
        if not isinstance(bars_map, dict):
            return
        for key, bars in bars_map.items():
            if not isinstance(bars, list) or not bars:
                continue
            # _set_market_daily_bars validates/dedupes OHLC before accepting.
            _core.feed._set_market_daily_bars(key, bars)
        sources = raw.get("sources") or {}
        if isinstance(sources, dict):
            try:
                _core.feed.market_daily_source.update({str(k): str(v) for k, v in sources.items() if v})
            except Exception:
                pass
    except Exception:
        pass


def _patch_index_persistence():
    feed = _core.feed
    original = feed._set_market_daily_bars

    def set_and_persist(self, key, bars):
        original(key, bars)
        try:
            if list(self.market_daily_bars.get(str(key).lower(), []) or []):
                _save_index_bars()
        except Exception:
            pass

    feed._set_market_daily_bars = MethodType(set_and_persist, feed)
    _restore_index_bars()


def _flow_enrich(row: dict) -> dict:
    daily = list(row.get("daily") or [])[-31:]
    cum = {k: sum(_n(x.get(k)) for x in daily) for k in ("foreign", "institution", "person")}
    denom = sum(abs(v) for v in cum.values()) or 0.0
    share = {k: (v / denom * 100.0 if denom else 0.0) for k, v in cum.items()}
    return {**row, "cumulative": cum, "share_pct": share, "window": "최근 약 1개월"}


def _save_commodity_state():
    try:
        with _COMMODITY_LOCK:
            payload = {"version": 1, "updated_at": _COMMODITY_UPDATED, "items": _COMMODITIES}
        _core.store.save_json(_COMMODITY_STATE_KEY, payload)
    except Exception:
        pass


def _load_commodity_state():
    global _COMMODITIES, _COMMODITY_UPDATED, _NIGHT_FLOW, _NIGHT_FLOW_UPDATED
    try:
        raw = _core.store.load_json(_COMMODITY_STATE_KEY, {}) or {}
        if isinstance(raw, dict) and isinstance(raw.get("items"), dict):
            _COMMODITIES = dict(raw.get("items") or {})
            _COMMODITY_UPDATED = float(raw.get("updated_at") or 0)
    except Exception:
        pass
    try:
        raw = _core.store.load_json(_NIGHT_FLOW_STATE_KEY, {}) or {}
        if isinstance(raw, dict) and isinstance(raw.get("data"), dict):
            _NIGHT_FLOW = dict(raw.get("data") or {})
            _NIGHT_FLOW_UPDATED = float(raw.get("updated_at") or 0)
    except Exception:
        pass


def _master_rows(frame):
    if frame is None:
        return []
    if hasattr(frame, "to_dict"):
        try:
            return frame.to_dict("records")
        except Exception:
            return []
    return frame if isinstance(frame, list) else []


def _row_text(row: dict) -> str:
    vals = []
    for k, v in (row or {}).items():
        if isinstance(v, (str, int, float)):
            vals.append(str(v))
    return " ".join(vals).upper()


_COMMODITY_DEFS = {
    "wti": {"label": "WTI 원유", "words": ("WTI", "CRUDE OIL", "LIGHT SWEET CRUDE")},
    "gold": {"label": "금", "words": ("GOLD",)},
    "copper": {"label": "구리", "words": ("COPPER",)},
    "silver": {"label": "은", "words": ("SILVER",)},
    "natgas": {"label": "천연가스", "words": ("NATURAL GAS", "NAT GAS")},
    "corn": {"label": "옥수수", "words": ("CORN",)},
    "soybean": {"label": "대두", "words": ("SOYBEAN", "SOYBEANS")},
    "wheat": {"label": "밀", "words": ("WHEAT",)},
}


def _discover_commodity_symbols(force: bool = False) -> dict[str, dict]:
    global _COMMODITY_SYMBOLS, _COMMODITY_SYMBOLS_AT
    now = time.time()
    if _COMMODITY_SYMBOLS and not force and now - _COMMODITY_SYMBOLS_AT < 21600:
        return dict(_COMMODITY_SYMBOLS)
    try:
        from nhplug.instruments import load_master
        rows = _master_rows(load_master("fucode_h"))
    except Exception:
        return dict(_COMMODITY_SYMBOLS)
    found: dict[str, dict] = {}
    for key, cfg in _COMMODITY_DEFS.items():
        cand = []
        for idx, row in enumerate(rows):
            text = _row_text(row)
            if not any(w in text for w in cfg["words"]):
                continue
            # Avoid micro/mini contracts when a standard contract is available.
            penalty = 1000 if any(x in text for x in ("MICRO", " E-MINI", "MINI ")) else 0
            symbol = str(
                row.get("isym") or row.get("InnerSymbol") or row.get("symb") or
                row.get("symbol") or row.get("code") or row.get("iem_cd") or ""
            ).strip().upper()
            exnm = str(
                row.get("exnm") or row.get("ExchCode") or row.get("exchange") or
                row.get("ExchangeCode") or row.get("exch_code") or ""
            ).strip().upper()
            name = str(
                row.get("name") or row.get("ItemName") or row.get("eng_name") or
                row.get("hname") or row.get("symb_name") or cfg["label"]
            ).strip()
            if not symbol:
                continue
            # Master ordering normally places nearer expiries first. Preserve it.
            cand.append((penalty + idx, {"symbol": symbol, "exnm": exnm, "name": name or cfg["label"]}))
        if cand:
            cand.sort(key=lambda x: x[0])
            found[key] = cand[0][1]
    if found:
        _COMMODITY_SYMBOLS = found
        _COMMODITY_SYMBOLS_AT = now
    return dict(_COMMODITY_SYMBOLS)


def _walk_dicts(v):
    if isinstance(v, dict):
        yield v
        for x in v.values():
            yield from _walk_dicts(x)
    elif isinstance(v, list):
        for x in v:
            yield from _walk_dicts(x)


def _pick_num(data, names: tuple[str, ...]) -> float:
    for row in _walk_dicts(data):
        for k in names:
            if k in row and row[k] not in (None, ""):
                return _n(row[k])
    return 0.0


def _pick_text(data, names: tuple[str, ...]) -> str:
    for row in _walk_dicts(data):
        for k in names:
            if k in row and row[k] not in (None, ""):
                return str(row[k]).strip()
    return ""


def _signed(v: float, sign: str) -> float:
    v = abs(float(v or 0))
    return -v if str(sign) in ("4", "5", "8", "9", "-", "▼") else v


def _fetch_one_commodity(key: str, meta: dict) -> dict:
    from nhplug import call
    symbol = str(meta.get("symbol") or "")
    exnm = str(meta.get("exnm") or "")
    if not symbol:
        raise RuntimeError("symbol missing")
    payload = {"iem_cd": symbol}
    if exnm:
        payload["exnm"] = exnm
    d = call("/gbfuture/quote/v1/current", payload)
    price = _pick_num(d, ("last", "ovrs_prpr", "close_prc", "close", "prpr", "price"))
    sign = _pick_text(d, ("sign", "prdy_vrss_sign", "updn_cls"))
    change = _signed(_pick_num(d, ("diff", "prdy_vrss", "change")), sign)
    rate = _signed(_pick_num(d, ("rate", "prdy_ctrt", "change_rate", "change_pct")), sign)
    if not rate and price and change and price - change:
        rate = change / (price - change) * 100.0
    return {
        "key": key,
        "label": _COMMODITY_DEFS[key]["label"],
        "symbol": symbol,
        "exchange": exnm,
        "name": meta.get("name") or _COMMODITY_DEFS[key]["label"],
        "price": price,
        "change": change,
        "change_pct": rate,
        "source": "NHPLUG 해외파생",
        "updated_at": time.time(),
        "stale": False,
    }


def _refresh_commodities(force: bool = False):
    global _COMMODITIES, _COMMODITY_UPDATED, _COMMODITY_REFRESHING, _COMMODITY_LAST_ATTEMPT
    with _COMMODITY_LOCK:
        now0 = time.time()
        if _COMMODITY_REFRESHING:
            return
        if not force and _COMMODITY_UPDATED and now0 - _COMMODITY_UPDATED < 45:
            return
        if not force and not _COMMODITY_UPDATED and _COMMODITY_LAST_ATTEMPT and now0 - _COMMODITY_LAST_ATTEMPT < 300:
            return
        _COMMODITY_REFRESHING = True
        _COMMODITY_LAST_ATTEMPT = now0
    try:
        metas = _discover_commodity_symbols(force=False)
        new = {}
        for key in _COMMODITY_DEFS:
            meta = metas.get(key)
            if not meta:
                continue
            try:
                new[key] = _fetch_one_commodity(key, meta)
            except Exception:
                pass
            # Respect the measured/known small request-rate envelope; this runs in background only.
            time.sleep(0.24)
        with _COMMODITY_LOCK:
            if new:
                merged = dict(_COMMODITIES)
                merged.update(new)
                _COMMODITIES = merged
                _COMMODITY_UPDATED = time.time()
                _save_commodity_state()
            else:
                # Existing cache remains usable, but mark it stale in snapshots.
                pass
    finally:
        with _COMMODITY_LOCK:
            _COMMODITY_REFRESHING = False


def _commodity_points(rate: float) -> float:
    a = abs(float(rate or 0))
    if a < 0.5:
        return 0.0
    if a < 1.0:
        return 2.0
    if a < 2.0:
        return 3.0
    if a < 3.0:
        return 4.0
    return 5.0


def _commodity_adjustment(item: dict) -> tuple[float, list[str]]:
    text = " ".join([
        str(item.get("sector") or ""), str(item.get("name") or ""), str(item.get("code") or "")
    ]).lower()
    with _COMMODITY_LOCK:
        snap = {k: dict(v) for k, v in _COMMODITIES.items()}
        updated = _COMMODITY_UPDATED
    if not snap or not updated or time.time() - updated > 1800:
        return 0.0, []

    rules = []
    # (commodity key, positive exposure keywords, inverse exposure keywords)
    rules.append(("wti",
                  ("에너지", "정유", "석유", "oil", "energy", "petroleum", "exploration", "drilling"),
                  ("항공", "airline", "운송", "transport", "shipping", "택배")))
    rules.append(("natgas",
                  ("가스", "lng", "natural gas", "gas producer", "에너지"),
                  ("비료", "fertilizer", "화학")))
    rules.append(("copper",
                  ("구리", "동", "copper", "광산", "mining", "비철", "소재"),
                  ()))
    rules.append(("gold",
                  ("금광", "gold", "귀금속", "precious metal", "광산", "mining"),
                  ()))
    rules.append(("silver",
                  ("은광", "silver", "귀금속", "precious metal"),
                  ()))
    rules.append(("corn",
                  ("농업", "agri", "곡물", "grain"),
                  ("사료", "feed", "식품", "food")))
    rules.append(("soybean",
                  ("농업", "agri", "곡물", "grain"),
                  ("사료", "feed", "식품", "food")))
    rules.append(("wheat",
                  ("농업", "agri", "곡물", "grain"),
                  ("제분", "bakery", "식품", "food")))

    contributions = []
    reasons = []
    for key, pos_words, inv_words in rules:
        row = snap.get(key)
        if not row:
            continue
        direction = 1 if any(w in text for w in pos_words) else -1 if inv_words and any(w in text for w in inv_words) else 0
        if not direction:
            continue
        rate = float(row.get("change_pct") or 0)
        pts = _commodity_points(rate)
        if not pts:
            continue
        signed = pts * (1 if rate > 0 else -1) * direction
        contributions.append(signed)
        reasons.append(f"{row.get('label') or key} {rate:+.2f}% → 원자재 {signed:+.0f}점")
    if not contributions:
        return 0.0, []
    total = max(-5.0, min(5.0, sum(contributions)))
    return round(total, 1), reasons[:2]


def _patch_candidate_commodity():
    original = _core.candidate

    def candidate_v343(q, market, smart=False, secmap=None, stockmap=None, leadermap=None, sector_rankmap=None, now=None):
        item = original(q, market, smart, secmap, stockmap, leadermap, sector_rankmap, now)
        market2 = str(market or "KR").upper()
        if smart or market2 not in ("KR", "US") or not isinstance(item, dict):
            return item
        adj, why = _commodity_adjustment(item)
        if not adj:
            item.setdefault("commodity_adjustment", 0.0)
            return item
        score = max(0.0, min(110.0, float(item.get("score") or 0) + adj))
        item["score"] = round(score, 1)
        if item.get("priority_score") is not None:
            try:
                item["priority_score"] = round(max(0.0, min(110.0, float(item.get("priority_score") or 0) + adj)), 1)
            except Exception:
                pass
        item["commodity_adjustment"] = adj
        item["commodity_reasons"] = why
        rs = list(item.get("reasons") or [])
        item["reasons"] = why + rs
        return item

    _core.candidate = candidate_v343


def _resolve_schema(spec: dict, schema: dict) -> dict:
    seen = set()
    cur = schema or {}
    while isinstance(cur, dict) and "$ref" in cur:
        ref = str(cur.get("$ref") or "")
        if not ref.startswith("#/") or ref in seen:
            break
        seen.add(ref)
        node = spec
        try:
            for part in ref[2:].split("/"):
                node = node[part]
            cur = node
        except Exception:
            break
    return cur if isinstance(cur, dict) else {}


def _discover_night_investor_spec(force: bool = False) -> dict:
    global _NIGHT_SPEC_CACHE
    now = time.time()
    if _NIGHT_SPEC_CACHE and not force and now - _NIGHT_SPEC_CACHE[0] < 21600:
        return dict(_NIGHT_SPEC_CACHE[1])
    try:
        r = requests.get("https://www.nhplug.com/openapi-docs/krfuture/openapi.json", timeout=10)
        r.raise_for_status()
        spec = r.json()
    except Exception:
        return dict(_NIGHT_SPEC_CACHE[1]) if _NIGHT_SPEC_CACHE else {}
    for path, methods in (spec.get("paths") or {}).items():
        for method, op in (methods or {}).items():
            if str(method).lower() not in ("post", "get") or not isinstance(op, dict):
                continue
            text = " ".join([str(op.get("summary") or ""), str(op.get("description") or ""), str(op.get("operationId") or "")]).lower()
            if not (("투자자" in text and "시간" in text) or "investor" in text):
                continue
            rb = op.get("requestBody") or {}
            content = rb.get("content") or {}
            schema = {}
            for ct in ("application/json", "application/x-www-form-urlencoded", "multipart/form-data"):
                if isinstance(content.get(ct), dict):
                    schema = content[ct].get("schema") or {}
                    break
            schema = _resolve_schema(spec, schema)
            result = {"path": path, "method": method.upper(), "schema": schema, "spec": spec,
                      "summary": op.get("summary") or op.get("description") or "시간대별투자자"}
            _NIGHT_SPEC_CACHE = (now, result)
            return dict(result)
    return {}


def _night_payload_from_schema(meta: dict) -> dict | None:
    schema = _resolve_schema(meta.get("spec") or {}, meta.get("schema") or {})
    # SDK call() wants the inner body rather than an Input_0 envelope.
    props = schema.get("properties") or {}
    if "Input_0" in props:
        schema = _resolve_schema(meta.get("spec") or {}, (props.get("Input_0") or {}))
        props = schema.get("properties") or {}
    required = list(schema.get("required") or [])
    symbol = str(getattr(_core.feed, "future_symbols", {}).get("kospi_night") or "").strip()
    now = datetime.now(_core.KST)
    payload = {}
    aliases = {
        "iem_cd": symbol, "symbol": symbol, "code": symbol,
        "market_cd": "KRX", "date": now.strftime("%Y%m%d"), "bsop_date": now.strftime("%Y%m%d"),
        "bas_dt": now.strftime("%Y%m%d"), "array_cnt": "40", "time": now.strftime("%H%M%S"),
        "inq_strt_time": "180000", "inq_end_time": now.strftime("%H%M%S"),
    }
    for name, desc in props.items():
        d = _resolve_schema(meta.get("spec") or {}, desc or {})
        if name in aliases and aliases[name]:
            payload[name] = aliases[name]
            continue
        if d.get("default") not in (None, ""):
            payload[name] = d.get("default")
            continue
        enum = d.get("enum") or []
        if enum:
            payload[name] = enum[0]
            continue
        if name in required:
            # Unknown required fields are not guessed; skip this optional collector safely.
            return None
    if not symbol and any(k in required for k in ("iem_cd", "symbol", "code")):
        return None
    return payload


def _parse_night_investor(data: dict) -> dict:
    candidates = []
    for row in _walk_dicts(data):
        keys = {str(k).lower() for k in row.keys()}
        has_f = any(k in keys for k in ("frgn_ntby_qty", "frgn", "foreign", "foreign_net", "frgn_seln_vol"))
        has_i = any(k in keys for k in ("gigwan", "institution", "institution_net", "orgn_ntby_qty", "orgn"))
        has_p = any(k in keys for k in ("person", "personal", "prsn_ntby_qty", "individual", "individual_net"))
        if has_f and (has_i or has_p):
            candidates.append(row)
    if not candidates:
        return {}
    def stamp(row):
        return str(row.get("bsop_date") or row.get("date") or "") + str(row.get("time") or row.get("bsop_time") or row.get("hour") or "")
    row = sorted(candidates, key=stamp)[-1]
    def val(names):
        for n in names:
            if n in row:
                return _n(row.get(n))
        return None
    f = val(("frgn_ntby_qty", "frgn", "foreign", "foreign_net", "frgn_seln_vol"))
    i = val(("gigwan", "institution", "institution_net", "orgn_ntby_qty", "orgn"))
    p = val(("person", "personal", "prsn_ntby_qty", "individual", "individual_net"))
    if f is None and i is None and p is None:
        return {}
    return {"foreign": f or 0.0, "institution": i or 0.0, "person": p or 0.0}


def _refresh_night_flow(force: bool = False):
    global _NIGHT_FLOW, _NIGHT_FLOW_UPDATED, _NIGHT_FLOW_REFRESHING, _NIGHT_FLOW_LAST_ATTEMPT
    with _LOCK:
        now0 = time.time()
        if _NIGHT_FLOW_REFRESHING:
            return
        if not force and _NIGHT_FLOW_UPDATED and now0 - _NIGHT_FLOW_UPDATED < 120:
            return
        if not force and _NIGHT_FLOW_LAST_ATTEMPT and now0 - _NIGHT_FLOW_LAST_ATTEMPT < 300:
            return
        _NIGHT_FLOW_REFRESHING = True
        _NIGHT_FLOW_LAST_ATTEMPT = now0
    try:
        meta = _discover_night_investor_spec()
        payload = _night_payload_from_schema(meta) if meta else None
        if not meta or not payload:
            return
        from nhplug import call
        data = call(meta["path"], payload)
        parsed = _parse_night_investor(data)
        if not parsed:
            return
        row = {
            "key": "kospi_night", "label": "KOSPI 야간선물",
            "source": "NHPLUG 국내파생 시간대별투자자", "asof": datetime.now(_core.KST).isoformat(),
            "latest": parsed, "daily": [], "days": 0, "ok": True,
            "unit": "계약/공식응답", "note": "야간선물 자체 투자자 수급",
        }
        with _LOCK:
            _NIGHT_FLOW = row
            _NIGHT_FLOW_UPDATED = time.time()
            try:
                _core.store.save_json(_NIGHT_FLOW_STATE_KEY, {"updated_at": _NIGHT_FLOW_UPDATED, "data": row})
            except Exception:
                pass
    except Exception:
        pass
    finally:
        with _LOCK:
            _NIGHT_FLOW_REFRESHING = False


def _coin_chart_ttl(interval: str) -> float:
    return 12.0 if interval in ("1m", "3m", "5m") else 30.0 if interval in ("10m", "15m", "30m", "1h") else 120.0


def _patch_coin_chart_cache():
    original = _core.coin_feed.chart

    def cached_chart(self, symbol, interval="1m", size=120):
        symbol2 = str(symbol or "").upper()
        interval2 = str(interval or "1m")
        size2 = max(20, min(500, int(size or 120)))
        key = (symbol2, interval2, size2)
        now = time.time()
        with _COIN_CHART_LOCK:
            cached = _COIN_CHART_CACHE.get(key)
        if cached and now - cached[0] <= _coin_chart_ttl(interval2):
            return list(cached[1])
        try:
            rows = original(symbol2, interval2, size2)
            if rows:
                with _COIN_CHART_LOCK:
                    _COIN_CHART_CACHE[key] = (now, list(rows))
                # Persist only slower-changing daily charts; this keeps restart fast without write spam.
                if interval2 == "1d":
                    try:
                        _core.store.save_json(f"v343_coin_chart_{symbol2}_1d", {"saved_at": now, "bars": rows[-200:]})
                    except Exception:
                        pass
                return rows
        except Exception:
            pass
        if cached:
            return list(cached[1])
        if interval2 == "1d":
            try:
                raw = _core.store.load_json(f"v343_coin_chart_{symbol2}_1d", {}) or {}
                rows = list(raw.get("bars") or [])
                if rows:
                    with _COIN_CHART_LOCK:
                        _COIN_CHART_CACHE[key] = (float(raw.get("saved_at") or 0), rows)
                    return rows[-size2:]
            except Exception:
                pass
        return []

    _core.coin_feed.chart = MethodType(cached_chart, _core.coin_feed)


def _bitcoin_snapshot(force: bool = False) -> dict:
    global _BTC_CACHE, _BTC_UPDATED
    now = time.time()
    if _BTC_CACHE and not force and now - _BTC_UPDATED < 12:
        return dict(_BTC_CACHE)
    q = _core.coin_feed.quote("BTC")
    if not q:
        try:
            _core.coin_feed.refresh_rest()
            q = _core.coin_feed.quote("BTC")
        except Exception:
            q = None
    try:
        bars = _core.coin_feed.chart("BTC", "1h", 30)
    except Exception:
        bars = []
    series = [float(x.get("close") or 0) for x in bars if _n(x.get("close")) > 0][-24:]
    if q and q.price > 0:
        payload = {
            "ok": True, "key": "bitcoin", "label": "BITCOIN", "symbol": "BTC", "market": "COIN",
            "value": float(q.price), "change_pct": float(q.change_pct or 0), "series": series,
            "source": "Coinone Public API", "status": "24시간", "asof": float(q.updated_at or now),
            "chart_url": "/coin/BTC", "updated_at": now,
        }
        _BTC_CACHE = payload
        _BTC_UPDATED = now
        return dict(payload)
    return dict(_BTC_CACHE) if _BTC_CACHE else {"ok": False, "key": "bitcoin", "label": "BITCOIN", "series": []}


def _commodity_loop():
    time.sleep(6)
    while True:
        try:
            _refresh_commodities()
        except Exception:
            pass
        time.sleep(60)


def _night_flow_loop():
    time.sleep(10)
    while True:
        try:
            _refresh_night_flow()
        except Exception:
            pass
        now = datetime.now(_core.KST)
        mins = now.hour * 60 + now.minute
        night = now.weekday() < 5 and mins >= 18 * 60 or (mins < 6 * 60 and (now - timedelta(days=1)).weekday() < 5)
        time.sleep(300 if night else 900)


def _btc_loop():
    time.sleep(3)
    while True:
        try:
            _bitcoin_snapshot(force=True)
        except Exception:
            pass
        time.sleep(15)


def install(namespace: dict):
    global _INSTALLED, _core, _ns, _BG_STARTED
    if _INSTALLED:
        return
    _INSTALLED = True
    _ns = namespace
    _core = namespace["core"]
    _load_persisted()
    _load_commodity_state()
    _patch_index_persistence()
    _patch_investor_20d()
    _patch_coin_chart_cache()
    _patch_candidate_commodity()

    @_core.app.get("/api/v343/index-diagnostics")
    def v343_index_diagnostics():
        return {"ok": True, "items": _index_diagnostics(), "build": _core.BUILD_ID,
                "cache": "persistent StateStore + background refresh"}

    @_core.app.get("/api/v343/market-flow")
    def v343_market_flow():
        if not _MARKET_FLOW_UPDATED or time.time() - _MARKET_FLOW_UPDATED > 120:
            threading.Thread(target=_refresh_market_flow, daemon=True).start()
        # Night-futures investor data is collected only when the official NH endpoint
        # can be discovered and parsed; no KOSPI cash-flow values are relabelled as futures.
        if not _NIGHT_FLOW_UPDATED or time.time() - _NIGHT_FLOW_UPDATED > 120:
            threading.Thread(target=_refresh_night_flow, daemon=True).start()
        with _LOCK:
            data = {k: _flow_enrich(dict(v)) for k, v in _MARKET_FLOW.items()}
            if _NIGHT_FLOW:
                data["kospi_night"] = dict(_NIGHT_FLOW)
            updated = max(_MARKET_FLOW_UPDATED, _NIGHT_FLOW_UPDATED)
            refreshing = _MARKET_FLOW_REFRESHING or _NIGHT_FLOW_REFRESHING
        if "kospi_night" not in data:
            data["kospi_night"] = {
                "key": "kospi_night", "label": "KOSPI 야간선물", "ok": False,
                "latest": {}, "daily": [], "source": "NHPLUG 국내파생",
                "note": "야간선물 투자자별 공식 수급 수신 대기 · 현물 수급으로 대체하지 않음",
            }
        return {"ok": True, "items": data, "updated_at": updated, "refreshing": refreshing,
                "source": "KRX + NHPLUG", "non_blocking_cache": True}

    @_core.app.get("/api/v343/disclosures")
    def v343_disclosures(market: str = "KR", months: int = 6, page: int = 1, page_size: int = 50):
        market2 = _core.normalize_market(market)
        if market2 == "US":
            return _us_history_page(page, page_size)
        return _dart_history_page(page, page_size, months)

    @_core.app.get("/api/v343/earnings")
    def v343_earnings(market: str = "KR", year: int | None = None, month: int | None = None):
        now = datetime.now(_core.KST)
        y = int(year or now.year)
        m = int(month or now.month)
        if m < 1 or m > 12:
            m = now.month
        market2 = _core.normalize_market(market)
        return _us_earnings_month(y, m) if market2 == "US" else _kr_earnings_month(y, m)

    @_core.app.get("/api/v343/investor-stock/{code}")
    def v343_investor_stock(code: str):
        code2 = str(code or "").upper().strip()
        q = _core.feed.q("KR", code2)
        rows = list(getattr(q, "investor_daily", []) or [])[-20:]
        sums = {k: sum(float(r.get(k, 0) or 0) for r in rows) for k in ("foreign", "institution", "person", "program")}
        denom = sum(abs(sums[k]) for k in ("foreign", "institution", "person")) or 0.0
        shares = {k: (sums[k] / denom * 100.0 if denom else 0.0) for k in ("foreign", "institution", "person")}
        return {"ok": True, "market": "KR", "code": code2, "days": len(rows), "items": rows,
                "sums": sums, "share_pct": shares, "source": "NHPLUG currentInvestor",
                "window": "최근 20거래일(약 1개월)"}

    @_core.app.get("/api/v343/commodities")
    def v343_commodities():
        if not _COMMODITY_UPDATED or time.time() - _COMMODITY_UPDATED > 60:
            threading.Thread(target=_refresh_commodities, daemon=True).start()
        with _COMMODITY_LOCK:
            rows = [dict(v) for _, v in sorted(_COMMODITIES.items())]
            updated = _COMMODITY_UPDATED
            refreshing = _COMMODITY_REFRESHING
        for r in rows:
            r["stale"] = not updated or time.time() - updated > 1800
        return {"ok": True, "items": rows, "updated_at": updated, "refreshing": refreshing,
                "source": "NHPLUG 해외파생", "score_rule": "관련 종목 단타 총합 -5~+5",
                "non_blocking_cache": True}

    @_core.app.get("/api/v343/bitcoin")
    def v343_bitcoin():
        return _bitcoin_snapshot(force=False)

    @_core.app.get("/api/v343/coin-chart/{symbol}")
    def v343_coin_chart(symbol: str, interval: str = "1d", size: int = 180):
        symbol2 = str(symbol or "").upper().strip()
        size2 = max(20, min(500, int(size or 180)))
        bars = _core.coin_feed.chart(symbol2, interval, size2)
        q = _core.coin_feed.quote(symbol2)
        return {"ok": bool(bars), "market": "COIN", "symbol": symbol2, "interval": interval,
                "bars": bars, "price": float(q.price) if q else 0.0,
                "source": "Coinone Public API · cache-first", "cached": True}

    prev_start = _core.start_background

    def start_background_v343():
        global _BG_STARTED
        prev_start()
        with _BG_LOCK:
            if _BG_STARTED:
                return
            _BG_STARTED = True
            threading.Thread(target=_flow_loop, daemon=True).start()
            threading.Thread(target=_us_loop, daemon=True).start()
            threading.Thread(target=_commodity_loop, daemon=True).start()
            threading.Thread(target=_night_flow_loop, daemon=True).start()
            threading.Thread(target=_btc_loop, daemon=True).start()

    _core.start_background = start_background_v343


def status_snapshot() -> dict:
    with _COMMODITY_LOCK:
        commodity_count = len(_COMMODITIES)
    return {
        "market_flow_cached": bool(_MARKET_FLOW),
        "market_flow_updated_at": _MARKET_FLOW_UPDATED,
        "night_flow_cached": bool(_NIGHT_FLOW),
        "night_flow_updated_at": _NIGHT_FLOW_UPDATED,
        "us_history_count": len(_US_HISTORY),
        "us_history_updated_at": _US_HISTORY_UPDATED,
        "commodity_count": commodity_count,
        "commodity_updated_at": _COMMODITY_UPDATED,
        "bitcoin_cached": bool(_BTC_CACHE),
        "index": _index_diagnostics() if _core else {},
    }
