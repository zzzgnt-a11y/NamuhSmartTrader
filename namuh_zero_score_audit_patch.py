from __future__ import annotations

from collections import deque
from copy import copy
from datetime import datetime, timedelta
from queue import Queue, Full, Empty
from zoneinfo import ZoneInfo
from pathlib import Path
import threading
import time

_INSTALLED = False
_Q: Queue = Queue(maxsize=32)
_PENDING: set[tuple[str, str, int]] = set()
_LOCK = threading.RLock()
_WORKERS_STARTED = False
_STATS = {"queued": 0, "done": 0, "failed": 0}


def _f(v, default=0.0):
    try:
        return float(str(v).replace(",", "").replace("+", "").strip())
    except Exception:
        return float(default)


def _digits(v):
    return "".join(ch for ch in str(v or "") if ch.isdigit())


def _walk(v):
    if isinstance(v, dict):
        yield v
        for x in v.values():
            yield from _walk(x)
    elif isinstance(v, (list, tuple)):
        for x in v:
            yield from _walk(x)


def _first(obj, keys):
    for k in keys:
        if k in obj and obj[k] not in (None, ""):
            return obj[k]
    return None


def _row_clock(row):
    ds = _digits(_first(row, ("bsop_date", "stck_bsop_date", "qry_date", "trade_date", "xymd", "date")))
    ts = _digits(_first(row, ("bsop_time", "stck_cntg_hour", "qry_time", "trade_time", "xytm", "time")))
    if len(ds) < 8:
        return "", -1
    ds = ds[:8]
    if len(ts) >= 4:
        hh, mm = int(ts[:2]), int(ts[2:4])
        if 0 <= hh <= 23 and 0 <= mm <= 59:
            return ds, hh * 60 + mm
    return ds, -1


def _cumulative_from_response(data, target_date: str, target_minute: int):
    # Prefer true cumulative-volume fields. If the endpoint only exposes per-bar
    # volume, sum each unique minute once. This prevents cumulative fields from
    # being accidentally summed as if they were minute volumes.
    cumulative = []
    incremental = {}
    for row in _walk(data):
        if not isinstance(row, dict):
            continue
        d, minute = _row_clock(row)
        if d != target_date or minute < 0 or minute > target_minute:
            continue
        cv = _f(_first(row, ("acml_vol", "acvol", "cum_volume", "acc_volume", "total_volume")))
        if cv > 0:
            cumulative.append((minute, cv))
            continue
        iv = _f(_first(row, ("vol", "movolume", "volume", "trade_volume", "trqu")))
        if iv >= 0:
            incremental[minute] = max(incremental.get(minute, 0.0), iv)
    if cumulative:
        return max(cumulative, key=lambda x: x[0])[1]
    if incremental:
        return sum(v for k, v in incremental.items() if k <= target_minute)
    return 0.0


def _date_candidates(now_local, n=28):
    d = now_local.date() - timedelta(days=1)
    out = []
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.strftime("%Y%m%d"))
        d -= timedelta(days=1)
    return out


def _fetch_session_cum(core, market: str, code: str, date: str, minute: int):
    from nhplug import call
    market = str(market).upper()
    code = str(code).upper()
    if market == "KR":
        orders = ["KRX"]
        try:
            for x in list(core.feed._market_order() or []):
                x = str(x or "").upper()
                if x and x not in orders:
                    orders.append(x)
        except Exception:
            pass
        if "NXT" not in orders:
            orders.append("NXT")
        for market_cd in orders:
            try:
                data = call("/krstock/quote/v1/period", {
                    "market_cd": market_cd, "iem_cd": code, "mrkt_div_cls_code": "", "edate": date,
                    "array_cnt": "0720", "maxavg": "000", "gubun": "5", "xtick": "001",
                    "today_cls_code": "0", "fake_tick": "0", "sur_flag": "0", "sur_gb_day_cnt": "00",
                    "sur_bf_end_time": "", "out1_scale_change": "0", "out2_scale_change": "0",
                }, timeout=8, raise_on_error=False)
                val = _cumulative_from_response(data, date, minute)
                if val > 0:
                    return val
            except Exception:
                continue
        return 0.0
    try:
        data = call("/gbstock/quote/v1/period", {
            "iem_cd": code, "end_dt": date, "count": "0720", "maxavg": "000",
            "gubun": "2", "xtick": "0001", "today_cls": "0", "market_cls": "1",
        }, timeout=8, raise_on_error=False)
        return _cumulative_from_response(data, date, minute)
    except Exception:
        return 0.0


def _session_active(c, market, now):
    dt = c._market_clock(market, now)
    m = dt.hour * 60 + dt.minute
    if str(market).upper() == "KR":
        return 9 * 60 <= m <= 15 * 60 + 30
    return 9 * 60 + 30 <= m <= 16 * 60


def _seed_from_shared_cache(c, volume_state, market, code, now):
    # Reuse any official 1m history that is already in the shared minute cache.
    # This is exact for rows whose volume is minute-volume; monotonic rows are
    # treated as cumulative volume and use the latest value.
    try:
        import namuh_minute_data_patch as mdp
        cached = mdp._CACHE.get((str(market).upper(), str(code).upper()))
        rows = list(cached[1] if cached else [])
    except Exception:
        rows = []
    if not rows:
        return 0
    dt = c._market_clock(market, now)
    today = dt.strftime("%Y%m%d")
    minute = dt.hour * 60 + dt.minute
    groups = {}
    for b in rows:
        if not isinstance(b, dict):
            continue
        s = _digits(b.get("time") or b.get("datetime") or b.get("date"))
        if len(s) < 12:
            continue
        d = s[:8]
        if d >= today:
            continue
        mm = int(s[8:10]) * 60 + int(s[10:12])
        if mm <= minute:
            groups.setdefault(d, []).append((mm, _f(b.get("volume"))))
    mkt = str(market).upper(); cd = str(code).upper()
    md = volume_state.setdefault(mkt, {}).setdefault(cd, {})
    added = 0
    for d, vals in groups.items():
        vals = sorted((x for x in vals if x[1] >= 0), key=lambda x: x[0])
        if not vals:
            continue
        vs = [x[1] for x in vals]
        monotonic = len(vs) >= 3 and sum(1 for i in range(1, len(vs)) if vs[i] >= vs[i-1]) >= len(vs) - 2
        cum = vs[-1] if monotonic else sum(vs)
        if cum > 0:
            md.setdefault(d, {})[str(minute)] = float(cum)
            added += 1
    return added


def _backfill_job(job):
    c, core, volume_state, market, code, minute, now = job
    key = (market, code, minute)
    try:
        dt = c._market_clock(market, now)
        got = 0
        mkt = str(market).upper(); cd = str(code).upper()
        md = volume_state.setdefault(mkt, {}).setdefault(cd, {})
        for d in _date_candidates(dt, 30):
            existing = _f((md.get(d) or {}).get(str(minute)))
            if existing > 0:
                got += 1
            else:
                v = _fetch_session_cum(core, mkt, cd, d, minute)
                if v > 0:
                    with _LOCK:
                        md.setdefault(d, {})[str(minute)] = float(v)
                    got += 1
                time.sleep(0.03)
            if got >= 15:
                break
        with _LOCK:
            if got >= 15:
                _STATS["done"] += 1
            else:
                _STATS["failed"] += 1
    except Exception:
        with _LOCK:
            _STATS["failed"] += 1
    finally:
        with _LOCK:
            _PENDING.discard(key)


def _worker():
    while True:
        try:
            job = _Q.get(timeout=1)
        except Empty:
            continue
        try:
            _backfill_job(job)
        finally:
            _Q.task_done()


def _start_workers():
    global _WORKERS_STARTED
    if _WORKERS_STARTED:
        return
    _WORKERS_STARTED = True
    for i in range(2):
        threading.Thread(target=_worker, daemon=True, name=f"volume15-backfill-{i+1}").start()


def _schedule_backfill(c, core, volume_state, market, code, now, nonvol_raw):
    if nonvol_raw < 15 or not _session_active(c, market, now):
        return False
    dt = c._market_clock(market, now)
    minute = dt.hour * 60 + dt.minute
    key = (str(market).upper(), str(code).upper(), minute)
    with _LOCK:
        if key in _PENDING:
            return True
        if _Q.full():
            return False
        _PENDING.add(key)
        _STATS["queued"] += 1
    try:
        _Q.put_nowait((c, core, volume_state, key[0], key[1], minute, now))
        return True
    except Full:
        with _LOCK:
            _PENDING.discard(key)
        return False


def _build_calc_quote(core, market, q):
    temp = copy(q)
    prices = [_f(x) for x in list(getattr(q, "prices", []) or []) if _f(x) > 0]
    source = "live_ticks"
    if len(prices) < 20:
        best = []
        best_tf = ""
        for tf in ("1m", "3m", "5m", "20m"):
            try:
                rows = [x for x in list(core.feed.bars(market, q.code, tf) or []) if isinstance(x, dict) and _f(x.get("close")) > 0]
            except Exception:
                rows = []
            if len(rows) > len(best):
                best, best_tf = rows, tf
            if len(rows) >= 20:
                break
        if best:
            prices = [_f(x.get("close")) for x in best[-160:] if _f(x.get("close")) > 0]
            source = f"official_{best_tf}_bars"
    px = _f(getattr(q, "price", 0))
    if px > 0 and (not prices or abs(prices[-1] - px) > max(1e-9, abs(px) * 1e-10)):
        prices.append(px)
    temp.prices = deque(prices[-480:], maxlen=480)

    daily = [dict(x) for x in list(getattr(q, "daily_bars", []) or []) if isinstance(x, dict) and _f(x.get("close")) > 0]
    if len(daily) < 10:
        try:
            if str(market).upper() == "KR" and callable(getattr(core.feed, "_fetch_kr_daily", None)):
                rows = list(core.feed._fetch_kr_daily(q.code, 30) or [])
            else:
                rows = list(core.feed.bars(market, q.code, "1d") or [])
            rows = [dict(x) for x in rows if isinstance(x, dict) and _f(x.get("close")) > 0]
            if len(rows) > len(daily):
                daily = rows
        except Exception:
            pass
    temp.daily_bars = daily
    return temp, source


def _patch_score_ui():
    # Show DATA_MISSING as '대기', not as a fake 0.0 score.
    root = Path(__file__).resolve().parent
    p = root / "static" / "stock.js"
    if not p.exists():
        return
    text = p.read_text(encoding="utf-8")
    old = '''function v366Metric(label,value,max){
 const n=num(value),mx=Math.max(.01,num(max)),w=Math.max(0,Math.min(100,n/mx*100));
 return `<div class="v366-metric"><div class="v366-metric-line"><span>${esc(label)}</span><b>${n.toFixed(1)}/${mx}</b></div><div class="v366-meter"><i style="width:${w}%"></i></div></div>`
}'''
    new = '''function v366Metric(label,value,max,status=''){
 const n=num(value),mx=Math.max(.01,num(max)),missing=status==='DATA_MISSING',zero=status==='RECIPE_ZERO',w=missing?0:Math.max(0,Math.min(100,n/mx*100));
 const val=missing?`대기/${mx}`:`${n.toFixed(1)}/${mx}`;
 const tag=missing?'<em class="v366-status missing">자료대기</em>':(zero?'<em class="v366-status zero">조건상 0점</em>':'');
 return `<div class="v366-metric ${missing?'missing':zero?'recipe-zero':''}"><div class="v366-metric-line"><span>${esc(label)}${tag}</span><b>${val}</b></div><div class="v366-meter"><i style="width:${w}%"></i></div></div>`
}'''
    if old in text:
        text = text.replace(old, new, 1)
    text = text.replace(
        "const sc=d.strategy_conditions||{},c1=sc.condition1||{},b=c1.breakdown||{},raw=c1.standard_raw||{},g=c1.gates||{};",
        "const sc=d.strategy_conditions||{},c1=sc.condition1||{},b=c1.breakdown||{},raw=c1.standard_raw||{},g=c1.gates||{},audit=c1.zero_audit||{};",
        1,
    )
    repl = {
        "${v366Metric('일봉',b.daily10,10)}": "${v366Metric('일봉',b.daily10,10,audit['일봉'])}",
        "${v366Metric('분봉',b.minute10,10)}": "${v366Metric('분봉',b.minute10,10,audit['분봉'])}",
        "${v366Metric('체결강도',b.execution12,12)}": "${v366Metric('체결강도',b.execution12,12,audit['체결강도'])}",
        "${v366Metric('호가',b.orderbook8,8)}": "${v366Metric('호가',b.orderbook8,8,audit['호가'])}",
        "${v366Metric('MACD',raw.MACD,10)}": "${v366Metric('MACD',raw.MACD,10,audit['MACD'])}",
        "${v366Metric('RSI',raw.RSI,10)}": "${v366Metric('RSI',raw.RSI,10,audit['RSI'])}",
        "${v366Metric('볼린저',raw['볼린저'],10)}": "${v366Metric('볼린저',raw['볼린저'],10,audit['볼린저'])}",
        "${v366Metric('거래량',raw['거래량'],15)}": "${v366Metric('거래량',raw['거래량'],15,audit['거래량'])}",
        "${v366Metric('이동평균',raw['이평'],10)}": "${v366Metric('이동평균',raw['이평'],10,audit['이평'])}",
        "${v366Metric('가격구조',raw['가격구조'],10)}": "${v366Metric('가격구조',raw['가격구조'],10,audit['가격구조'])}",
        "${v366Metric('엘리어트',raw['엘리어트'],10)}": "${v366Metric('엘리어트',raw['엘리어트'],10,audit['엘리어트'])}",
        "${v366Metric('섹터 상대강도',b.sector_relative7_5,7.5)}": "${v366Metric('섹터 상대강도',b.sector_relative7_5,7.5,audit['섹터 상대강도'])}",
        "${v366Metric('주도섹터 수급',b.leading_sector_flow3_75,3.75)}": "${v366Metric('주도섹터 수급',b.leading_sector_flow3_75,3.75,audit['주도섹터 수급'])}",
        "${v366Metric('뉴스 / 공시',b.news3_75,3.75)}": "${v366Metric('뉴스 / 공시',b.news3_75,3.75,audit['뉴스/공시'])}",
    }
    for a, b in repl.items():
        text = text.replace(a, b, 1)
    text = text.replace(
        '<div class="v366-score-total">${total.toFixed(1)} <span>/ 100</span></div>',
        '<div class="v366-score-total">${total.toFixed(1)} <span>/ 100${c1.score_complete===false?" · 부분점수":""}</span></div>',
        1,
    )
    p.write_text(text, encoding="utf-8")

    cssp = root / "static" / "v366_unified.css"
    if cssp.exists():
        css = cssp.read_text(encoding="utf-8")
        marker = "/* NAMUH ZERO AUDIT UI */"
        if marker not in css:
            css += '''\n/* NAMUH ZERO AUDIT UI */\n.v366-status{display:inline-block;margin-left:6px;padding:2px 5px;border-radius:999px;font-size:8px;font-style:normal;font-weight:800;vertical-align:1px}.v366-status.missing{color:#f1bd6c;background:rgba(236,176,69,.11);border:1px solid rgba(236,176,69,.22)}.v366-status.zero{color:#8fa4be;background:rgba(116,139,168,.10);border:1px solid rgba(116,139,168,.18)}.v366-metric.missing .v366-meter i{width:0!important}.v366-metric.missing .v366-metric-line b{color:#f1bd6c}\n'''
            cssp.write_text(css, encoding="utf-8")

def apply(ns=None):
    global _INSTALLED
    if _INSTALLED:
        return True
    core = ns.get("core") if isinstance(ns, dict) else None
    if core is None:
        return False
    import namuh_conditions_final_patch as c
    import engine

    old_daily10 = c._daily10
    old_minute10 = c._minute_reversal10
    old_exec_gate = c._execution_gate
    old_standard45 = c._standard45

    def daily10(q, today):
        score, ok, meta = old_daily10(q, today)
        meta = dict(meta or {})
        meta["zero_status"] = "DATA_MISSING" if not meta.get("ready") else ("RECIPE_ZERO" if _f(score) == 0 else "SCORED")
        return score, ok, meta

    def minute10(core_, q, market):
        score, ok, meta = old_minute10(core_, q, market)
        meta = dict(meta or {})
        fresh_session = False
        try:
            rows = [x for x in list(core_.feed.bars(market, q.code, "1m") or []) if isinstance(x, dict)]
            local = c._market_clock(market, datetime.fromtimestamp(time.time(), tz=core_.KST))
            today = local.strftime("%Y%m%d")
            valid = []
            for b in rows[-8:]:
                ds = _digits(b.get("time") or b.get("datetime") or b.get("date"))
                if len(ds) >= 8 and ds[:8] == today:
                    valid.append(b)
            fresh_session = len(valid) >= 3
        except Exception:
            fresh_session = False
        if not meta.get("ready") or not fresh_session:
            meta["zero_status"] = "DATA_MISSING"
            meta["session_ready"] = False
            return 0.0, False, meta
        meta["session_ready"] = True
        meta["zero_status"] = "RECIPE_ZERO" if _f(score) == 0 else "SCORED"
        return score, ok, meta

    def exec_gate(q, now_ts=None, history=None):
        raw = getattr(q, "execution_strength", None)
        if raw in (None, ""):
            raw = getattr(q, "volume_power", None)
        hist = list(history if history is not None else getattr(q, "execution_history", []) or [])
        nowv = _f(now_ts, time.time())
        latest = _f(hist[-1][0]) if hist else 0.0
        if _f(raw) <= 0 and not hist:
            return False, "체결강도 데이터 대기"
        if latest > 0 and nowv - latest > 90:
            return False, "체결강도 데이터 대기"
        return old_exec_gate(q, now_ts, history)

    def standard45(core_, q, market, sec_score, stock_score, now, volume_state):
        temp, price_source = _build_calc_quote(core_, market, q)
        try:
            a = core_.scalp_analysis(temp, sec_score, stock_score, market, now)
        except Exception:
            try:
                a = engine.scalp_analysis(temp, sec_score, stock_score, market, now)
            except Exception:
                a = {"breakdown": {}}
        b = dict((a or {}).get("breakdown") or {})
        today = c._market_clock(market, now).strftime("%Y%m%d")

        _seed_from_shared_cache(c, volume_state, market, q.code, now)
        vr, sample_days = c._volume_ratio_same_time(volume_state, market, q.code, _f(getattr(q, "volume", 0)), now)

        struct10, struct_meta = c._price_structure10(temp, today)
        # Elliott uses current price as the current wave point, not only yesterday's close.
        ell = _f(b.get("엘리어트"))
        ell_reason = ""
        try:
            qell = copy(temp)
            db = [dict(x) for x in list(getattr(temp, "daily_bars", []) or []) if isinstance(x, dict) and _f(x.get("close")) > 0]
            px = _f(getattr(q, "price", 0))
            if px > 0:
                qell.daily_bars = db + [{"date": today, "open": _f(getattr(q, "open", 0), px), "high": _f(getattr(q, "high", 0), px), "low": _f(getattr(q, "low", 0), px), "close": px}]
            ell, ell_reason = engine.elliott_points(qell, False)
        except Exception:
            pass

        vol15 = c._interp_volume15(vr)
        raw = {
            "MACD": c._clamp(b.get("MACD"), 0, 10),
            "RSI": c._clamp(b.get("RSI"), 0, 10),
            "볼린저": c._clamp(b.get("볼린저"), 0, 10),
            "거래량": c._clamp(vol15, 0, 15),
            "이평": c._clamp(b.get("이평"), 0, 10),
            "가격구조": c._clamp(struct10, 0, 10),
            "엘리어트": c._clamp(ell, 0, 10),
        }
        prices_ready = len(list(getattr(temp, "prices", []) or [])) >= 20
        completed = c._completed_daily(temp, today)
        availability = {
            "MACD": prices_ready and "MACD" in b,
            "RSI": prices_ready and "RSI" in b,
            "볼린저": prices_ready and "볼린저" in b,
            "거래량": vr is not None and sample_days >= 15,
            "이평": prices_ready and "이평" in b,
            "가격구조": len(completed) >= 9 and _f(getattr(q, "price", 0)) > 0,
            "엘리어트": (len(completed) >= 7 or len(list(getattr(temp, "prices", []) or [])) >= 8),
        }
        zero_audit = {
            name: ("DATA_MISSING" if not availability[name] else ("RECIPE_ZERO" if _f(raw[name]) == 0 else "SCORED"))
            for name in raw
        }
        nonvol_raw = sum(_f(v) for k, v in raw.items() if k != "거래량")
        queued = False
        if not availability["거래량"] and _f(getattr(q, "volume", 0)) > 0:
            queued = _schedule_backfill(c, core_, volume_state, market, q.code, now, nonvol_raw)

        raw_total = sum(raw.values())
        std45 = round(c._clamp(raw_total / 75.0 * 45.0, 0, 45), 1)
        meta = {
            "volume_ratio": None if vr is None else round(vr, 3),
            "volume_history_days": sample_days,
            "volume_backfill_queued": queued,
            "price_structure": struct_meta,
            "elliott_reason": ell_reason,
            "price_source": price_source,
            "availability": availability,
            "zero_audit": zero_audit,
            "complete": all(availability.values()),
            "missing": [k for k, v in availability.items() if not v],
        }
        return std45, raw, meta

    c._daily10 = daily10
    c._minute_reversal10 = minute10
    c._execution_gate = exec_gate
    c._standard45 = standard45

    # The final Condition1 candidate remains the sole score owner. This wrapper
    # only labels zeroes and blocks entry if a required input is unavailable; it
    # never converts a genuine recipe zero into points and never changes weights.
    old_candidate = core.candidate
    if not getattr(old_candidate, "_namuh_zero_audit", False):
        def candidate(*args, **kwargs):
            out = old_candidate(*args, **kwargs)
            if not isinstance(out, dict):
                return out
            try:
                q = args[0] if args else kwargs.get("q")
                sector_rankmap = args[6] if len(args) > 6 else kwargs.get("sector_rankmap")
                c1 = dict(out.get("condition1") or {})
                if not c1:
                    return out
                bd = dict(c1.get("breakdown") or {})
                tm = dict(c1.get("technical_meta") or {})
                audit = {}
                dm = dict(c1.get("daily_meta") or {})
                mm = dict(c1.get("minute_meta") or {})
                audit["일봉"] = dm.get("zero_status") or ("DATA_MISSING" if not dm.get("ready") else ("RECIPE_ZERO" if _f(bd.get("daily10")) == 0 else "SCORED"))
                audit["분봉"] = mm.get("zero_status") or ("DATA_MISSING" if not mm.get("ready") else ("RECIPE_ZERO" if _f(bd.get("minute10")) == 0 else "SCORED"))
                er = str(c1.get("execution_reason") or "")
                audit["체결강도"] = "DATA_MISSING" if ("데이터 대기" in er or "축적 중" in er or not er) else ("RECIPE_ZERO" if _f(bd.get("execution12")) == 0 else "SCORED")
                ob = dict(c1.get("orderbook") or {})
                audit["호가"] = "DATA_MISSING" if ob.get("ratio") is None else ("RECIPE_ZERO" if _f(bd.get("orderbook8")) == 0 else "SCORED")
                for k, status in dict(tm.get("zero_audit") or {}).items():
                    audit[k] = status

                # Bonus data: only mark a zero as genuine when its ranking/feed can actually be evaluated.
                sc = dict(out.get("score_components") or {})
                try:
                    import namuh_condition1_v2_patch as c1old
                    _sp, _srank, sector_name = c1old._leading_sector5(core, q, out, sector_rankmap)
                except Exception:
                    sector_name = ""
                rank_source = bool(isinstance(sector_rankmap, dict) and sector_name in sector_rankmap) or out.get("sector_rank") is not None or out.get("leading_sector_rank") is not None
                audit["섹터 상대강도"] = "DATA_MISSING" if not rank_source else ("RECIPE_ZERO" if _f(bd.get("sector_relative7_5")) == 0 else "SCORED")
                try:
                    import namuh_condition1_v2_patch as c1old
                    _fp, _frank, peer_count = c1old._sector_inner_flow5(core, q)
                except Exception:
                    peer_count = 0
                flow_source = int(peer_count or 0) > 0
                audit["주도섹터 수급"] = "DATA_MISSING" if not flow_source else ("RECIPE_ZERO" if _f(bd.get("leading_sector_flow3_75")) == 0 else "SCORED")
                news_source = (q is not None and hasattr(q, "events")) or "fresh_event_points" in out or "news5" in sc
                audit["뉴스/공시"] = "DATA_MISSING" if not news_source else ("RECIPE_ZERO" if _f(bd.get("news3_75")) == 0 else "SCORED")

                missing = [k for k, v in audit.items() if v == "DATA_MISSING"]
                c1["zero_audit"] = audit
                c1["score_complete"] = not missing
                c1["score_status"] = "READY" if not missing else "DATA_WAIT"
                c1["missing_inputs"] = missing
                if missing:
                    c1["gate"] = False
                out["condition1"] = c1
                if missing:
                    labels = [x for x in list(out.get("condition_labels") or []) if x != "조건1"]
                    out["condition_labels"] = labels
                    out["condition_display"] = "복합조건" if len(labels) > 1 else (labels[0] if labels else "")
                    reasons = list(out.get("reasons") or [])
                    msg = "조건1 데이터 대기 · " + ", ".join(missing[:6])
                    if msg not in reasons:
                        reasons.insert(1 if reasons else 0, msg)
                    out["reasons"] = reasons[:12]
                return out
            except Exception as exc:
                out["zero_audit_error"] = str(exc)[:160]
                return out
        candidate._namuh_zero_audit = True
        core.candidate = candidate

    _start_workers()
    try:
        old_health = core.health_payload
        if callable(old_health) and not getattr(old_health, "_namuh_zero_audit", False):
            def health():
                d = dict(old_health())
                with _LOCK:
                    d["condition1_zero_audit"] = {**_STATS, "pending": len(_PENDING), "queue": _Q.qsize()}
                return d
            health._namuh_zero_audit = True
            core.health_payload = health
    except Exception:
        pass

    try:
        _patch_score_ui()
    except Exception as exc:
        print("NAMUH ZERO AUDIT UI ERROR:", str(exc)[:180], flush=True)
    _INSTALLED = True
    print("NAMUH zero-score audit active: false zero guard + history-backed standard + volume15 backfill", flush=True)
    return True
