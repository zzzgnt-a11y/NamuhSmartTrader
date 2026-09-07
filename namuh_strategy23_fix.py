from __future__ import annotations

import re
import threading
import time
from collections import deque
from datetime import datetime

STATE_KEY = "strategy123_state_v2"
ENTRY2_AM = (9 * 60, 9 * 60 + 30)
ENTRY2_PM = (13 * 60, 14 * 60)
C3_MONITOR = (9 * 60, 11 * 60)
C3_TRADE = (11 * 60, 13 * 60)
C3_ENTRY = (2.7, 3.3)
C3_TARGET = (4.7, 5.3)
FEE_BUFFER = 0.05


def _mins(dt):
    return dt.hour * 60 + dt.minute


def _walk(v):
    if isinstance(v, dict):
        yield v
        for x in v.values():
            yield from _walk(x)
    elif isinstance(v, list):
        for x in v:
            yield from _walk(x)


def _num(data, keys):
    for o in _walk(data):
        for k in keys:
            if k in o and o[k] not in (None, ""):
                try:
                    return float(str(o[k]).replace(",", "").replace("+", "").strip())
                except Exception:
                    pass
    return 0.0


def _change20(ch):
    ch = float(ch or 0)
    if ch <= 0:
        pts = 0.0
    elif ch < 1:
        pts = 4.0 * ch
    elif ch < 2:
        pts = 4.0 + (ch - 1.0) * 4.0
    elif ch < 3:
        pts = 8.0 + (ch - 2.0) * 4.0
    elif ch < 5:
        pts = 12.0 + (ch - 3.0) * 4.0
    else:
        pts = 20.0
    return round(max(0.0, min(20.0, pts)), 1)


def _rising(hist):
    if len(hist) < 3:
        return False
    a, b, c = [float(x[1]) for x in list(hist)[-3:]]
    return a < b < c and c - a >= 1.0


def _exit_signal(hist):
    if len(hist) < 3:
        return False, ""
    a, b, c = [float(x[1]) for x in list(hist)[-3:]]
    if b > a and c <= b:
        return True, f"3분 점수 고립상승 {a:.1f}→{b:.1f}→{c:.1f}"
    if c < b - 0.4:
        return True, f"3분 점수 하락 {b:.1f}→{c:.1f}"
    return False, ""


def apply(ns):
    core = ns.get("core") if isinstance(ns, dict) else None
    if core is None or getattr(core, "_NAMUH_STRATEGY23_FIX_APPLIED", False):
        return
    core._NAMUH_STRATEGY23_FIX_APPLIED = True

    lock = threading.RLock()
    long_cache = {}
    long_queue = deque()
    long_queued = set()
    c3_rows = {}
    c3_hist = {}
    c3_codes = []
    c3_scanned = set()
    c3_day = ""
    c3_full_sweeps = 0
    c1_hist = {}
    c1_last = {}
    c2_hist = {}
    c2_last = {}

    def _save_state_drop(code):
        try:
            st = core.store.load_json(STATE_KEY, {}) or {}
            if isinstance(st, dict):
                pos = st.get("positions") or {}
                if isinstance(pos, dict):
                    pos.pop(str(code), None)
                    st["positions"] = pos
                core.store.save_json(STATE_KEY, st)
        except Exception:
            pass

    def _queue_long(code):
        code = str(code or "")
        if not code or code in long_queued:
            return
        row = long_cache.get(code) or {}
        if time.time() - float(row.get("fetched_at") or 0) < 21600:
            return
        long_queued.add(code)
        long_queue.append(code)

    def _fetch_long(code):
        import requests
        url = "https://fchart.stock.naver.com/sise.nhn"
        r = requests.get(url, params={"symbol": code, "timeframe": "day", "count": "10000", "requestType": "0"}, timeout=10,
                         headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        rows = []
        for s in re.findall(r'data="([^"]+)"', r.text):
            p = s.split("|")
            if len(p) < 5:
                continue
            try:
                d, o, h, l, c = p[:5]
                rows.append((str(d), float(h), float(c)))
            except Exception:
                continue
        if len(rows) < 120:
            raise RuntimeError(f"long history too short: {len(rows)}")
        rows.sort(key=lambda x: x[0])
        today = datetime.now(core.KST).strftime("%Y%m%d")
        completed = [x for x in rows if x[0] < today]
        if not completed:
            raise RuntimeError("no completed daily history")
        high_day, high, high_close = max(completed, key=lambda x: x[1])
        prev_close = completed[-1][2]
        return {
            "ready": True,
            "fetched_at": time.time(),
            "history_days": len(completed),
            "high_day": high_day,
            "high": high,
            "high_day_close": high_close,
            "prev_close": prev_close,
            "source": "NAVER_ACTUAL_DAILY",
        }

    def _long_worker():
        time.sleep(4)
        while True:
            try:
                if not long_queue:
                    time.sleep(0.5)
                    continue
                code = long_queue.popleft()
                long_queued.discard(code)
                try:
                    row = _fetch_long(code)
                    with lock:
                        long_cache[code] = row
                except Exception as exc:
                    with lock:
                        long_cache[code] = {"ready": False, "fetched_at": time.time(), "error": str(exc)[:160]}
                time.sleep(0.35)
            except Exception:
                time.sleep(1)

    def _load_c3_codes():
        nonlocal c3_codes
        try:
            from nhplug.instruments import load_master
            frame = load_master("m_new_stock")
            rows = frame.to_dict("records") if hasattr(frame, "to_dict") else list(frame or [])
            out = []
            for r in rows:
                market = str(r.get("mrkt_div_cls_code") or r.get("sMarket") or "").strip()
                if market not in ("1", "4"):
                    continue
                raw = str(r.get("shrn_iscd") or r.get("sCode") or r.get("code") or "")
                m = re.search(r"(\d{6})", raw)
                if m:
                    out.append(m.group(1))
            c3_codes = list(dict.fromkeys(out))
        except Exception:
            c3_codes = list((getattr(core.feed, "kr_master_meta", {}) or {}).keys())

    def _scan_one(code):
        from nhplug import call
        last = None
        for market_cd in core.feed._market_order():
            try:
                data = call("/krstock/quote/v1/currentPrice", {"iem_cd": code, "market_cd": market_cd})
                price = _num(data, ("stck_prpr", "prpr", "price", "cur_pr", "now_pr"))
                ch = _num(data, ("prdy_ctrt", "change_pct", "fluctuation_rate", "rate"))
                op = _num(data, ("stck_oprc", "open"))
                ex = _num(data, ("cttr", "volpower", "execution_strength"))
                vol = _num(data, ("acml_vol", "volume", "vol"))
                if price > 0 and ch > -99:
                    meta = (getattr(core.feed, "kr_master_meta", {}) or {}).get(code, {}) or {}
                    row = {
                        "code": code, "price": price, "change_pct": ch, "open": op,
                        "execution_strength": ex, "volume": vol,
                        "sector": str(meta.get("sector") or ""), "name": str(meta.get("name") or code),
                        "updated_at": time.time(), "source": "NH_CURRENT_PRICE",
                    }
                    return row
            except Exception as exc:
                last = exc
                if "429" in str(exc):
                    raise
        if last:
            raise last
        return None

    def _c3_worker():
        nonlocal c3_day, c3_full_sweeps
        time.sleep(5)
        _load_c3_codes()
        idx = 0
        while True:
            now = datetime.now(core.KST)
            mins = _mins(now)
            day = now.strftime("%Y%m%d")
            if day != c3_day:
                with lock:
                    c3_day = day
                    c3_rows.clear(); c3_hist.clear(); c3_scanned.clear(); c3_full_sweeps = 0
                idx = 0
            if now.weekday() >= 5 or not (8 * 60 + 58 <= mins < C3_TRADE[1]):
                time.sleep(5)
                continue
            if not c3_codes:
                _load_c3_codes(); time.sleep(2); continue
            code = c3_codes[idx % len(c3_codes)]
            idx += 1
            try:
                row = _scan_one(code)
                if row:
                    ts = float(row["updated_at"])
                    with lock:
                        c3_rows[code] = row
                        c3_scanned.add(code)
                        h = c3_hist.setdefault(code, deque(maxlen=16))
                        if not h or ts - float(h[-1][0]) >= 480:
                            h.append((ts, float(row["change_pct"])))
                if idx % len(c3_codes) == 0:
                    with lock:
                        c3_full_sweeps += 1
                time.sleep(0.28)
            except Exception as exc:
                time.sleep(1.8 if "429" in str(exc) else 0.4)

    threading.Thread(target=_long_worker, daemon=True).start()
    threading.Thread(target=_c3_worker, daemon=True).start()

    old_candidate = core.candidate
    def candidate(q, market, smart=False, secmap=None, stockmap=None, leadermap=None, sector_rankmap=None, now=None):
        out = old_candidate(q, market, smart, secmap, stockmap, leadermap, sector_rankmap, now)
        if smart or not isinstance(out, dict) or str(market or "").upper() != "KR":
            return out
        c2 = dict(out.get("condition2") or {})
        base_score = float(c2.get("score") or 0)
        if base_score >= 55:
            _queue_long(q.code)
        with lock:
            hist = dict(long_cache.get(str(q.code)) or {})
        front = dict(c2.get("front60") or {})
        vol20 = float(front.get("volume20") or 0)
        exec20 = float(front.get("execution20") or 0)
        tech40 = float(c2.get("technical40") or 0)
        gate = False
        if hist.get("ready") and float(hist.get("prev_close") or 0) > 0 and float(getattr(q, "price", 0) or 0) > 0:
            ch = (float(q.price) / float(hist["prev_close"]) - 1.0) * 100.0
            ch20 = _change20(ch)
            total = round(max(0.0, min(100.0, vol20 + exec20 + ch20 + tech40)), 1)
            ratio = float(q.price) / float(hist.get("high_day_close") or 1)
            monthly = {**hist, "pass": bool(ratio <= 0.60), "drop_pct": round((1.0-ratio)*100.0, 1)}
            kospi = dict(c2.get("kospi_1m") or {})
            blocked = bool(getattr(q, "event_blocked", False))
            gate = bool(not blocked and total >= 72.0 and kospi.get("ready") and kospi.get("up") and monthly.get("pass"))
            front.update({"change20": ch20, "change_pct": round(ch, 3), "change_source": "PREV_CLOSE"})
            c2.update({"score": total, "front60": front, "monthly_discount": monthly, "gate": gate})
            out["condition2_score"] = total
        else:
            c2["gate"] = False
            c2["monthly_discount"] = {**hist, "ready": False, "pass": False, "source": hist.get("source") or "LONG_HISTORY_PENDING"}
        out["condition2"] = c2
        out["condition2_gate_pass"] = bool(c2.get("gate"))
        return out
    core.candidate = candidate

    def _sample_scores(candidates, ts):
        for x in list(candidates or []):
            code = str(x.get("code") or "")
            if not code:
                continue
            for cond, score, last_map, hist_map in (
                ("C1", x.get("score"), c1_last, c1_hist),
                ("C2", x.get("condition2_score"), c2_last, c2_hist),
            ):
                if score is None:
                    continue
                key = cond + ":" + code
                if ts - float(last_map.get(key, 0) or 0) >= 175:
                    last_map[key] = ts
                    hist_map.setdefault(key, deque(maxlen=8)).append((ts, float(score or 0)))

    def _c3_coverage():
        with lock:
            total = len(c3_codes)
            scanned = len(c3_scanned)
            sweeps = c3_full_sweeps
        return total, scanned, sweeps, (scanned / total if total else 0.0)

    def _c3_qualified_rows(now):
        total, scanned, sweeps, coverage = _c3_coverage()
        if coverage < 0.90 or sweeps < 1:
            return []
        sectors = list((core.CACHE.get("KR") or {}).get("sectors") or [])
        top3 = {str(x.get("sector") or ""): i + 1 for i, x in enumerate(sectors[:3])}
        out = []
        with lock:
            items = list(c3_hist.items())
            rows = dict(c3_rows)
        for code, hist in items:
            vals = [float(x[1]) for x in hist]
            if len(vals) < 3:
                continue
            span = float(hist[-1][0]) - float(hist[0][0])
            if span < 900:
                continue
            in_band = sum(2.7 <= x <= 5.3 for x in vals) / len(vals)
            if in_band < 0.70 or min(vals) > 3.3 or max(vals) < 4.0:
                continue
            row = rows.get(code)
            if not row:
                continue
            sector = str(row.get("sector") or "")
            sr = top3.get(sector)
            if not sr:
                continue
            out.append({**row, "sector_rank": sr, "band_ratio": in_band, "samples": len(vals)})
        out.sort(key=lambda x: (x["band_ratio"], -x["sector_rank"]), reverse=True)
        return out

    def _buy_c3(row, now):
        code = str(row.get("code") or "")
        if not code or code in core.protected or "KR:" + code in core.paper.positions:
            return False
        if len(core.paper.market_positions("KR")) >= 3:
            return False
        try:
            fresh = _scan_one(code)
        except Exception:
            return False
        if not fresh:
            return False
        ch = float(fresh.get("change_pct") or 0)
        if not (C3_ENTRY[0] <= ch <= C3_ENTRY[1]):
            return False
        q = core.feed.q("KR", code)
        px = float(fresh.get("price") or 0)
        if px <= 0:
            return False
        q.name = str(fresh.get("name") or q.name or code)
        q.sector = str(fresh.get("sector") or q.sector or "")
        q.mark(px, float(fresh.get("volume") or 0), now.timestamp())
        if float(fresh.get("open") or 0) > 0:
            q.open = float(fresh["open"])
        day = core.trading_day_key("KR", now)
        budget = core.paper.effective_budget_krw(day)
        remain = min(core.paper.cash_krw, budget - core.paper.held_cost_krw())
        qty = int(min(remain, max(px, budget / 2.0)) // px) if remain >= px else 0
        if qty < 1:
            return False
        p = core.paper.buy(q, qty, "KR", 1.0, day, strategy="조건3", entry_session="C3_11_13")
        if not p:
            return False
        p.strategy = "조건3"
        core._persist_paper()
        print(f"STRATEGY23 FIX BUY 조건3 {code} chg={ch:.2f}% coverage={_c3_coverage()[3]:.1%}", flush=True)
        return True

    def _buy_c1_exception(x, now):
        code = str(x.get("code") or "")
        if not code or code in core.protected or "KR:" + code in core.paper.positions:
            return False
        if not bool((x.get("condition1") or {}).get("gate")):
            return False
        if not _rising(c1_hist.get("C1:" + code, deque())):
            return False
        q = core.feed.quotes_for("KR").get(code)
        ts = now.timestamp()
        if q is None or ts - float(getattr(q, "updated_at", 0) or 0) > 30:
            return False
        eh = list(getattr(q, "execution_history", []) or [])
        if not eh or ts - float(eh[-1][0]) > 40:
            return False
        ok = core._buy_one("KR", x, "조건1", "C1_SCORE_RISE", now)
        if ok:
            p = core.paper.positions.get("KR:" + code)
            if p:
                p.strategy = "조건1"
            core._persist_paper()
        return bool(ok)

    old_trade = core.trade_scalp
    def trade_scalp(market, candidates, now=None):
        if str(market or "").upper() != "KR":
            return old_trade(market, candidates, now)
        now = (now or core.datetime.now(core.KST)).astimezone(core.KST)
        mins = _mins(now); ts = now.timestamp()
        _sample_scores(candidates, ts)
        if C3_TRADE[0] <= mins < C3_TRADE[1]:
            for row in _c3_qualified_rows(now):
                if _buy_c3(row, now):
                    return
            for x in list(candidates or []):
                if _buy_c1_exception(x, now):
                    return
            return
        allow_c2 = (ENTRY2_AM[0] <= mins <= ENTRY2_AM[1]) or (ENTRY2_PM[0] <= mins <= ENTRY2_PM[1])
        changed = []
        if not allow_c2:
            for x in list(candidates or []):
                if x.get("condition2_gate_pass"):
                    changed.append((x, x.get("condition2_gate_pass"), (x.get("condition2") or {}).get("gate")))
                    x["condition2_gate_pass"] = False
                    if isinstance(x.get("condition2"), dict):
                        x["condition2"]["gate"] = False
        try:
            return old_trade(market, candidates, now)
        finally:
            for x, a, b in changed:
                x["condition2_gate_pass"] = a
                if isinstance(x.get("condition2"), dict):
                    x["condition2"]["gate"] = b
    core.trade_scalp = trade_scalp

    def _sell_c2(p, q, reason):
        px = float(getattr(q, "price", 0) or p.current_price or 0)
        if px <= 0:
            return False
        core.paper.mark("KR", p.code, px, 1.0)
        ok = core.paper.sell("KR", p.code, px, 1.0, reason)
        if ok:
            _save_state_drop(p.code)
            core._persist_paper()
            print(f"STRATEGY23 FIX SELL 조건2 {p.code} {reason}", flush=True)
        return bool(ok)

    old_sell = core.mark_and_sell
    def mark_and_sell(market, scalp, smart, now=None):
        if str(market or "").upper() != "KR":
            return old_sell(market, scalp, smart, now)
        now = (now or core.datetime.now(core.KST)).astimezone(core.KST)
        mins = _mins(now); ts = now.timestamp()
        item_map = {str(x.get("code") or ""): x for x in list(scalp or [])}
        hidden = {}
        for p in list(core.paper.market_positions("KR")):
            if str(getattr(p, "strategy", "")) != "조건2":
                continue
            q = core.feed.quotes_for("KR").get(p.code)
            if q is None or float(getattr(q, "price", 0) or 0) <= 0:
                hidden[p.key] = p; core.paper.positions.pop(p.key, None); continue
            core.paper.mark("KR", p.code, float(q.price), 1.0)
            pnl = float(p.pnl_pct)
            if core.must_force_sell_pre(p, now):
                if _sell_c2(p, q, "08:49 프리세션 강제청산"): continue
            target = (item_map.get(p.code) or {}).get("vi_target") or (item_map.get(p.code) or {}).get("vi_pre")
            if target and float(target) > float(p.avg_price) and float(q.price) >= float(target):
                if _sell_c2(p, q, "VI 직전 익절"): continue
            if mins >= 15 * 60 + 19:
                if _sell_c2(p, q, "KRX 15:19 동시호가 전 강제청산"): continue
            if pnl <= -1.5:
                if _sell_c2(p, q, "기존 손절 -1.5%"): continue
            if pnl >= 1.0:
                if _sell_c2(p, q, "조건2 +1% 목표 익절"): continue
            x = item_map.get(p.code) or {}
            score = x.get("condition2_score")
            key = "C2:" + p.code
            if score is not None and ts - float(c2_last.get(key, 0) or 0) >= 175:
                c2_last[key] = ts; c2_hist.setdefault(key, deque(maxlen=8)).append((ts, float(score or 0)))
            sig, why = _exit_signal(c2_hist.get(key, deque()))
            if sig and _sell_c2(p, q, why):
                continue
            try:
                entered = datetime.fromtimestamp(float(p.entry_ts or ts), core.KST)
            except Exception:
                entered = now
            em = _mins(entered)
            deadline = 10 * 60 + 30 if ENTRY2_AM[0] <= em <= ENTRY2_AM[1] else 14 * 60 + 50 if ENTRY2_PM[0] <= em <= ENTRY2_PM[1] else None
            if deadline is not None and mins >= deadline and pnl > FEE_BUFFER:
                if _sell_c2(p, q, "조건2 시간목표 미달 · 수수료버퍼 제외 순이익 청산"): continue
            hidden[p.key] = p
            core.paper.positions.pop(p.key, None)
        try:
            result = old_sell(market, scalp, smart, now)
        finally:
            for key, p in hidden.items():
                if key not in core.paper.positions:
                    core.paper.positions[key] = p
            if hidden:
                core._persist_paper()
        return result
    core.mark_and_sell = mark_and_sell

    old_health = core.health_payload
    def health():
        d = dict(old_health())
        total, scanned, sweeps, coverage = _c3_coverage()
        with lock:
            ready_long = sum(1 for x in long_cache.values() if x.get("ready"))
            qualified = len(_c3_qualified_rows(datetime.now(core.KST))) if total else 0
        d["condition23_fix"] = {
            "condition2": {"outside_window_exception": False, "long_history_ready": ready_long, "long_history_source": "NAVER actual daily; no pass when unavailable"},
            "condition3": {"master_count": total, "scanned": scanned, "coverage_pct": round(coverage * 100, 1), "full_sweeps": sweeps, "qualified": qualified, "source": "NH currentPrice all KOSPI/KOSDAQ"},
        }
        return d
    core.health_payload = health

    print("NAMUH STRATEGY23 FIX active: C2 strict windows/long-history + C3 all-market NH scan", flush=True)
