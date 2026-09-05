from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional
import os
import time

from indicators import sma, rsi, macd, bollinger

KST = timezone(timedelta(hours=9))


def _f(v, default=0.0):
    try:
        return float(v)
    except Exception:
        return float(default)


@dataclass
class Quote:
    code: str
    name: str = ""
    sector: str = ""
    price: float = 0.0
    open: float = 0.0
    high: float = 0.0
    low: float = 0.0
    volume: float = 0.0
    prev_volume: float = 0.0
    prev_day_volume: float = 0.0
    per: float = 0.0
    pbr: float = 0.0
    foreign_net: float = 0.0
    institution_net: float = 0.0
    program_net: float = 0.0
    program_net_volume: float = 0.0
    execution_strength: float = 100.0
    prices: deque = field(default_factory=lambda: deque(maxlen=480))
    tick_history: deque = field(default_factory=lambda: deque(maxlen=6000))
    execution_history: deque = field(default_factory=lambda: deque(maxlen=720))
    flow_history: deque = field(default_factory=lambda: deque(maxlen=720))
    daily_bars: deque = field(default_factory=lambda: deque(maxlen=120))
    events: list = field(default_factory=list)
    event_score: float = 0.0
    event_blocked: bool = False
    updated_at: float = 0.0

    def mark(self, price, volume=0, timestamp=None):
        if not price:
            return

        ts = _f(timestamp, time.time())
        price = _f(price)
        volume = _f(volume)

        self.price = price

        if not self.open:
            self.open = price

        self.high = max(
            self.high or price,
            price,
        )

        self.low = min(
            self.low or price,
            price,
        )

        if self.volume and volume > self.volume:
            self.prev_volume = self.volume

        self.volume = max(
            self.volume,
            volume,
        )

        self.prices.append(price)
        self.tick_history.append(
            (
                ts,
                price,
                volume,
            )
        )

        self.updated_at = ts

    def update_execution(
        self,
        value,
        timestamp=None,
    ):
        value = _f(value)

        if value <= 0:
            return

        ts = _f(
            timestamp,
            time.time(),
        )

        self.execution_strength = value

        self.execution_history.append(
            (
                ts,
                value,
            )
        )

        cutoff = ts - 120

        while (
            self.execution_history
            and self.execution_history[0][0] < cutoff
        ):
            self.execution_history.popleft()

    def update_flow(
        self,
        foreign=None,
        institution=None,
        program=None,
        timestamp=None,
    ):
        if foreign is not None:
            self.foreign_net = _f(foreign)

        if institution is not None:
            self.institution_net = _f(institution)

        if program is not None:
            self.program_net = _f(program)

        ts = _f(
            timestamp,
            time.time(),
        )

        self.flow_history.append(
            (
                ts,
                self.foreign_net,
                self.institution_net,
                self.program_net,
            )
        )

        cutoff = ts - 3600

        while (
            self.flow_history
            and self.flow_history[0][0] < cutoff
        ):
            self.flow_history.popleft()

    def set_daily_bars(
        self,
        bars,
    ):
        clean = []
        seen = set()

        for b in bars or []:
            date = (
                str(
                    b.get("date") or ""
                )
                .replace("-", "")
                .replace("/", "")
            )

            if (
                len(date) != 8
                or not date.isdigit()
                or date in seen
            ):
                continue

            close = _f(
                b.get("close")
            )

            if close <= 0:
                continue

            seen.add(date)

            clean.append(
                {
                    "date": date,
                    "open": _f(
                        b.get("open"),
                        close,
                    ),
                    "high": _f(
                        b.get("high"),
                        close,
                    ),
                    "low": _f(
                        b.get("low"),
                        close,
                    ),
                    "close": close,
                    "volume": _f(
                        b.get("volume")
                    ),
                }
            )

        clean.sort(
            key=lambda x: x["date"]
        )

        self.daily_bars.clear()
        self.daily_bars.extend(
            clean[-120:]
        )

        if len(clean) >= 2:
            self.prev_day_volume = (
                clean[-2]["volume"]
                if clean[-2]["volume"] > 0
                else self.prev_day_volume
            )


@dataclass
class Position:
    market: str
    code: str
    name: str
    qty: int
    avg_price: float
    current_price: float
    fx_buy: float = 1.0
    fx_current: float = 1.0
    strategy: str = "SCALP"
    entry_session: str = ""
    entry_ts: float = 0.0

    @property
    def key(self):
        return (
            f"{self.market}:"
            f"{self.code}"
        )

    @property
    def cost_krw(self):
        return (
            self.qty
            * self.avg_price
            * (
                self.fx_buy
                if self.market == "US"
                else 1.0
            )
        )

    @property
    def value_krw(self):
        return (
            self.qty
            * self.current_price
            * (
                self.fx_current
                if self.market == "US"
                else 1.0
            )
        )

    @property
    def pnl_krw(self):
        return (
            self.value_krw
            - self.cost_krw
        )

    @property
    def pnl_pct(self):
        if not self.cost_krw:
            return 0.0

        return (
            self.pnl_krw
            / self.cost_krw
            * 100
        )


class PaperAccount:
    def __init__(self):
        self.initial_cash_krw = int(
            os.getenv(
                "PAPER_INITIAL_CASH",
                "1000000",
            )
        )

        self.cash_krw = float(
            self.initial_cash_krw
        )

        self.positions: Dict[
            str,
            Position,
        ] = {}

        self.trades = []
        self.budget_day = ""

        self.explicit_budget_krw: Optional[
            int
        ] = None

        self.auto_max_if_unset = (
            os.getenv(
                "PAPER_AUTO_MAX_IF_UNSET",
                "1",
            ).strip()
            != "0"
        )

    def ensure_budget_day(
        self,
        day_key,
    ):
        if (
            day_key
            and self.budget_day != day_key
        ):
            self.budget_day = day_key
            self.explicit_budget_krw = None

    def set_budget(
        self,
        amount,
        day_key,
    ):
        self.ensure_budget_day(
            day_key
        )

        if amount is None:
            self.explicit_budget_krw = None
        else:
            self.explicit_budget_krw = max(
                0,
                min(
                    int(amount),
                    self.initial_cash_krw,
                ),
            )

    def set_auto_max(
        self,
        enabled,
    ):
        self.auto_max_if_unset = bool(
            enabled
        )

    def effective_budget_krw(
        self,
        day_key,
    ):
        self.ensure_budget_day(
            day_key
        )

        if self.explicit_budget_krw is not None:
            return self.explicit_budget_krw

        if self.auto_max_if_unset:
            return self.initial_cash_krw

        return 0

    def held_cost_krw(
        self,
        market=None,
    ):
        return sum(
            p.cost_krw
            for p in self.positions.values()
            if (
                market is None
                or p.market == market
            )
        )

    def equity_krw(self):
        return (
            self.cash_krw
            + sum(
                p.value_krw
                for p in self.positions.values()
            )
        )

    def market_positions(
        self,
        market,
    ):
        return [
            p
            for p in self.positions.values()
            if p.market == market
        ]

    def buy(
        self,
        quote,
        qty,
        market,
        fx_rate,
        day_key,
        strategy="SCALP",
        entry_session="",
    ):
        market = market.upper()

        if (
            qty < 1
            or quote.price <= 0
        ):
            return None

        fx = _f(
            fx_rate
            if market == "US"
            else 1.0
        )

        if (
            market == "US"
            and fx <= 0
        ):
            return None

        key = (
            f"{market}:"
            f"{quote.code}"
        )

        if key in self.positions:
            return None

        cost = (
            quote.price
            * qty
            * fx
        )

        budget = (
            self.effective_budget_krw(
                day_key
            )
        )

        if cost > self.cash_krw:
            return None

        if (
            self.held_cost_krw()
            + cost
            > budget
        ):
            return None

        self.cash_krw -= cost

        now = datetime.now(
            KST
        )

        p = Position(
            market,
            quote.code,
            quote.name or quote.code,
            int(qty),
            float(quote.price),
            float(quote.price),
            fx,
            fx,
            strategy.upper(),
            entry_session,
            time.time(),
        )

        self.positions[
            key
        ] = p

        trade = {
            "date":
                now.strftime(
                    "%Y-%m-%d"
                ),
            "time":
                now.strftime(
                    "%H:%M:%S"
                ),
            "market":
                market,
            "side":
                "BUY",
            "code":
                p.code,
            "name":
                p.name,
            "qty":
                p.qty,
            "price":
                p.avg_price,
            "currency":
                (
                    "USD"
                    if market == "US"
                    else "KRW"
                ),
            "fx_rate":
                (
                    fx
                    if market == "US"
                    else None
                ),
            "gross_krw":
                round(cost),
            "pnl":
                0,
            "pnl_pct":
                0,
            "strategy":
                p.strategy,
            "entry_session":
                p.entry_session,
        }

        self.trades.insert(
            0,
            trade,
        )

        return trade

    def sell(
        self,
        market,
        code,
        price,
        fx_rate,
        reason="",
    ):
        market = market.upper()

        key = (
            f"{market}:"
            f"{code}"
        )

        p = self.positions.get(
            key
        )

        if (
            not p
            or price <= 0
        ):
            return None

        fx = _f(
            fx_rate
            if market == "US"
            else 1.0
        )

        if (
            market == "US"
            and fx <= 0
        ):
            return None

        proceeds = (
            float(price)
            * p.qty
            * fx
        )

        pnl = (
            proceeds
            - p.cost_krw
        )

        pct = (
            pnl
            / p.cost_krw
            * 100
            if p.cost_krw
            else 0
        )

        self.cash_krw += proceeds

        del self.positions[
            key
        ]

        now = datetime.now(
            KST
        )

        trade = {
            "date":
                now.strftime(
                    "%Y-%m-%d"
                ),
            "time":
                now.strftime(
                    "%H:%M:%S"
                ),
            "market":
                market,
            "side":
                "SELL",
            "code":
                p.code,
            "name":
                p.name,
            "qty":
                p.qty,
            "price":
                float(price),
            "currency":
                (
                    "USD"
                    if market == "US"
                    else "KRW"
                ),
            "fx_rate":
                (
                    fx
                    if market == "US"
                    else None
                ),
            "gross_krw":
                round(proceeds),
            "pnl":
                round(pnl),
            "pnl_pct":
                pct,
            "strategy":
                p.strategy,
            "entry_session":
                p.entry_session,
            "reason":
                reason,
        }

        self.trades.insert(
            0,
            trade,
        )

        return trade

    def mark(
        self,
        market,
        code,
        price,
        fx_rate,
    ):
        p = self.positions.get(
            f"{market.upper()}:{code}"
        )

        if not p:
            return

        p.current_price = float(
            price
        )

        if (
            p.market == "US"
            and fx_rate > 0
        ):
            p.fx_current = float(
                fx_rate
            )


def rsi_points(
    rv,
):
    rv = _f(rv)

    if rv < 30:
        return round(
            max(
                0,
                min(
                    4,
                    rv / 30 * 4,
                ),
            ),
            1,
        )

    if rv < 40:
        return 9.0

    if rv < 50:
        return 10.0

    if rv < 60:
        return 8.0

    if rv <= 65:
        return 7.0

    return 0.0


def macd_points(
    m,
    signal,
):
    m = _f(m)
    signal = _f(signal)

    gap = abs(
        m - signal
    )

    scale = max(
        abs(m),
        abs(signal),
        1e-9,
    )

    strength = min(
        1.0,
        gap / scale,
    )

    if m > signal:
        if m > 0:
            pts = (
                7
                + 3 * strength
            )
        else:
            pts = (
                4
                + 2 * strength
            )

    elif m < signal:
        if m > 0:
            pts = max(
                0,
                3
                - 3 * strength,
            )
        else:
            pts = max(
                0,
                1
                - strength,
            )

    else:
        pts = 0

    return round(
        max(
            0,
            min(
                10,
                pts,
            ),
        ),
        1,
    )


def bollinger_points(
    price,
    lower,
    mid,
    upper,
):
    if (
        lower is None
        or mid is None
        or upper is None
        or upper <= lower
    ):
        return 0.0

    price = _f(price)
    lower = _f(lower)
    mid = _f(mid)
    upper = _f(upper)

    if price <= lower:
        return 10.0

    if price >= upper:
        return 0.0

    if price <= mid:
        return round(
            10
            - 8
            * (
                (
                    price
                    - lower
                )
                / max(
                    mid
                    - lower,
                    1e-9,
                )
            ),
            1,
        )

    return round(
        max(
            0,
            2
            - 2
            * (
                (
                    price
                    - mid
                )
                / max(
                    upper
                    - mid,
                    1e-9,
                )
            ),
        ),
        1,
    )


def volume_points(
    q,
):
    prev = _f(
        q.prev_day_volume
    )

    cur = _f(
        q.volume
    )

    if (
        prev <= 0
        or cur < 0
    ):
        return (
            0.0,
            None,
        )

    ratio = (
        cur
        / prev
        * 100
    )

    if ratio <= 30:
        pts = 2

    elif ratio <= 100:
        pts = (
            2
            + (
                ratio
                - 30
            )
            / 70
            * 8
        )

    else:
        pts = (
            10
            + min(
                5,
                (
                    ratio
                    - 100
                )
                / 100
                * 5,
            )
        )

    return (
        round(
            min(
                15,
                max(
                    0,
                    pts,
                ),
            ),
            1,
        ),
        round(
            ratio,
            1,
        ),
    )


def execution_gate(
    q,
    now_ts=None,
):
    strength = _f(
        q.execution_strength
    )

    if strength >= 110:
        return (
            True,
            "체결강도 110+",
        )

    if strength < 90:
        return (
            False,
            "체결강도 90 미만",
        )

    hist = list(
        q.execution_history
    )

    if len(hist) < 2:
        return (
            False,
            "체결강도 50초 추세 축적 중",
        )

    end = _f(
        now_ts,
        hist[-1][0],
    )

    checkpoints = []

    for age in (
        50,
        40,
        30,
        20,
        10,
        0,
    ):
        target = (
            end
            - age
        )

        candidates = [
            x
            for x in hist
            if (
                x[0]
                <= target + 2.5
                and x[0]
                >= target - 7.5
            )
        ]

        if not candidates:
            return (
                False,
                "체결강도 50초 추세 축적 중",
            )

        checkpoints.append(
            min(
                candidates,
                key=lambda x:
                    abs(
                        x[0]
                        - target
                    ),
            )
        )

    vals = [
        x[1]
        for x in checkpoints
    ]

    if min(vals) < 90:
        return (
            False,
            "체결강도 90 미만 구간",
        )

    if all(
        vals[i + 1]
        - vals[i]
        >= 0.5
        for i in range(5)
    ):
        return (
            True,
            "체결강도 90+ · 10초당 +0.5 · 50초",
        )

    return (
        False,
        "체결강도 상승속도 부족",
    )


def moving_average_points(
    px,
    price,
):
    if len(px) < 20:
        return (
            0.0,
            "이평 축적 중",
        )

    ma5 = sma(
        px,
        5,
    )

    ma10 = sma(
        px,
        10,
    )

    ma20 = sma(
        px,
        20,
    )

    mas = [
        x
        for x in (
            ma5,
            ma10,
            ma20,
        )
        if x
    ]

    price = _f(
        price
    )

    if ma5 > ma10 > ma20:
        overhead = [
            x
            for x in mas
            if x > price
        ]

        if not overhead:
            return (
                10.0,
                "상승 · 상단 이평 저항 없음",
            )

        d = (
            (
                min(overhead)
                - price
            )
            / price
            * 100
        )

        if d <= 1:
            pts = 1
        elif d <= 2:
            pts = 3
        elif d <= 4:
            pts = 5
        elif d <= 7:
            pts = 7
        else:
            pts = 10

        return (
            float(pts),
            f"상승 · 저항 이평 {d:.1f}%",
        )

    if ma5 < ma10 < ma20:
        supports = [
            x
            for x in mas
            if x <= price
        ]

        if not supports:
            return (
                0.0,
                "하락 · 이평 지지 없음",
            )

        d = (
            (
                price
                - max(supports)
            )
            / price
            * 100
        )

        if d <= 1:
            pts = 10
        elif d <= 2:
            pts = 8
        elif d <= 4:
            pts = 6
        elif d <= 7:
            pts = 3
        else:
            pts = 0

        return (
            float(pts),
            f"하락 · 지지 이평 {d:.1f}%",
        )

    return (
        5.0,
        "이평 혼조",
    )


def price_structure_points(
    q,
):
    bars = list(
        q.daily_bars
    )

    if len(bars) < 3:
        return (
            0.0,
            "일봉 축적 중",
        )

    three = bars[
        -3:
    ]

    close_up = (
        three[0]["close"]
        < three[1]["close"]
        < three[2]["close"]
    )

    low_up = (
        three[0]["low"]
        < three[1]["low"]
        < three[2]["low"]
    )

    if (
        close_up
        and low_up
    ):
        three_score = 10.0
        three_reason = (
            "3일 종가·저점 상승"
        )

    elif close_up:
        three_score = 7.0
        three_reason = (
            "3일 종가 상승"
        )

    else:
        three_score = 0.0
        three_reason = ""

    box_score = 0.0
    box_reason = ""

    if len(bars) >= 10:
        ten = bars[
            -10:
        ]

        lo = min(
            b["low"]
            for b in ten
        )

        hi = max(
            b["high"]
            for b in ten
        )

        width = (
            (
                hi
                - lo
            )
            / max(
                lo,
                1e-9,
            )
            * 100
        )

        if (
            width <= 10
            and hi > lo
        ):
            pos = (
                (
                    q.price
                    - lo
                )
                / (
                    hi
                    - lo
                )
                * 100
            )

            if pos <= 15:
                box_score = 10
            elif pos <= 30:
                box_score = 8
            elif pos <= 40:
                box_score = 5
            elif pos <= 50:
                box_score = 2
            elif pos <= 60:
                box_score = 1
            else:
                box_score = 0

            box_reason = (
                f"10일 박스 "
                f"{max(0, min(100, pos)):.0f}% 위치"
            )

    if box_score > three_score:
        return (
            float(box_score),
            box_reason,
        )

    return (
        three_score,
        three_reason
        or box_reason
        or "가격 구조 중립",
    )


def elliott_points(
    q,
    smart=False,
):
    bars = list(
        q.daily_bars
    )

    if len(bars) >= 8:
        series = [
            b["close"]
            for b in bars[-12:]
        ]
    else:
        series = list(
            q.prices
        )[-40:]

    if len(series) < 8:
        return (
            0.0,
            "엘리어트 추정 축적 중",
        )

    lo = min(series)
    hi = max(series)
    cur = series[-1]

    pos = (
        (
            cur
            - lo
        )
        / max(
            hi
            - lo,
            1e-9,
        )
        * 100
    )

    recent = (
        series[-1]
        - series[-3]
    )

    lows_up = (
        min(
            series[-3:-1]
        )
        >= min(
            series[-6:-3]
        )
    )

    if smart:
        if (
            pos <= 30
            and recent >= 0
        ):
            pts = 10
            label = (
                "엘리어트 1~2파 저점권 추정"
            )

        elif (
            pos <= 55
            and recent > 0
        ):
            pts = 8
            label = (
                "엘리어트 3파 초입 추정"
            )

        elif pos <= 75:
            pts = 5
            label = (
                "엘리어트 중간 진행 추정"
            )

        elif pos <= 90:
            pts = 2
            label = (
                "엘리어트 후반 추정"
            )

        else:
            pts = 0
            label = (
                "엘리어트 고점권 추정"
            )

    else:
        if (
            25 <= pos <= 55
            and recent > 0
        ):
            pts = 9
            label = (
                "엘리어트 1~3파 초입 추정"
            )

        elif (
            55 < pos <= 78
            and recent > 0
            and lows_up
        ):
            pts = 10
            label = (
                "엘리어트 3파 진행 추정"
            )

        elif (
            pos <= 25
            and recent > 0
        ):
            pts = 7
            label = (
                "엘리어트 저점 반등 추정"
            )

        elif pos <= 90:
            pts = 4
            label = (
                "엘리어트 후반 추정"
            )

        else:
            pts = 1
            label = (
                "엘리어트 고점권 추정"
            )

    return (
        float(pts),
        label,
    )


def flow_points(
    q,
):
    f = _f(
        q.foreign_net
    )

    i = _f(
        q.institution_net
    )

    p = _f(
        q.program_net
    )

    hist = list(
        q.flow_history
    )

    pair = (
        f > 0
        and i > 0
    )

    if pair:
        fi = 5.0

    elif (
        f > 0
        or i > 0
    ):
        fi = 2.5

    else:
        fi = 0.0

    if len(hist) >= 2:
        old = hist[
            max(
                0,
                len(hist) - 6,
            )
        ]

        if (
            pair
            and (
                f + i
            )
            > (
                old[1]
                + old[2]
            )
        ):
            fi = min(
                6.0,
                fi + 1.0,
            )

        elif (
            (
                f > 0
                or i > 0
            )
            and (
                f + i
            )
            > (
                old[1]
                + old[2]
            )
        ):
            fi = min(
                3.0,
                fi + 0.5,
            )

    if p > 0:
        prog = 2.5

        if (
            len(hist) >= 2
            and p
            > hist[
                max(
                    0,
                    len(hist) - 6,
                )
            ][3]
        ):
            prog = 4.0

    elif p < 0:
        prog = -1.0

    else:
        prog = 0.0

    return (
        round(
            max(
                0,
                min(
                    10,
                    fi + prog,
                ),
            ),
            1,
        ),
        pair,
    )


def _phase(
    now=None,
):
    now = (
        now
        or datetime.now(KST)
    ).astimezone(
        KST
    )

    m = (
        now.hour * 60
        + now.minute
    )

    if 480 <= m < 540:
        return "PRE08"

    if 540 <= m < 600:
        return "OPEN"

    if 600 <= m < 720:
        return "SLEEP"

    if m >= 870:
        return "LATE"

    return "REGULAR"


def scalp_analysis(
    q,
    sector_score=0,
    sector_stock_score=0,
    market="KR",
    now=None,
):
    market = str(
        market
    ).upper()

    px = list(
        q.prices
    )

    if len(px) < 20:
        return {
            "score":
                0.0,
            "reasons":
                [
                    "지표 데이터 축적 중"
                ],
            "breakdown":
                {},
            "gate":
                False,
            "phase":
                _phase(now),
        }

    m, sig = macd(
        px
    )

    rv = rsi(
        px
    )

    mid, upper, lower = bollinger(
        px
    )

    mp = macd_points(
        m,
        sig,
    )

    rp = rsi_points(
        rv
    )

    bp = bollinger_points(
        q.price,
        lower,
        mid,
        upper,
    )

    vp, vr = volume_points(
        q
    )

    mapts, mareason = moving_average_points(
        px,
        q.price,
    )

    struct, structreason = price_structure_points(
        q
    )

    ell, ellreason = elliott_points(
        q,
        False,
    )

    event = max(
        0,
        min(
            10,
            _f(
                q.event_score
            ),
        ),
    )

    phase = _phase(
        now
    )

    breakdown = {
        "MACD":
            mp,
        "RSI":
            rp,
        "볼린저":
            bp,
        "거래량":
            vp,
        "이평":
            mapts,
        "가격구조":
            struct,
        "엘리어트":
            ell,
    }

    reasons = [
        f"MACD {mp:.1f}",
        f"RSI {rv:.0f} +{rp:.1f}",
        f"볼린저 +{bp:.1f}",
        (
            f"전일대비 거래량 "
            f"{vr:.0f}% +{vp:.1f}"
            if vr is not None
            else "전일거래량 대기"
        ),
        mareason,
        structreason,
        ellreason,
    ]

    if market == "KR":
        gate, gate_reason = execution_gate(
            q
        )

        flow, pair = flow_points(
            q
        )

        breakdown.update(
            {
                "수급":
                    flow,
                "섹터":
                    max(
                        0,
                        min(
                            10,
                            _f(
                                sector_score
                            ),
                        ),
                    ),
                "섹터내강도":
                    max(
                        0,
                        min(
                            5,
                            _f(
                                sector_stock_score
                            ),
                        ),
                    ),
                "이벤트":
                    event,
            }
        )

        reasons.extend(
            [
                gate_reason,
                (
                    f"수급 +{flow:.1f}"
                    + (
                        " · 쌍끌이"
                        if pair
                        else ""
                    )
                ),
                (
                    f"섹터 "
                    f"+{breakdown['섹터']:.1f}"
                ),
                (
                    f"섹터내 강도 "
                    f"+{breakdown['섹터내강도']:.1f}"
                ),
            ]
        )

        if q.events:
            reasons.append(
                f"최근 공시 +{event:.1f}"
            )

        if q.event_blocked:
            return {
                "score":
                    0.0,
                "reasons":
                    [
                        "악재성 공시 진입차단"
                    ]
                    + reasons,
                "breakdown":
                    breakdown,
                "gate":
                    False,
                "phase":
                    phase,
            }

        if not gate:
            return {
                "score":
                    0.0,
                "reasons":
                    [
                        gate_reason
                    ]
                    + reasons,
                "breakdown":
                    breakdown,
                "gate":
                    False,
                "phase":
                    phase,
            }

        technical = (
            mp
            + rp
            + bp
            + vp
            + mapts
            + struct
            + ell
        )

        flowblock = flow

        other = (
            technical
            + breakdown["섹터"]
            + breakdown["섹터내강도"]
            + event
        )

        if phase == "SLEEP":
            other *= 0.50

            flowblock *= (
                5.0
                if pair
                else 3.0
            )

            score = (
                (
                    other
                    + flowblock
                )
                / max(
                    1,
                    54 + 50,
                )
                * 100
            )

        elif phase == "LATE":
            score = (
                (
                    other
                    + flowblock * 1.5
                )
                / max(
                    1,
                    98 + 15,
                )
                * 100
            )

        else:
            score = (
                (
                    other
                    + flowblock
                )
                / 108
                * 100
            )

    else:
        gate = True

        score = (
            (
                mp
                + rp
                + bp
                + vp
                + mapts
                + struct
                + ell
            )
            / 73
            * 100
        )

    return {
        "score":
            round(
                max(
                    0,
                    min(
                        100,
                        score,
                    ),
                ),
                1,
            ),
        "reasons":
            reasons,
        "breakdown":
            breakdown,
        "gate":
            gate,
        "phase":
            phase,
    }


def scalp_score(
    q,
    sector_score=0,
    sector_stock_score=0,
    market="KR",
    now=None,
):
    a = scalp_analysis(
        q,
        sector_score,
        sector_stock_score,
        market,
        now,
    )

    return (
        a["score"],
        a["reasons"],
    )


def _accumulation_component(
    q,
    which,
):
    idx = (
        1
        if which == "foreign"
        else 2
    )

    current = (
        q.foreign_net
        if which == "foreign"
        else q.institution_net
    )

    if current <= 0:
        return 0.0

    pts = 15.0

    hist = list(
        q.flow_history
    )

    if len(hist) >= 3:
        vals = [
            x[idx]
            for x in hist[-12:]
        ]

        positive = (
            sum(
                v > 0
                for v in vals
            )
            / len(vals)
        )

        pts += (
            8
            * positive
        )

        if vals[-1] >= vals[0]:
            pts += 7

    return round(
        min(
            30,
            pts,
        ),
        1,
    )


def smart_price_points(
    q,
):
    bars = list(
        q.daily_bars
    )

    if len(bars) < 10:
        return (
            0.0,
            "10일 종가 축적 중",
        )

    closes = [
        b["close"]
        for b in bars[-10:]
    ]

    cur = closes[-1]

    rank = (
        sum(
            x < cur
            for x in closes
        )
        + 1
    )

    if rank <= 3:
        pts = 10

    elif rank <= 5:
        pts = 6

    elif rank <= 7:
        pts = 3

    else:
        pts = 0

    return (
        float(pts),
        f"10일 종가 하위 {rank}위",
    )


def smart_analysis(
    q,
):
    foreign = _accumulation_component(
        q,
        "foreign",
    )

    institution = _accumulation_component(
        q,
        "institution",
    )

    prog = 0.0

    if q.program_net > 0:
        prog = 7.0

        hist = list(
            q.flow_history
        )

        if (
            len(hist) >= 2
            and q.program_net
            > hist[
                max(
                    0,
                    len(hist) - 6,
                )
            ][3]
        ):
            prog = 10.0

    price, pr_reason = smart_price_points(
        q
    )

    ell, ell_reason = elliott_points(
        q,
        True,
    )

    val = 0.0

    if (
        0
        < q.per
        <= 15
    ):
        val += 5

    if (
        0
        < q.pbr
        <= 1.5
    ):
        val += 5

    score = (
        foreign
        + institution
        + prog
        + price
        + ell
        + val
    )

    reasons = [
        f"외국인 매집 +{foreign:.1f}",
        f"기관 매집 +{institution:.1f}",
        f"프로그램 +{prog:.1f}",
        pr_reason,
        ell_reason,
        f"가치 +{val:.1f}",
    ]

    if (
        q.foreign_net > 0
        and q.institution_net > 0
    ):
        reasons.insert(
            0,
            "외국인·기관 쌍끌이 매집",
        )

    return {
        "score":
            round(
                max(
                    0,
                    min(
                        100,
                        score,
                    ),
                ),
                1,
            ),
        "reasons":
            reasons,
        "breakdown":
            {
                "외국인매집":
                    foreign,
                "기관매집":
                    institution,
                "프로그램":
                    prog,
                "가격위치":
                    price,
                "엘리어트":
                    ell,
                "가치":
                    val,
            },
    }


def smart_score(
    q,
):
    a = smart_analysis(
        q
    )

    return (
        a["score"],
        a["reasons"],
    )


def completed_daily_bars(
    q,
    now=None,
):
    now = (
        now
        or datetime.now(KST)
    ).astimezone(
        KST
    )

    today = now.strftime(
        "%Y%m%d"
    )

    out = []

    for b in q.daily_bars:
        if (
            b["date"] < today
            or (
                b["date"] == today
                and (
                    now.hour * 60
                    + now.minute
                )
                >= 930
            )
        ):
            out.append(b)

    return out


def smart_buy_eligibility(
    q,
    now=None,
):
    now = (
        now
        or datetime.now(KST)
    ).astimezone(
        KST
    )

    bars = completed_daily_bars(
        q,
        now,
    )

    if len(bars) < 10:
        return (
            False,
            None,
            "10거래일 종가 축적 중",
        )

    ten = bars[
        -10:
    ]

    latest = ten[-1]
    cur = latest["close"]

    rank = (
        sum(
            b["close"] < cur
            for b in ten
        )
        + 1
    )

    today = now.strftime(
        "%Y%m%d"
    )

    if latest["date"] >= today:
        return (
            False,
            rank,
            "금일 종가 확정 · 다음 거래일 대기",
        )

    return (
        rank <= 3,
        rank,
        (
            f"10일 종가 하위 {rank}위"
            if rank <= 3
            else (
                f"10일 종가 하위 "
                f"{rank}위 · 매수대기"
            )
        ),
    )


def scalp_session(
    now=None,
):
    now = (
        now
        or datetime.now(KST)
    ).astimezone(
        KST
    )

    if now.weekday() >= 5:
        return "CLOSED"

    m = (
        now.hour * 60
        + now.minute
    )

    if 480 <= m < 529:
        return "PRE08"

    if 529 <= m < 540:
        return "PAUSE"

    if 540 <= m < 870:
        return "REGULAR"

    if 870 <= m < 1200:
        return "LATE"

    return "CLOSED"


def must_force_sell_pre(
    position,
    now=None,
):
    if (
        position.strategy != "SCALP"
        or position.entry_session != "PRE08"
    ):
        return False

    now = (
        now
        or datetime.now(KST)
    ).astimezone(
        KST
    )

    return (
        now.hour * 60
        + now.minute
    ) >= 529
