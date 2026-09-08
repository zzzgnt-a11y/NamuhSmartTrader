from __future__ import annotations

import re
from pathlib import Path

_INSTALLED = False
ROOT = Path(__file__).resolve().parent


def _f(v, default=0.0):
    try:
        return float(v)
    except Exception:
        return float(default)


def _trade_key(t):
    def r(v, n=8):
        try:
            return round(float(v), n)
        except Exception:
            return 0.0
    return (
        str(t.get("date") or ""), str(t.get("time") or ""),
        str(t.get("market") or "COIN").upper(), str(t.get("side") or "").upper(),
        str(t.get("code") or "").upper(),
        r(t.get("qty")), r(t.get("price")), r(t.get("gross_krw"), 2), r(t.get("pnl"), 2),
        str(t.get("strategy") or ""), str(t.get("reason") or ""),
    )


def _normalized_trades(core):
    out = []
    seen = set()
    raw = list(getattr(core.coin_paper, "trades", []) or [])[:1000]
    for item in raw:
        if not isinstance(item, dict):
            continue
        t = dict(item)
        t["market"] = "COIN"
        t["side"] = str(t.get("side") or "").upper()
        key = _trade_key(t)
        if key in seen:
            continue
        seen.add(key)
        out.append(t)
    return out, max(0, len(raw) - len(out))


def _daily_ledger(trades):
    daily = {}
    for t in trades:
        date = str(t.get("date") or "")[:10]
        if not date:
            continue
        d = daily.setdefault(date, {
            "date": date, "realized_pnl": 0.0,
            "buy_count": 0, "sell_count": 0, "fill_count": 0,
        })
        side = str(t.get("side") or "").upper()
        d["fill_count"] += 1
        if side == "BUY":
            d["buy_count"] += 1
        elif side == "SELL":
            d["sell_count"] += 1
            d["realized_pnl"] += _f(t.get("pnl"))
    rows = []
    for date in sorted(daily):
        d = dict(daily[date])
        d["realized_pnl"] = int(round(d["realized_pnl"]))
        rows.append(d)
    return rows


def _install_account_ledger(core):
    old = core.coin_account_state
    if getattr(old, "_namuh_v374_coin_ledger", False):
        return

    def coin_account_state():
        data = dict(old())
        trades, duplicate_count = _normalized_trades(core)
        sells = [t for t in trades if str(t.get("side") or "").upper() == "SELL"]
        buys = [t for t in trades if str(t.get("side") or "").upper() == "BUY"]
        realized = sum(_f(t.get("pnl")) for t in sells)
        equity = _f(data.get("equity"), core.coin_paper.equity_krw())
        initial = _f(data.get("initial_cash"), core.coin_paper.initial_cash_krw)
        total_pnl = equity - initial
        unrealized = _f(data.get("unrealized_pnl"), core.coin_paper.unrealized_pnl_krw())
        data.update({
            "trades": trades,
            "trade_count": len(trades),
            "buy_count": len(buys),
            "sell_count": len(sells),
            "realized_trade_count": len(sells),
            "realized_pnl": int(round(realized)),
            "unrealized_pnl": int(round(unrealized)),
            "total_pnl": int(round(total_pnl)),
            "pnl": int(round(total_pnl)),
            "pnl_pct": (total_pnl / initial * 100.0 if initial else 0.0),
            "daily_realized": _daily_ledger(trades),
            "ledger_duplicate_count": duplicate_count,
            "ledger_basis": "SELL pnl by KST trade date; BUY/SELL fills counted separately",
        })
        return data

    coin_account_state._namuh_v374_coin_ledger = True
    coin_account_state._old = old
    core.coin_account_state = coin_account_state


def _patch_frontend():
    p = ROOT / "static/coin.js"
    if not p.exists():
        return False
    try:
        text = p.read_text(encoding="utf-8")
        before = text

        text = text.replace(
            '$("coinEquity").textContent=won(a.equity);$("coinPnl").textContent=`${won(a.pnl)} · ${pct(a.pnl_pct)}`;$("coinPnl").className=Number(a.pnl)>=0?"pos":"neg";',
            '$("coinEquity").textContent=won(a.equity);const totalPnl=Number(a.total_pnl??a.pnl??0),realizedPnl=Number(a.realized_pnl??0);$("coinPnl").textContent=`총 ${signedWon(totalPnl)} (${pct(a.pnl_pct)}) · 실현 ${signedWon(realizedPnl)}`;$("coinPnl").className=totalPnl>=0?"pos":"neg";'
        )

        text = text.replace(
            'const rows=coinLastTrades.filter(t=>coinTradeFilter==="ALL"||String(t.side||"").toUpperCase()===coinTradeFilter).slice(0,80);',
            'const rows=coinLastTrades.filter(t=>coinTradeFilter==="ALL"||String(t.side||"").toUpperCase()===coinTradeFilter).slice(0,300);'
        )

        text = text.replace(
            'cnt=v?.items?.length?`<span class="cnt">거래 ${v.items.length}건</span>`:\'\';',
            'cnt=v?.items?.length?`<span class="cnt">매도 ${Number(v.realized_count||0)}회 · 체결 ${v.items.length}건</span>`:\'\';'
        )

        old_show = 'function showCoinDay(k,redraw=true){coinSelectedDate=k;const d=coinProfitMap[k],items=d?.items||[],has=Boolean(d?.realized_count);$("coinDaySummary").textContent=`${k} · ${has?\'실현손익 \'+signedWon(d.total):\'실현손익 없음\'} · 거래 ${items.length}건`;$("coinDayList").innerHTML=items.length?items.map(t=>{const s=String(t.side||"").toUpperCase(),rp=s===\'SELL\'?signedWon(t.pnl):\'-\';return `<div class="coin-day-row"><div><span class="coin-ledger-side ${s===\'BUY\'?\'buy\':\'sell\'}">${s===\'BUY\'?\'매수\':\'매도\'}</span> <b>${esc(t.name||t.code)}</b><br><small>${esc(t.time||\'\')} · ${esc(t.strategy||\'\')} · 체결금액 ${won(t.gross_krw||0)}</small></div><div><b class="${s===\'SELL\'?(Number(t.pnl||0)>=0?\'pos\':\'neg\'):\'\'}">${rp}</b><br><small>${s===\'SELL\'?pct(t.pnl_pct):\'실현 전\'}</small></div></div>`}).join(\'\'):\'<div class="empty">이 날짜의 거래내역 없음</div>\';if(redraw)renderCoinCalendar()}'
        new_show = 'function showCoinDay(k,redraw=true){coinSelectedDate=k;const d=coinProfitMap[k],items=d?.items||[],has=Boolean(d?.realized_count),buyCount=items.filter(t=>String(t.side||"").toUpperCase()==="BUY").length,sellCount=items.filter(t=>String(t.side||"").toUpperCase()==="SELL").length;$("coinDaySummary").textContent=`${k} · ${has?\'실현손익 \'+signedWon(d.total):\'실현손익 없음\'} · 매수 ${buyCount}건 · 매도 ${sellCount}건 · 체결 ${items.length}건`;$("coinDayList").innerHTML=items.length?items.map(t=>{const s=String(t.side||"").toUpperCase(),rp=s===\'SELL\'?signedWon(t.pnl):\'-\';return `<div class="coin-day-row"><div><span class="coin-ledger-side ${s===\'BUY\'?\'buy\':\'sell\'}">${s===\'BUY\'?\'매수\':\'매도\'}</span> <b>${esc(t.name||t.code)}</b><br><small>${esc(t.time||\'\')} · ${esc(t.strategy||\'\')} · 체결금액 ${won(t.gross_krw||0)}</small></div><div><b class="${s===\'SELL\'?(Number(t.pnl||0)>=0?\'pos\':\'neg\'):\'\'}">${rp}</b><br><small>${s===\'SELL\'?pct(t.pnl_pct):\'실현 전\'}</small></div></div>`}).join(\'\'):\'<div class="empty">이 날짜의 거래내역 없음</div>\';if(redraw)renderCoinCalendar()}'
        text = text.replace(old_show, new_show)

        if text != before:
            p.write_text(text, encoding="utf-8")
        return True
    except Exception as exc:
        print("V374 coin frontend patch error:", str(exc)[:180], flush=True)
        return False


def _install_health(core):
    old = core.health_payload
    if getattr(old, "_namuh_v374_coin_ledger", False):
        return

    def health():
        d = dict(old())
        trades, dupes = _normalized_trades(core)
        realized = sum(_f(t.get("pnl")) for t in trades if str(t.get("side") or "").upper() == "SELL")
        d["v374"] = {
            "active": True,
            "coin_ledger_fix": True,
            "coin_trade_count": len(trades),
            "coin_duplicate_rows_removed_from_view": dupes,
            "coin_realized_pnl": int(round(realized)),
            "calendar_basis": "SELL realized pnl / KST date",
            "trade_history_view_rows": 300,
        }
        return d

    health._namuh_v374_coin_ledger = True
    health._old = old
    core.health_payload = health


def apply(ns=None):
    global _INSTALLED
    if _INSTALLED:
        return True
    core = ns.get("core") if isinstance(ns, dict) else None
    if core is None:
        return False
    _INSTALLED = True

    _install_account_ledger(core)
    frontend = _patch_frontend()
    _install_health(core)

    trades, dupes = _normalized_trades(core)
    sells = [t for t in trades if str(t.get("side") or "").upper() == "SELL"]
    realized = sum(_f(t.get("pnl")) for t in sells)
    print(
        "NAMUH V374 COIN LEDGER FIX active: "
        f"trades={len(trades)} sells={len(sells)} realized={int(round(realized))} "
        f"duplicates={dupes} frontend={frontend}",
        flush=True,
    )
    return True
