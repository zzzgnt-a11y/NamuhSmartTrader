from __future__ import annotations

from dataclasses import dataclass, field
from collections import deque
from typing import Dict
import os
import time

from indicators import (
    sma,
    rsi,
    williams_r,
    macd,
    bollinger,
    dmi_proxy,
)


@dataclass
class Quote:
    code: str
    name: str = ""
    sector: str = ""

    price: float = 0
    open: float = 0
    high: float = 0
    low: float = 0

    volume: float = 0
    prev_volume: float = 0

    per: float = 0
    pbr: float = 0

    foreign_net: float = 0
    institution_net: float = 0

    execution_strength: float = 100

    prices: deque = field(
        default_factory=lambda: deque(
            maxlen=240
        )
    )

    updated_at: float = 0

    def mark(
        self,
        p,
        v=0,
    ):
        if not p:
            return

        p = float(p)

        self.price = p

        if not self.open:
            self.open = p

        self.high = max(
            self.high or p,
            p,
        )

        self.low = min(
            self.low or p,
            p,
        )

        self.volume = max(
            self.volume,
            float(v or 0),
        )

        self.prices.append(p)

        self.updated_at = time.time()


@dataclass
class Position:
    code: str
    name: str
    qty: int
    avg_price: int
    current_price: int

    @property
    def cost(self):
        return (
            self.qty
            * self.avg_price
        )

    @property
    def value(self):
        return (
            self.qty
            * self.current_price
        )

    @property
    def pnl(self):
        return (
            self.value
            - self.cost
        )

    @property
    def pnl_pct(self):
        if not self.cost:
            return 0

        return (
            self.pnl
            / self.cost
            * 100
        )


class PaperAccount:
    def __init__(self):
        self.initial_cash = int(
            os.getenv(
                "PAPER_INITIAL_CASH",
                "1000000",
            )
        )

        self.cash = (
            self.initial_cash
        )

        self.daily_budget = int(
            os.getenv(
                "PAPER_DAILY_BUDGET",
                "200000",
            )
        )

        self.positions: Dict[
            str,
            Position,
        ] = {}

        self.trades = []

    def held_cost(self):
        return sum(
            p.cost
            for p
            in self.positions.values()
        )

    def equity(self):
        return (
            self.cash
            + sum(
                p.value
                for p
                in self.positions.values()
            )
        )

    def set_budget(
        self,
        value,
    ):
        self.daily_budget = max(
            0,
            int(value),
        )

    def buy(
        self,
        q: Quote,
        qty: int,
    ):
        cost = (
            int(q.price)
            * qty
        )

        if qty < 1:
            return None

        if cost > self.cash:
            return None

        if (
            self.held_cost()
            + cost
            > self.daily_budget
        ):
            return None

        if q.code in self.positions:
            return None

        self.cash -= cost

        self.positions[
            q.code
        ] = Position(
            q.code,
            q.name,
            qty,
            int(q.price),
            int(q.price),
        )

        trade = {
            "date":
                time.strftime(
                    "%Y-%m-%d"
                ),

            "time":
                time.strftime(
                    "%H:%M:%S"
                ),

            "side":
                "BUY",

            "code":
                q.code,

            "name":
                q.name,

            "qty":
                qty,

            "price":
                int(q.price),

            "pnl":
                0,

            "pnl_pct":
                0,
        }

        self.trades.insert(
            0,
            trade,
        )

        return trade

    def sell(
        self,
        code,
        price,
    ):
        position = (
            self.positions.get(
                code
            )
        )

        if not position:
            return None

        proceeds = (
            int(price)
            * position.qty
        )

        pnl = (
            proceeds
            - position.cost
        )

        pnl_pct = (
            pnl
            / position.cost
            * 100
            if position.cost
            else 0
        )

        self.cash += proceeds

        del self.positions[
            code
        ]

        trade = {
            "date":
                time.strftime(
                    "%Y-%m-%d"
                ),

            "time":
                time.strftime(
                    "%H:%M:%S"
                ),

            "side":
                "SELL",

            "code":
                position.code,

            "name":
                position.name,

            "qty":
                position.qty,

            "price":
                int(price),

            "pnl":
                pnl,

            "pnl_pct":
                pnl_pct,
        }

        self.trades.insert(
            0,
            trade,
        )

        return trade

    def mark(
        self,
        code,
        price,
    ):
        if code in self.positions:
            self.positions[
                code
            ].current_price = int(
                price
            )


def scalp_score(
    q: Quote,
    sector_score=0,
):
    prices = list(
        q.prices
    )

    if len(prices) < 20:
        return (
            0,
            [
                "지표 데이터 축적 중"
            ],
        )

    score = 0
    why = []

    m,
    signal = macd(
        prices
    )

    rv = rsi(
        prices
    )

    wr = williams_r(
        prices
    )

    ma5 = sma(
        prices,
        5,
    )

    ma10 = sma(
        prices,
        10,
    )

    ma20 = sma(
        prices,
        20,
    )

    mid,
    upper,
    _ = bollinger(
        prices
    )

    pdi,
    mdi,
    adx = dmi_proxy(
        prices
    )

    if m > signal:
        score += 10
        why.append(
            "MACD"
        )

    if 50 <= rv <= 72:
        score += 10

        why.append(
            f"RSI {rv:.0f}"
        )

    elif rv > 82:
        score -= 8

    if (
        -70
        <= wr
        <= -15
    ):
        score += 5

        why.append(
            "Williams %R"
        )

    if (
        ma5
        and ma10
        and ma20
        and ma5
        > ma10
        > ma20
    ):
        score += 15

        why.append(
            "5>10>20"
        )

    if (
        mid
        and upper
        and mid
        < q.price
        < upper
    ):
        score += 8

        why.append(
            "볼린저 추세"
        )

    if (
        pdi > mdi
        and adx >= 12
    ):
        score += 10

        why.append(
            "DMI"
        )

    if (
        q.prev_volume > 0
        and (
            q.volume
            / q.prev_volume
        ) >= 1.5
    ):
        score += 10

        why.append(
            "거래량 "
            f"{q.volume / q.prev_volume:.1f}배"
        )

    if (
        q.execution_strength
        >= 105
    ):
        score += 10

        why.append(
            "체결강도 "
            f"{q.execution_strength:.0f}"
        )

    if sector_score > 0:
        add = min(
            15,
            sector_score,
        )

        score += add

        why.append(
            "주도섹터 "
            f"+{add:.0f}"
        )

    return (
        max(
            0,
            min(
                100,
                round(
                    score,
                    1,
                ),
            ),
        ),
        why,
    )


def smart_score(
    q: Quote,
):
    prices = list(
        q.prices
    )

    score = 0
    why = []

    if (
        0
        < q.per
        <= 15
    ):
        score += 15

        why.append(
            f"PER {q.per:.2f}"
        )

    if (
        0
        < q.pbr
        <= 1.5
    ):
        score += 15

        why.append(
            f"PBR {q.pbr:.2f}"
        )

    if (
        q.foreign_net
        > 0
    ):
        score += 12

        why.append(
            "외국인 순매수"
        )

    if (
        q.institution_net
        > 0
    ):
        score += 12

        why.append(
            "기관 순매수"
        )

    if len(prices) >= 20:
        ma5 = sma(
            prices,
            5,
        )

        ma20 = sma(
            prices,
            20,
        )

        rv = rsi(
            prices
        )

        if (
            ma5
            and ma20
            and ma5 >= ma20
            and rv < 72
        ):
            score += 12

            why.append(
                "완만한 누적 추세"
            )

        if (
            len(prices) >= 6
            and prices[-6] > 0
            and (
                (
                    prices[-1]
                    / prices[-6]
                )
                - 1
            )
            * 100
            < 8
        ):
            score += 8

            why.append(
                "급등 전 누적"
            )

    return (
        max(
            0,
            min(
                100,
                score,
            ),
        ),
        why,
    )
