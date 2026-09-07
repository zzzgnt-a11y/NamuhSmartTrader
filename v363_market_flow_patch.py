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
    for key in ("output", "OutBlock_1", "block1", "result", "Output_0", "output_0"):
        v = data.get(key)
        if isinstance(v, list):
            return v
    for v in data.values():
        if isinstance(v, list) and v and isinstance(v[0], dict):
            return v
    return []


def _daily_market_flow(core, mkt_id: str):
    d = datetime.now(KST).strftime("%Y%m%d")
    payload = {
        "bld": "dbms/MDC/STAT/standard/MDCSTAT02202",
        "inqTpCd": "2",       # daily trend
        "trdVolVal": "2",     # trading value
        "askBid": "3",        # net purchase
        "mktId": mkt_id,
        "strtDd": d,
        "endDd": d,
        "money": "3",
        "csvxls_isNo": "false",
    }
    data = core.feed._krx_post(payload)
    rows = _rows(data)
    row = None
    for x in rows:
        if not isinstance(x, dict):
            continue
        if str(x.get("TRD_DD") or x.get("BAS_DD") or "").replace("/", "").replace("-", "")[:8] == d:
            row = x
            break
    if row is None and rows:
        row = rows[0]
    if not isinstance(row, dict):
        raise RuntimeError("KRX 투자자별 거래실적 응답 없음")
    # MDCSTAT02202 general view: institution / other corporation / person /
    # foreign / total. Values are net trading values because askBid=3.
    return {
        "institution": _num(row.get("TRDVAL1") or row.get("ORG_NTBY_TRDVAL") or row.get("INST_NET")),
        "person": _num(row.get("TRDVAL3") or row.get("PRSN_NTBY_TRDVAL") or row.get("PERSON_NET")),
        "foreign": _num(row.get("TRDVAL4") or row.get("FRGN_NTBY_TRDVAL") or row.get("FOREIGN_NET")),
        "date": str(row.get("TRD_DD") or d),
    }


def _build(core):
    now = datetime.now(KST)
    markets = {
        "KOSPI": _daily_market_flow(core, "STK"),
        "KOSDAQ": _daily_market_flow(core, "KSQ"),
    }
    return {
        "ok": True,
        "asof": now.strftime("%Y-%m-%d"),
        "updated_hm": now.strftime("%H:%M"),
        "source": "KRX 투자자별 거래실적",
        "unit": "KRW",
        "markets": markets,
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
            with _LOCK:
                _CACHE["payload"] = out
                _CACHE["ts"] = now
            return out
        except Exception as exc:
            with _LOCK:
                old = _CACHE.get("payload")
            if old:
                return {**old, "stale": True, "error": str(exc)[:180]}
            return {"ok": False, "error": str(exc)[:180], "markets": {}}
