from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional
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

KST = timezone(
    timedelta(hours=9)
)


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

    per: float = 0.0
    pbr: float = 0.0

    foreign_net: float = 0.0
    institution_net: float = 0.0

    execution_strength: float = 100.0

    prices: deque = field(
        default_factory=lambda: deque(
            maxlen=240
        )
    )

    updated_at: float = 0.0

    def mark(
        self,
        price,
        volume=0,
    ):
        if not price:
            return

        price = float(
            price
        )

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

        volume = float(
            volume or 0
        )

        if (
            self.volume
            and volume > self.volume
        ):
            self.prev_volume = (
                self.volume
            )

        self.volume = max(
            self.volume,
            volume,
        )

        self.prices.append(
            price
        )

        self.updated_at = (
            time.time()
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

    @property
    def key(
        self
    ):
        return (
            f"{self.market}:"
            f"{self.code}"
        )

    @property
    def cost_krw(
        self
    ):
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
    def value_krw(
        self
    ):
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
    def pnl_krw(
        self
    ):
        return (
            self.value_krw
            - self.cost_krw
        )

    @property
    def pnl_pct(
        self
    ):
        if not self.cost_krw:
            return 0.0

        return (
            self.pnl_krw
            / self.cost_krw
            * 100
        )


class PaperAccount:

    def __init__(
        self
    ):
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
        day_key: str,
    ):
        if (
            day_key
            and self.budget_day
            != day_key
        ):
            self.budget_day = (
                day_key
            )

            self.explicit_budget_krw = (
                None
            )

    def set_budget(
        self,
        amount: Optional[int],
        day_key: str,
    ):
        self.ensure_budget_day(
            day_key
        )

        if amount is None:
            self.explicit_budget_krw = (
                None
            )

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
        enabled: bool,
    ):
        self.auto_max_if_unset = bool(
            enabled
        )

    def effective_budget_krw(
        self,
        day_key: str,
    ):
        self.ensure_budget_day(
            day_key
        )

        if (
            self.explicit_budget_krw
            is not None
        ):
            return (
                self.explicit_budget_krw
            )

        if self.auto_max_if_unset:
            return (
                self.initial_cash_krw
            )

        return 0

    def held_cost_krw(
        self,
        market: Optional[str] = None,
    ):
        return sum(
            p.cost_krw

            for p in
            self.positions.values()

            if (
                market is None
                or p.market == market
            )
        )

    def equity_krw(
        self
    ):
        return (
            self.cash_krw
            + sum(
                p.value_krw
                for p
                in self.positions.values()
            )
        )

    def market_positions(
        self,
        market: str,
    ):
        return [
            p

            for p
            in self.positions.values()

            if p.market == market
        ]

    def buy(
        self,
        quote: Quote,
        qty: int,
        market: str,
        fx_rate: float,
        day_key: str,
    ):
        market = (
            market.upper()
        )

        if (
            qty < 1
            or quote.price <= 0
        ):
            return None

        fx = float(
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

        cost_krw = (
            quote.price
            * qty
            * fx
        )

        budget = (
            self.effective_budget_krw(
                day_key
            )
        )

        if (
            cost_krw
            > self.cash_krw
        ):
            return None

        if (
            self.held_cost_krw()
            + cost_krw
            > budget
        ):
            return None

        self.cash_krw -= (
            cost_krw
        )

        p = Position(
            market=market,
            code=quote.code,
            name=(
                quote.name
                or quote.code
            ),
            qty=qty,
            avg_price=float(
                quote.price
            ),
            current_price=float(
                quote.price
            ),
            fx_buy=fx,
            fx_current=fx,
        )

        self.positions[
            key
        ] = p

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
                "BUY",

            "code":
                p.code,

            "name":
                p.name,

            "qty":
                qty,

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
                round(
                    cost_krw
                ),

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
        market: str,
        code: str,
        price: float,
        fx_rate: float,
    ):
        market = (
            market.upper()
        )

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

        fx = float(
            fx_rate
            if market == "US"
            else 1.0
        )

        if (
            market == "US"
            and fx <= 0
        ):
            return None

        proceeds_krw = (
            float(price)
            * p.qty
            * fx
        )

        pnl_krw = (
            proceeds_krw
            - p.cost_krw
        )

        pnl_pct = (
            pnl_krw
            / p.cost_krw
            * 100
            if p.cost_krw
            else 0.0
        )

        self.cash_krw += (
            proceeds_krw
        )

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
                float(
                    price
                ),

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
                round(
                    proceeds_krw
                ),

            "pnl":
                round(
                    pnl_krw
                ),

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
        market: str,
        code: str,
        price: float,
        fx_rate: float,
    ):
        key = (
            f"{market.upper()}:"
            f"{code}"
        )

        p = self.positions.get(
            key
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


def scalp_score(
    q: Quote,
    sector_score=0,
):
    px = list(
        q.prices
    )

    if len(px) < 20:
        return (
            0,
            [
                "지표 데이터 축적 중"
            ],
        )

    score = 0
    why = []

    m, signal = macd(
        px
    )

    rv = rsi(
        px
    )

    wr = williams_r(
        px
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

    mid, upper, _ = bollinger(
        px
    )

    pdi, mdi, adx = dmi_proxy(
        px
    )

    if m > signal:
        score += 10
        why.append(
            "MACD"
        )

    if (
        50
        <= rv
        <= 72
    ):
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
            f"주도섹터 +{add:.0f}"
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
    px = list(
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

    if len(px) >= 20:

        ma5 = sma(
            px,
            5,
        )

        ma20 = sma(
            px,
            20,
        )

        rv = rsi(
            px
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
            len(px) >= 6
            and px[-6] > 0
            and (
                px[-1]
                / px[-6]
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
