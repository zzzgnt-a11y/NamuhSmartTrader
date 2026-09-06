from __future__ import annotations

import hashlib
import re
import threading
import time
from datetime import datetime, timedelta

_INSTALLED = False
_core = None
_ns = None
_track_search_stock = None
_active_alert_map = None

_LOCK = threading.RLock()
_STATE_KEY = "v34_2_disclosure_alerts"
_ITEMS: dict[str, dict] = {}
_LOADED = False
_LAST_SCAN = 0.0
_TRACK_ATTEMPT: dict[tuple[str, str], float] = {}
_BG_LOCK = threading.Lock()
_BG_STARTED = False


def _event_date_text(e: dict) -> str:
    raw = str(
        e.get("date") or e.get("rcept_dt") or e.get("filingDate")
        or e.get("accepted_date") or ""
    ).strip()
    if len(raw) >= 10 and raw[4:5] == "-" and raw[7:8] == "-":
        return raw[:10]
    digits = re.sub(r"\D", "", raw)
    if len(digits) >= 8:
        return f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}"
    return ""


def _event_time_text(e: dict) -> str:
    raw = str(e.get("time") or e.get("rcept_time") or e.get("accepted_time") or "").strip()
    if not raw:
        return ""
    digits = re.sub(r"\D", "", raw)
    if len(digits) >= 6:
        return f"{digits[:2]}:{digits[2:4]}:{digits[4:6]}"
    if len(digits) >= 4:
        return f"{digits[:2]}:{digits[2:4]}"
    return raw[:12]


def _material(e: dict) -> bool:
    if bool(e.get("blocked")):
        return True
    sentiment = str(e.get("sentiment") or "").lower()
    if sentiment in ("positive", "negative"):
        return True
    try:
        return abs(float(e.get("score") or 0)) > 0
    except Exception:
        return False


def _normalize(market: str, e: dict) -> dict | None:
    market = "US" if str(market).upper() == "US" else "KR"
    if not isinstance(e, dict) or not _material(e):
        return None
    code = str(
        e.get("code") or e.get("stock_code") or e.get("iem_cd")
        or e.get("ticker") or ""
    ).upper().strip()
    title = str(e.get("title") or e.get("report_nm") or e.get("form") or "").strip()
    if not code or not title:
        return None
    sentiment = str(e.get("sentiment") or "").lower()
    blocked = bool(e.get("blocked"))
    if blocked:
        sentiment = "negative"
    if sentiment not in ("positive", "negative"):
        try:
            sentiment = "positive" if float(e.get("score") or 0) > 0 else "negative"
        except Exception:
            return None
    score = -5.0 if sentiment == "negative" else 5.0
    date = _event_date_text(e)
    tm = _event_time_text(e)
    name = str(
        e.get("corp_name") or e.get("name") or e.get("company_name")
        or e.get("corp") or code
    ).strip()
    source = str(e.get("source") or ("SEC EDGAR" if market == "US" else "DART")).strip()
    url = str(e.get("url") or e.get("link") or "").strip()
    label = str(
        e.get("label") or (
            "강한 악재" if blocked else ("호재" if score > 0 else "악재")
        )
    ).strip()
    stable = "|".join((market, code, date, title, url))
    alert_id = hashlib.sha1(stable.encode("utf-8", "ignore")).hexdigest()[:24]
    return {
        "id": alert_id, "market": market, "code": code, "name": name or code,
        "title": title, "date": date, "time": tm, "source": source, "url": url,
        "sentiment": sentiment, "label": label, "score": score, "blocked": blocked,
    }


def _load_state():
    global _LOADED, _ITEMS
    with _LOCK:
        if _LOADED:
            return
        raw = _core.store.load_json(_STATE_KEY, {"items": []}) or {"items": []}
        rows = raw.get("items") if isinstance(raw, dict) else raw
        out = {}
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            rid = str(row.get("id") or "").strip()
            if rid:
                out[rid] = dict(row)
        _ITEMS = out
        _LOADED = True


def _save_state():
    global _ITEMS
    _load_state()
    with _LOCK:
        rows = list(_ITEMS.values())
        # Requirement: unread alerts never expire automatically.
        unread = [x for x in rows if not bool(x.get("read"))]
        read = [x for x in rows if bool(x.get("read"))]
        read.sort(
            key=lambda x: float(x.get("read_at") or x.get("detected_at") or 0),
            reverse=True,
        )
        rows = unread + read[:300]
        rows.sort(
            key=lambda x: (
                str(x.get("date") or ""), str(x.get("time") or ""),
                float(x.get("detected_at") or 0),
            ),
            reverse=True,
        )
        _ITEMS = {str(x["id"]): x for x in rows if x.get("id")}
        _core.store.save_json(_STATE_KEY, {"version": 1, "items": rows})


def _ingest(market: str, events) -> int:
    _load_state()
    now = time.time()
    # Prevent an initial boot from filling the unread rail with old history,
    # while still covering Friday/weekend disclosures on Monday.
    fresh_cutoff = (datetime.now(_core.KST) - timedelta(days=7)).strftime("%Y-%m-%d")
    changed = False
    added = 0
    with _LOCK:
        for e in events or []:
            row = _normalize(market, e)
            if not row:
                continue
            if row.get("date") and row["date"] < fresh_cutoff and row["id"] not in _ITEMS:
                continue
            old = _ITEMS.get(row["id"])
            if old:
                merged = dict(old)
                keep_read = bool(old.get("read"))
                keep_read_at = float(old.get("read_at") or 0)
                keep_detected = float(old.get("detected_at") or now)
                merged.update(row)
                merged["read"] = keep_read
                merged["read_at"] = keep_read_at
                merged["detected_at"] = keep_detected
                if merged != old:
                    _ITEMS[row["id"]] = merged
                    changed = True
            else:
                row.update({"read": False, "read_at": 0.0, "detected_at": now})
                _ITEMS[row["id"]] = row
                changed = True
                added += 1
    if changed:
        _save_state()
    return added


def _collect_once():
    global _LAST_SCAN
    kr_events = []
    us_events = []
    try:
        state = _core.events.state("KR") or {}
        kr_events.extend(list(state.get("items") or []))
    except Exception:
        pass
    try:
        for q0 in list(_core.feed.quotes_for("KR").values()):
            kr_events.extend(list(getattr(q0, "events", []) or []))
    except Exception:
        pass
    try:
        sec_lock = _ns.get("_SEC_LOCK")
        if sec_lock:
            with sec_lock:
                us_events.extend(list(_ns.get("_US_EVENTS") or []))
        else:
            us_events.extend(list(_ns.get("_US_EVENTS") or []))
    except Exception:
        pass
    try:
        for q0 in list(_core.feed.quotes_for("US").values()):
            us_events.extend(list(getattr(q0, "events", []) or []))
    except Exception:
        pass
    _ingest("KR", kr_events)
    _ingest("US", us_events)
    _LAST_SCAN = time.time()


def _market_open(market: str) -> bool:
    market = "US" if str(market).upper() == "US" else "KR"
    try:
        return bool(_core.feed.market_open_for_key("sp500" if market == "US" else "kospi"))
    except Exception:
        now = datetime.now(_core.KST)
        if market == "KR":
            mins = now.hour * 60 + now.minute
            return now.weekday() < 5 and 9 * 60 <= mins <= 15 * 60 + 30
        try:
            from zoneinfo import ZoneInfo
            ny = now.astimezone(ZoneInfo("America/New_York"))
            mins = ny.hour * 60 + ny.minute
            return ny.weekday() < 5 and 9 * 60 + 30 <= mins <= 16 * 60
        except Exception:
            return False


def _previous_weekday(now_dt: datetime) -> str:
    d = now_dt.date() - timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d.isoformat()


def focus_map(market: str) -> dict[str, dict]:
    market = "US" if str(market).upper() == "US" else "KR"
    # Weekend/closed-session rule: collect and alert, but do not focus/analyze
    # the affected stock until that market is open.
    if not _market_open(market):
        return {}
    _load_state()
    now_dt = datetime.now(_core.KST)
    cutoff = _previous_weekday(now_dt)
    today = now_dt.date().isoformat()
    out: dict[str, dict] = {}
    with _LOCK:
        rows = list(_ITEMS.values())
    for row in rows:
        if row.get("market") != market:
            continue
        d = str(row.get("date") or "")
        if not d:
            try:
                d = datetime.fromtimestamp(
                    float(row.get("detected_at") or 0), _core.KST
                ).date().isoformat()
            except Exception:
                d = ""
        if not d or d < cutoff or d > today:
            continue
        code = str(row.get("code") or "").upper()
        if not code:
            continue
        old = out.get(code)
        if old is None or (
            str(row.get("date") or ""), str(row.get("time") or "")
        ) > (
            str(old.get("date") or ""), str(old.get("time") or "")
        ):
            out[code] = dict(row)
    return out


def _warm_focus():
    now = time.time()
    for market in ("KR", "US"):
        focus = focus_map(market)
        rows = sorted(
            focus.values(),
            key=lambda x: (
                bool(x.get("blocked")), str(x.get("date") or ""),
                str(x.get("time") or ""),
            ),
            reverse=True,
        )[:12]
        for row in rows:
            code = str(row.get("code") or "").upper()
            key = (market, code)
            if now - float(_TRACK_ATTEMPT.get(key, 0) or 0) < 300:
                continue
            _TRACK_ATTEMPT[key] = now
            try:
                _track_search_stock(market, code)
            except Exception:
                try:
                    q0 = _core.feed.q(market, code)
                    q0.name = str(row.get("name") or q0.name or code)
                    if code not in _core.feed.code_lists[market]:
                        _core.feed.code_lists[market].append(code)
                except Exception:
                    pass


def _api_rows(market: str) -> tuple[list[dict], bool]:
    market = "US" if str(market).upper() == "US" else "KR"
    _collect_once()
    _load_state()
    market_open = _market_open(market)
    focus = focus_map(market) if market_open else {}
    with _LOCK:
        rows = [
            dict(x) for x in _ITEMS.values()
            if x.get("market") == market and not bool(x.get("read"))
        ]
    rows.sort(
        key=lambda x: (
            str(x.get("date") or ""), str(x.get("time") or ""),
            float(x.get("detected_at") or 0),
        ),
        reverse=True,
    )
    for row in rows:
        row["focus_active"] = str(row.get("code") or "").upper() in focus
        row["focus_label"] = (
            "집중분석 중" if row["focus_active"] else "다음 거래일 장중 집중분석"
        )
    return rows, market_open


def mark_read(alert_id: str) -> dict:
    _load_state()
    alert_id = str(alert_id or "").strip()
    changed = False
    row = None
    with _LOCK:
        if alert_id in _ITEMS:
            row = _ITEMS[alert_id]
            if not bool(row.get("read")):
                row["read"] = True
                row["read_at"] = time.time()
                changed = True
    if changed:
        _save_state()
    return {
        "ok": row is not None,
        "id": alert_id,
        "read": bool(row.get("read")) if row else False,
        "analysis_priority_independent_of_read": True,
    }


def status_snapshot() -> dict:
    _load_state()
    with _LOCK:
        unread = sum(1 for x in _ITEMS.values() if not bool(x.get("read")))
    return {
        "unread": unread,
        "last_scan": _LAST_SCAN,
        "persist_until_read": True,
        "focus_kr": len(focus_map("KR")),
        "focus_us": len(focus_map("US")),
    }


def _loop():
    time.sleep(3)
    while True:
        try:
            _collect_once()
            _warm_focus()
        except Exception:
            pass
        time.sleep(30)


def install(namespace: dict):
    global _INSTALLED, _core, _ns, _track_search_stock, _active_alert_map, _BG_STARTED
    if _INSTALLED:
        return
    _INSTALLED = True
    _ns = namespace
    _core = namespace["core"]
    _track_search_stock = namespace["_track_search_stock"]
    _active_alert_map = namespace["_active_alert_map"]

    # Layer disclosure focus after the v34.1 abnormal-flow sorter.  Read state
    # never participates in this ranking, by design.
    prev_rebuild = _core.rebuild_cache

    def rebuild_cache_v342(market, now=None):
        scalp, smart = prev_rebuild(market, now)
        market2 = str(market or "KR").upper()
        if market2 not in ("KR", "US"):
            return scalp, smart
        focus = focus_map(market2)
        if not focus:
            return scalp, smart
        flow = _active_alert_map() if market2 == "KR" else {}

        def decorate_and_sort(rows):
            for item in rows:
                code = str(item.get("code") or "").upper()
                ev = focus.get(code)
                if ev:
                    item["disclosure_focus"] = {
                        "active": True, "id": ev.get("id"), "label": ev.get("label"),
                        "score": ev.get("score"), "blocked": bool(ev.get("blocked")),
                        "date": ev.get("date"), "title": ev.get("title"),
                    }
            rows.sort(
                key=lambda x: (
                    str(x.get("code") or "").upper() in focus,
                    bool(focus.get(str(x.get("code") or "").upper(), {}).get("blocked")),
                    abs(float(focus.get(str(x.get("code") or "").upper(), {}).get("score") or 0)),
                    str(x.get("code") or "").upper() in flow,
                    float(flow.get(str(x.get("code") or "").upper(), {}).get("priority_score", 0) or 0),
                    float(x.get("score", 0) or 0) >= 72,
                    float(x.get("priority_score", x.get("score", 0)) or 0),
                    float(x.get("score", 0) or 0),
                ),
                reverse=True,
            )

        decorate_and_sort(scalp)
        if market2 == "KR":
            decorate_and_sort(smart)
        with _core.cache_lock:
            _core.CACHE[market2]["scalp"] = list(scalp[:50])
            if market2 == "KR":
                _core.CACHE[market2]["smart"] = list(smart[:50])
        return scalp, smart

    _core.rebuild_cache = rebuild_cache_v342

    @_core.app.get("/api/v34/disclosure-alerts")
    def disclosure_alerts(market: str = "KR"):
        market2 = _core.normalize_market(market)
        if market2 not in ("KR", "US"):
            return {
                "market": market2, "items": [], "unread_total": 0,
                "market_open": False, "persist_until_read": True,
            }
        rows, market_open = _api_rows(market2)
        return {
            "ok": True, "market": market2, "items": rows[:20],
            "unread_total": len(rows), "market_open": market_open,
            "last_scan": _LAST_SCAN, "persist_until_read": True,
        }

    @_core.app.post("/api/v34/disclosure-alerts/{alert_id}/read")
    def read_disclosure_alert(alert_id: str):
        return mark_read(alert_id)

    prev_start = _core.start_background

    def start_background_v342():
        global _BG_STARTED
        prev_start()
        with _BG_LOCK:
            if _BG_STARTED:
                return
            _BG_STARTED = True
            threading.Thread(target=_loop, daemon=True).start()

    _core.start_background = start_background_v342
