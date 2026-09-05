from __future__ import annotations

import json
import math
import threading
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from typing import Dict, Iterable, Optional

import requests

COINONE_API = "https://api.coinone.co.kr"
COINONE_WS = "wss://stream.coinone.co.kr"
KST = timezone(timedelta(hours=9))


def _f(v, default=0.0):
    try:
        return float(v)
    except Exception:
        return float(default)


def _clamp(v, lo=0.0, hi=100.0):
    return max(lo, min(hi, float(v or 0)))


@dataclass
class CoinQuote:
    symbol: str
    name: str = ""
    price: float = 0.0
    first: float = 0.0
    high: float = 0.0
    low: float = 0.0
    quote_volume: float = 0.0
    target_volume: float = 0.0
    volume_power: float = 100.0
    ask_price: float = 0.0
    ask_qty: float = 0.0
    bid_price: float = 0.0
    bid_qty: float = 0.0
    updated_at: float = 0.0

    @property
    def change_pct(self):
        if self.first <= 0:
            return 0.0
        return (self.price / self.first - 1.0) * 100.0

    @property
    def spread_pct(self):
        if self.ask_price <= 0 or self.bid_price <= 0:
            return None
        mid = (self.ask_price + self.bid_price) / 2.0
        if mid <= 0:
            return None
        return (self.ask_price - self.bid_price) / mid * 100.0

    @property
    def book_imbalance(self):
        total = self.ask_qty + self.bid_qty
        if total <= 0:
            return 0.0
        return (self.bid_qty - self.ask_qty) / total * 100.0


@dataclass
class CryptoPosition:
    symbol: str
    name: str
    qty: float
    avg_price: float
    current_price: float
    strategy: str = "COIN_SCALP"
    entry_ts: float = 0.0

    @property
    def key(self):
        return f"COIN:{self.symbol}"

    @property
    def cost_krw(self):
        return self.qty * self.avg_price

    @property
    def value_krw(self):
        return self.qty * self.current_price

    @property
    def pnl_krw(self):
        return self.value_krw - self.cost_krw

    @property
    def pnl_pct(self):
        if self.cost_krw <= 0:
            return 0.0
        return self.pnl_krw / self.cost_krw * 100.0


class CryptoPaperAccount:
    """Paper-only Coinone account, completely isolated from the stock paper account."""

    def __init__(self, initial_cash_krw=1_500_000):
        self.initial_cash_krw = int(initial_cash_krw)
        self.cash_krw = float(self.initial_cash_krw)
        self.positions: Dict[str, CryptoPosition] = {}
        self.trades = []
        self.lock = threading.RLock()

    def held_cost_krw(self):
        with self.lock:
            return sum(p.cost_krw for p in self.positions.values())

    def equity_krw(self):
        with self.lock:
            return self.cash_krw + sum(p.value_krw for p in self.positions.values())

    def unrealized_pnl_krw(self):
        with self.lock:
            return sum(p.pnl_krw for p in self.positions.values())

    def mark(self, symbol, price):
        if price <= 0:
            return
        with self.lock:
            p = self.positions.get(f"COIN:{str(symbol).upper()}")
            if p:
                p.current_price = float(price)

    def buy(self, quote: CoinQuote, krw_amount, strategy="COIN_SCALP"):
        if not quote or quote.price <= 0:
            return None
        symbol = quote.symbol.upper()
        key = f"COIN:{symbol}"
        with self.lock:
            if key in self.positions:
                return None
            spend = min(float(krw_amount or 0), self.cash_krw)
            if spend < 10_000:
                return None
            qty = spend / quote.price
            if qty <= 0:
                return None
            self.cash_krw -= spend
            p = CryptoPosition(symbol, quote.name or symbol, qty, quote.price, quote.price, strategy, time.time())
            self.positions[key] = p
            now = datetime.now(KST)
            trade = {
                "date": now.strftime("%Y-%m-%d"), "time": now.strftime("%H:%M:%S"),
                "market": "COIN", "side": "BUY", "code": symbol, "name": p.name,
                "qty": qty, "price": quote.price, "currency": "KRW", "gross_krw": round(spend),
                "pnl": 0, "pnl_pct": 0.0, "strategy": strategy,
            }
            self.trades.insert(0, trade)
            self.trades = self.trades[:1000]
            return trade

    def sell(self, symbol, price, reason=""):
        symbol = str(symbol).upper()
        if price <= 0:
            return None
        key = f"COIN:{symbol}"
        with self.lock:
            p = self.positions.get(key)
            if not p:
                return None
            proceeds = p.qty * float(price)
            pnl = proceeds - p.cost_krw
            pct = pnl / p.cost_krw * 100.0 if p.cost_krw else 0.0
            self.cash_krw += proceeds
            del self.positions[key]
            now = datetime.now(KST)
            trade = {
                "date": now.strftime("%Y-%m-%d"), "time": now.strftime("%H:%M:%S"),
                "market": "COIN", "side": "SELL", "code": symbol, "name": p.name,
                "qty": p.qty, "price": float(price), "currency": "KRW", "gross_krw": round(proceeds),
                "pnl": round(pnl), "pnl_pct": pct, "strategy": p.strategy, "reason": reason,
            }
            self.trades.insert(0, trade)
            self.trades = self.trades[:1000]
            return trade

    def payload(self):
        with self.lock:
            return {
                "initial_cash_krw": self.initial_cash_krw,
                "cash_krw": self.cash_krw,
                "positions": [asdict(p) for p in self.positions.values()],
                "trades": list(self.trades[:1000]),
            }

    def restore(self, data):
        if not isinstance(data, dict):
            return
        with self.lock:
            self.initial_cash_krw = int(data.get("initial_cash_krw") or self.initial_cash_krw)
            self.cash_krw = float(data.get("cash_krw", self.initial_cash_krw))
            self.positions.clear()
            for x in data.get("positions") or []:
                try:
                    p = CryptoPosition(
                        str(x["symbol"]).upper(), str(x.get("name") or x["symbol"]), float(x["qty"]),
                        float(x["avg_price"]), float(x.get("current_price") or x["avg_price"]),
                        str(x.get("strategy") or "COIN_SCALP"), float(x.get("entry_ts") or 0),
                    )
                    self.positions[p.key] = p
                except Exception:
                    continue
            self.trades = list(data.get("trades") or [])[:1000]


class CoinoneFeed:
    """Coinone public market-data feed. No private key and no real-order endpoint is used."""

    def __init__(self, top_n=40):
        self.http = requests.Session()
        self.http.headers.update({"Accept": "application/json", "User-Agent": "GY-Trading-OS/1.0"})
        self.top_n = max(10, min(80, int(top_n or 40)))
        self.quotes: Dict[str, CoinQuote] = {}
        self.market_symbols = []
        self.currency_names = {}
        self.updated_at = 0.0
        self.connected = False
        self.ws_connected = False
        self.error = ""
        self.ws_error = ""
        self._stop = threading.Event()
        self._started = False
        self._lock = threading.RLock()
        self._ws_symbols = []
        self._last_rest = 0.0

    def _get(self, path, **params):
        r = self.http.get(COINONE_API + path, params=params or None, timeout=10)
        r.raise_for_status()
        j = r.json()
        if str(j.get("result", "success")).lower() != "success" or str(j.get("error_code", "0")) not in ("0", ""):
            raise RuntimeError(f"Coinone {j.get('error_code')}: {j.get('error_msg') or j.get('message') or 'API error'}")
        return j

    def _load_names(self):
        try:
            j = self._get("/public/v2/currencies")
            names = {}
            for x in j.get("currencies") or []:
                s = str(x.get("symbol") or "").upper()
                if s:
                    names[s] = str(x.get("name") or s)
            if names:
                self.currency_names = names
        except Exception:
            pass

    def refresh_rest(self):
        try:
            if not self.currency_names:
                self._load_names()
            try:
                m = self._get("/public/v2/markets/KRW")
                self.market_symbols = [str(x.get("target_currency") or "").upper() for x in m.get("markets") or [] if x.get("target_currency")]
            except Exception:
                pass
            j = self._get("/public/v2/ticker_new/KRW", additional_data="true")
            now = time.time()
            seen = []
            with self._lock:
                for x in j.get("tickers") or []:
                    symbol = str(x.get("target_currency") or "").upper()
                    if not symbol:
                        continue
                    q = self.quotes.get(symbol) or CoinQuote(symbol, self.currency_names.get(symbol, symbol))
                    q.name = self.currency_names.get(symbol, q.name or symbol)
                    q.price = _f(x.get("last"), q.price)
                    q.first = _f(x.get("first"), q.first)
                    q.high = _f(x.get("high"), q.high)
                    q.low = _f(x.get("low"), q.low)
                    q.quote_volume = _f(x.get("quote_volume"), q.quote_volume)
                    q.target_volume = _f(x.get("target_volume"), q.target_volume)
                    asks = x.get("best_asks") or []
                    bids = x.get("best_bids") or []
                    if asks:
                        q.ask_price = _f(asks[0].get("price"), q.ask_price)
                        q.ask_qty = _f(asks[0].get("qty"), q.ask_qty)
                    if bids:
                        q.bid_price = _f(bids[0].get("price"), q.bid_price)
                        q.bid_qty = _f(bids[0].get("qty"), q.bid_qty)
                    q.updated_at = now
                    self.quotes[symbol] = q
                    seen.append(symbol)
                if not self.market_symbols:
                    self.market_symbols = seen
                ranked = sorted(self.quotes.values(), key=lambda q: q.quote_volume, reverse=True)
                self._ws_symbols = [q.symbol for q in ranked[: self.top_n]]
            self.updated_at = now
            self._last_rest = now
            self.connected = True
            self.error = ""
            return True
        except Exception as exc:
            self.connected = False
            self.error = str(exc)[:240]
            return False

    def _apply_ws_ticker(self, d):
        symbol = str(d.get("target_currency") or d.get("tc") or "").upper()
        if not symbol:
            return
        now = time.time()
        with self._lock:
            q = self.quotes.get(symbol) or CoinQuote(symbol, self.currency_names.get(symbol, symbol))
            q.name = self.currency_names.get(symbol, q.name or symbol)
            q.price = _f(d.get("last") if "last" in d else d.get("la"), q.price)
            q.first = _f(d.get("first") if "first" in d else d.get("fi"), q.first)
            q.high = _f(d.get("high") if "high" in d else d.get("hi"), q.high)
            q.low = _f(d.get("low") if "low" in d else d.get("lo"), q.low)
            q.quote_volume = _f(d.get("quote_volume") if "quote_volume" in d else d.get("qv"), q.quote_volume)
            q.target_volume = _f(d.get("target_volume") if "target_volume" in d else d.get("tv"), q.target_volume)
            q.volume_power = _f(d.get("volume_power") if "volume_power" in d else d.get("vp"), q.volume_power or 100)
            q.ask_price = _f(d.get("ask_best_price") if "ask_best_price" in d else d.get("abp"), q.ask_price)
            q.ask_qty = _f(d.get("ask_best_qty") if "ask_best_qty" in d else d.get("abq"), q.ask_qty)
            q.bid_price = _f(d.get("bid_best_price") if "bid_best_price" in d else d.get("bbp"), q.bid_price)
            q.bid_qty = _f(d.get("bid_best_qty") if "bid_best_qty" in d else d.get("bbq"), q.bid_qty)
            q.updated_at = now
            self.quotes[symbol] = q
        self.updated_at = now

    def _ws_loop(self):
        delay = 1
        while not self._stop.is_set():
            ws = None
            try:
                try:
                    import websocket
                except Exception as exc:
                    self.ws_error = f"websocket-client unavailable: {exc}"
                    time.sleep(30)
                    continue
                symbols = list(self._ws_symbols)
                if not symbols:
                    self.refresh_rest()
                    symbols = list(self._ws_symbols)
                if not symbols:
                    time.sleep(5)
                    continue
                ws = websocket.create_connection(COINONE_WS, timeout=35)
                ws.settimeout(35)
                first = json.loads(ws.recv())
                if str(first.get("response_type", "")).upper() not in ("CONNECTED", ""):
                    raise RuntimeError(str(first)[:160])
                for symbol in symbols:
                    ws.send(json.dumps({
                        "request_type": "SUBSCRIBE", "channel": "TICKER",
                        "topic": {"quote_currency": "KRW", "target_currency": symbol},
                    }))
                self.ws_connected = True
                self.ws_error = ""
                delay = 1
                last_ping = time.time()
                while not self._stop.is_set():
                    if time.time() - last_ping > 600:
                        ws.send(json.dumps({"request_type": "PING"}))
                        last_ping = time.time()
                    try:
                        raw = ws.recv()
                    except Exception as exc:
                        # socket timeouts are used as a chance to send an app-level PING
                        if "timed out" in str(exc).lower():
                            ws.send(json.dumps({"request_type": "PING"}))
                            last_ping = time.time()
                            continue
                        raise
                    if not raw:
                        continue
                    msg = json.loads(raw)
                    rt = str(msg.get("response_type") or msg.get("r") or "").upper()
                    ch = str(msg.get("channel") or msg.get("c") or "").upper()
                    if rt == "DATA" and ch == "TICKER":
                        self._apply_ws_ticker(msg.get("data") or msg.get("d") or {})
                    elif rt == "ERROR":
                        raise RuntimeError(str(msg.get("message") or msg)[:200])
            except Exception as exc:
                self.ws_connected = False
                self.ws_error = str(exc)[:240]
                try:
                    if ws:
                        ws.close()
                except Exception:
                    pass
                if self._stop.wait(delay):
                    return
                delay = min(30, delay * 2)

    def _rest_loop(self):
        while not self._stop.is_set():
            self.refresh_rest()
            if self._stop.wait(10):
                return

    def start(self):
        if self._started:
            return
        self._started = True
        threading.Thread(target=self._rest_loop, daemon=True).start()
        threading.Thread(target=self._ws_loop, daemon=True).start()

    def stop(self):
        self._stop.set()

    def top_quotes(self, n=30):
        with self._lock:
            return sorted([q for q in self.quotes.values() if q.price > 0], key=lambda q: q.quote_volume, reverse=True)[:n]

    def quote(self, symbol):
        with self._lock:
            return self.quotes.get(str(symbol).upper())

    def candidates(self, n=20):
        ranked = self.top_quotes(max(self.top_n, n))
        if not ranked:
            return []
        max_vol = max((q.quote_volume for q in ranked), default=1.0) or 1.0
        out = []
        for idx, q in enumerate(ranked):
            change = q.change_pct
            # Avoid rewarding already-vertical pumps. 1~8% 24h momentum scores best.
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
            rank_score = 30.0 * (1.0 - idx / max(1, len(ranked) - 1))
            liquidity = 15.0 * math.sqrt(max(0.0, q.quote_volume) / max_vol)
            power = _clamp((q.volume_power - 90) / 45 * 15, 0, 15)
            spread = q.spread_pct
            spread_score = 5.0 if spread is None else _clamp((0.7 - spread) / 0.7 * 5, 0, 5)
            imbalance = _clamp((q.book_imbalance + 20) / 60 * 5, 0, 5)
            score = _clamp(momentum + rank_score + liquidity + power + spread_score + imbalance)
            reasons = []
            if idx < 5:
                reasons.append("거래대금 상위")
            if change >= 1:
                reasons.append(f"24H +{change:.1f}%")
            if q.volume_power >= 105:
                reasons.append(f"체결강도 {q.volume_power:.0f}")
            if q.book_imbalance >= 10:
                reasons.append("매수호가 우위")
            if spread is not None and spread <= 0.2:
                reasons.append("스프레드 양호")
            fresh_age = max(0.0, time.time() - q.updated_at) if q.updated_at else 9999
            out.append({
                "market": "COIN", "code": q.symbol, "name": q.name or q.symbol,
                "price": q.price, "change_pct": change, "quote_volume": q.quote_volume,
                "target_volume": q.target_volume, "volume_power": q.volume_power,
                "spread_pct": spread, "book_imbalance": q.book_imbalance,
                "score": round(score, 1), "reasons": reasons[:4], "fresh_age": round(fresh_age, 1),
                "updated_at": q.updated_at,
            })
        out.sort(key=lambda x: x["score"], reverse=True)
        return out[:n]

    def chart(self, symbol, interval="1m", size=120):
        symbol = str(symbol).upper()
        allowed = {"1m", "3m", "5m", "10m", "15m", "30m", "1h", "2h", "4h", "6h", "1d", "1w", "1mon"}
        if interval not in allowed:
            interval = "1m"
        size = max(20, min(500, int(size or 120)))
        j = self._get(f"/public/v2/chart/KRW/{symbol}", interval=interval, size=size)
        out = []
        seen = set()
        for x in j.get("chart") or []:
            ts = int(_f(x.get("timestamp")))
            o, h, l, c = (_f(x.get("open")), _f(x.get("high")), _f(x.get("low")), _f(x.get("close")))
            if ts <= 0 or min(o, h, l, c) <= 0 or ts in seen:
                continue
            seen.add(ts)
            out.append({
                "time": ts, "open": o, "high": h, "low": l, "close": c,
                "volume": _f(x.get("target_volume")), "quote_volume": _f(x.get("quote_volume")),
            })
        out.sort(key=lambda x: x["time"])
        return out[-size:]

    def health(self):
        return {
            "configured": True,
            "rest_connected": self.connected,
            "ws_connected": self.ws_connected,
            "error": self.error,
            "ws_error": self.ws_error,
            "updated_at": self.updated_at,
            "market_count": len(self.market_symbols),
            "priced_count": sum(1 for q in self.quotes.values() if q.price > 0),
            "top_n": self.top_n,
            "source": "Coinone Public API",
            "real_orders_enabled": False,
        }

