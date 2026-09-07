from __future__ import annotations

import os
import threading
import time
from collections import deque
from datetime import datetime

STATE_KEY = "strategy123_state_v2"
FEE_BUFFER_PCT = float(os.getenv("NAMUH_KR_FEE_BUFFER_PCT", "0.05") or 0.05)

ENTRY1_AM = (9 * 60, 9 * 60 + 20)
ENTRY1_PM = (13 * 60, 14 * 60)
ENTRY2_AM = (9 * 60, 9 * 60 + 30)
ENTRY2_PM = (13 * 60, 14 * 60)
C3_MONITOR = (9 * 60, 11 * 60)
C3_TRADE = (11 * 60, 13 * 60)
C3_ENTRY_BAND = (2.7, 3.3)
C3_TARGET_BAND = (4.7, 5.3)


def _clamp(v, lo=0.0, hi=100.0):
    try:
        x = float(v or 0)
    except Exception:
        x = 0.0
    return max(lo, min(hi, x))


def _mins(dt):
    return int(dt.hour) * 60 + int(dt.minute)


def _event_date_age(core, raw, now=None):
    now = (now or datetime.now(core.KST)).astimezone(core.KST)
    s = str(raw or "").replace("-", "").replace("/", "")[:8]
    try:
        d = datetime.strptime(s, "%Y%m%d").date()
    except Exception:
        return None
    return (now.date() - d).days


def _fresh_positive_event5(core, q, now=None):
    """DART/공시 호재는 오늘 포함 3일, 뉴스 호재는 당일만 인정."""
    best = 0.0
    meta = None
    for e in list(getattr(q, "events", []) or []):
        if not isinstance(e, dict) or str(e.get("sentiment") or "").lower() != "positive":
            continue
        age = _event_date_age(core, e.get("date"), now)
        if age is None or age < 0:
            continue
        src = (str(e.get("source") or "") + " " + str(e.get("url") or "") + " " + str(e.get("kind") or "")).lower()
        is_disclosure = any(k in src for k in ("dart", "opendart", "공시", "disclosure"))
        valid = age <= 2 if is_disclosure else age == 0
        if not valid:
            continue
        impact = str(e.get("impact") or "").lower()
        raw_score = float(e.get("score") or 0)
        pts = 5.0 if impact == "strong" or raw_score >= 9 else 3.0 if raw_score > 0 else 0.0
        if pts > best:
            best = pts
            meta = {"type": "공시" if is_disclosure else "뉴스", "age_days": age, "title": e.get("title"), "points": pts}
    return round(best, 1), meta


def _same_sector_rank(core, q):
    """같은 섹터에서 수급/체결강도/등락률 3개 순위를 합산한다."""
    sector = core.sector_name(q, "KR")
    peers = []
    for p in list(core.feed.quotes_for("KR").values()):
        if float(getattr(p, "price", 0) or 0) <= 0 or float(getattr(p, "open", 0) or 0) <= 0:
            continue
        if core.sector_name(p, "KR") != sector:
            continue
        vol = max(1.0, float(getattr(p, "volume", 0) or 0))
        flow = (
            float(getattr(p, "foreign_net", 0) or 0)
            + float(getattr(p, "institution_net", 0) or 0)
            + float(getattr(p, "program_net", 0) or 0)
        ) / vol
        ex = float(getattr(p, "execution_strength", 0) or 0)
        ch = (float(p.price) / float(p.open) - 1.0) * 100.0
        peers.append((str(p.code), flow, ex, ch))
    if not peers:
        return 999, 0, {"sector": sector, "peer_count": 0}
    ranks = {}
    for idx in (1, 2, 3):
        ordered = sorted(peers, key=lambda x: x[idx], reverse=True)
        for r, row in enumerate(ordered, 1):
            ranks.setdefault(row[0], [999, 999, 999])[idx - 1] = r
    composite = sorted(
        peers,
        key=lambda x: (
            sum(ranks.get(x[0], [999, 999, 999])),
            ranks.get(x[0], [999])[0],
        ),
    )
    rank = next((i for i, row in enumerate(composite, 1) if row[0] == str(q.code)), 999)
    if rank <= 2:
        pts = 5.0
    elif rank == 3:
        pts = 4.5
    elif rank == 4:
        pts = 4.0
    elif rank == 5:
        pts = 3.5
    elif rank == 6:
        pts = 3.0
    elif rank == 7:
        pts = 2.5
    elif rank == 8:
        pts = 2.0
    elif rank == 9:
        pts = 1.5
    elif rank == 10:
        pts = 1.0
    else:
        pts = 0.5
    return rank, min(len(peers), 999), {"sector": sector, "peer_count": len(peers), "rank_parts": ranks.get(str(q.code), [])}


def _completed_kospi_1m(core, now=None):
    now = now or datetime.now(core.KST)
    try:
        bars = list(core.feed.market_bars("kospi", "1m") or [])
    except Exception:
        bars = []
    bucket = int(now.timestamp() // 60) * 60
    complete = []
    for b in bars:
        try:
            ts = float(b.get("time") or 0)
        except Exception:
            continue
        if ts and ts < bucket:
            complete.append(b)
    if not complete:
        return {"ready": False, "up": False, "bars": len(bars), "label": "KOSPI 완료 1분봉 대기"}
    b = complete[-1]
    o = float(b.get("open") or 0)
    c = float(b.get("close") or 0)
    return {
        "ready": o > 0 and c > 0,
        "up": bool(o > 0 and c > o),
        "bars": len(bars),
        "time": b.get("time"),
        "open": o,
        "close": c,
        "label": "KOSPI 직전 1분봉 상승" if c > o > 0 else "KOSPI 직전 1분봉 비상승",
    }


def _monthly_discount(q):
    """수신 일봉을 월별로 묶고, 최고 고가가 찍힌 날의 종가 대비 40% 이상 하락 여부."""
    bars = list(getattr(q, "daily_bars", []) or [])
    clean = []
    months = {}
    for b in bars:
        try:
            d = str(b.get("date") or "")
            h = float(b.get("high") or 0)
            c = float(b.get("close") or 0)
        except Exception:
            continue
        if len(d) < 6 or h <= 0 or c <= 0:
            continue
        clean.append((d, h, c))
        m = d[:6]
        row = months.setdefault(m, {"high": h, "close": c, "date": d})
        if h >= float(row.get("high") or 0):
            row.update({"high": h, "close": c, "date": d})
    if len(clean) < 20:
        return {"ready": False, "pass": False, "history_days": len(clean), "months": len(months)}
    d, h, ref_close = max(clean, key=lambda x: x[1])
    px = float(getattr(q, "price", 0) or 0)
    ratio = px / ref_close if ref_close > 0 else 999
    return {
        "ready": True,
        "pass": bool(px > 0 and ratio <= 0.60),
        "history_days": len(clean),
        "months": len(months),
        "high_day": d,
        "high": h,
        "high_day_close": ref_close,
        "price": px,
        "price_vs_high_day_close_pct": round(ratio * 100.0, 1) if ratio < 900 else None,
        "drop_pct": round((1.0 - ratio) * 100.0, 1) if ratio < 900 else None,
    }


def _change20(q):
    o = float(getattr(q, "open", 0) or 0)
    p = float(getattr(q, "price", 0) or 0)
    if o <= 0 or p <= 0:
        return 0.0, 0.0
    ch = (p / o - 1.0) * 100.0
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
    return round(_clamp(pts, 0, 20), 1), round(ch, 3)


def _top_sector_rank_from_out(out):
    try:
        return int(out.get("sector_rank") or 999)
    except Exception:
        return 999


def _in_window(mins, window):
    return window[0] <= mins <= window[1]


def _score_rising_exception(hist):
    if len(hist) < 3:
        return False
    a, b, c = [float(x[1]) for x in list(hist)[-3:]]
    return a < b < c and (c - a) >= 1.0


def _score_exit_signal(hist):
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
    if core is None or getattr(core, "_NAMUH_STRATEGY123_APPLIED", False):
        return
    core._NAMUH_STRATEGY123_APPLIED = True

    lock = threading.RLock()
    raw_state = core.store.load_json(STATE_KEY, {}) or {}
    state = raw_state if isinstance(raw_state, dict) else {}
    state.setdefault("positions", {})
    state.setdefault("c3_qualified", {})
    state.setdefault("c3_day", "")
    score_hist = {}
    c3_hist = {}
    last_score_sample = {}
    last_c3_sample = {}
    history_queue = deque()
    history_queued = set()

    def persist():
        with lock:
            payload = {
                "positions": dict(state.get("positions") or {}),
                "c3_qualified": dict(state.get("c3_qualified") or {}),
                "c3_day": str(state.get("c3_day") or ""),
            }
        try:
            core.store.save_json(STATE_KEY, payload)
        except Exception:
            pass

    def queue_history(code):
        code = str(code or "")
        if not code or code in history_queued:
            return
        q = core.feed.quotes_for("KR").get(code)
        if q is not None and len(list(getattr(q, "daily_bars", []) or [])) >= 100:
            return
        history_queued.add(code)
        history_queue.append(code)

    def history_worker():
        time.sleep(20)
        while True:
            try:
                if not history_queue:
                    time.sleep(2)
                    continue
                code = history_queue.popleft()
                history_queued.discard(code)
                try:
                    core.feed.ensure_daily_bars("KR", code, 120, force=True)
                except Exception:
                    pass
                time.sleep(2.5)
            except Exception:
                time.sleep(3)

    threading.Thread(target=history_worker, daemon=True).start()

    old_candidate = core.candidate

    def candidate(q, market, smart=False, secmap=None, stockmap=None, leadermap=None, sector_rankmap=None, now=None):
        out = old_candidate(q, market, smart, secmap, stockmap, leadermap, sector_rankmap, now)
        if smart or not isinstance(out, dict) or str(market or "").upper() != "KR":
            return out

        comps = dict(out.get("score_components") or {})
        old_news = float(comps.get("news5", 0) or 0)
        old_sector = float(comps.get("sector_flow5", 0) or 0)

        news5, event_meta = _fresh_positive_event5(core, q, now)
        peer_rank, peer_count, peer_meta = _same_sector_rank(core, q)
        if peer_rank <= 2:
            sector5 = 5.0
        elif peer_rank == 3:
            sector5 = 4.5
        elif peer_rank == 4:
            sector5 = 4.0
        elif peer_rank == 5:
            sector5 = 3.5
        elif peer_rank == 6:
            sector5 = 3.0
        elif peer_rank == 7:
            sector5 = 2.5
        elif peer_rank == 8:
            sector5 = 2.0
        elif peer_rank == 9:
            sector5 = 1.5
        elif peer_rank == 10:
            sector5 = 1.0
        else:
            sector5 = 0.5 if peer_count else 0.0

        blocked = bool(getattr(q, "event_blocked", False))
        try:
            blocked = blocked or any(bool(e.get("blocked")) for e in list(getattr(q, "events", []) or []) if isinstance(e, dict))
        except Exception:
            pass

        recipe = float(out.get("recipe_score", 0) or 0) - old_news - old_sector + news5 + sector5
        total = float(out.get("score", 0) or 0) - old_news - old_sector + news5 + sector5
        if blocked:
            total = 0.0
        recipe = round(_clamp(recipe, 0, 80), 1)
        total = round(_clamp(total, 0, 100), 1)
        comps["news5"] = news5
        comps["sector_flow5"] = sector5
        out["score_components"] = comps
        out["recipe_score"] = recipe
        out["score"] = total
        out["priority_score"] = total
        out["fresh_event_points"] = news5
        out["fresh_event_meta"] = event_meta
        out["sector_peer_rank"] = peer_rank
        out["sector_peer_count"] = peer_count
        out["sector_peer_rank_meta"] = peer_meta
        out["entry_gate_pass"] = bool(not blocked and bool(out.get("execution_gate_pass", False)) and total >= 72.0)

        vol20 = round(_clamp(float(comps.get("volume15", 0) or 0) / 15.0 * 20.0, 0, 20), 1)
        exec20 = round(_clamp(float(comps.get("execution20", 0) or 0), 0, 20), 1)
        change20, change_pct = _change20(q)
        tech40 = round(_clamp(float(out.get("technical_score", comps.get("technical20", 0)) or 0) * 2.0, 0, 40), 1)
        c2_total = round(_clamp(vol20 + exec20 + change20 + tech40, 0, 100), 1)
        kospi = _completed_kospi_1m(core, now)
        monthly = _monthly_discount(q)
        if c2_total >= 60 and int(monthly.get("history_days") or 0) < 100:
            queue_history(q.code)
        c2_pass = bool(not blocked and c2_total >= 72.0 and kospi.get("ready") and kospi.get("up") and monthly.get("ready") and monthly.get("pass"))

        out["condition1"] = {"score": total, "gate": bool(out.get("entry_gate_pass", False)), "label": "조건1"}
        out["condition2"] = {
            "score": c2_total,
            "front60": {"volume20": vol20, "execution20": exec20, "change20": change20, "change_pct": change_pct},
            "technical40": tech40,
            "kospi_1m": kospi,
            "monthly_discount": monthly,
            "gate": c2_pass,
            "label": "조건2",
        }
        out["condition2_score"] = c2_total
        out["condition2_gate_pass"] = c2_pass
        out["condition3"] = {
            "sector_rank": _top_sector_rank_from_out(out),
            "sector_top3": _top_sector_rank_from_out(out) <= 3,
            "change_pct": change_pct,
            "monitor_window": "09:00~11:00",
            "trade_window": "11:00~13:00",
            "entry_band": [2.7, 3.3],
            "target_band": [4.7, 5.3],
            "label": "조건3",
        }
        labels = []
        if out["condition1"]["gate"]:
            labels.append("조건1")
        if c2_pass:
            labels.append("조건2")
        if out["condition3"]["sector_top3"]:
            labels.append("조건3 관찰")
        out["condition_labels"] = labels

        reasons = [r for r in list(out.get("reasons") or []) if not str(r).startswith("공시/호재") and not str(r).startswith("섹터수급")]
        reasons.insert(0, f"조건1 {total:.1f}점 · 조건2 {c2_total:.1f}점")
        reasons.append(f"호재점수 {news5:.1f}/5 · 공시 3일/뉴스 당일")
        reasons.append(f"동일섹터 종합순위 {peer_rank}/{peer_count} · 섹터점수 {sector5:.1f}/5")
        out["reasons"] = reasons
        return out

    core.candidate = candidate

    old_restore = core._restore_paper

    def restore_paper():
        old_restore()
        changed = False
        for p in list(core.paper.positions.values()):
            if p.market == "KR" and str(p.strategy or "SCALP") == "SCALP":
                p.strategy = "조건1"
                changed = True
            if p.market == "KR" and p.strategy in ("조건1", "조건2", "조건3"):
                state["positions"].setdefault(p.code, {"condition": p.strategy, "entry_ts": float(p.entry_ts or time.time()), "max_pnl_30m": -999.0})
        if changed:
            try:
                core._persist_paper()
            except Exception:
                pass
        persist()

    core._restore_paper = restore_paper

    def _candidate_score_snapshot(candidates, now_ts):
        for x in list(candidates or []):
            code = str(x.get("code") or "")
            if not code:
                continue
            for cond, score in (("조건1", x.get("score")), ("조건2", x.get("condition2_score"))):
                if score is None:
                    continue
                key = cond + ":" + code
                if now_ts - float(last_score_sample.get(key, 0) or 0) < 175:
                    continue
                last_score_sample[key] = now_ts
                score_hist.setdefault(key, deque(maxlen=8)).append((now_ts, float(score or 0)))

    def _sync_row_to_snapshot(code, raw):
        if not isinstance(raw, dict):
            return None
        try:
            received = float(raw.get("_received_at") or 0)
        except Exception:
            received = 0.0
        if received and time.time() - received > float(getattr(core, "MINUTE_SYNC_TTL", 180) or 180):
            return None
        price = 0.0
        for k in ("price", "current_price", "close", "stck_prpr", "now_price"):
            try:
                price = float(raw.get(k) or 0)
            except Exception:
                price = 0.0
            if price > 0:
                break
        ch = None
        for k in ("change_pct", "change_rate", "fluctuation_rate", "prdy_ctrt", "rate", "pct"):
            if raw.get(k) is not None:
                try:
                    ch = float(raw.get(k))
                    break
                except Exception:
                    pass
        open_px = 0.0
        for k in ("open", "open_price", "stck_oprc"):
            try:
                open_px = float(raw.get(k) or 0)
            except Exception:
                open_px = 0.0
            if open_px > 0:
                break
        if ch is None and price > 0 and open_px > 0:
            ch = (price / open_px - 1.0) * 100.0
        if ch is None:
            return None
        meta = (getattr(core.feed, "kr_master_meta", {}) or {}).get(code, {}) or {}
        sector = str(raw.get("sector") or meta.get("sector") or "")
        name = str(raw.get("name") or meta.get("name") or code)
        return {"code": code, "price": price, "open": open_px, "change_pct": float(ch), "sector": sector, "name": name, "source": "PC_1M"}

    def _available_universe():
        merged = {}
        try:
            with core.MINUTE_SYNC_LOCK:
                sync_rows = dict((core.MINUTE_SYNC.get("rows") or {}))
        except Exception:
            sync_rows = {}
        for code, raw in sync_rows.items():
            s = _sync_row_to_snapshot(str(code), raw)
            if s:
                merged[str(code)] = s
        for code, q in list(core.feed.quotes_for("KR").items()):
            if float(getattr(q, "price", 0) or 0) <= 0 or float(getattr(q, "open", 0) or 0) <= 0:
                continue
            merged[str(code)] = {
                "code": str(code),
                "price": float(q.price),
                "open": float(q.open),
                "change_pct": (float(q.price) / float(q.open) - 1.0) * 100.0,
                "sector": core.sector_name(q, "KR"),
                "name": str(getattr(q, "name", "") or code),
                "source": "NH_LIVE",
            }
        return merged

    def _c3_monitor(now):
        mins = _mins(now)
        day = now.strftime("%Y%m%d")
        if state.get("c3_day") != day:
            state["c3_day"] = day
            state["c3_qualified"] = {}
            c3_hist.clear()
            last_c3_sample.clear()
            persist()
        if not (C3_MONITOR[0] <= mins < C3_MONITOR[1]):
            return
        ts = now.timestamp()
        universe = _available_universe()
        for code, row in universe.items():
            ch = float(row.get("change_pct") or 0)
            if ch < 2.2 or ch > 5.8:
                continue
            if ts - float(last_c3_sample.get(code, 0) or 0) < 55:
                continue
            last_c3_sample[code] = ts
            h = c3_hist.setdefault(code, deque(maxlen=140))
            h.append((ts, ch, float(row.get("price") or 0), str(row.get("sector") or ""), str(row.get("name") or code)))
            vals = [float(x[1]) for x in h]
            if len(vals) < 8:
                continue
            in_band = sum(2.7 <= x <= 5.3 for x in vals) / len(vals)
            touched_low = any(2.7 <= x <= 3.3 for x in vals)
            touched_high = any(4.7 <= x <= 5.3 for x in vals)
            if in_band >= 0.70 and touched_low and touched_high:
                state["c3_qualified"][code] = {
                    "qualified_at": ts,
                    "samples": len(vals),
                    "band_ratio": round(in_band, 3),
                    "min": round(min(vals), 3),
                    "max": round(max(vals), 3),
                    "sector": row.get("sector"),
                    "name": row.get("name"),
                }
        if int(ts) % 60 < 6:
            persist()

    def _c3_candidates(now):
        mins = _mins(now)
        if not (C3_TRADE[0] <= mins < C3_TRADE[1]):
            return []
        universe = _available_universe()
        sectors = list((core.CACHE.get("KR") or {}).get("sectors") or [])
        top3 = {str(x.get("sector") or ""): i + 1 for i, x in enumerate(sectors[:3])}
        out = []
        for code, qual in list((state.get("c3_qualified") or {}).items()):
            row = universe.get(code)
            if not row:
                continue
            sector = str(row.get("sector") or qual.get("sector") or "")
            sr = top3.get(sector)
            if not sr or sr > 3:
                continue
            ch = float(row.get("change_pct") or 0)
            if not (C3_ENTRY_BAND[0] <= ch <= C3_ENTRY_BAND[1]):
                continue
            quality = float(qual.get("band_ratio") or 0) * 100.0 + (4 - sr) * 5.0
            out.append({**row, "sector_rank": sr, "quality": quality, "qual": qual})
        out.sort(key=lambda x: (x["quality"], -abs(float(x["change_pct"]) - 3.0)), reverse=True)
        return out

    def _fresh_price_exec(q, now_ts):
        if q is None or float(getattr(q, "price", 0) or 0) <= 0:
            return False
        if now_ts - float(getattr(q, "updated_at", 0) or 0) > 30:
            return False
        eh = list(getattr(q, "execution_history", []) or [])
        return bool(eh and now_ts - float(eh[-1][0]) <= 40)

    def _buy_item(item, condition, now, entry_session):
        code = str(item.get("code") or "")
        if not code or f"KR:{code}" in core.paper.positions or code in core.protected:
            return False
        if len(core.paper.market_positions("KR")) >= 3:
            return False
        q = core.feed.quotes_for("KR").get(code)
        if q is None:
            return False
        target = item.get("vi_target") or item.get("vi_pre")
        if target and float(q.price or 0) >= float(target):
            return False
        ok = core._buy_one("KR", item, condition, entry_session, now)
        if ok:
            p = core.paper.positions.get("KR:" + code)
            if p is not None:
                p.strategy = condition
            entry_score = float(item.get("score") if condition == "조건1" else item.get("condition2_score") or 0)
            state["positions"][code] = {
                "condition": condition,
                "entry_ts": float(getattr(p, "entry_ts", now.timestamp()) if p is not None else now.timestamp()),
                "entry_score": entry_score,
                "max_pnl_30m": -999.0,
                "target_hit": False,
            }
            key = condition + ":" + code
            score_hist[key] = deque([(now.timestamp(), entry_score)], maxlen=8)
            last_score_sample[key] = now.timestamp()
            core._persist_paper()
            persist()
            print(f"STRATEGY BUY {condition} {code} price={float(q.price):.0f}", flush=True)
        return bool(ok)

    def _buy_c3(row, now):
        code = str(row.get("code") or "")
        if not code or f"KR:{code}" in core.paper.positions or code in core.protected:
            return False
        if len(core.paper.market_positions("KR")) >= 3:
            return False
        q = core.feed.q("KR", code)
        px = float(row.get("price") or 0)
        ch = float(row.get("change_pct") or 0)
        if px <= 0:
            return False
        q.name = str(row.get("name") or q.name or code)
        q.sector = str(row.get("sector") or q.sector or "")
        q.mark(px, float(getattr(q, "volume", 0) or 0), now.timestamp())
        if float(getattr(q, "open", 0) or 0) <= 0 and ch > -99:
            q.open = px / (1.0 + ch / 100.0)
        day = core.trading_day_key("KR", now)
        budget = core.paper.effective_budget_krw(day)
        remain = min(core.paper.cash_krw, budget - core.paper.held_cost_krw())
        if remain < px:
            return False
        target_cash = min(remain, max(px, budget / 2.0))
        qty = int(target_cash // px)
        if qty < 1:
            return False
        pos = core.paper.buy(q, qty, "KR", 1.0, day, strategy="조건3", entry_session="C3_11_13")
        if pos is None:
            return False
        pos.strategy = "조건3"
        state["positions"][code] = {
            "condition": "조건3",
            "entry_ts": float(pos.entry_ts or now.timestamp()),
            "entry_change_pct": ch,
            "max_pnl_30m": -999.0,
            "target_hit": False,
        }
        core._persist_paper()
        persist()
        print(f"STRATEGY BUY 조건3 {code} chg={ch:.2f}% price={px:.0f} sector_rank={row.get('sector_rank')}", flush=True)
        return True

    old_trade = core.trade_scalp

    def trade_scalp(market, candidates, now=None):
        if str(market or "").upper() != "KR":
            return old_trade(market, candidates, now)
        now = (now or core.datetime.now(core.KST)).astimezone(core.KST)
        mins = _mins(now)
        ts = now.timestamp()

        _candidate_score_snapshot(candidates, ts)
        _c3_monitor(now)

        if C3_TRADE[0] <= mins < C3_TRADE[1]:
            for row in _c3_candidates(now):
                if _buy_c3(row, now):
                    return

        for x in list(candidates or []):
            if len(core.paper.market_positions("KR")) >= 3:
                break
            code = str(x.get("code") or "")
            if not code or code in core.protected or f"KR:{code}" in core.paper.positions:
                continue
            q = core.feed.quotes_for("KR").get(code)
            if not _fresh_price_exec(q, ts):
                continue

            c1_gate = bool((x.get("condition1") or {}).get("gate"))
            c1_time = _in_window(mins, ENTRY1_AM) or _in_window(mins, ENTRY1_PM)
            c1_hist = score_hist.get("조건1:" + code, deque())
            if c1_gate and (c1_time or _score_rising_exception(c1_hist)):
                if _buy_item(x, "조건1", now, "C1_AM" if _in_window(mins, ENTRY1_AM) else "C1_PM" if _in_window(mins, ENTRY1_PM) else "C1_SCORE_RISE"):
                    return

            c2_gate = bool(x.get("condition2_gate_pass", False))
            c2_time = _in_window(mins, ENTRY2_AM) or _in_window(mins, ENTRY2_PM)
            c2_hist = score_hist.get("조건2:" + code, deque())
            if c2_gate and (c2_time or _score_rising_exception(c2_hist)):
                if _buy_item(x, "조건2", now, "C2_AM" if _in_window(mins, ENTRY2_AM) else "C2_PM" if _in_window(mins, ENTRY2_PM) else "C2_SCORE_RISE"):
                    return

    core.trade_scalp = trade_scalp

    def _current_strategy_score(code, condition, scalp):
        for x in list(scalp or []):
            if str(x.get("code") or "") != str(code):
                continue
            return float(x.get("score") if condition == "조건1" else x.get("condition2_score") or 0)
        return None

    def _deadline_for(condition, entered):
        em = _mins(entered)
        if condition == "조건1":
            if ENTRY1_AM[0] <= em <= ENTRY1_AM[1]:
                return 10 * 60
            if ENTRY1_PM[0] <= em <= ENTRY1_PM[1]:
                return 15 * 60 + 10
        if condition == "조건2":
            if ENTRY2_AM[0] <= em <= ENTRY2_AM[1]:
                return 10 * 60 + 30
            if ENTRY2_PM[0] <= em <= ENTRY2_PM[1]:
                return 14 * 60 + 50
        return None

    def _sell(core_p, q, reason):
        px = float(getattr(q, "price", 0) or getattr(core_p, "current_price", 0) or 0)
        if px <= 0:
            return False
        try:
            core.paper.mark("KR", core_p.code, px, 1.0)
        except Exception:
            pass
        if core.paper.sell("KR", core_p.code, px, 1.0, reason):
            state["positions"].pop(core_p.code, None)
            core._persist_paper()
            persist()
            print(f"STRATEGY SELL {core_p.strategy} {core_p.code} {reason} pnl={core_p.pnl_pct:.3f}%", flush=True)
            return True
        return False

    old_sell = core.mark_and_sell

    def mark_and_sell(market, scalp, smart, now=None):
        if str(market or "").upper() != "KR":
            return old_sell(market, scalp, smart, now)
        now = (now or core.datetime.now(core.KST)).astimezone(core.KST)
        mins = _mins(now)
        qs = core.feed.quotes_for("KR")

        smart_map = {str(x.get("code") or ""): float(x.get("score", 0) or 0) for x in list(smart or [])}
        item_map = {str(x.get("code") or ""): x for x in list(scalp or [])}

        for p in list(core.paper.market_positions("KR")):
            q = qs.get(p.code)
            if q is None or float(getattr(q, "price", 0) or 0) <= 0:
                continue
            core.paper.mark("KR", p.code, float(q.price), 1.0)
            condition = str(getattr(p, "strategy", "") or "")
            meta = state["positions"].setdefault(
                p.code,
                {"condition": condition if condition in ("조건1", "조건2", "조건3") else condition, "entry_ts": float(getattr(p, "entry_ts", 0) or now.timestamp()), "max_pnl_30m": -999.0},
            )
            try:
                entered = datetime.fromtimestamp(float(getattr(p, "entry_ts", 0) or meta.get("entry_ts") or now.timestamp()), core.KST)
            except Exception:
                entered = now
            age_min = max(0.0, (now.timestamp() - entered.timestamp()) / 60.0)
            pnl = float(p.pnl_pct)

            if core.must_force_sell_pre(p, now):
                if _sell(p, q, "08:49 프리세션 강제청산"):
                    continue
            target = (item_map.get(p.code) or {}).get("vi_target") or (item_map.get(p.code) or {}).get("vi_pre")
            if condition != "SMART" and target and float(target) > float(p.avg_price) and float(q.price) >= float(target):
                if _sell(p, q, "VI 직전 익절"):
                    continue
            entry_mins = _mins(entered)
            if entry_mins >= 15 * 60 + 40:
                if mins >= 19 * 60 + 59:
                    if _sell(p, q, "NXT 19:59 장마감 강제청산"):
                        continue
            elif mins >= 15 * 60 + 19:
                if _sell(p, q, "KRX 15:19 동시호가 전 강제청산"):
                    continue

            if condition == "조건3" and mins >= C3_TRADE[1]:
                if _sell(p, q, "조건3 13:00 전략 종료"):
                    continue

            if pnl <= -1.5:
                if _sell(p, q, "기존 손절 -1.5%"):
                    continue
            if pnl >= 3.0:
                if _sell(p, q, "기존 목표수익 +3%"):
                    continue

            if condition in ("조건1", "조건2"):
                if pnl >= 1.0:
                    if _sell(p, q, f"{condition} +1% 목표 익절"):
                        continue

                score = _current_strategy_score(p.code, condition, scalp)
                if score is not None:
                    key = condition + ":" + p.code
                    if now.timestamp() - float(last_score_sample.get(key, 0) or 0) >= 175:
                        last_score_sample[key] = now.timestamp()
                        score_hist.setdefault(key, deque(maxlen=8)).append((now.timestamp(), score))
                    sig, sig_reason = _score_exit_signal(score_hist.get(key, deque()))
                    if sig:
                        if _sell(p, q, sig_reason):
                            continue

                deadline = _deadline_for(condition, entered)
                if deadline is not None and mins >= deadline and pnl > FEE_BUFFER_PCT:
                    if _sell(p, q, f"{condition} 시간목표 미달 · 수수료버퍼 제외 순이익 청산"):
                        continue

            if condition == "조건3":
                o = float(getattr(q, "open", 0) or 0)
                ch = (float(q.price) / o - 1.0) * 100.0 if o > 0 else 0.0
                if ch >= C3_TARGET_BAND[0]:
                    if _sell(p, q, f"조건3 목표등락률 도달 {ch:.2f}%"):
                        continue
                if age_min >= 20.0 and pnl > FEE_BUFFER_PCT:
                    if _sell(p, q, "조건3 20분 목표 미도달 · 순이익 익절"):
                        continue

            if condition in ("조건1", "조건2"):
                if age_min <= 30.0:
                    meta["max_pnl_30m"] = max(float(meta.get("max_pnl_30m", -999) or -999), pnl)
                elif float(meta.get("max_pnl_30m", -999) or -999) <= 0.5 and pnl > FEE_BUFFER_PCT:
                    if _sell(p, q, "30분 +0.5% 미달 · 수수료버퍼 제외 순이익 청산"):
                        continue

            if condition == "SMART":
                sc = smart_map.get(p.code, 50.0)
                if sc < 46:
                    if _sell(p, q, "SMART AI 점수 이탈"):
                        continue

        persist()

    core.mark_and_sell = mark_and_sell

    old_health = core.health_payload

    def health():
        d = dict(old_health())
        try:
            samsung_1m = len(list(core.feed.bars("KR", "005930", "1m") or []))
        except Exception:
            samsung_1m = 0
        try:
            kospi_1m = len(list(core.feed.market_bars("kospi", "1m") or []))
        except Exception:
            kospi_1m = 0
        try:
            sync = core._minute_sync_status()
        except Exception:
            sync = {}
        d["strategy_models"] = {
            "condition1": "RECIPE80+TECH20; 09:00-09:20/13:00-14:00; outside=time-exception if 3m score rises",
            "condition2": "VOLUME20+EXEC20+CHANGE20+TECH40; KOSPI prev completed 1m up; current <=60% of high-day close",
            "condition3": "09:00-11:00 monitor 3~5%; 11:00-13:00 entry 2.7~3.3%; target >=4.7%; top3 sector",
        }
        d["positive_event_window"] = {"disclosure_days": 3, "news_days": 1}
        d["minute_runtime"] = {
            "samsung_1m_bars": samsung_1m,
            "kospi_1m_bars": kospi_1m,
            "pc_sync_count": sync.get("count"),
            "pc_sync_fresh": sync.get("fresh"),
        }
        d["condition3_monitor"] = {
            "qualified": len(state.get("c3_qualified") or {}),
            "available_universe": len(_available_universe()),
            "master_count": len(getattr(core.feed, "kr_master_meta", {}) or {}),
            "monitor": "09:00~11:00",
            "trade": "11:00~13:00",
        }
        d["fee_buffer_pct"] = FEE_BUFFER_PCT
        return d

    core.health_payload = health

    def diag_worker():
        while True:
            try:
                time.sleep(60)
                h = health()
                m = h.get("minute_runtime") or {}
                c3 = h.get("condition3_monitor") or {}
                print(
                    f"STRATEGY123 DIAG samsung_1m={m.get('samsung_1m_bars')} kospi_1m={m.get('kospi_1m_bars')} "
                    f"pc_sync={m.get('pc_sync_count')} fresh={m.get('pc_sync_fresh')} "
                    f"c3_available={c3.get('available_universe')}/{c3.get('master_count')} qualified={c3.get('qualified')}",
                    flush=True,
                )
            except Exception as exc:
                print("STRATEGY123 DIAG ERROR:", str(exc)[:160], flush=True)

    threading.Thread(target=diag_worker, daemon=True).start()
    print(
        "NAMUH STRATEGY123 active: C1/C2/C3 + 3m score exits + 30m low-profit exit + disclosure3d/news1d + sector peer rank",
        flush=True,
    )
