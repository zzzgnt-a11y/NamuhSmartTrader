from __future__ import annotations

import threading
import time
from collections import deque
from datetime import datetime

STATE_KEY = "strategy123_us_state_v1"
ENTRY_WINDOW = (22 * 60, 24 * 60)          # KST 22:00 ~ 24:00, all C1/C2/C3 entries
C3_MONITOR_WINDOW = (20 * 60, 22 * 60)    # monitor only; no entry before 22:00 KST
C3_ENTRY_BAND = (2.7, 3.3)
C3_TARGET_BAND = (4.7, 5.3)
FEE_BUFFER_PCT = 0.05


def _clamp(v, lo=0.0, hi=100.0):
    try:
        x = float(v or 0)
    except Exception:
        x = 0.0
    return max(lo, min(hi, x))


def _mins(dt):
    return int(dt.hour) * 60 + int(dt.minute)


def _in_window(mins, w):
    return w[0] <= mins < w[1]


def _change_pct(q):
    o = float(getattr(q, "open", 0) or 0)
    p = float(getattr(q, "price", 0) or 0)
    return (p / o - 1.0) * 100.0 if o > 0 and p > 0 else 0.0


def _change20(q):
    ch = _change_pct(q)
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


def _monthly_discount(q):
    bars = list(getattr(q, "daily_bars", []) or [])
    clean = []
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
    if len(clean) < 20:
        return {"ready": False, "pass": False, "history_days": len(clean), "source": "US_DAILY_PENDING"}
    d, high, ref_close = max(clean, key=lambda x: x[1])
    px = float(getattr(q, "price", 0) or 0)
    ratio = px / ref_close if ref_close > 0 else 999.0
    return {
        "ready": True,
        "pass": bool(px > 0 and ratio <= 0.60),
        "history_days": len(clean),
        "high_day": d,
        "high": high,
        "high_day_close": ref_close,
        "price": px,
        "drop_pct": round((1.0 - ratio) * 100.0, 1) if ratio < 900 else None,
        "source": "NH_US_DAILY",
    }


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
    if core is None or getattr(core, "_NAMUH_US_STRATEGY123_APPLIED", False):
        return
    core._NAMUH_US_STRATEGY123_APPLIED = True

    lock = threading.RLock()
    raw = core.store.load_json(STATE_KEY, {}) or {}
    state = raw if isinstance(raw, dict) else {}
    state.setdefault("positions", {})
    state.setdefault("c3_qualified", {})
    state.setdefault("c3_day", "")
    score_hist = {}
    score_last = {}
    c3_hist = {}
    c3_last = {}

    def persist():
        try:
            with lock:
                payload = {
                    "positions": dict(state.get("positions") or {}),
                    "c3_qualified": dict(state.get("c3_qualified") or {}),
                    "c3_day": str(state.get("c3_day") or ""),
                }
            core.store.save_json(STATE_KEY, payload)
        except Exception:
            pass

    old_candidate = core.candidate

    def candidate(q, market, smart=False, secmap=None, stockmap=None, leadermap=None, sector_rankmap=None, now=None):
        out = old_candidate(q, market, smart, secmap, stockmap, leadermap, sector_rankmap, now)
        if smart or not isinstance(out, dict) or str(market or "").upper() != "US":
            return out

        blocked = bool(getattr(q, "event_blocked", False))
        try:
            blocked = blocked or any(bool(e.get("blocked")) for e in list(getattr(q, "events", []) or []) if isinstance(e, dict))
        except Exception:
            pass

        total = float(out.get("score", 0) or 0)
        c1_gate = bool(not blocked and out.get("execution_gate_pass", False) and total >= 72.0)

        comps = dict(out.get("score_components") or {})
        vol20 = round(_clamp(float(comps.get("volume15", 0) or 0) / 15.0 * 20.0, 0, 20), 1)
        exec20 = round(_clamp(float(comps.get("execution20", 0) or 0), 0, 20), 1)
        change20, change_pct = _change20(q)
        tech40 = round(_clamp(float(out.get("technical_score", comps.get("technical20", 0)) or 0) * 2.0, 0, 40), 1)
        c2_total = round(_clamp(vol20 + exec20 + change20 + tech40, 0, 100), 1)
        monthly = _monthly_discount(q)

        # US equivalent of the KR broad-market direction gate.  If NASDAQ
        # official data is temporarily unavailable, it is fail-soft rather than
        # blocking every US candidate; the score/execution/monthly gates remain.
        idx = dict((getattr(core.feed, "market", {}) or {}).get("nasdaq") or {})
        idx_ready = float(idx.get("value") or 0) > 0
        idx_change = float(idx.get("change_pct") or 0) if idx_ready else None
        idx_up = bool(idx_ready and idx_change is not None and idx_change > 0)
        index_gate = bool(idx_up if idx_ready else True)
        c2_gate = bool(
            not blocked
            and out.get("execution_gate_pass", False)
            and c2_total >= 72.0
            and monthly.get("ready")
            and monthly.get("pass")
            and index_gate
        )

        sector_rank = int(out.get("sector_rank") or 999)
        c3_top3 = sector_rank <= 3
        code = str(out.get("code") or "").upper()
        with lock:
            c3_qualified = code in (state.get("c3_qualified") or {})
        c3_gate = bool(c3_qualified and c3_top3 and C3_ENTRY_BAND[0] <= change_pct <= C3_ENTRY_BAND[1])

        out["condition1"] = {"score": total, "gate": c1_gate, "label": "조건1"}
        out["condition2"] = {
            "score": c2_total,
            "front60": {"volume20": vol20, "execution20": exec20, "change20": change20, "change_pct": change_pct},
            "technical40": tech40,
            "monthly_discount": monthly,
            "nasdaq_gate": {"ready": idx_ready, "up": idx_up, "change_pct": idx_change, "failsoft": not idx_ready},
            "gate": c2_gate,
            "label": "조건2",
        }
        out["condition2_score"] = c2_total
        out["condition2_gate_pass"] = c2_gate
        out["condition3"] = {
            "sector_rank": sector_rank,
            "sector_top3": c3_top3,
            "qualified": c3_qualified,
            "change_pct": change_pct,
            "monitor_window_kst": "20:00~22:00",
            "trade_window_kst": "22:00~24:00",
            "entry_band": list(C3_ENTRY_BAND),
            "target_band": list(C3_TARGET_BAND),
            "gate": c3_gate,
            "label": "조건3",
        }
        labels = []
        if c1_gate:
            labels.append("조건1")
        if c2_gate:
            labels.append("조건2")
        if c3_gate:
            labels.append("조건3")
        out["condition_labels"] = labels
        out["condition_display"] = "복합조건" if len(labels) > 1 else (labels[0] if labels else "")
        out["us_entry_window_kst"] = "22:00~24:00"
        reasons = list(out.get("reasons") or [])
        reasons.insert(0, f"미장 조건1 {total:.1f}점 · 조건2 {c2_total:.1f}점 · 조건1/2/3 진입 KST 22:00~24:00")
        out["reasons"] = reasons
        return out

    core.candidate = candidate

    old_restore = core._restore_paper

    def restore_paper():
        old_restore()
        changed = False
        for p in list(core.paper.positions.values()):
            if p.market != "US":
                continue
            if str(p.strategy or "SCALP") == "SCALP":
                p.strategy = "조건1"
                changed = True
            if p.strategy in ("조건1", "조건2", "조건3"):
                state["positions"].setdefault(
                    p.code,
                    {"condition": p.strategy, "entry_ts": float(p.entry_ts or time.time()), "max_pnl_30m": -999.0},
                )
        if changed:
            try:
                core._persist_paper()
            except Exception:
                pass
        persist()

    core._restore_paper = restore_paper

    def _sample_scores(candidates, ts):
        for x in list(candidates or []):
            code = str(x.get("code") or "").upper()
            if not code:
                continue
            for cond, score in (("조건1", x.get("score")), ("조건2", x.get("condition2_score"))):
                if score is None:
                    continue
                key = cond + ":" + code
                if ts - float(score_last.get(key, 0) or 0) >= 175:
                    score_last[key] = ts
                    score_hist.setdefault(key, deque(maxlen=8)).append((ts, float(score or 0)))

    def _c3_monitor(candidates, now):
        day = now.strftime("%Y%m%d")
        if state.get("c3_day") != day:
            with lock:
                state["c3_day"] = day
                state["c3_qualified"] = {}
                c3_hist.clear()
                c3_last.clear()
            persist()
        if not _in_window(_mins(now), C3_MONITOR_WINDOW):
            return
        ts = now.timestamp()
        qmap = core.feed.quotes_for("US")
        for x in list(candidates or []):
            code = str(x.get("code") or "").upper()
            if not code:
                continue
            q = qmap.get(code)
            if q is None:
                continue
            ch = _change_pct(q)
            if ch < 2.2 or ch > 5.8:
                continue
            if ts - float(c3_last.get(code, 0) or 0) < 55:
                continue
            c3_last[code] = ts
            h = c3_hist.setdefault(code, deque(maxlen=140))
            h.append((ts, ch))
            vals = [float(v[1]) for v in h]
            if len(vals) < 8:
                continue
            in_band = sum(2.7 <= v <= 5.3 for v in vals) / len(vals)
            touched_low = any(C3_ENTRY_BAND[0] <= v <= C3_ENTRY_BAND[1] for v in vals)
            touched_high = any(C3_TARGET_BAND[0] <= v <= C3_TARGET_BAND[1] for v in vals)
            if in_band >= 0.70 and touched_low and touched_high:
                with lock:
                    state["c3_qualified"][code] = {
                        "qualified_at": ts,
                        "samples": len(vals),
                        "band_ratio": round(in_band, 3),
                        "min": round(min(vals), 3),
                        "max": round(max(vals), 3),
                    }
        if int(ts) % 60 < 6:
            persist()

    def _buy(item, condition, now):
        code = str(item.get("code") or "").upper()
        if not code or f"US:{code}" in core.paper.positions:
            return False
        if len(core.paper.market_positions("US")) >= 3:
            return False
        ok, _ = core.feed.entry_data_status("US", code, now.timestamp())
        if not ok:
            return False
        if not core._buy_one("US", item, condition, f"{condition}_KST_22_24", now):
            return False
        p = core.paper.positions.get("US:" + code)
        if p is not None:
            p.strategy = condition
        score = float(item.get("score") if condition == "조건1" else item.get("condition2_score") or item.get("score") or 0)
        state["positions"][code] = {
            "condition": condition,
            "entry_ts": float(getattr(p, "entry_ts", now.timestamp()) if p is not None else now.timestamp()),
            "entry_score": score,
            "max_pnl_30m": -999.0,
        }
        key = condition + ":" + code
        if condition in ("조건1", "조건2"):
            score_hist[key] = deque([(now.timestamp(), score)], maxlen=8)
            score_last[key] = now.timestamp()
        try:
            core._persist_paper()
        except Exception:
            pass
        persist()
        print(f"US STRATEGY BUY {condition} {code} KST={now.strftime('%H:%M')} price={float(item.get('price') or 0):.4f}", flush=True)
        return True

    old_trade = core.trade_scalp

    def trade_scalp(market, candidates, now=None):
        if str(market or "").upper() != "US":
            return old_trade(market, candidates, now)
        now = (now or core.datetime.now(core.KST)).astimezone(core.KST)
        if now.weekday() >= 5:
            return
        mins = _mins(now)
        ts = now.timestamp()
        _sample_scores(candidates, ts)
        _c3_monitor(candidates, now)

        # User rule: every US condition may enter only from 22:00 through 24:00 KST.
        if not _in_window(mins, ENTRY_WINDOW):
            return

        # Keep KR C3 priority semantics: qualified C3 gets first chance.
        for x in list(candidates or []):
            code = str(x.get("code") or "").upper()
            if len(core.paper.market_positions("US")) >= 3:
                return
            if not code or f"US:{code}" in core.paper.positions:
                continue
            c3 = x.get("condition3") or {}
            if bool(c3.get("gate")) and _buy(x, "조건3", now):
                return

        for x in list(candidates or []):
            code = str(x.get("code") or "").upper()
            if len(core.paper.market_positions("US")) >= 3:
                break
            if not code or f"US:{code}" in core.paper.positions:
                continue
            if bool((x.get("condition1") or {}).get("gate")):
                if _buy(x, "조건1", now):
                    return
            if bool(x.get("condition2_gate_pass", False)):
                if _buy(x, "조건2", now):
                    return

    core.trade_scalp = trade_scalp

    def _current_score(code, condition, scalp):
        for x in list(scalp or []):
            if str(x.get("code") or "").upper() != str(code).upper():
                continue
            return float(x.get("score") if condition == "조건1" else x.get("condition2_score") or 0)
        return None

    def _sell(p, q, reason):
        px = float(getattr(q, "price", 0) or getattr(p, "current_price", 0) or 0)
        fx = float(core._fx("US") or 0)
        if px <= 0 or fx <= 0:
            return False
        try:
            core.paper.mark("US", p.code, px, fx)
        except Exception:
            pass
        if core.paper.sell("US", p.code, px, fx, reason):
            state["positions"].pop(p.code, None)
            try:
                core._persist_paper()
            except Exception:
                pass
            persist()
            print(f"US STRATEGY SELL {p.strategy} {p.code} {reason}", flush=True)
            return True
        return False

    old_sell = core.mark_and_sell

    def mark_and_sell(market, scalp, smart, now=None):
        if str(market or "").upper() != "US":
            return old_sell(market, scalp, smart, now)
        now = (now or core.datetime.now(core.KST)).astimezone(core.KST)

        # Preserve existing US -1.5/+3/score-drop and 15:59 ET forced exit first.
        out = old_sell(market, scalp, smart, now)
        live_codes = {p.code for p in core.paper.market_positions("US")}
        dirty = False
        for code in list((state.get("positions") or {}).keys()):
            if code not in live_codes:
                state["positions"].pop(code, None)
                dirty = True
        if dirty:
            persist()

        qmap = core.feed.quotes_for("US")
        for p in list(core.paper.market_positions("US")):
            condition = str(getattr(p, "strategy", "") or "")
            if condition not in ("조건1", "조건2", "조건3"):
                continue
            q = qmap.get(p.code)
            if q is None or float(getattr(q, "price", 0) or 0) <= 0:
                continue
            fx = float(core._fx("US") or 0)
            if fx <= 0:
                continue
            core.paper.mark("US", p.code, float(q.price), fx)
            pnl = float(p.pnl_pct)
            meta = state["positions"].setdefault(
                p.code,
                {"condition": condition, "entry_ts": float(getattr(p, "entry_ts", 0) or now.timestamp()), "max_pnl_30m": -999.0},
            )
            try:
                entered = datetime.fromtimestamp(float(getattr(p, "entry_ts", 0) or meta.get("entry_ts") or now.timestamp()), core.KST)
            except Exception:
                entered = now
            age_min = max(0.0, (now.timestamp() - entered.timestamp()) / 60.0)

            if condition in ("조건1", "조건2"):
                if pnl >= 1.0:
                    if _sell(p, q, f"{condition} +1% 목표 익절"):
                        continue

                score = _current_score(p.code, condition, scalp)
                if score is not None:
                    key = condition + ":" + p.code
                    if now.timestamp() - float(score_last.get(key, 0) or 0) >= 175:
                        score_last[key] = now.timestamp()
                        score_hist.setdefault(key, deque(maxlen=8)).append((now.timestamp(), score))
                    sig, reason = _score_exit_signal(score_hist.get(key, deque()))
                    if sig and _sell(p, q, reason):
                        continue

                if age_min <= 30.0:
                    meta["max_pnl_30m"] = max(float(meta.get("max_pnl_30m", -999.0) or -999.0), pnl)
                if age_min >= 30.0 and float(meta.get("max_pnl_30m", -999.0) or -999.0) <= 0.5 and pnl > FEE_BUFFER_PCT:
                    if _sell(p, q, f"{condition} 30분 +0.5% 이하 · 순이익 전환 청산"):
                        continue

            if condition == "조건3":
                ch = _change_pct(q)
                if ch >= C3_TARGET_BAND[0]:
                    if _sell(p, q, f"조건3 목표등락률 도달 {ch:.2f}%"):
                        continue

        persist()
        return out

    core.mark_and_sell = mark_and_sell

    try:
        old_health = core.health_payload
        def health():
            d = dict(old_health())
            d["us_strategy_conditions"] = ["조건1", "조건2", "조건3"]
            d["us_condition_entry_window_kst"] = "22:00~24:00"
            d["us_c3_monitor_window_kst"] = "20:00~22:00"
            return d
        core.health_payload = health
    except Exception:
        pass

    print("NAMUH US STRATEGY123 active: C1/C2/C3 entries KST 22:00~24:00", flush=True)
