from __future__ import annotations

import calendar
import email.utils
import html as html_lib
import re
import threading
import time
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import requests

_INSTALLED = False
_core = None
_v343 = None
_runtime_ns = None
_LOCK = threading.RLock()
_HTTP = requests.Session()
_HTTP.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131 Safari/537.36 GY-Trading-OS/34.8",
    "Accept": "application/json,text/plain,text/html,application/xml,text/xml,*/*",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.7,en;q=0.6",
})

_DART_PAGE_CACHE: dict[tuple, tuple[float, dict]] = {}
_DART_STOCK_CACHE: dict[tuple, tuple[float, dict]] = {}
_DART_RSS_CACHE: tuple[float, dict] | None = None
_NAVER_DISC_CACHE: dict[str, tuple[float, dict]] = {}
_NAVER_MARKET_DISC_CACHE: dict[tuple, tuple[float, dict]] = {}
_NAVER_BARS_CACHE: dict[str, tuple[float, list[dict]]] = {}
_INDEX_CACHE: dict[str, tuple[float, list[dict]]] = {}
_STOCK_ATTEMPT: dict[str, float] = {}
_INVESTOR_ATTEMPT: dict[str, float] = {}
_INVESTOR_REFRESHING: set[str] = set()
_INDEX_ATTEMPT: dict[str, float] = {}
_SEC_SEARCH_CACHE: tuple[float, list[dict]] | None = None


def _n(v: Any) -> float:
    if v is None:
        return 0.0
    if isinstance(v, (int, float)):
        try:
            return float(v)
        except Exception:
            return 0.0
    s = str(v).strip().replace(",", "").replace("원", "").replace("%", "")
    s = s.replace("−", "-").replace("+", "")
    m = re.search(r"-?\d+(?:\.\d+)?", s)
    try:
        return float(m.group(0)) if m else 0.0
    except Exception:
        return 0.0


def _iso_date(v: Any) -> str:
    raw = str(v or "").strip()
    digits = re.sub(r"\D", "", raw)
    if len(digits) >= 8:
        digits = digits[:8]
        return f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}"
    return raw[:10] if len(raw) >= 10 and raw[4:5] == "-" and raw[7:8] == "-" else ""


def _compact_date(v: Any) -> str:
    return _iso_date(v).replace("-", "")


def _months_ago(d, months: int):
    months = max(1, int(months or 1))
    y, m = d.year, d.month - months
    while m <= 0:
        y -= 1
        m += 12
    return d.replace(year=y, month=m, day=min(d.day, calendar.monthrange(y, m)[1]))


def _walk(obj):
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from _walk(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk(v)


def _pick(d: dict, keys, default=None):
    for k in keys:
        if k in d and d.get(k) not in (None, ""):
            return d.get(k)
    return default


def _clean_text(s: Any) -> str:
    s = html_lib.unescape(re.sub(r"<[^>]+>", " ", str(s or "")))
    return re.sub(r"\s+", " ", s).strip()


def _classify(title: str):
    try:
        from events import classify_event
        c = classify_event(title)
        sent = str(c.get("sentiment") or "neutral")
        blocked = bool(c.get("blocked"))
        return sent, str(c.get("label") or "중립"), (5.0 if sent == "positive" else -5.0 if sent == "negative" else 0.0), blocked
    except Exception:
        t = str(title or "")
        block = bool(re.search(r"상장폐지|횡령|배임|회생절차|파산|거래정지", t))
        neg = bool(re.search(r"유상증자|전환사채|신주인수권|감자|소송|적자|손실|정정", t))
        pos = bool(re.search(r"공급계약|단일판매|수주|자기주식취득|흑자전환|승인|특허", t))
        if block:
            return "negative", "강한 악재", -5.0, True
        if neg and not pos:
            return "negative", "악재", -5.0, False
        if pos and not neg:
            return "positive", "호재", 5.0, False
        return "neutral", "중립", 0.0, False


def _event_row(*, code="", corp_name="", title="", date="", source="", url="", form=""):
    sent, label, score, blocked = _classify(title)
    return {
        "market": "KR", "code": str(code or "").strip(), "corp_name": str(corp_name or code or "").strip(),
        "title": str(title or "").strip(), "date": _iso_date(date), "time": "", "source": source,
        "url": url, "sentiment": sent, "label": label, "score": score, "blocked": blocked, "form": form,
    }


def _dart_key() -> str:
    try:
        return str(getattr(_core.events, "api_key", "") or "").strip()
    except Exception:
        return ""


def _dart_get(params: dict) -> dict:
    key = _dart_key()
    if not key:
        return {"status": "NO_KEY", "message": "DART_API_KEY 미설정", "list": []}
    r = _HTTP.get("https://opendart.fss.or.kr/api/list.json", params={"crtfc_key": key, **params}, timeout=15)
    r.raise_for_status()
    return r.json()


def _dart_row(x: dict, code_override: str = "") -> dict | None:
    code = str(code_override or x.get("stock_code") or "").strip()
    title = str(x.get("report_nm") or "").strip()
    if not title:
        return None
    rcp = str(x.get("rcept_no") or "")
    return _event_row(
        code=code, corp_name=str(x.get("corp_name") or code), title=title, date=x.get("rcept_dt"),
        source="DART 공식", url=f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcp}" if rcp else "",
        form=str(x.get("corp_cls") or ""),
    )


def _dart_market_page(months: int, page: int, page_size: int) -> dict:
    months = max(1, min(3, int(months or 3)))
    page = max(1, int(page or 1)); page_size = max(10, min(100, int(page_size or 50)))
    today = datetime.now(_core.KST).date(); begin = _months_ago(today, months)
    key = (months, page, page_size, today.isoformat()); now = time.time()
    cached = _DART_PAGE_CACHE.get(key)
    if cached and now - cached[0] < 60:
        return cached[1]
    j = _dart_get({"bgn_de": begin.strftime("%Y%m%d"), "end_de": today.strftime("%Y%m%d"),
                   "page_no": str(page), "page_count": str(page_size), "sort": "date", "sort_mth": "desc"})
    status = str(j.get("status") or "")
    if status not in ("000", "013"):
        raise RuntimeError(j.get("message") or status or "DART 조회 오류")
    rows = [r for r in (_dart_row(x) for x in (j.get("list") or [])) if r]
    payload = {"ok": True, "market": "KR", "months": months, "page": page, "page_size": page_size,
               "total_count": int(j.get("total_count") or len(rows)), "total_page": int(j.get("total_page") or 1),
               "items": rows, "source": "DART 공식 · 전종목", "updated_at": now}
    _DART_PAGE_CACHE[key] = (now, payload)
    return payload


def _corp_code_map() -> dict[str, str]:
    out = {}
    try:
        meta = dict(getattr(_core.feed, "kr_master_meta", {}) or {})
        for code, m in meta.items():
            name = str((m or {}).get("name") or "").strip()
            if name:
                out[name] = str(code)
    except Exception:
        pass
    try:
        cat = dict((_runtime_ns or {}).get("_SEARCH_CATALOG", {}).get("KR", {}) or {})
        for code, m in cat.items():
            name = str((m or {}).get("name") or "").strip()
            if name:
                out.setdefault(name, str(code))
    except Exception:
        pass
    return out


def _dart_rss_recent() -> dict:
    global _DART_RSS_CACHE
    now = time.time()
    if _DART_RSS_CACHE and now - _DART_RSS_CACHE[0] < 90:
        return _DART_RSS_CACHE[1]
    r = _HTTP.get("https://dart.fss.or.kr/api/todayRSS.xml", timeout=15)
    r.raise_for_status()
    text = r.content.decode("utf-8", "ignore")
    root = ET.fromstring(text)
    reverse = _corp_code_map(); rows = []
    for item in root.findall(".//item"):
        title_raw = _clean_text(item.findtext("title") or "")
        link = _clean_text(item.findtext("link") or "")
        pub = _clean_text(item.findtext("pubDate") or "")
        corp, title = "", title_raw
        if " / " in title_raw:
            corp, title = [x.strip() for x in title_raw.split(" / ", 1)]
        elif " - " in title_raw:
            corp, title = [x.strip() for x in title_raw.split(" - ", 1)]
        date = ""
        try:
            dt = email.utils.parsedate_to_datetime(pub)
            date = dt.astimezone(_core.KST).date().isoformat()
        except Exception:
            m = re.search(r"(20\d{2})[-./]?(\d{2})[-./]?(\d{2})", pub)
            if m:
                date = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
        code = reverse.get(corp, "")
        if title:
            rows.append(_event_row(code=code, corp_name=corp or code, title=title, date=date,
                                   source="DART 최근공시 RSS", url=link, form="RSS"))
    rows = rows[:50]
    payload = {"ok": True, "market": "KR", "months": 0, "page": 1, "page_size": 50,
               "total_count": len(rows), "total_page": 1, "items": rows,
               "source": "DART 최근공시 RSS · API키 불필요", "status": "DART API키 미설정 → 공식 RSS fallback",
               "updated_at": now}
    _DART_RSS_CACHE = (now, payload)
    return payload


def _notice_value(d: dict, keys):
    for k in keys:
        if k in d and d.get(k) not in (None, "", [], {}):
            return d.get(k)
    return None


def _naver_notice_rows(payload, *, code_override: str = "", market_scope: bool = False) -> list[dict]:
    """Normalize current Naver Stock disclosure/market-notice payloads.

    Naver has changed field names several times.  We intentionally accept the
    currently observed stock.naver.com shapes plus older mobile shapes, while
    requiring a title + real date so unrelated nested objects are ignored.
    """
    rows: list[dict] = []
    seen = set()
    title_keys = (
        "title", "noticeTitle", "articleTitle", "subject", "reportName",
        "disclosureTitle", "headline", "newsTitle", "name",
    )
    date_keys = (
        "date", "localDate", "articleDate", "noticeDate", "disclosureDate",
        "rceptDt", "rcept_dt", "bizdate", "businessDate", "tradeDate",
        "createdAt", "createdDate", "publishedAt", "publishDate", "writeDate",
        "regDate", "datetime", "dateTime",
    )
    corp_keys = (
        "itemName", "stockName", "companyName", "corpName", "corp_name",
        "issuerName", "officeName", "company", "sourceName",
    )
    code_keys = ("itemCode", "stockCode", "symbolCode", "code", "ticker")
    url_keys = ("url", "link", "articleUrl", "noticeUrl", "endUrl", "disclosureUrl", "detailUrl")
    id_keys = ("aid", "articleId", "articleNo", "noticeId", "id")
    source_keys = ("officeName", "providerName", "source", "pressName", "mediaName")

    for d in _walk(payload):
        if not isinstance(d, dict):
            continue
        title = _clean_text(_notice_value(d, title_keys) or "")
        date = _iso_date(_notice_value(d, date_keys) or "")
        if not title or not date:
            continue

        raw_code = str(code_override or _notice_value(d, code_keys) or "").strip().upper()
        m = re.search(r"(?<!\d)(\d{6})(?!\d)", raw_code)
        code = m.group(1) if m else (str(code_override or "").strip().upper() if code_override else "")
        corp = _clean_text(_notice_value(d, corp_keys) or "")
        source = _clean_text(_notice_value(d, source_keys) or "") or "네이버 증권 공시"

        raw_url = str(_notice_value(d, url_keys) or "").strip()
        if raw_url.startswith("/"):
            raw_url = urllib.parse.urljoin("https://stock.naver.com", raw_url)
        elif raw_url and not raw_url.startswith(("http://", "https://")):
            raw_url = ""
        article_id = str(_notice_value(d, id_keys) or "").strip()
        if not raw_url and article_id:
            if market_scope:
                raw_url = f"https://stock.naver.com/news/marketNotice/{urllib.parse.quote(article_id)}"
            elif code:
                raw_url = f"https://stock.naver.com/domestic/stock/{code}/notice/{urllib.parse.quote(article_id)}"

        key = (date, title, code, raw_url)
        if key in seen:
            continue
        seen.add(key)
        rows.append(_event_row(code=code, corp_name=corp or code, title=title, date=date,
                               source=source, url=raw_url, form="공시"))
    rows.sort(key=lambda x: (x.get("date") or "", x.get("title") or ""), reverse=True)
    return rows


def _pc_naver_disclosures(code: str, pages: int = 4) -> list[dict]:
    rows = []
    for page in range(1, max(1, pages) + 1):
        r = _HTTP.get("https://finance.naver.com/item/news_notice.naver", params={"code": code, "page": page},
                      headers={"Referer": f"https://finance.naver.com/item/news.naver?code={code}"}, timeout=12)
        r.raise_for_status()
        html = r.content.decode("euc-kr", "ignore")
        found = 0
        for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", html, flags=re.I | re.S):
            tds = re.findall(r"<td[^>]*>(.*?)</td>", tr, flags=re.I | re.S)
            if len(tds) != 3:
                continue
            title = _clean_text(tds[0]); info = _clean_text(tds[1]); date = _clean_text(tds[2])
            if not title or not re.search(r"20\d{2}[.\-/]\d{2}[.\-/]\d{2}", date):
                continue
            hrefm = re.search(r"href=[\"']([^\"']+)[\"']", tds[0], flags=re.I)
            href = hrefm.group(1) if hrefm else ""
            url = urllib.parse.urljoin("https://finance.naver.com", html_lib.unescape(href)) if href else ""
            rows.append(_event_row(code=code, corp_name="", title=title, date=date,
                                   source=(info or "네이버 증권 공시"), url=url, form="공시"))
            found += 1
        if found == 0:
            break
    return rows


def _naver_market_disclosures(months: int = 3, page: int = 1, page_size: int = 50) -> dict:
    """Key-free KR market disclosures from the current Naver Stock public route."""
    months = max(1, min(3, int(months or 3)))
    page = max(1, int(page or 1)); page_size = max(10, min(100, int(page_size or 50)))
    today = datetime.now(_core.KST).date(); begin = _months_ago(today, months)
    cache_key = (months, page, page_size, today.isoformat()); now = time.time()
    cached = _NAVER_MARKET_DISC_CACHE.get(cache_key)
    if cached and now - cached[0] < 60:
        return cached[1]

    errors = []
    rows: list[dict] = []
    # Current Npay Securities market-disclosure route (verified 2026-08 docs).
    try:
        r = _HTTP.get("https://stock.naver.com/api/domestic/news/noticeList",
                      params={"page": page, "pageSize": page_size,
                              "startDate": begin.strftime("%Y%m%d"), "endDate": today.strftime("%Y%m%d")},
                      headers={"Referer": "https://stock.naver.com/news/marketNotice"}, timeout=15)
        r.raise_for_status()
        rows = _naver_notice_rows(r.json(), market_scope=True)
        if not rows:
            errors.append("Naver market notice: 0 rows")
    except Exception as exc:
        errors.append(f"Naver market notice: {type(exc).__name__}: {exc}")

    # Secondary current Naver disclosure/news focus route.  It is not used when
    # the market-notice route produced rows, but prevents a blank panel if that
    # route is temporarily changed upstream.
    if not rows:
        try:
            r = _HTTP.get("https://stock.naver.com/api/domestic/news/focus",
                          params={"sid": "406", "page": page, "pageSize": page_size,
                                  "date": today.strftime("%Y%m%d"), "enableFallback": "true", "maxDays": "7"},
                          headers={"Referer": "https://stock.naver.com/news/section?tab=disclosure-memo"}, timeout=15)
            r.raise_for_status()
            rows = _naver_notice_rows(r.json(), market_scope=True)
            if not rows:
                errors.append("Naver disclosure focus: 0 rows")
        except Exception as exc:
            errors.append(f"Naver disclosure focus: {type(exc).__name__}: {exc}")

    if rows:
        cutoff = begin.isoformat()
        rows = [x for x in rows if str(x.get("date") or "") >= cutoff]
        payload = {"ok": True, "market": "KR", "months": months, "page": page, "page_size": page_size,
                   "total_count": len(rows), "total_page": 1, "items": rows[:page_size],
                   "source": "네이버 증권 시장공시 · API키 불필요", "status": "공시 연결 정상",
                   "updated_at": now}
        _NAVER_MARKET_DISC_CACHE[cache_key] = (now, payload)
        return payload
    raise RuntimeError(" | ".join(errors)[:500] or "네이버 시장공시 0건")


def _naver_stock_disclosures(code: str, months: int = 3) -> dict:
    code = str(code or "").strip().upper(); months = max(1, min(3, int(months or 3)))
    now = time.time(); key = f"{code}:{months}"
    cached = _NAVER_DISC_CACHE.get(key)
    if cached and now - cached[0] < 120:
        return cached[1]
    cutoff = _months_ago(datetime.now(_core.KST).date(), months).isoformat(); items = []
    errors = []

    # 1) Current Npay Securities public stock disclosure route.
    try:
        for start_idx in (0, 100, 200):
            r = _HTTP.get("https://stock.naver.com/api/domestic/detail/notice",
                          params={"itemCode": code, "startIdx": start_idx, "pageSize": 100},
                          headers={"Referer": f"https://stock.naver.com/domestic/stock/{code}/notice"}, timeout=15)
            r.raise_for_status()
            page_rows = _naver_notice_rows(r.json(), code_override=code, market_scope=False)
            items.extend(page_rows)
            if len(page_rows) < 80:
                break
            if page_rows and min(str(x.get("date") or "9999-99-99") for x in page_rows) < cutoff:
                break
        if not items:
            errors.append("Naver current stock notice: 0 rows")
    except Exception as exc:
        errors.append(f"Naver current stock notice: {type(exc).__name__}: {exc}")

    # 2) Older mobile JSON route retained as compatibility fallback.
    if not items:
        try:
            for page in range(1, 7):
                r = _HTTP.get("https://m.stock.naver.com/front-api/stock/domestic/disclosure",
                              params={"code": code, "page": page, "pageSize": 50}, timeout=12)
                if not r.ok:
                    break
                page_rows = _naver_notice_rows(r.json(), code_override=code, market_scope=False)
                items.extend(page_rows)
                if len(page_rows) < 20:
                    break
            if not items:
                errors.append("Naver legacy mobile notice: 0 rows")
        except Exception as exc:
            errors.append(f"Naver legacy mobile notice: {type(exc).__name__}: {exc}")

    # 3) Legacy PC HTML is the final no-key fallback.
    if not items:
        try:
            items = _pc_naver_disclosures(code, pages=5)
            if not items:
                errors.append("Naver PC notice: 0 rows")
        except Exception as exc:
            errors.append(f"Naver PC notice: {type(exc).__name__}: {exc}")

    uniq = {(x.get("date"), x.get("title"), x.get("url")): x for x in items if str(x.get("date") or "") >= cutoff}
    rows = sorted(uniq.values(), key=lambda x: (x.get("date") or "", x.get("title") or ""), reverse=True)
    if rows:
        payload = {"ok": True, "market": "KR", "code": code, "months": months, "items": rows, "count": len(rows),
                   "source": "네이버 증권 종목공시 · DART키 fallback", "status": "공시 연결 정상",
                   "updated_at": now}
        _NAVER_DISC_CACHE[key] = (now, payload)
        return payload
    return {"ok": False, "market": "KR", "code": code, "months": months, "items": [], "count": 0,
            "source": "네이버 증권 종목공시", "status": (" | ".join(errors)[:500] or "공시 0건"),
            "updated_at": now}

def _dart_stock_history(code: str, months: int = 3) -> dict:
    code = str(code or "").strip().upper(); months = max(1, min(3, int(months or 3)))
    today = datetime.now(_core.KST).date(); now = time.time(); key = (code, months, today.isoformat())
    cached = _DART_STOCK_CACHE.get(key)
    if cached and now - cached[0] < 120:
        return cached[1]
    if not _dart_key():
        return _naver_stock_disclosures(code, months)
    try:
        _core.events._load_corp_map(); corp = getattr(_core.events, "_corp_by_stock", {}).get(code)
    except Exception:
        corp = None
    if not corp:
        return _naver_stock_disclosures(code, months)
    begin = _months_ago(today, months); page = 1; total_page = 1; items = []
    while page <= total_page and page <= 10:
        j = _dart_get({"corp_code": corp[0], "bgn_de": begin.strftime("%Y%m%d"), "end_de": today.strftime("%Y%m%d"),
                       "page_no": str(page), "page_count": "100", "sort": "date", "sort_mth": "desc"})
        status = str(j.get("status") or "")
        if status == "013":
            break
        if status != "000":
            return _naver_stock_disclosures(code, months)
        total_page = int(j.get("total_page") or 1)
        items.extend([r for r in (_dart_row(x, code_override=code) for x in (j.get("list") or [])) if r]); page += 1
    uniq = {(x.get("date"), x.get("title"), x.get("url")): x for x in items}
    rows = sorted(uniq.values(), key=lambda x: (x.get("date") or "", x.get("title") or ""), reverse=True)
    payload = {"ok": True, "market": "KR", "code": code, "corp_name": corp[1], "months": months, "items": rows,
               "count": len(rows), "source": "DART 공식 · 종목별 3개월", "updated_at": now}
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
    return {"ok": True, "market": "US", "code": str(code or "").upper(), "months": months,
            "items": rows, "count": len(rows), "source": "SEC EDGAR"}


def _normalized_daily(rows: list[dict]) -> list[dict]:
    out, seen = [], set()
    for b in rows or []:
        raw = _compact_date(b.get("date") or b.get("time") or b.get("localDate"))
        if len(raw) != 8 or not raw.isdigit() or raw in seen:
            continue
        o = _n(_pick(b, ("open", "openPrice", "stck_oprc", "ov"), 0)); h = _n(_pick(b, ("high", "highPrice", "stck_hgpr", "hv"), 0))
        l = _n(_pick(b, ("low", "lowPrice", "stck_lwpr", "lv"), 0)); c = _n(_pick(b, ("close", "closePrice", "stck_clpr", "nv"), 0))
        v = _n(_pick(b, ("volume", "accumulatedTradingVolume", "acml_vol", "aq"), 0))
        if min(o, h, l, c) <= 0 or h < max(o, c) or l > min(o, c):
            continue
        seen.add(raw); out.append({"time": raw, "open": o, "high": h, "low": l, "close": c, "volume": v})
    out.sort(key=lambda x: x["time"])
    return out


def _load_saved_stock_bars(market: str, code: str) -> list[dict]:
    try:
        raw = _core.store.load_json(f"v344_stock_daily:{market}:{code}", {}) or {}
        return list(raw.get("bars") if isinstance(raw, dict) else [])[-120:]
    except Exception:
        return []


def _save_stock_bars(market: str, code: str, bars: list[dict]):
    try:
        _core.store.save_json(f"v344_stock_daily:{market}:{code}", {"version": 2, "saved_at": time.time(), "bars": list(bars or [])[-120:]})
    except Exception:
        pass


def _naver_stock_bars(code: str, days: int = 60) -> list[dict]:
    code = str(code or "").strip(); days = max(20, min(120, int(days or 60))); now = time.time()
    cached = _NAVER_BARS_CACHE.get(code)
    if cached and now - cached[0] < 90 and len(cached[1]) >= min(days, 20):
        return list(cached[1])[-days:]
    rows = []
    try:
        end = datetime.now(_core.KST).strftime("%Y%m%d")
        start = (datetime.now(_core.KST) - timedelta(days=max(180, days * 3))).strftime("%Y%m%d")
        r = _HTTP.get(f"https://api.stock.naver.com/chart/domestic/item/{code}",
                      params={"periodType": "dayCandle", "startDateTime": start, "endDateTime": end}, timeout=12)
        r.raise_for_status(); payload = r.json()
        rows = _normalized_daily(list(_walk(payload)))
    except Exception:
        rows = []
    # Legacy official-KRX-backed Naver chart fallback
    if not rows:
        try:
            end = datetime.now(_core.KST).strftime("%Y%m%d")
            start = (datetime.now(_core.KST) - timedelta(days=max(180, days * 3))).strftime("%Y%m%d")
            r = _HTTP.get("https://api.finance.naver.com/siseJson.naver",
                          params={"symbol": code, "requestType": 1, "startTime": start, "endTime": end, "timeframe": "day"}, timeout=12)
            r.raise_for_status(); text = r.text
            for m in re.finditer(r"\[\s*[\"']?(20\d{6})[\"']?\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)", text):
                d, o, h, l, c, v = m.groups(); rows.append({"time": d, "open": _n(o), "high": _n(h), "low": _n(l), "close": _n(c), "volume": _n(v)})
            rows = _normalized_daily(rows)
        except Exception:
            rows = []
    if rows:
        _NAVER_BARS_CACHE[code] = (now, rows[-120:])
    return rows[-days:]


def _naver_kr_quote(code: str) -> dict:
    try:
        r = _HTTP.get(f"https://m.stock.naver.com/api/stock/{code}/basic", timeout=10); r.raise_for_status(); d = r.json()
        return {"price": _n(d.get("closePrice")), "name": str(d.get("stockName") or ""),
                "change_pct": _n(d.get("fluctuationsRatio")), "status": str(d.get("marketStatus") or ""),
                "asof": str(d.get("localTradedAt") or ""), "source": "Naver/KRX 현재가"}
    except Exception:
        return {}


def _previous_weekday(d):
    d = d - timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def _expected_trade_date(market: str) -> str:
    market = "US" if str(market).upper() == "US" else "KR"; now = datetime.now(_core.KST)
    if market == "KR":
        d = now.date()
        if d.weekday() >= 5:
            while d.weekday() >= 5: d -= timedelta(days=1)
        elif now.hour * 60 + now.minute < 9 * 60:
            d = _previous_weekday(d)
        return d.strftime("%Y%m%d")
    ny = now.astimezone(ZoneInfo("America/New_York")); d = ny.date()
    if d.weekday() >= 5:
        while d.weekday() >= 5: d -= timedelta(days=1)
    elif ny.hour * 60 + ny.minute < 9 * 60 + 30:
        d = _previous_weekday(d)
    return d.strftime("%Y%m%d")


def _regular_cash_open(market: str) -> bool:
    market = "US" if str(market).upper() == "US" else "KR"; now = datetime.now(_core.KST)
    if market == "KR":
        m = now.hour * 60 + now.minute; return now.weekday() < 5 and 540 <= m <= 930
    ny = now.astimezone(ZoneInfo("America/New_York")); m = ny.hour * 60 + ny.minute
    return ny.weekday() < 5 and 570 <= m <= 960


def _daily_bars(market: str, code: str, days: int = 60) -> tuple[list[dict], str]:
    market = "US" if str(market).upper() == "US" else "KR"; code = str(code or "").upper().strip(); days = max(20, min(120, int(days or 60)))
    q = _core.feed.q(market, code); current = _normalized_daily(list(getattr(q, "daily_bars", []) or [])); source = "NH 공식 일봉"
    saved = _normalized_daily(_load_saved_stock_bars(market, code))
    if len(current) < min(days, 20):
        try:
            fetched = _core.feed.ensure_daily_bars(market, code, max(days, 30), force=True)
            current = _normalized_daily(fetched)
        except Exception:
            pass
    if market == "KR" and len(current) < min(days, 20):
        naver = _naver_stock_bars(code, days)
        if naver:
            current = naver; source = "Naver/KRX 실제 일봉 OHLC"
            try:
                q.set_daily_bars([{"date": x["time"], "open": x["open"], "high": x["high"], "low": x["low"], "close": x["close"], "volume": x["volume"]} for x in naver])
            except Exception:
                pass
    if not current and saved:
        current = saved; source = "저장된 공식 일봉"
    # only live regular-session quote can form today's provisional candle
    expected = _expected_trade_date(market)
    try:
        quote_day = datetime.fromtimestamp(float(getattr(q, "updated_at", 0) or 0), _core.KST)
        if market == "US": quote_day = quote_day.astimezone(ZoneInfo("America/New_York"))
        quote_day = quote_day.strftime("%Y%m%d")
    except Exception:
        quote_day = ""
    if _regular_cash_open(market) and quote_day == expected and _n(getattr(q, "price", 0)) > 0 and _n(getattr(q, "open", 0)) > 0:
        live = {"time": expected, "open": _n(q.open), "high": max(_n(q.high), _n(q.open), _n(q.price)),
                "low": min(x for x in (_n(q.low), _n(q.open), _n(q.price)) if x > 0), "close": _n(q.price), "volume": _n(q.volume)}
        by = {x["time"]: x for x in current}; by[expected] = live; current = [by[k] for k in sorted(by)]
        source += " + 정규장 현재값"
    current = current[-days:]
    if current: _save_stock_bars(market, code, current)
    return current, source


def _apply_stock_meta(market: str, code: str):
    q = _core.feed.q(market, code)
    try:
        fn = (_runtime_ns or {}).get("_ensure_search_catalog"); cat = fn(market) if callable(fn) else {}; meta = cat.get(code) or {}
        if meta:
            q.name = str(meta.get("name") or q.name or code); q.sector = str(meta.get("sector") or q.sector or "")
    except Exception:
        pass
    return q


def _stock_payload(market: str, code: str, timeframe: str, days: int = 60) -> dict:
    market = "US" if str(market).upper() == "US" else "KR"; code = str(code or "").upper().strip(); tf = str(timeframe or "1d").lower(); q = _apply_stock_meta(market, code)
    try:
        d = dict(_core.stock_detail(market, code, timeframe=tf))
    except Exception:
        d = {"market": market, "code": code, "name": q.name or code, "sector": q.sector or "", "price": _n(getattr(q, "price", 0)), "scores": {}, "analysis": None, "flow": {}, "events": []}
    d["name"] = q.name or d.get("name") or code; d["sector"] = q.sector or d.get("sector") or ""
    if market == "KR" and _n(d.get("price")) <= 0:
        nq = _naver_kr_quote(code)
        if nq.get("price"):
            d["price"] = nq["price"]; d["price_display_source"] = nq.get("source")
            if nq.get("name") and (not d.get("name") or d.get("name") == code): d["name"] = nq["name"]
    if tf in ("1d", "d", "day", "일봉"):
        bars, source = _daily_bars(market, code, days); d["bars"] = bars; d["chart_source"] = source; d["chart_days"] = len(bars)
        d["default_timeframe"] = "1d"; d["chart_last_date"] = bars[-1]["time"] if bars else ""; d["chart_expected_date"] = _expected_trade_date(market); d["chart_regular_session_only"] = True
        if _n(d.get("price")) <= 0 and bars:
            d["price"] = bars[-1]["close"]; d["price_display_source"] = "최근 공식 종가"
        else:
            d.setdefault("price_display_source", "현재가")
    try:
        hist = _dart_stock_history(code, 3) if market == "KR" else _us_stock_history(code, 3)
        d["events"] = list(hist.get("items") or []); d["event_history_months"] = 3; d["event_history_source"] = hist.get("source"); d["event_history_status"] = hist.get("status") or ""
    except Exception as exc:
        d["event_history_error"] = str(exc)[:180]
    return d


def _parse_investor_payload(data) -> list[dict]:
    rows, seen = [], set()
    for d in _walk(data):
        date = _iso_date(_pick(d, ("bsop_date", "stck_bsop_date", "trade_date", "date", "xymd", "trd_dd", "bizdate", "localDate"), ""))
        if not date or date in seen:
            continue
        has = any(k in d for k in ("frgn_ntby_qty", "invest", "gigwan", "orgn_ntby_qty", "person", "prsn_ntby_qty", "foreignerPureBuyQuant", "organPureBuyQuant", "individualPureBuyQuant"))
        if not has:
            continue
        seen.add(date); rows.append({
            "date": date,
            "foreign": _n(_pick(d, ("frgn_ntby_qty", "invest", "foreignerPureBuyQuant"), 0)),
            "institution": _n(_pick(d, ("gigwan", "orgn_ntby_qty", "organPureBuyQuant"), 0)),
            "person": _n(_pick(d, ("person", "prsn_ntby_qty", "individualPureBuyQuant"), 0)),
            "program": _n(_pick(d, ("program", "prgm_ntby_qty"), 0)),
        })
    rows.sort(key=lambda x: x["date"]); return rows[-20:]


def _fetch_investor_20(code: str) -> tuple[list[dict], str]:
    try:
        from nhplug import call
        last = None
        for market_cd in _core.feed._market_order():
            try:
                data = call("/krstock/quote/v1/currentInvestor", {"market_cd": market_cd, "iem_cd": code, "array_cnt": "20"})
                rows = _parse_investor_payload(data)
                if rows: return rows, "NHPLUG currentInvestor · 20거래일"
            except Exception as exc:
                last = exc
        if last: raise last
    except Exception:
        pass
    try:
        r = _HTTP.get("https://m.stock.naver.com/front-api/stock/domestic/trend", params={"code": code}, timeout=10); r.raise_for_status()
        rows = _parse_investor_payload(r.json())
        if rows: return rows, "Naver 공개 투자자 동향 fallback"
    except Exception:
        pass
    q = _core.feed.q("KR", code); rows = _parse_investor_payload(list(getattr(q, "investor_daily", []) or []))
    return rows, "메모리 수급 캐시"


def _investor_payload(code: str) -> dict:
    code = str(code or "").upper().strip(); rows, source = _fetch_investor_20(code)
    sums = {k: sum(_n(r.get(k)) for r in rows) for k in ("foreign", "institution", "person", "program")}
    denom = sum(abs(sums[k]) for k in ("foreign", "institution", "person")) or 0.0
    shares = {k: (sums[k] / denom * 100.0 if denom else 0.0) for k in ("foreign", "institution", "person")}
    return {"ok": True, "market": "KR", "code": code, "days": len(rows), "items": rows, "sums": sums,
            "share_pct": shares, "source": source, "window": "최근 20거래일", "refreshing": False,
            "updated_at": time.time() if rows else float(getattr(_core.feed, "investor_updated_at", 0) or 0)}


def _naver_index_bars(key: str, days: int) -> tuple[list[dict], str]:
    key = str(key).lower(); now = time.time(); cache = _INDEX_CACHE.get(key)
    if cache and now - cache[0] < 120 and cache[1]: return list(cache[1])[-days:], "Naver 공식연동 지수 OHLC"
    code = {"kospi": "KOSPI", "kosdaq": "KOSDAQ", "sp500": ".INX", "nasdaq": ".IXIC", "sox": ".SOX"}.get(key)
    if not code: return [], ""
    try:
        url = f"https://api.stock.naver.com/chart/domestic/index/{code}" if key in ("kospi", "kosdaq") else f"https://api.stock.naver.com/chart/foreign/index/{code}"
        r = _HTTP.get(url, params={"periodType": "dayCandle"}, timeout=12); r.raise_for_status(); rows = _normalized_daily(list(_walk(r.json())))
        if rows: _INDEX_CACHE[key] = (now, rows[-120:])
        return rows[-days:], "Naver 공식연동 지수 OHLC"
    except Exception:
        return [], ""


def _naver_index_quote(key: str) -> dict:
    key = str(key).lower(); code = {"kospi": "KOSPI", "kosdaq": "KOSDAQ"}.get(key)
    if code:
        try:
            r = _HTTP.get(f"https://m.stock.naver.com/api/index/{code}/basic", timeout=10); r.raise_for_status(); d = r.json()
            return {"value": _n(d.get("closePrice")), "change": _n(d.get("compareToPreviousClosePrice")),
                    "change_pct": _n(d.get("fluctuationsRatio")), "status": str(d.get("marketStatus") or ""),
                    "source": "Naver/KRX 지수", "asof": str(d.get("localTradedAt") or "")}
        except Exception:
            return {}
    reuters = {"sp500": ".INX", "nasdaq": ".IXIC", "sox": ".SOX"}.get(key)
    if reuters:
        try:
            r = _HTTP.get("https://api.stock.naver.com/index/nation/USA", timeout=10); r.raise_for_status()
            for d in _walk(r.json()):
                if str(d.get("reutersCode") or "") == reuters:
                    return {"value": _n(d.get("closePrice")), "change": _n(d.get("compareToPreviousClosePrice")),
                            "change_pct": _n(d.get("fluctuationsRatio")), "status": str(d.get("marketStatus") or ""),
                            "source": "Naver 해외지수", "asof": str(d.get("localTradedAt") or "")}
        except Exception:
            pass
    return {}


def _index_status_label(key: str, open_now: bool) -> str:
    if open_now: return "정규장 거래중" if key in ("kospi", "kosdaq", "sp500", "nasdaq", "sox") else "선물 거래중"
    if key in ("kospi", "kosdaq"): return "KRX 정규장 종료/휴장"
    if key in ("sp500", "nasdaq", "sox"): return "미국 정규장 종료/휴장"
    return "선물 휴장/정산시간"


def _index_payload(market: str, key: str, days: int = 60) -> dict:
    market = "US" if str(market or "KR").upper() == "US" else "KR"; key = str(key or "").lower().strip(); days = max(20, min(120, int(days or 60)))
    allowed = {"KR": {"kospi", "kosdaq", "kospi_night", "nasdaq_future", "sox"}, "US": {"sp500", "nasdaq", "nasdaq_future", "sox"}}
    if key not in allowed[market]: return {"ok": False, "market": market, "key": key, "bars": [], "error": "index not available"}
    item = dict(_core.feed.market_item(key) or {}); bars = _normalized_daily(list(_core.feed.market_bars(key, "1d") or []))[-days:]; chart_source = str(getattr(_core.feed, "market_daily_source", {}).get(key, "") or item.get("source") or "")
    if key in ("kospi", "kosdaq", "sp500", "nasdaq", "sox") and len(bars) < min(days, 20):
        nb, ns = _naver_index_bars(key, days)
        if nb: bars, chart_source = nb, ns
    if _n(item.get("value")) <= 0 and key in ("kospi", "kosdaq", "sp500", "nasdaq", "sox"):
        nq = _naver_index_quote(key)
        if nq: item.update({"value": nq.get("value"), "change": nq.get("change"), "change_pct": nq.get("change_pct"), "status": nq.get("status"), "source": nq.get("source"), "asof": nq.get("asof")})
    open_now = bool(_core.feed.market_open_for_key(key)); label = item.get("label") or {"kospi":"코스피","kosdaq":"코스닥","sp500":"S&P500","nasdaq":"나스닥","sox":"필라델피아 반도체지수","kospi_night":"코스피 야간선물","nasdaq_future":"나스닥 선물"}.get(key,key)
    return {"ok": True, "market": market, "key": key, "label": label, "value": item.get("value"), "change": item.get("change"), "change_pct": item.get("change_pct"),
            "quote_status": item.get("status") or "", "quote_source": item.get("source") or "", "quote_asof": item.get("asof") or "",
            "market_open": open_now, "market_status": _index_status_label(key, open_now), "bars": bars, "bar_count": len(bars),
            "chart_valid_ohlc": bool(bars), "chart_source": chart_source or "공식 데이터", "chart_error": "" if bars else str(getattr(_core.feed, "market_daily_error", {}).get(key, "") or "공식 OHLC 수신 대기"),
            "chart_last_date": bars[-1]["time"] if bars else "", "chart_last_close": bars[-1]["close"] if bars else None, "chart_is_live_quote": False,
            "note": "현재 지수값과 실제 일봉 OHLC를 분리 표시합니다.", "flow_supported": market == "KR" and key in ("kospi", "kosdaq", "kospi_night")}


def _session_payload() -> dict:
    now = datetime.now(_core.KST); default = _core.default_view_market(now); nxt = _core.feed.session_state("KR") or {}
    return {"ok": True, "kst": now.isoformat(), "default_view": default, "kr_active": bool(_core.trading_window(now) == "KR"),
            "us_active": bool(_core.trading_window(now) == "US"), "nxt": nxt, "kr_close_label": "장 종료 · NXT 거래 종료"}


def _catalog_search(market: str, raw: str) -> list[dict]:
    needle = re.sub(r"[\s._/()\-]+", "", str(raw or "").casefold()); out = []
    try:
        fn = (_runtime_ns or {}).get("_ensure_search_catalog"); cat = fn(market) if callable(fn) else {}
    except Exception:
        cat = {}
    live = _core.feed.quotes_for(market)
    for code, meta in dict(cat or {}).items():
        name = str((meta or {}).get("name") or code); cn = re.sub(r"[\s._/()\-]+", "", str(code).casefold()); nn = re.sub(r"[\s._/()\-]+", "", name.casefold())
        if needle not in cn and needle not in nn: continue
        q = live.get(code); rank = 0 if needle in (cn, nn) else 1 if cn.startswith(needle) or nn.startswith(needle) else 2
        out.append({"market": market, "code": str(code), "name": name, "sector": str((meta or {}).get("sector") or ""),
                    "price": _n(getattr(q, "price", 0)) if q else 0, "tracked": bool(q), "_rank": rank})
    return out


def _naver_ac_search(raw: str) -> list[dict]:
    try:
        r = _HTTP.get("https://ac.finance.naver.com/ac", params={"q": raw, "q_enc":"UTF-8", "st":"111", "r_format":"json", "r_count":"30", "r_lt":"111", "frm":"stock"},
                      headers={"Referer":"https://finance.naver.com/"}, timeout=8); r.raise_for_status(); data = r.json()
        arr = (data.get("items") or [[]])[0] if isinstance(data, dict) else []
        out = []
        for x in arr or []:
            if not isinstance(x, (list, tuple)) or len(x) < 2: continue
            name, code = str(x[0] or "").strip(), str(x[1] or "").strip(); market_name = str(x[3] or "") if len(x) > 3 else ""
            if re.fullmatch(r"\d{6}", code) and name:
                out.append({"market":"KR", "code":code, "name":name, "sector":market_name or "국내주식", "price":0, "tracked":False, "_rank":0 if raw in (name,code) else 1})
        return out
    except Exception:
        return []


def _sec_search(raw: str) -> list[dict]:
    global _SEC_SEARCH_CACHE
    now = time.time(); rows = []
    if _SEC_SEARCH_CACHE and now - _SEC_SEARCH_CACHE[0] < 86400:
        rows = _SEC_SEARCH_CACHE[1]
    else:
        try:
            r = _HTTP.get("https://www.sec.gov/files/company_tickers.json", headers={"User-Agent":"GY-Trading-OS public-market-data contact"}, timeout=15); r.raise_for_status(); data = r.json()
            rows = [{"market":"US", "code":str(x.get("ticker") or "").upper(), "name":str(x.get("title") or x.get("ticker") or ""), "sector":"미국주식", "price":0, "tracked":False}
                    for x in data.values() if str(x.get("ticker") or "").strip()]
            _SEC_SEARCH_CACHE = (now, rows)
        except Exception:
            rows = []
    needle = re.sub(r"[\s._/()\-]+", "", raw.casefold()); out=[]
    for x in rows:
        cn = re.sub(r"[\s._/()\-]+", "", x["code"].casefold()); nn = re.sub(r"[\s._/()\-]+", "", x["name"].casefold())
        if needle in cn or needle in nn:
            y=dict(x); y["_rank"] = 0 if needle in (cn,nn) else 1 if cn.startswith(needle) or nn.startswith(needle) else 2; out.append(y)
    return out


def _search_v348(market: str, raw: str) -> dict:
    market = "US" if str(market or "KR").upper() == "US" else "KR"; raw = str(raw or "").strip()
    if not raw: return {"ok":True,"market":market,"items":[]}
    rows = _catalog_search(market, raw)
    if market == "KR": rows.extend(_naver_ac_search(raw))
    elif len(rows) < 10: rows.extend(_sec_search(raw))
    dedup={}
    for x in rows:
        code=str(x.get("code") or "").upper();
        if not code: continue
        old=dedup.get(code)
        if old is None or int(x.get("_rank",9)) < int(old.get("_rank",9)): dedup[code]=x
        elif old and not old.get("price") and x.get("price"): old["price"]=x["price"]
    out=list(dedup.values()); out.sort(key=lambda x:(int(x.get("_rank",9)),len(str(x.get("name") or "")),str(x.get("name") or ""),str(x.get("code") or "")))
    for x in out: x.pop("_rank",None)
    return {"ok":True,"market":market,"items":out[:40],"source":"NH master + Naver AC" if market=="KR" else "NH master + SEC tickers","fallback_ready":True}


def _track_v348(market: str, code: str, name: str = "", sector: str = "") -> dict:
    market = "US" if str(market or "KR").upper() == "US" else "KR"; code = str(code or "").upper().strip(); q = _core.feed.q(market, code)
    if name: q.name = str(name)
    if sector: q.sector = str(sector)
    if code not in _core.feed.code_lists[market]: _core.feed.code_lists[market].append(code)
    err=""
    try:
        from nhplug import call
        if market=="KR":
            last=None
            for market_cd in _core.feed._market_order():
                try:
                    data=call("/krstock/quote/v1/currentPrice",{"iem_cd":code,"market_cd":market_cd}); _core.feed._apply_kr(code,data)
                    if _n(q.price)>0: last=None; break
                except Exception as exc: last=exc
            if last and _n(q.price)<=0: raise last
        else:
            data=call("/gbstock/quote/v1/current",{"iem_cd":code}); _core.feed._apply_us(code,data)
    except Exception as exc:
        err=str(exc)[:180]
    display_price=_n(q.price); source="NHPLUG 현재가"
    if market=="KR" and display_price<=0:
        nq=_naver_kr_quote(code)
        if nq.get("price"): display_price=nq["price"]; source=nq.get("source") or source; q.name=q.name if q.name!=code else nq.get("name") or q.name
    bars=[]
    if market=="KR":
        bars=_naver_stock_bars(code,60)
        if bars:
            try: q.set_daily_bars([{"date":x["time"],"open":x["open"],"high":x["high"],"low":x["low"],"close":x["close"],"volume":x["volume"]} for x in bars])
            except Exception: pass
    else:
        try: bars=_core.feed.ensure_daily_bars(market,code,30)
        except Exception: bars=[]
    return {"ok":True,"market":market,"code":code,"name":q.name or name or code,"sector":q.sector or sector or "","price":display_price,"price_source":source,"daily_bars":len(bars),"quote_error":err}


def install(ns: dict):
    global _INSTALLED, _core, _v343, _runtime_ns
    if _INSTALLED: return
    _INSTALLED=True; _core=ns["core"]; _runtime_ns=ns
    import v343_features as _v343_mod
    _v343=_v343_mod

    # append the final mobile/search/sector typography layer without touching trading logic
    try:
        inject=ns.get("_inject")
        if callable(inject): inject("static/index.html", extra_css=("/static/v348.css",), scripts=("/static/v348.js",))
    except Exception as exc:
        print(f"V348 UI inject warning: {exc}", flush=True)

    @_core.app.get("/api/v348/search")
    def v348_search(market: str="KR", q: str=""):
        return _search_v348(market,q)

    @_core.app.post("/api/v348/track/{market}/{code}")
    def v348_track(market: str, code: str, name: str="", sector: str=""):
        return _track_v348(market,code,name,sector)

    @_core.app.get("/api/v344/session")
    def v344_session(): return _session_payload()

    @_core.app.get("/api/v344/disclosures")
    def v344_disclosures(market: str="KR", months: int=3, page: int=1, page_size: int=50):
        market=str(market or "KR").upper()
        if market=="US":
            try:
                d=dict(_v343._us_history_page(max(1,int(page)),max(10,min(100,int(page_size)))))
                cutoff=(datetime.now(_core.KST).date()-timedelta(days=max(1,min(3,int(months)))*31)).isoformat(); rows=[x for x in list(d.get("items") or []) if str(x.get("date") or "")>=cutoff]
                d.update({"ok":True,"items":rows,"months":min(3,int(months or 3)),"source":"SEC EDGAR","scope":d.get("scope") or "현재 추적 종목"}); return d
            except Exception as exc: return {"ok":False,"market":"US","items":[],"status":str(exc)[:180],"source":"SEC EDGAR"}
        errors=[]
        if _dart_key():
            try:
                d=_dart_market_page(months,page,page_size)
                if d.get("items"):
                    print(f"V348 DISC market source=DART count={len(d.get('items') or [])}", flush=True)
                    return d
                errors.append("DART 0건")
            except Exception as exc:
                errors.append(f"DART {type(exc).__name__}: {exc}")
        try:
            d=_naver_market_disclosures(months,page,page_size)
            if d.get("items"):
                print(f"V348 DISC market source=NAVER count={len(d.get('items') or [])}", flush=True)
                return d
            errors.append(d.get("status") or "Naver 0건")
        except Exception as exc:
            errors.append(f"Naver {type(exc).__name__}: {exc}")
        try:
            d=_dart_rss_recent()
            if d.get("items"):
                print(f"V348 DISC market source=DART_RSS count={len(d.get('items') or [])}", flush=True)
                return d
            errors.append("DART RSS 0건")
        except Exception as exc:
            errors.append(f"DART RSS {type(exc).__name__}: {exc}")
        msg=" | ".join(str(x) for x in errors if x)[:500]
        print(f"V348 DISC market FAIL {msg}", flush=True)
        return {"ok":False,"market":"KR","items":[],"status":msg or "공시 연결 실패","source":"DART/Naver fallback"}

    @_core.app.get("/api/v344/disclosures/{market}/{code}")
    def v344_stock_disclosures(market: str, code: str, months: int=3):
        try:
            d=_dart_stock_history(code,months) if str(market).upper()=="KR" else _us_stock_history(code,months)
            print(f"V348 DISC stock market={str(market).upper()} code={str(code).upper()} ok={bool(d.get('ok'))} count={len(d.get('items') or [])} source={d.get('source')}", flush=True)
            return d
        except Exception as exc:
            print(f"V348 DISC stock FAIL market={str(market).upper()} code={str(code).upper()} err={type(exc).__name__}:{exc}", flush=True)
            return {"ok":False,"market":str(market).upper(),"code":str(code).upper(),"items":[],"status":str(exc)[:180]}

    @_core.app.get("/api/v344/stock/{market}/{code}")
    def v344_stock(market: str, code: str, timeframe: str="1d", days: int=60): return _stock_payload(market,code,timeframe,days)

    @_core.app.get("/api/v344/investor-stock/{code}")
    def v344_investor_stock(code: str): return _investor_payload(code)

    @_core.app.get("/api/v344/index/{market}/{key}")
    def v344_index(market: str, key: str, days: int=60): return _index_payload(market,key,days)

    @_core.app.get("/api/v344/diagnostics/{market}/{code}")
    def v344_diagnostics(market: str, code: str):
        market2="US" if str(market).upper()=="US" else "KR"; code2=str(code or "").upper().strip(); q=_core.feed.q(market2,code2); rows=_normalized_daily(list(getattr(q,"daily_bars",[]) or [])); saved=_normalized_daily(_load_saved_stock_bars(market2,code2))
        return {"ok":True,"market":market2,"code":code2,"memory_daily_bars":len(rows),"saved_daily_bars":len(saved),"memory_last":rows[-1]["time"] if rows else "","saved_last":saved[-1]["time"] if saved else "","expected":_expected_trade_date(market2),"dart_key":bool(_dart_key()),"dart_rss_cache":bool(_DART_RSS_CACHE),"naver_bar_cache":len(_NAVER_BARS_CACHE)}


def status_snapshot() -> dict:
    return {"installed":_INSTALLED,"dart_market_cache":len(_DART_PAGE_CACHE),"dart_stock_cache":len(_DART_STOCK_CACHE),"dart_rss_cached":bool(_DART_RSS_CACHE),"naver_disc_cache":len(_NAVER_DISC_CACHE),"naver_market_disc_cache":len(_NAVER_MARKET_DISC_CACHE),"naver_bars_cache":len(_NAVER_BARS_CACHE),"index_cache":len(_INDEX_CACHE),"version":"v34.8-disclosure-hotfix"}
