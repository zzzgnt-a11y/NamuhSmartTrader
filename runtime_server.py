from __future__ import annotations

import math
import os
import threading
import time
from datetime import datetime
from pathlib import Path

import uvicorn
from pydantic import BaseModel

import app as core


# Layer v33 UI assets on top of the existing pages at process start.
def _inject_asset(path: str, css: bool = False, script: str | None = None):
    p = Path(path)
    if not p.exists():
        return
    text = p.read_text(encoding="utf-8")
    if css and "/static/v33.css" not in text:
        text = text.replace("</head>", '  <link rel="stylesheet" href="/static/v33.css?v=33">\n</head>')
    if script and script not in text:
        text = text.replace("</body>", f'  <script src="{script}?v=33"></script>\n</body>')
    p.write_text(text, encoding="utf-8")


_inject_asset("static/index.html", css=True, script="/static/v33.js")
_inject_asset("static/coin.html", css=True, script="/static/coin-v33.js")
_inject_asset("static/coin-detail.html", css=True, script="/static/coin-detail-v33.js")


# Global switch: OFF blocks only NEW entries. Existing holdings are always managed.
CONTROL_KEY = "global_trading_control_v33"
CONTROL_LOCK = threading.RLock()
_saved_control = core.store.load_json(CONTROL_KEY, {}) or {}
GLOBAL_NEW_ENTRIES_ENABLED = bool(_saved_control.get("new_entries_enabled", core.AUTO_TRADING_ENABLED))


def _entries_enabled() -> bool:
    with CONTROL_LOCK:
        return bool(GLOBAL_NEW_ENTRIES_ENABLED)


def _save_control():
    core.store.save_json(
        CONTROL_KEY,
        {
            "new_entries_enabled": _entries_enabled(),
            "exit_monitoring_enabled": True,
            "updated_at": time.time(),
        },
    )


class TradingControlRequest(BaseModel):
    new_entries_enabled: bool


@core.app.get("/api/trading-control")
def trading_control():
    return {
        "ok": True,
        "new_entries_enabled": _entries_enabled(),
        "exit_monitoring_enabled": True,
        "browser_independent": True,
        "loop_seconds": core.AUTO_LOOP_SECONDS,
        "persistence": core.store.status(),
        "build": core.BUILD_ID,
    }


@core.app.post("/api/trading-control")
def set_trading_control(data: TradingControlRequest):
    global GLOBAL_NEW_ENTRIES_ENABLED
    with CONTROL_LOCK:
        GLOBAL_NEW_ENTRIES_ENABLED = bool(data.new_entries_enabled)
    _save_control()
    return trading_control()


# Coin score detail, matching the existing 100-point formula.
_original_coin_candidates = core.coin_feed.candidates


def _clamp(v, lo=0.0, hi=100.0):
    return max(lo, min(hi, float(v or 0)))


def _coin_score_parts(q, idx, count, max_vol):
    change = q.change_pct
    if change <= -2:
        momentum = 0.0
    elif change < 1:
        momentum = _clamp((change + 2) / 3 * 12, 0, 12)
    elif change <= 8:
        momentum = 12 + (change - 1) / 7 * 18
    elif change <= 15:
        momentum = 30 - (change - 8) / 7 * 15
    else:
        momentum = 8.0
    rank_score = 30.0 * (1.0 - idx / max(1, count - 1))
    liquidity = 15.0 * math.sqrt(max(0.0, q.quote_volume) / (max_vol or 1.0))
    power = _clamp((q.volume_power - 90) / 45 * 15, 0, 15)
    spread = q.spread_pct
    spread_score = 5.0 if spread is None else _clamp((0.7 - spread) / 0.7 * 5, 0, 5)
    imbalance = _clamp((q.book_imbalance + 20) / 60 * 5, 0, 5)
    return [
        {"key": "volume_rank", "label": "거래대금순위", "score": round(rank_score, 1), "max": 30.0},
        {"key": "momentum", "label": "모멘텀", "score": round(momentum, 1), "max": 30.0},
        {"key": "liquidity", "label": "유동성", "score": round(liquidity, 1), "max": 15.0},
        {"key": "execution", "label": "체결강도", "score": round(power, 1), "max": 15.0},
        {"key": "spread", "label": "스프레드", "score": round(spread_score, 1), "max": 5.0},
        {"key": "imbalance", "label": "호가균형", "score": round(imbalance, 1), "max": 5.0},
    ]


def candidates_v33(n=20):
    items = _original_coin_candidates(n)
    ranked = core.coin_feed.top_quotes(max(core.coin_feed.top_n, n))
    if not ranked:
        return items
    idx_map = {q.symbol: i for i, q in enumerate(ranked)}
    max_vol = max((q.quote_volume for q in ranked), default=1.0) or 1.0
    for item in items:
        q = core.coin_feed.quote(item.get("code"))
        if not q:
            continue
        parts = _coin_score_parts(q, idx_map.get(q.symbol, len(ranked) - 1), len(ranked), max_vol)
        item["score_breakdown"] = parts
        item["score_total"] = round(sum(x["score"] for x in parts), 1)
    return items


core.coin_feed.candidates = candidates_v33


# Add buy/sell context to history without changing the underlying paper engines.
def _enrich_trades(trades):
    out = [dict(t) for t in (trades or [])]
    open_buy = {}
    for i in range(len(out) - 1, -1, -1):
        t = out[i]
        key = f"{t.get('market', '')}:{t.get('code', '')}"
        side = str(t.get("side") or "").upper()
        if side == "BUY":
            t["buy_price"] = t.get("price")
            t["buy_amount"] = t.get("gross_krw", 0)
            t["sell_price"] = None
            t["sell_amount"] = None
            open_buy[key] = dict(t)
        elif side == "SELL":
            b = open_buy.get(key)
            t["buy_price"] = b.get("price") if b else None
            t["buy_amount"] = b.get("gross_krw") if b else None
            t["sell_price"] = t.get("price")
            t["sell_amount"] = t.get("gross_krw", 0)
            t["realized_pnl"] = t.get("pnl", 0)
            t["realized_pnl_pct"] = t.get("pnl_pct", 0)
            open_buy.pop(key, None)
    return out


_original_paper_state = core.paper_state
_original_coin_account_state = core.coin_account_state
_original_global_account_state = core.global_account_state
_original_health_payload = core.health_payload


def paper_state_v33(market):
    d = _original_paper_state(market)
    pnl = float(d.get("equity", 0)) - float(d.get("initial_cash", 0))
    d["overall_pnl"] = round(pnl)
    d["overall_pnl_pct"] = (pnl / float(d.get("initial_cash", 1)) * 100) if d.get("initial_cash") else 0.0
    d["trades"] = _enrich_trades(d.get("trades"))
    d["new_entries_enabled"] = _entries_enabled()
    d["exit_monitoring_enabled"] = True
    d["auto_trade_enabled"] = bool(_entries_enabled() and core.trading_window() == market)
    return d


def coin_account_state_v33():
    d = _original_coin_account_state()
    d["trades"] = _enrich_trades(d.get("trades"))
    d["global_new_entries_enabled"] = _entries_enabled()
    d["effective_auto_trade_enabled"] = bool(_entries_enabled() and d.get("auto_trade_enabled", True))
    d["exit_monitoring_enabled"] = True
    return d


def global_account_state_v33():
    d = _original_global_account_state()
    d["new_entries_enabled"] = _entries_enabled()
    d["exit_monitoring_enabled"] = True
    return d


def health_payload_v33():
    d = _original_health_payload()
    d["global_new_entries_enabled"] = _entries_enabled()
    d["exit_monitoring_enabled"] = True
    d["browser_independent"] = True
    return d


core.paper_state = paper_state_v33
core.coin_account_state = coin_account_state_v33
core.global_account_state = global_account_state_v33
core.health_payload = health_payload_v33


@core.app.get("/api/pnl-calendar")
def pnl_calendar(scope: str = "stock", year: int | None = None, month: int | None = None):
    scope = str(scope or "stock").lower()
    now = datetime.now(core.KST)
    year = int(year or now.year)
    month = int(month or now.month)
    source = []
    if scope in ("stock", "all"):
        source.extend(core.paper.trades)
    if scope in ("coin", "all"):
        source.extend(core.coin_paper.trades)
    days = {}
    for t in source:
        if str(t.get("side") or "").upper() != "SELL":
            continue
        date = str(t.get("date") or "")
        if not date.startswith(f"{year:04d}-{month:02d}-"):
            continue
        row = days.setdefault(date, {"date": date, "pnl": 0.0, "trades": []})
        row["pnl"] += float(t.get("pnl") or 0)
        row["trades"].append(dict(t))
    total = sum(x["pnl"] for x in days.values())
    return {
        "ok": True,
        "scope": scope,
        "year": year,
        "month": month,
        "total_pnl": round(total),
        "days": {k: {**v, "pnl": round(v["pnl"])} for k, v in sorted(days.items())},
        "build": core.BUILD_ID,
    }


# Server-side loops. Closing the phone/browser has no effect.
def ai_loop_v33():
    core.LOOP_STATE["started_at"] = time.time()
    last_persist = 0.0
    while True:
        core.LOOP_STATE["last_tick"] = time.time()
        core.LOOP_STATE["iterations"] += 1
        try:
            now = datetime.now(core.KST)
            kr_scalp, kr_smart = core.rebuild_cache("KR", now)
            us_scalp, _ = core.rebuild_cache("US", now)
            active = core.trading_window(now)
            if active == "KR":
                core.mark_and_sell("KR", kr_scalp, kr_smart, now)
                if _entries_enabled():
                    core.trade_scalp("KR", kr_scalp, now)
                    core.trade_smart_kr(kr_smart, now)
            elif active == "US":
                core.mark_and_sell("US", us_scalp, [], now)
                if _entries_enabled():
                    core.trade_scalp("US", us_scalp, now)
            if time.time() - last_persist >= 60:
                core._persist_paper()
                _save_control()
                last_persist = time.time()
            core.LOOP_STATE["last_ok"] = time.time()
            core.LOOP_STATE["last_error"] = ""
        except Exception as exc:
            core.LOOP_STATE["last_error"] = str(exc)[:300]
            print("AI LOOP V33 ERROR:", exc, flush=True)
        time.sleep(core.AUTO_LOOP_SECONDS)


def coin_trade_loop_v33():
    core.COIN_LOOP_STATE["started_at"] = time.time()
    last_persist = 0.0
    while True:
        core.COIN_LOOP_STATE["last_tick"] = time.time()
        core.COIN_LOOP_STATE["iterations"] += 1
        try:
            candidates = core.coin_feed.candidates(50)
            score_map = {x.get("code"): float(x.get("score", 0) or 0) for x in candidates}
            changed = False
            for p in list(core.coin_paper.positions.values()):
                q = core.coin_feed.quote(p.symbol)
                if not q or q.price <= 0:
                    continue
                core.coin_paper.mark(p.symbol, q.price)
                score = score_map.get(p.symbol, 50.0)
                reason = ""
                if p.pnl_pct >= 3.0:
                    reason = "목표수익 +3% 도달"
                elif p.pnl_pct <= -1.5:
                    reason = "손절 기준 도달"
                elif score < 46:
                    reason = "AI 점수 이탈"
                if reason and core.coin_paper.sell(p.symbol, q.price, reason):
                    core.COIN_COOLDOWN[p.symbol] = time.time()
                    changed = True
            settings = core._coin_settings_snapshot()
            if _entries_enabled() and settings.get("auto_trade_enabled", True):
                entry = float(settings.get("entry_score", 66) or 66)
                for item in candidates:
                    if float(item.get("score", 0) or 0) < entry:
                        break
                    symbol = str(item.get("code") or "").upper()
                    if not symbol or f"COIN:{symbol}" in core.coin_paper.positions:
                        continue
                    if float(item.get("fresh_age", 9999) or 9999) > 30:
                        continue
                    if time.time() - float(core.COIN_COOLDOWN.get(symbol, 0) or 0) < 300:
                        continue
                    q = core.coin_feed.quote(symbol)
                    available = core._coin_available_budget()
                    budget = core._coin_effective_budget()
                    if not q or q.price <= 0 or available < 10000:
                        continue
                    spend = min(available, max(10000.0, budget * 0.20))
                    if core.coin_paper.buy(q, spend, "COIN_SCALP"):
                        changed = True
                        break
            if changed:
                core._persist_coin()
                core._persist_coin_settings()
            if time.time() - last_persist >= 60:
                core._persist_coin()
                core._persist_coin_settings()
                _save_control()
                last_persist = time.time()
            core.COIN_LOOP_STATE["last_ok"] = time.time()
            core.COIN_LOOP_STATE["last_error"] = ""
        except Exception as exc:
            core.COIN_LOOP_STATE["last_error"] = str(exc)[:300]
            print("COIN LOOP V33 ERROR:", exc, flush=True)
        time.sleep(core.AUTO_LOOP_SECONDS)


core.ai_loop = ai_loop_v33
core.coin_trade_loop = coin_trade_loop_v33


@core.app.get("/api/v33/status")
def v33_status():
    return {
        "ok": True,
        "version": "v33",
        "new_entries_enabled": _entries_enabled(),
        "exit_monitoring_enabled": True,
        "persistence": core.store.status(),
        "loop": dict(core.LOOP_STATE),
        "coin_loop": dict(core.COIN_LOOP_STATE),
        "build": core.BUILD_ID,
    }


if __name__ == "__main__":
    uvicorn.run(
        core.app,
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "8787")),
        reload=False,
    )
