from __future__ import annotations

import math
import threading
import time
from collections import deque
from datetime import datetime
from types import MethodType
from zoneinfo import ZoneInfo

_INSTALLED = False
_LEDGER_KEY = "paper_market_accounts_v1"
_OVERLAP_KEY = "strategy_overlap_display_v1"
_COIN_META_KEY = "coin_condition2_meta_v1"
_FEE_BUFFER = 0.05


def _f(v, default=0.0):
    try:
        return float(v)
    except Exception:
        return float(default)


def _clamp(v, lo=0.0, hi=100.0):
    return max(lo, min(hi, _f(v)))


def _mins(dt):
    return dt.hour * 60 + dt.minute


def _labels_display(labels):
    labels = [str(x) for x in labels if x]
    labels = list(dict.fromkeys(labels))
    return "복합조건" if len(labels) >= 2 else (labels[0] if labels else "")


def _wma(values, n):
    n = max(1, int(n))
    vals = list(values)
    out = [None] * len(vals)
    den = n * (n + 1) / 2.0
    for i in range(n - 1, len(vals)):
        w = vals[i - n + 1:i + 1]
        out[i] = sum((j + 1) * w[j] for j in range(n)) / den
    return out


def _hma(values, n=26):
    vals = list(values)
    n2 = max(1, n // 2)
    root = max(1, int(round(math.sqrt(n))))
    a = _wma(vals, n2)
    b = _wma(vals, n)
    raw = []
    for x, y in zip(a, b):
        raw.append(None if x is None or y is None else 2.0 * x - y)
    out = [None] * len(vals)
    for i in range(root - 1, len(raw)):
        w = raw[i - root + 1:i + 1]
        if any(x is None for x in w):
            continue
        den = root * (root + 1) / 2.0
        out[i] = sum((j + 1) * w[j] for j in range(root)) / den
    return out


def _coin_c2_signal(bars):
    rows = [dict(x) for x in list(bars or []) if isinstance(x, dict)]
    if len(rows) < 35:
        return {"ready": False, "buy": False, "sell": False, "bars": len(rows), "reason": "캔들 35개 미만"}
    # The newest exchange candle can still be forming. Signals use the latest
    # completed candle only.
    rows = rows[:-1] if len(rows) > 35 else rows
    if len(rows) < 35:
        return {"ready": False, "buy": False, "sell": False, "bars": len(rows), "reason": "완료봉 35개 미만"}
    src = [(_f(x.get("high")) + _f(x.get("low"))) / 2.0 for x in rows]
    closes = [_f(x.get("close")) for x in rows]
    vols = [_f(x.get("volume")) for x in rows]
    h = _hma(src, 26)
    if any(h[-i] is None for i in (1, 2, 3)):
        return {"ready": False, "buy": False, "sell": False, "bars": len(rows), "reason": "HMA26 준비중"}
    obv = [0.0]
    for i in range(1, len(rows)):
        d = vols[i] if closes[i] > closes[i - 1] else -vols[i] if closes[i] < closes[i - 1] else 0.0
        obv.append(obv[-1] + d)
    if len(obv) < 7:
        return {"ready": False, "buy": False, "sell": False, "bars": len(rows), "reason": "TFS 준비중"}
    base = sum(obv[-7:]) / 7.0
    tfs = obv[-1] - base
    bull = _f(rows[-1].get("close")) > _f(rows[-1].get("open"))
    bear = _f(rows[-1].get("close")) < _f(rows[-1].get("open"))
    buy_sig = h[-2] <= h[-3] and h[-1] > h[-2]
    sell_sig = h[-2] >= h[-3] and h[-1] < h[-2]
    lows = [_f(x.get("low")) for x in rows]
    highs = [_f(x.get("high")) for x in rows]
    swing_low = 0.0
    swing_high = 0.0
    for i in range(len(rows) - 2, max(1, len(rows) - 12), -1):
        if lows[i] > 0 and lows[i] <= lows[i - 1] and lows[i] <= lows[i + 1]:
            swing_low = lows[i]
            break
    for i in range(len(rows) - 2, max(1, len(rows) - 12), -1):
        if highs[i] > 0 and highs[i] >= highs[i - 1] and highs[i] >= highs[i + 1]:
            swing_high = highs[i]
            break
    if swing_low <= 0:
        swing_low = min(x for x in lows[-6:] if x > 0)
    if swing_high <= 0:
        swing_high = max(highs[-6:])
    return {
        "ready": True,
        "buy": bool(buy_sig and bull and tfs < 0),
        "sell": bool(sell_sig and bear and tfs > 0),
        "hull_buy_signal": bool(buy_sig),
        "hull_sell_signal": bool(sell_sig),
        "bull_candle": bool(bull),
        "bear_candle": bool(bear),
        "tfs": round(tfs, 8),
        "tfs_below_zero": bool(tfs < 0),
        "tfs_above_zero": bool(tfs > 0),
        "hma": round(_f(h[-1]), 8),
        "swing_low": swing_low,
        "swing_high": swing_high,
        "bars": len(rows),
        "source": "Hull Suite HMA26/hl2 + OBV-SMA7 TFS",
    }


def apply(ns):
    global _INSTALLED
    if _INSTALLED:
        return
    core = ns.get("core")
    if core is None:
        return
    _INSTALLED = True

    # Final UI owners are appended after every legacy/runtime asset, so they do
    # not race older scripts. No polling/MutationObserver is added here.
    try:
        from pathlib import Path
        p = Path("static/stock.js")
        if p.exists():
            text = p.read_text(encoding="utf-8")
            text = text.replace(
                "Math.floor((TF==='1d'?42:55)/zoom)",
                "Math.floor((TF==='1d'?42:(TF==='1m'?60:30))/zoom)"
            )
            old_sd = "function shortDate(v){const s=String(v||'').replace(/\\D/g,'');return s.length>=8?`${s.slice(4,6)}/${s.slice(6,8)}`:String(v||'')}"
            new_sd = "function shortDate(v){const s=String(v||'').replace(/\\D/g,'');if(TF!=='1d'&&s.length>=12)return `${s.slice(8,10)}:${s.slice(10,12)}`;return s.length>=8?`${s.slice(4,6)}/${s.slice(6,8)}`:String(v||'')}"
            text = text.replace(old_sd, new_sd)
            p.write_text(text, encoding="utf-8")
        inject = ns.get("_inject")
        if callable(inject):
            inject("static/index.html", css=False, scripts=("/static/v360_final.js",))
            inject("static/stock.html", css=False, scripts=("/static/stock-v360.js",))
            inject("static/coin.html", css=False, scripts=("/static/coin-v360.js",))
    except Exception as exc:
        print("NAMUH V360 UI INSTALL ERROR:", str(exc)[:180], flush=True)

    lock = threading.RLock()
    paper = core.paper
    market_initial = {"KR": float(paper.initial_cash_krw), "US": float(paper.initial_cash_krw)}
    market_cash = {"KR": float(paper.initial_cash_krw), "US": float(paper.initial_cash_krw)}
    ledger_loaded = False
    overlap = {}
    coin_meta = {}
    coin_c2_cache = {}
    coin_c2_lock = threading.RLock()
    stock_score_hist = {}
    stock_last_sample = {}
    us_c3_hist = {}
    us_c3_last_sample = {}

    # ---------------------------- persistence / independent KR-US ledgers
    old_restore = core._restore_paper
    old_persist = core._persist_paper
    old_effective = paper.effective_budget_krw
    old_buy = paper.buy
    old_sell = paper.sell

    def base_budget():
        explicit = getattr(paper, "explicit_budget_krw", None)
        if explicit is not None:
            return max(0.0, min(float(explicit), float(paper.initial_cash_krw)))
        return float(paper.initial_cash_krw) if getattr(paper, "auto_max_if_unset", True) else 0.0

    def sync_global_cash():
        paper.cash_krw = float(market_cash["KR"] + market_cash["US"])

    def reconstruct_cash(market):
        cash = float(market_initial[market])
        # Replaying the stored cash legs migrates the former shared book into
        # two independent paper accounts without fabricating fills.
        for t in reversed(list(getattr(paper, "trades", []) or [])):
            if str(t.get("market") or "").upper() != market:
                continue
            gross = _f(t.get("gross_krw"))
            if str(t.get("side") or "").upper() == "BUY":
                cash -= gross
            elif str(t.get("side") or "").upper() == "SELL":
                cash += gross
        return max(0.0, cash)

    def load_aux():
        nonlocal overlap, coin_meta, ledger_loaded
        d = core.store.load_json(_LEDGER_KEY, {}) or {}
        if isinstance(d, dict) and isinstance(d.get("cash"), dict):
            for m in ("KR", "US"):
                if d["cash"].get(m) is not None:
                    market_cash[m] = max(0.0, _f(d["cash"].get(m), market_initial[m]))
        else:
            for m in ("KR", "US"):
                market_cash[m] = reconstruct_cash(m)
        od = core.store.load_json(_OVERLAP_KEY, {}) or {}
        overlap = dict(od) if isinstance(od, dict) else {}
        cm = core.store.load_json(_COIN_META_KEY, {}) or {}
        coin_meta = dict(cm) if isinstance(cm, dict) else {}
        sync_global_cash()
        ledger_loaded = True

    def save_aux():
        try:
            core.store.save_json(_LEDGER_KEY, {
                "version": 1, "cash": dict(market_cash), "initial": dict(market_initial), "updated_at": time.time()
            })
            core.store.save_json(_OVERLAP_KEY, dict(overlap))
            core.store.save_json(_COIN_META_KEY, dict(coin_meta))
        except Exception:
            pass

    def restore():
        old_restore()
        # Stock asset owner may have changed the initial cash during restore.
        market_initial["KR"] = float(paper.initial_cash_krw)
        market_initial["US"] = float(paper.initial_cash_krw)
        load_aux()
        # Legacy coin strategy name -> Condition 1 only. This changes labels,
        # not the existing entry/exit recipe.
        try:
            for p in core.coin_paper.positions.values():
                if str(getattr(p, "strategy", "")) in ("COIN_SCALP", "SCALP"):
                    p.strategy = "조건1"
            for t in core.coin_paper.trades:
                if str(t.get("strategy") or "") in ("COIN_SCALP", "SCALP"):
                    t["strategy"] = "조건1"
            core._persist_coin()
        except Exception:
            pass
        save_aux()

    def persist():
        if not ledger_loaded:
            return old_persist()
        sync_global_cash()
        old_persist()
        save_aux()

    core._restore_paper = restore
    core._persist_paper = persist

    def effective_budget(self, day_key):
        # Compatibility budget exposed to old strategy code is the sum of the
        # two independent market budgets. Per-market limits are enforced below.
        return base_budget() * 2.0

    paper.effective_budget_krw = MethodType(effective_budget, paper)

    def buy(self, quote, qty, market, fx_rate, day_key, strategy="SCALP", entry_session=""):
        m = str(market or "").upper()
        if m not in ("KR", "US"):
            return old_buy(quote, qty, market, fx_rate, day_key, strategy, entry_session)
        fx = _f(fx_rate if m == "US" else 1.0, 1.0)
        unit = _f(getattr(quote, "price", 0)) * fx
        if unit <= 0:
            return None
        available = min(
            market_cash[m],
            max(0.0, base_budget() - _f(paper.held_cost_krw(m))),
        )
        affordable = int(available // unit)
        qty = min(int(qty or 0), affordable)
        if qty < 1:
            return None
        sync_global_cash()
        trade = old_buy(quote, qty, m, fx_rate, day_key, strategy, entry_session)
        if trade:
            market_cash[m] = max(0.0, market_cash[m] - _f(trade.get("gross_krw")))
            sync_global_cash()
            save_aux()
        return trade

    def sell(self, market, code, price, fx_rate, reason=""):
        m = str(market or "").upper()
        sync_global_cash()
        trade = old_sell(m, code, price, fx_rate, reason)
        if trade and m in market_cash:
            market_cash[m] += _f(trade.get("gross_krw"))
            sync_global_cash()
            save_aux()
        return trade

    paper.buy = MethodType(buy, paper)
    paper.sell = MethodType(sell, paper)

    # ---------------------------- overlap display (logic remains independent)
    def active_kr_labels(item, now):
        mins = _mins(now)
        labels = []
        c1 = bool((item.get("condition1") or {}).get("gate"))
        c2 = bool(item.get("condition2_gate_pass", False))
        c1time = 9*60 <= mins <= 9*60+20 or 13*60 <= mins <= 14*60
        c2time = 9*60 <= mins <= 9*60+30 or 13*60 <= mins <= 15*60
        if c1 and c1time:
            labels.append("조건1")
        if c2 and c2time:
            labels.append("조건2")
        return labels

    old_trade_scalp = core.trade_scalp
    old_mark_sell = core.mark_and_sell
    old_candidate = core.candidate

    def sample_score(key, score, ts):
        if ts - _f(stock_last_sample.get(key)) < 175:
            return
        stock_last_sample[key] = ts
        stock_score_hist.setdefault(key, deque(maxlen=8)).append((ts, _f(score)))

    def rising(key):
        h = list(stock_score_hist.get(key, []))
        return len(h) >= 3 and h[-1][1] > h[-2][1] > h[-3][1]

    def exit_score(key):
        h = list(stock_score_hist.get(key, []))
        if len(h) < 3:
            return False, ""
        a, b, c = h[-3][1], h[-2][1], h[-1][1]
        if c < b:
            return True, "3분 점수 하락 전환"
        if b > a and b > c:
            return True, "3분 점수 고립상승"
        return False, ""

    def high_day_discount(q):
        rows = list(getattr(q, "daily_bars", []) or [])
        if len(rows) < 60:
            return {"ready": False, "pass": False, "ratio": None}
        row = max(rows, key=lambda x: _f(x.get("high")))
        close = _f(row.get("close"))
        price = _f(getattr(q, "price", 0))
        if close <= 0 or price <= 0:
            return {"ready": False, "pass": False, "ratio": None}
        ratio = price / close
        return {"ready": True, "pass": ratio <= 0.60, "ratio": round(ratio, 4), "high_day_close": close}

    def us_benchmark_up():
        for code, label in (("SPY", "SPY"), ("QQQ", "QQQ")):
            try:
                b = list(core.feed.bars("US", code, "1m") or [])
                if len(b) >= 2:
                    # Use the previous completed candle. The newest can still be forming.
                    x = b[-2]
                    return {"ready": True, "up": _f(x.get("close")) > _f(x.get("open")), "benchmark": label, "bar": x}
            except Exception:
                continue
        return {"ready": False, "up": False, "benchmark": "SPY/QQQ"}

    def candidate(q, market, smart=False, secmap=None, stockmap=None, leadermap=None, sector_rankmap=None, now=None):
        out = old_candidate(q, market, smart, secmap, stockmap, leadermap, sector_rankmap, now)
        if smart or not isinstance(out, dict) or str(market or "").upper() != "US":
            return out
        comps = dict(out.get("score_components") or {})
        score = _f(out.get("score"))
        blocked = bool(getattr(q, "event_blocked", False))
        c1_gate = bool(not blocked and score >= 72 and out.get("entry_gate_pass", True))
        vol20 = round(_clamp(_f(comps.get("volume15")) / 15.0 * 20.0, 0, 20), 1)
        exec20 = round(_clamp(_f(comps.get("execution20"), 10.0), 0, 20), 1)
        op = _f(getattr(q, "open", 0))
        ch = ((_f(getattr(q, "price", 0)) / op - 1.0) * 100.0) if op > 0 else 0.0
        change20 = round(_clamp((ch + 2.0) / 7.0 * 20.0, 0, 20), 1)
        tech_raw = out.get("technical_score")
        if tech_raw is None:
            tech_raw = comps.get("technical20")
        tech40 = round(_clamp(_f(tech_raw) * 2.0, 0, 40), 1)
        c2score = round(_clamp(vol20 + exec20 + change20 + tech40), 1)
        bench = us_benchmark_up()
        discount = high_day_discount(q)
        c2_gate = bool(not blocked and c2score >= 70 and bench.get("ready") and bench.get("up") and discount.get("ready") and discount.get("pass"))
        rank = 999
        for k in ("sector_rank", "sector_peer_rank"):
            if out.get(k) is not None:
                try:
                    rank = int(out.get(k))
                    break
                except Exception:
                    pass
        out["condition1"] = {"score": score, "gate": c1_gate, "label": "조건1"}
        out["condition2"] = {
            "score": c2score, "gate": c2_gate, "label": "조건2",
            "front60": {"volume20": vol20, "execution20": exec20, "change20": change20, "change_pct": ch},
            "technical40": tech40, "market_1m": bench, "monthly_discount": discount,
        }
        out["condition2_score"] = c2score
        out["condition2_gate_pass"] = c2_gate
        out["condition3"] = {
            "score": score, "score_gate": score >= 75, "sector_rank": rank,
            "sector_top3": rank <= 3, "change_pct": ch,
            "monitor_window": "09:30~11:30 ET", "trade_window": "11:30~13:30 ET",
            "entry_band": [2.7, 3.3], "target_band": [4.7, 5.3], "label": "조건3",
        }
        labels = []
        if c1_gate:
            labels.append("조건1")
        if c2_gate:
            labels.append("조건2")
        out["condition_labels"] = labels
        out["condition_display"] = _labels_display(labels)
        return out

    core.candidate = candidate

    def us_now(now):
        if now is None:
            return datetime.now(ZoneInfo("America/New_York"))
        if getattr(now, "tzinfo", None) is None:
            now = now.replace(tzinfo=core.KST)
        return now.astimezone(ZoneInfo("America/New_York"))

    def us_c3_record(candidates, ny):
        m = _mins(ny)
        if not (9*60+30 <= m < 11*60+30):
            return
        ts = ny.timestamp()
        for x in list(candidates or []):
            code = str(x.get("code") or "")
            if not code or ts - _f(us_c3_last_sample.get(code)) < 55:
                continue
            us_c3_last_sample[code] = ts
            ch = _f((x.get("condition3") or {}).get("change_pct"))
            rank = int(_f((x.get("condition3") or {}).get("sector_rank"), 999))
            us_c3_hist.setdefault(code, deque(maxlen=180)).append((ts, ch, rank))

    def us_c3_ok(x, ny):
        code = str(x.get("code") or "")
        h = list(us_c3_hist.get(code, []))
        if len(h) < 3:
            return False
        elapsed = h[-1][0] - h[0][0]
        if elapsed < 900:
            return False
        vals = [a[1] for a in h]
        inside = sum(2.7 <= v <= 5.3 for v in vals) / max(1, len(vals))
        c3 = x.get("condition3") or {}
        return bool(
            inside >= 0.70 and min(vals) <= 3.3 and max(vals) >= 4.0
            and int(_f(c3.get("sector_rank"), 999)) <= 3
            and _f(c3.get("score"), x.get("score")) >= 75
            and 2.7 <= _f(c3.get("change_pct")) <= 3.3
        )

    def record_overlap(market, code, labels, entry_ts=None):
        labels = list(dict.fromkeys(labels))
        if len(labels) < 2:
            return
        overlap[f"{market}:{code}"] = {"labels": labels, "entry_ts": _f(entry_ts, time.time()), "updated_at": time.time()}
        save_aux()

    def trade_scalp(market, candidates, now=None):
        mkt = str(market or "").upper()
        if mkt == "KR":
            before = set(paper.positions)
            kst = (now or datetime.now(core.KST)).astimezone(core.KST)
            labelmap = {str(x.get("code") or ""): active_kr_labels(x, kst) for x in list(candidates or [])}
            out = old_trade_scalp(market, candidates, now)
            for key in set(paper.positions) - before:
                if not key.startswith("KR:"):
                    continue
                code = key.split(":", 1)[1]
                record_overlap("KR", code, labelmap.get(code, []), getattr(paper.positions.get(key), "entry_ts", time.time()))
            return out
        if mkt != "US":
            return old_trade_scalp(market, candidates, now)

        ny = us_now(now)
        ts = ny.timestamp()
        us_c3_record(candidates, ny)
        mins = _mins(ny)
        for x in list(candidates or []):
            code = str(x.get("code") or "")
            if not code:
                continue
            sample_score("US:조건1:" + code, x.get("score"), ts)
            sample_score("US:조건2:" + code, x.get("condition2_score"), ts)
        if len(paper.market_positions("US")) >= 3:
            return

        for x in list(candidates or []):
            code = str(x.get("code") or "")
            if not code or "US:" + code in paper.positions:
                continue
            c1 = bool((x.get("condition1") or {}).get("gate"))
            c2 = bool(x.get("condition2_gate_pass", False))
            c3 = bool(11*60+30 <= mins < 13*60+30 and us_c3_ok(x, ny))
            c1time = 9*60+30 <= mins <= 9*60+50 or 13*60 <= mins <= 14*60
            c2time = 9*60+30 <= mins <= 10*60 or 13*60 <= mins <= 15*60
            c1pass = c1 and (c1time or rising("US:조건1:" + code))
            c2pass = c2 and c2time
            labels = [name for name, ok in (("조건1", c1pass), ("조건2", c2pass), ("조건3", c3)) if ok]
            if not labels:
                continue
            strategy = labels[0]
            session = f"US_{strategy}"
            if core._buy_one("US", x, strategy, session, now):
                p = paper.positions.get("US:" + code)
                if p:
                    p.strategy = strategy
                    record_overlap("US", code, labels, p.entry_ts)
                core._persist_paper()
                return

    core.trade_scalp = trade_scalp

    def market_deadline(strategy, entered_ny):
        em = _mins(entered_ny)
        if strategy == "조건1":
            if 9*60+30 <= em <= 9*60+50:
                return 10*60+30
            if 13*60 <= em <= 14*60:
                return 15*60+10
        if strategy == "조건2":
            if 9*60+30 <= em <= 10*60:
                return 11*60
            if 13*60 <= em <= 15*60:
                return 14*60+50
        return None

    def mark_and_sell(market, scalp, smart, now=None):
        if str(market or "").upper() != "US":
            return old_mark_sell(market, scalp, smart, now)
        ny = us_now(now)
        mins = _mins(ny)
        qmap = core.feed.quotes_for("US")
        imap = {str(x.get("code") or ""): x for x in list(scalp or [])}
        handled = set()
        for p in list(paper.market_positions("US")):
            strategy = str(getattr(p, "strategy", "") or "")
            if strategy not in ("조건1", "조건2", "조건3"):
                continue
            q = qmap.get(p.code)
            if not q or _f(getattr(q, "price", 0)) <= 0:
                continue
            handled.add(p.code)
            fx = core._fx("US")
            paper.mark("US", p.code, q.price, fx)
            pnl = _f(p.pnl_pct)
            try:
                entered = datetime.fromtimestamp(_f(p.entry_ts, ny.timestamp()), core.KST).astimezone(ZoneInfo("America/New_York"))
            except Exception:
                entered = ny
            age = max(0.0, (ny.timestamp() - entered.timestamp()) / 60.0)
            item = imap.get(p.code) or {}
            score = _f(item.get("score") if strategy != "조건2" else item.get("condition2_score"))
            sample_score("US:" + strategy + ":" + p.code, score, ny.timestamp())

            reason = ""
            if mins >= 15*60+55:
                reason = "미장 정규장 마감 전 강제청산"
            elif pnl <= -1.5:
                reason = "손절 -1.5%"
            elif strategy in ("조건1", "조건2") and pnl >= 1.0:
                reason = f"{strategy} +1% 목표 익절"
            elif strategy == "조건3":
                c3 = item.get("condition3") or {}
                if _f(c3.get("change_pct")) >= 4.7:
                    reason = "조건3 목표등락률 도달"
                elif age >= 20 and pnl > _FEE_BUFFER:
                    reason = "조건3 20분 목표 미도달 · 순이익 익절"
                elif mins >= 13*60+30:
                    reason = "조건3 전략 종료"
            if not reason and strategy in ("조건1", "조건2"):
                sig, why = exit_score("US:" + strategy + ":" + p.code)
                if sig:
                    reason = why
                deadline = market_deadline(strategy, entered)
                if not reason and deadline is not None and mins >= deadline and pnl > _FEE_BUFFER:
                    reason = f"{strategy} 시간목표 미달 · 순이익 청산"
                if not reason and age > 30 and pnl > _FEE_BUFFER:
                    # Preserve the same low-profit timeout intent. We cannot
                    # reconstruct intra-position peak after a cold restart, so
                    # only apply when current PnL itself is <= +0.5%.
                    if pnl <= 0.5:
                        reason = "30분 +0.5% 미달 · 순이익 청산"
            if reason:
                if paper.sell("US", p.code, q.price, fx, reason):
                    core._persist_paper()
        # Let the legacy owner handle only non-condition US positions.
        leftovers = [p for p in paper.market_positions("US") if p.code not in handled]
        if leftovers:
            return old_mark_sell(market, scalp, smart, now)

    core.mark_and_sell = mark_and_sell

    # ---------------------------- market-specific account state / PnL
    old_paper_state = core.paper_state
    old_global = core.global_account_state

    def trade_overlap_label(t):
        m = str(t.get("market") or "").upper()
        code = str(t.get("code") or "")
        meta = overlap.get(f"{m}:{code}") or {}
        labels = list(meta.get("labels") or [])
        if len(labels) < 2:
            return str(t.get("strategy") or "")
        return "복합조건"

    def paper_state(market):
        m = str(market or "KR").upper()
        d = dict(old_paper_state(m))
        positions = []
        for x in list(d.get("positions") or []):
            if str(x.get("market") or "").upper() != m:
                continue
            y = dict(x)
            meta = overlap.get(f"{m}:{y.get('code')}") or {}
            display = _labels_display(meta.get("labels") or [])
            if display:
                y["strategy_display"] = display
                if display == "복합조건":
                    y["strategy"] = display
                    y["condition_labels"] = list(meta.get("labels") or [])
            positions.append(y)
        trades = []
        for t in list(getattr(paper, "trades", []) or []):
            if str(t.get("market") or "").upper() != m:
                continue
            y = dict(t)
            display = trade_overlap_label(y)
            if display:
                y["strategy_display"] = display
                if display == "복합조건":
                    y["strategy"] = display
            trades.append(y)
        realized = sum(_f(t.get("pnl")) for t in trades if str(t.get("side") or "").upper() == "SELL")
        unrealized = sum(_f(p.pnl_krw) for p in paper.market_positions(m))
        equity = market_cash[m] + sum(_f(p.value_krw) for p in paper.market_positions(m))
        initial = market_initial[m]
        d.update({
            "initial_cash": round(initial), "cash": round(market_cash[m]), "equity": round(equity),
            "held_cost": round(paper.held_cost_krw(m)), "market_held_cost": round(paper.held_cost_krw(m)),
            "positions": positions, "trades": trades[:300], "account_scope": m + "_ONLY",
            "budget": round(base_budget()), "effective_budget": round(base_budget()),
            "realized_pnl": round(realized), "overall_pnl": round(realized),
            "overall_pnl_pct": realized / initial * 100 if initial else 0.0,
            "unrealized_pnl": round(unrealized), "pnl_display_mode": "REALIZED_ONLY",
        })
        return d

    def global_account():
        d = dict(old_global())
        kr = paper_state("KR")
        us = paper_state("US")
        d.update({
            "initial_cash": round(market_initial["KR"] + market_initial["US"] + core.coin_paper.initial_cash_krw),
            "stock_initial_cash": round(market_initial["KR"] + market_initial["US"]),
            "kr_equity": kr["equity"], "us_equity": us["equity"],
            "kr_cash": kr["cash"], "us_cash": us["cash"],
            "kr_realized_pnl": kr["realized_pnl"], "us_realized_pnl": us["realized_pnl"],
            "account_separation": True,
        })
        return d

    core.paper_state = paper_state
    core.global_account_state = global_account

    # ---------------------------- combined AI score + exact KR flow values
    old_stock_detail = core.stock_detail

    def stock_detail(market, code, timeframe="1d"):
        d = dict(old_stock_detail(market, code, timeframe))
        scores = dict(d.get("scores") or {})
        weights = {"1d": 0.40, "1m": 0.20, "3m": 0.15, "5m": 0.15, "20m": 0.10}
        vals = [(k, _f(scores.get(k)), w) for k, w in weights.items() if scores.get(k) is not None]
        if vals:
            den = sum(w for _, _, w in vals)
            combined = sum(v * w for _, v, w in vals) / max(den, 1e-9)
            scores["종합"] = round(combined, 1)
            d["combined_score"] = round(combined, 1)
        d["scores"] = scores
        if str(market or "").upper() == "KR":
            q = core.feed.q("KR", str(code).upper())
            flow = dict(d.get("flow") or {})
            flow.update({
                "foreign_net": _f(getattr(q, "foreign_net", 0)),
                "institution_net": _f(getattr(q, "institution_net", 0)),
                "person_net": _f(getattr(q, "person_net", 0)),
            })
            d["flow"] = flow
            d["investor_numeric"] = {
                "person": flow["person_net"], "foreign": flow["foreign_net"], "institution": flow["institution_net"],
                "unit": "shares", "source": "NHPLUG currentInvestor/current flow",
            }
        try:
            snap = core.intraday_snapshot(str(market).upper(), str(code).upper())
            d["intraday_counts"] = snap.get("counts")
            d["intraday_targets"] = snap.get("targets")
        except Exception:
            pass
        return d

    core.stock_detail = stock_detail
    for route in core.app.router.routes:
        if getattr(route, "path", "") == "/api/stock/{market}/{code}":
            try:
                route.endpoint = stock_detail
                route.dependant.call = stock_detail
            except Exception:
                pass

    # ---------------------------- separate calendar payloads by market
    old_state = core.state

    def state(market="KR"):
        d = dict(old_state(market))
        m = str(d.get("mode") or market or "KR").upper()
        if m == "KR":
            # US FOMC/CPI/PPI/NFP must not appear in the KR calendar.
            d["macro_events"] = []
            d["calendar_scope"] = "KR"
        elif m == "US":
            d["calendar_scope"] = "US"
        else:
            d["macro_events"] = []
            d["calendar_scope"] = "COIN"
        return d

    core.state = state
    for route in core.app.router.routes:
        if getattr(route, "path", "") == "/api/state":
            try:
                route.endpoint = state
                route.dependant.call = state
            except Exception:
                pass

    # ---------------------------- Coin Condition 1 + Hull/TFS Condition 2
    original_candidates = core.coin_feed.candidates
    old_coin_restore = core._restore_coin

    def restore_coin():
        old_coin_restore()
        changed = False
        for p in core.coin_paper.positions.values():
            if str(getattr(p, "strategy", "")) in ("COIN_SCALP", "SCALP"):
                p.strategy = "조건1"
                changed = True
        for t in core.coin_paper.trades:
            if str(t.get("strategy") or "") in ("COIN_SCALP", "SCALP"):
                t["strategy"] = "조건1"
                changed = True
        if changed:
            core._persist_coin()

    core._restore_coin = restore_coin

    def candidates(n=20):
        rows = original_candidates(n)
        with coin_c2_lock:
            c2 = dict(coin_c2_cache)
        entry = _f(core._coin_settings_snapshot().get("entry_score"), 66)
        out = []
        for x in rows:
            y = dict(x)
            sig = dict(c2.get(str(y.get("code") or "").upper()) or {})
            c1 = _f(y.get("score")) >= entry
            c2pass = bool(sig.get("ready") and sig.get("buy"))
            labels = [name for name, ok in (("조건1", c1), ("조건2", c2pass)) if ok]
            y["condition1"] = {"score": _f(y.get("score")), "gate": c1, "label": "조건1"}
            y["condition2"] = sig
            y["condition2"]["gate"] = c2pass
            y["condition2"]["label"] = "조건2"
            y["condition_labels"] = labels
            y["condition_display"] = _labels_display(labels)
            out.append(y)
        return out

    core.coin_feed.candidates = candidates

    def coin_c2_worker():
        while True:
            try:
                rows = original_candidates(50)
                if not rows:
                    time.sleep(5)
                    continue
                for x in rows:
                    symbol = str(x.get("code") or "").upper()
                    if not symbol:
                        continue
                    try:
                        bars = core.coin_feed.chart(symbol, "1m", 60)
                        sig = _coin_c2_signal(bars)
                        sig["updated_at"] = time.time()
                        with coin_c2_lock:
                            coin_c2_cache[symbol] = sig
                    except Exception as exc:
                        with coin_c2_lock:
                            old = dict(coin_c2_cache.get(symbol) or {})
                            old["error"] = str(exc)[:160]
                            coin_c2_cache[symbol] = old
                    time.sleep(0.75)
            except Exception:
                time.sleep(3)

    threading.Thread(target=coin_c2_worker, daemon=True).start()

    def coin_trade_loop():
        st = core.COIN_LOOP_STATE
        st["started_at"] = time.time()
        last_persist = 0.0
        while True:
            st["last_tick"] = time.time()
            st["iterations"] += 1
            try:
                rows = candidates(50)
                score_map = {str(x.get("code") or "").upper(): _f(x.get("score")) for x in rows}
                changed = False
                for p in list(core.coin_paper.positions.values()):
                    q = core.coin_feed.quote(p.symbol)
                    if not q or q.price <= 0:
                        continue
                    core.coin_paper.mark(p.symbol, q.price)
                    strategy = str(getattr(p, "strategy", "") or "조건1")
                    if strategy in ("COIN_SCALP", "SCALP"):
                        strategy = "조건1"
                        p.strategy = strategy
                    reason = ""
                    if strategy == "조건2":
                        meta = coin_meta.get(p.symbol) or {}
                        stop = _f(meta.get("stop"))
                        target = _f(meta.get("target"))
                        sig = dict(coin_c2_cache.get(p.symbol) or {})
                        if stop > 0 and q.price <= stop:
                            reason = "조건2 직전 전저점 손절"
                        elif target > 0 and q.price >= target:
                            reason = "조건2 손익비 1:1 익절"
                        elif sig.get("sell"):
                            reason = "조건2 SELL 시그널"
                    else:
                        score = score_map.get(p.symbol, 50.0)
                        if p.pnl_pct >= 3.0:
                            reason = "조건1 목표수익 +3% 도달"
                        elif p.pnl_pct <= -1.5:
                            reason = "조건1 손절 -1.5%"
                        elif score < 46:
                            reason = "조건1 AI 점수 이탈"
                    if reason and core.coin_paper.sell(p.symbol, q.price, reason):
                        core.COIN_COOLDOWN[p.symbol] = time.time()
                        changed = True

                settings = core._coin_settings_snapshot()
                if settings.get("auto_trade_enabled", True):
                    entry = _f(settings.get("entry_score"), 66)
                    for item in rows:
                        symbol = str(item.get("code") or "").upper()
                        if not symbol or f"COIN:{symbol}" in core.coin_paper.positions:
                            continue
                        if _f(item.get("fresh_age"), 9999) > 30:
                            continue
                        if time.time() - _f(core.COIN_COOLDOWN.get(symbol)) < 300:
                            continue
                        c1 = _f(item.get("score")) >= entry
                        sig = dict(item.get("condition2") or {})
                        c2 = bool(sig.get("ready") and sig.get("buy"))
                        labels = [name for name, ok in (("조건1", c1), ("조건2", c2)) if ok]
                        if not labels:
                            continue
                        q = core.coin_feed.quote(symbol)
                        available = core._coin_available_budget()
                        budget = core._coin_effective_budget()
                        if not q or q.price <= 0 or available < 10000:
                            continue
                        spend = min(available, max(10000.0, budget * 0.20))
                        strategy = labels[0]
                        trade = core.coin_paper.buy(q, spend, strategy)
                        if trade:
                            if len(labels) >= 2:
                                overlap[f"COIN:{symbol}"] = {"labels": labels, "entry_ts": time.time(), "updated_at": time.time()}
                            if strategy == "조건2":
                                stop = _f(sig.get("swing_low"))
                                risk = max(0.0, q.price - stop)
                                if stop <= 0 or risk <= 0:
                                    # No valid prior low means no valid Condition 2 entry.
                                    core.coin_paper.sell(symbol, q.price, "조건2 손절기준 무효 · 진입취소")
                                else:
                                    coin_meta[symbol] = {
                                        "entry": q.price, "stop": stop, "target": q.price + risk,
                                        "risk": risk, "entered_at": time.time(), "source": sig.get("source"),
                                    }
                            changed = True
                            break
                if changed:
                    core._persist_coin()
                    core._persist_coin_settings()
                    save_aux()
                if time.time() - last_persist >= 60:
                    core._persist_coin()
                    core._persist_coin_settings()
                    save_aux()
                    last_persist = time.time()
                st["last_ok"] = time.time()
                st["last_error"] = ""
            except Exception as exc:
                st["last_error"] = str(exc)[:300]
                print("COIN LOOP FINAL ERROR:", exc, flush=True)
            time.sleep(core.AUTO_LOOP_SECONDS)

    core.coin_trade_loop = coin_trade_loop

    old_coin_state = core.coin_account_state

    def coin_account_state():
        d = dict(old_coin_state())
        for p in d.get("positions") or []:
            meta = overlap.get("COIN:" + str(p.get("code") or "")) or {}
            display = _labels_display(meta.get("labels") or [])
            if display:
                p["strategy_display"] = display
                if display == "복합조건":
                    p["strategy"] = display
                    p["condition_labels"] = list(meta.get("labels") or [])
            elif str(p.get("strategy") or "") in ("COIN_SCALP", "SCALP"):
                p["strategy"] = "조건1"
        for t in d.get("trades") or []:
            if str(t.get("strategy") or "") in ("COIN_SCALP", "SCALP"):
                t["strategy"] = "조건1"
            meta = overlap.get("COIN:" + str(t.get("code") or "")) or {}
            display = _labels_display(meta.get("labels") or [])
            if display:
                t["strategy_display"] = display
                if display == "복합조건":
                    t["strategy"] = display
        d["strategy_models"] = {
            "condition1": "기존 코인 AI 단타 전략",
            "condition2": "Hull Suite HMA26 source=hl2 + TFS(OBV-SMA7); BUY+양봉+TFS<0; 전저점 손절; 1:1 익절",
        }
        return d

    core.coin_account_state = coin_account_state

    old_health = core.health_payload
    def health():
        d = dict(old_health())
        d["market_accounts"] = {
            "KR": {"initial": market_initial["KR"], "cash": market_cash["KR"]},
            "US": {"initial": market_initial["US"], "cash": market_cash["US"]},
            "separate": True,
        }
        d["intraday_targets"] = {"1m": 60, "3m": 30, "5m": 30, "20m": 30}
        with coin_c2_lock:
            d["coin_condition2_cached"] = len(coin_c2_cache)
        d["coin_strategy_models"] = {
            "condition1": "existing coin recipe",
            "condition2": "HMA26/hl2 + TFS OBV-SMA7",
        }
        return d
    core.health_payload = health

    print("NAMUH FINAL REQUESTS active: separate KR/US accounts + US C1/C2/C3 + coin C1/C2 + composite labels", flush=True)
