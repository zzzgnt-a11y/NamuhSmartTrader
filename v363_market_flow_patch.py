from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))
_LOCK = threading.RLock()
_CACHE = {"ts": 0.0, "payload": None}


def _num(v):
    try:
        return float(str(v or 0).replace(",", "").replace("+", "").strip())
    except Exception:
        return 0.0


def _rows(data):
    if not isinstance(data, dict):
        return []
    for key in ("output", "OutBlock_1", "output1", "block1", "result", "Output_0", "output_0"):
        v = data.get(key)
        if isinstance(v, list):
            return v
    for v in data.values():
        if isinstance(v, list) and v and isinstance(v[0], dict):
            return v
    return []


def _digits(v):
    return "".join(ch for ch in str(v or "") if ch.isdigit())[:8]


def _daily_market_flow(core, mkt_id: str):
    now = datetime.now(KST)
    end = now.strftime("%Y%m%d")
    start = (now - timedelta(days=14)).strftime("%Y%m%d")
    # Match the known KRX MDCSTAT02202 request shape used by pykrx.  The ETF,
    # ETN and ELW fields must be present even when excluded.  money=1 keeps the
    # returned trading value in won so the UI can format it without guessing.
    payload = {
        "bld": "dbms/MDC/STAT/standard/MDCSTAT02202",
        "strtDd": start,
        "endDd": end,
        "mktId": mkt_id,
        "etf": "",
        "etn": "",
        "elw": "",
        "inqTpCd": "2",
        "trdVolVal": "2",
        "askBid": "3",
        "money": "1",
        "csvxls_isNo": "false",
    }
    data = core.feed._krx_post(payload)
    rows = [x for x in _rows(data) if isinstance(x, dict)]
    if not rows:
        raise RuntimeError("KRX 투자자별 거래실적 응답 없음")
    rows.sort(key=lambda x: _digits(x.get("TRD_DD") or x.get("BAS_DD")), reverse=True)
    row = rows[0]
    d = _digits(row.get("TRD_DD") or row.get("BAS_DD")) or end
    return {
        "institution": _num(row.get("TRDVAL1") or row.get("ORG_NTBY_TRDVAL") or row.get("INST_NET")),
        "person": _num(row.get("TRDVAL3") or row.get("PRSN_NTBY_TRDVAL") or row.get("PERSON_NET")),
        "foreign": _num(row.get("TRDVAL4") or row.get("FRGN_NTBY_TRDVAL") or row.get("FOREIGN_NET")),
        "date": f"{d[:4]}-{d[4:6]}-{d[6:8]}" if len(d) == 8 else str(row.get("TRD_DD") or ""),
    }


def _from_v343_cache(core):
    """Reuse only previously persisted KRX-origin market flow, never fake zeroes."""
    markets = {}
    try:
        import v343_features as vf
        raw = dict(getattr(vf, "_MARKET_FLOW", {}) or {})
    except Exception:
        raw = {}
    if not raw:
        try:
            saved = core.store.load_json("v343_market_flow", {}) or {}
            raw = dict(saved.get("markets") or {}) if isinstance(saved, dict) else {}
        except Exception:
            raw = {}
    for label, key in (("KOSPI", "kospi"), ("KOSDAQ", "kosdaq")):
        row = raw.get(key) or {}
        latest = row.get("latest") or {}
        if not latest:
            daily = list(row.get("daily") or [])
            latest = daily[-1] if daily else {}
        if latest:
            markets[label] = {
                "foreign": _num(latest.get("foreign")),
                "institution": _num(latest.get("institution")),
                "person": _num(latest.get("person")),
                "date": str(row.get("asof") or latest.get("date") or ""),
            }
    if len(markets) != 2:
        return None
    asof = min(str(markets[k].get("date") or "") for k in markets)
    return {
        "ok": True,
        "asof": asof,
        "updated_hm": datetime.now(KST).strftime("%H:%M"),
        "source": "KRX 투자자별 거래실적 · 공식 캐시",
        "unit": "KRW",
        "markets": markets,
        "stale": True,
    }


def _build(core):
    now = datetime.now(KST)
    markets = {
        "KOSPI": _daily_market_flow(core, "STK"),
        "KOSDAQ": _daily_market_flow(core, "KSQ"),
    }
    dates = [str(x.get("date") or "") for x in markets.values() if x.get("date")]
    return {
        "ok": True,
        "asof": min(dates) if dates else now.strftime("%Y-%m-%d"),
        "updated_hm": now.strftime("%H:%M"),
        "source": "KRX 투자자별 거래실적",
        "unit": "KRW",
        "markets": markets,
        "stale": False,
    }


def apply(ns):
    core = ns.get("core") if isinstance(ns, dict) else None
    if core is None or getattr(core, "_V363_MARKET_FLOW_PATCHED", False):
        return
    core._V363_MARKET_FLOW_PATCHED = True

    @core.app.get("/api/v363/kr-market-flow")
    def v363_kr_market_flow():
        now = time.time()
        with _LOCK:
            if _CACHE["payload"] is not None and now - float(_CACHE["ts"] or 0) < 60:
                return _CACHE["payload"]
        try:
            out = _build(core)
        except Exception as exc:
            out = _from_v343_cache(core)
            if out:
                out = {**out, "error": str(exc)[:180]}
            else:
                with _LOCK:
                    old = _CACHE.get("payload")
                if old:
                    return {**old, "stale": True, "error": str(exc)[:180]}
                return {"ok": False, "error": str(exc)[:180], "markets": {}}
        with _LOCK:
            _CACHE["payload"] = out
            _CACHE["ts"] = now
        return out

    # Final runtime layer: function/data stability only. It deliberately leaves
    # every existing site design, control and option position unchanged.
    try:
        import namuh_v367_unified
        namuh_v367_unified.apply(ns)
    except Exception as exc:
        print("NAMUH V367 INSTALL ERROR:", str(exc)[:240], flush=True)
