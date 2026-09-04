from __future__ import annotations

import os
import re
import threading
import time

from contextlib import (
    asynccontextmanager,
)

from dotenv import load_dotenv

from fastapi import (
    FastAPI,
    Query,
)

from fastapi.responses import (
    FileResponse,
)

from fastapi.staticfiles import (
    StaticFiles,
)

from pydantic import (
    BaseModel,
)

from engine import (
    PaperAccount,
    scalp_score,
    smart_score,
)

from nhfeed import (
    NHFeed,
)


load_dotenv()


MARKETS = (
    "KR",
    "US",
)


feed = NHFeed()


papers = {
    market:
        PaperAccount()

    for market
    in MARKETS
}


protected = {
    x.strip()

    for x
    in os.getenv(
        "PROTECTED_CODES",
        "",
    ).split(
        ","
    )

    if x.strip()
}


SECTOR_FALLBACK = {
    "005930":
        "반도체",

    "000660":
        "반도체",

    "042700":
        "반도체",

    "035420":
        "인터넷/AI",

    "035720":
        "인터넷/AI",

    "068270":
        "바이오",

    "012450":
        "방산",

    "267260":
        "전력기기",
}


cache_lock = (
    threading.Lock()
)


CACHE = {
    "KR": {
        "sectors": [],
        "scalp": [],
        "smart": [],
        "updated_at": 0.0,
    },

    "US": {
        "sectors": [],
        "scalp": [],
        "smart": [],
        "updated_at": 0.0,
    },
}


_started = False


def normalize_market(
    value: str | None,
) -> str:
    value = (
        str(
            value
            or "KR"
        )
        .upper()
        .strip()
    )

    if value in MARKETS:
        return value

    return "KR"


def number(
    value
):
    try:
        return float(
            value
            or 0
        )

    except Exception:
        return 0.0


def krw(
    value
):
    return int(
        round(
            number(
                value
            )
        )
    )


def build_sectors(
    market: str,
):
    agg = {}

    for q in list(
        feed
        .quotes_for(
            market
        )
        .values()
    ):
        if (
            q.price <= 0
            or q.open <= 0
        ):
            continue

        if market == "KR":
            sector = (
                q.sector
                or SECTOR_FALLBACK.get(
                    q.code,
                    "기타",
                )
            )

        else:
            sector = (
                q.sector
                or "기타"
            )

        item = agg.setdefault(
            sector,
            {
                "sector":
                    sector,

                "sum":
                    0.0,

                "n":
                    0,

                "money":
                    0.0,

                "leader":
                    "",

                "best":
                    -999.0,
            },
        )

        change = (
            (
                q.price
                / q.open
            )
            - 1
        ) * 100

        item[
            "sum"
        ] += change

        item[
            "n"
        ] += 1

        item[
            "money"
        ] += (
            q.price
            * q.volume
        )

        if (
            change
            > item[
                "best"
            ]
        ):
            item[
                "best"
            ] = change

            item[
                "leader"
            ] = q.name

    output = []

    for item in (
        agg.values()
    ):
        if not item[
            "n"
        ]:
            continue

        average = (
            item[
                "sum"
            ]
            / item[
                "n"
            ]
        )

        score = max(
            0,
            min(
                15,
                average
                * 2
                + (
                    2
                    if item[
                        "money"
                    ] > 0
                    else 0
                ),
            ),
        )

        output.append(
            {
                "sector":
                    item[
                        "sector"
                    ],

                "change_pct":
                    average,

                "leader":
                    item[
                        "leader"
                    ],

                "score":
                    score,
            }
        )

    return sorted(
        output,
        key=lambda x: x[
            "score"
        ],
        reverse=True,
    )[:8]


def candidate(
    q,
    market: str,
    smart: bool = False,
    secmap=None,
):
    if market == "KR":
        sector = (
            q.sector
            or SECTOR_FALLBACK.get(
                q.code,
                "기타",
            )
        )

    else:
        sector = (
            q.sector
            or "기타"
        )

    if smart:
        (
            score,
            why,
        ) = smart_score(
            q
        )

    else:
        (
            score,
            why,
        ) = scalp_score(
            q,
            (
                secmap.get(
                    sector,
                    0,
                )
                if secmap
                else 0
            ),
        )

    return {
        "market":
            market,

        "code":
            q.code,

        "name":
            q.name
            or q.code,

        "sector":
            sector,

        "currency":
            (
                "KRW"
                if market
                == "KR"
                else "USD"
            ),

        "price":
            (
                krw(
                    q.price
                )
                if market
                == "KR"
                else round(
                    number(
                        q.price
                    ),
                    4,
                )
            ),

        "open":
            (
                krw(
                    q.open
                )
                if market
                == "KR"
                else round(
                    number(
                        q.open
                    ),
                    4,
                )
            ),

        "score":
            score,

        "execution_strength":
            q.execution_strength,

        "per":
            q.per,

        "pbr":
            q.pbr,

        "foreign_net":
            (
                q.foreign_net
                if market
                == "KR"
                else None
            ),

        "institution_net":
            (
                q.institution_net
                if market
                == "KR"
                else None
            ),

        "vi_pre":
            (
                krw(
                    q.open
                    * 1.10
                    * 0.997
                )
                if (
                    market
                    == "KR"
                    and q.open
                )
                else None
            ),

        "reasons":
            why,

        "series": [
            (
                krw(
                    x
                )
                if market
                == "KR"
                else round(
                    number(
                        x
                    ),
                    4,
                )
            )

            for x
            in list(
                q.prices
            )[-60:]
        ],
    }


def rebuild_cache(
    market: str,
):
    market = normalize_market(
        market
    )

    sectors = (
        build_sectors(
            market
        )
    )

    secmap = {
        x[
            "sector"
        ]:
            x[
                "score"
            ]

        for x
        in sectors
    }

    quotes = [
        q

        for q
        in list(
            feed
            .quotes_for(
                market
            )
            .values()
        )

        if q.price > 0
    ]

    scalp = []
    smart = []

    for q in quotes:
        try:
            scalp.append(
                candidate(
                    q,
                    market,
                    False,
                    secmap,
                )
            )

            smart.append(
                candidate(
                    q,
                    market,
                    True,
                )
            )

        except Exception:
            continue

    scalp.sort(
        key=lambda x: x[
            "score"
        ],
        reverse=True,
    )

    smart.sort(
        key=lambda x: x[
            "score"
        ],
        reverse=True,
    )

    with cache_lock:
        CACHE[
            market
        ][
            "sectors"
        ] = sectors

        CACHE[
            market
        ][
            "scalp"
        ] = scalp[
            :50
        ]

        CACHE[
            market
        ][
            "smart"
        ] = smart[
            :50
        ]

        CACHE[
            market
        ][
            "updated_at"
        ] = time.time()

    return scalp


def trade_from_candidates(
    candidates,
):
    """
    국내 PAPER 계정만 자동운용한다.

    실제 증권사 주문 API는
    이 함수에서 호출하지 않는다.
    """

    paper = papers[
        "KR"
    ]

    quotes = (
        feed.quotes_for(
            "KR"
        )
    )

    score_map = {
        x[
            "code"
        ]:
            x[
                "score"
            ]

        for x
        in candidates
    }

    for position in list(
        paper
        .positions
        .values()
    ):
        q = quotes.get(
            position.code
        )

        if (
            not q
            or q.price <= 0
        ):
            continue

        paper.mark(
            position.code,
            q.price,
        )

        score = (
            score_map.get(
                position.code,
                50,
            )
        )

        if (
            position.pnl_pct
            >= 2.5
            or position.pnl_pct
            <= -1.5
            or score < 46
        ):
            paper.sell(
                position.code,
                q.price,
            )

    for item in candidates:
        if (
            len(
                paper.positions
            ) >= 3
            or item[
                "score"
            ] < 72
        ):
            break

        code = item[
            "code"
        ]

        if (
            code in protected
            or code
            in paper.positions
        ):
            continue

        if (
            item.get(
                "vi_pre"
            )
            and item[
                "price"
            ]
            >= item[
                "vi_pre"
            ]
        ):
            continue

        q = quotes.get(
            code
        )

        if (
            not q
            or q.price <= 0
        ):
            continue

        remain = min(
            paper.cash,
            (
                paper.daily_budget
                - paper.held_cost()
            ),
        )

        if remain < q.price:
            continue

        target = min(
            remain,
            max(
                q.price,
                (
                    paper.daily_budget
                    / 2
                ),
            ),
        )

        qty = int(
            target
            // q.price
        )

        if qty >= 1:
            paper.buy(
                q,
                qty,
            )


def ai_loop():
    while True:
        try:
            kr_scalp = (
                rebuild_cache(
                    "KR"
                )
            )

            rebuild_cache(
                "US"
            )

            trade_from_candidates(
                kr_scalp
            )

        except Exception as exc:
            print(
                "AI LOOP ERROR:",
                exc,
            )

        time.sleep(
            5
        )


def start_background():
    global _started

    if _started:
        return

    _started = True

    if (
        os.getenv(
            "NHPLUG_APP_KEY"
        )
        and os.getenv(
            "NHPLUG_APP_SECRET"
        )
    ):
        feed.start()

    threading.Thread(
        target=ai_loop,
        daemon=True,
    ).start()


@asynccontextmanager
async def lifespan(
    _app: FastAPI
):
    start_background()

    yield


app = FastAPI(
    title=(
        "GY 모의투자 시스템"
    ),
    lifespan=lifespan,
)


app.mount(
    "/static",
    StaticFiles(
        directory="static"
    ),
    name="static",
)


@app.get("/")
def home():
    return FileResponse(
        "static/index.html"
    )


def health_payload():
    return {
        "ok":
            True,

        "nh_configured":
            bool(
                os.getenv(
                    "NHPLUG_APP_KEY"
                )
                and os.getenv(
                    "NHPLUG_APP_SECRET"
                )
            ),

        "nh_realtime":
            feed.connected_any(),

        "realtime":
            dict(
                feed.connected
            ),

        "errors":
            dict(
                feed.errors
            ),

        "orders_sent":
            0,

        "scan_index":
            dict(
                feed.scan_index
            ),

        "tracked": {
            market:
                len(
                    feed.quotes_for(
                        market
                    )
                )

            for market
            in MARKETS
        },

        "priced": {
            market:
                sum(
                    1

                    for q
                    in feed
                    .quotes_for(
                        market
                    )
                    .values()

                    if q.price > 0
                )

            for market
            in MARKETS
        },

        "sample_prices": {
            market: [
                {
                    "code":
                        q.code,

                    "name":
                        q.name,

                    "price":
                        (
                            krw(
                                q.price
                            )
                            if market
                            == "KR"
                            else round(
                                q.price,
                                4,
                            )
                        ),
                }

                for q
                in list(
                    feed
                    .quotes_for(
                        market
                    )
                    .values()
                )

                if q.price > 0
            ][:5]

            for market
            in MARKETS
        },

        "market_updated_at":
            feed.market_updated_at,

        "market_errors":
            dict(
                feed.market_errors
            ),
    }


@app.get(
    "/api/health"
)
def health():
    return health_payload()


class Budget(
    BaseModel
):
    amount: int
    market: str = "KR"


@app.post(
    "/api/budget"
)
def set_budget(
    data: Budget
):
    market = (
        normalize_market(
            data.market
        )
    )

    paper = papers[
        market
    ]

    amount = max(
        0,
        min(
            int(
                data.amount
            ),
            paper.initial_cash,
        ),
    )

    paper.set_budget(
        amount
    )

    return {
        "ok":
            True,

        "market":
            market,

        "budget":
            paper.daily_budget,

        "initial_cash":
            paper.initial_cash,
    }


def serialize_paper(
    market: str,
):
    paper = papers[
        market
    ]

    positions = [
        {
            "market":
                market,

            "code":
                p.code,

            "name":
                p.name,

            "qty":
                p.qty,

            "avg_price":
                krw(
                    p.avg_price
                ),

            "current_price":
                krw(
                    p.current_price
                ),

            "pnl":
                krw(
                    p.pnl
                ),

            "pnl_pct":
                p.pnl_pct,
        }

        for p
        in paper.positions.values()
    ]

    return {
        "initial_cash":
            krw(
                paper.initial_cash
            ),

        "cash":
            krw(
                paper.cash
            ),

        "equity":
            krw(
                paper.equity()
            ),

        "budget":
            krw(
                paper.daily_budget
            ),

        "held_cost":
            krw(
                paper.held_cost()
            ),

        "positions":
            positions,

        "trades":
            paper.trades[
                :100
            ],

        "auto_trade_enabled":
            market == "KR",
    }


@app.get(
    "/api/state"
)
def state(
    market: str = Query(
        "KR"
    ),
):
    market = (
        normalize_market(
            market
        )
    )

    with cache_lock:
        sectors = list(
            CACHE[
                market
            ][
                "sectors"
            ]
        )

        scalp = list(
            CACHE[
                market
            ][
                "scalp"
            ][
                :30
            ]
        )

        smart = list(
            CACHE[
                market
            ][
                "smart"
            ][
                :30
            ]
        )

        updated_at = (
            CACHE[
                market
            ][
                "updated_at"
            ]
        )

    return {
        "market_mode":
            market,

        "health":
            health_payload(),

        "market":
            feed.market_state(
                market
            ),

        "session":
            feed.session_state(
                market
            ),

        "sectors":
            sectors,

        "scalp":
            scalp,

        "smart":
            smart,

        "cache_updated_at":
            updated_at,

        "paper":
            serialize_paper(
                market
            ),

        "protected_codes":
            (
                sorted(
                    protected
                )
                if market
                == "KR"
                else []
            ),
    }


@app.get(
    "/api/market-check"
)
def market_check():
    kr = state(
        "KR"
    )

    us = state(
        "US"
    )

    kr_codes = {
        str(
            item.get(
                "code",
                "",
            )
        )

        for key
        in (
            "scalp",
            "smart",
        )

        for item
        in kr.get(
            key,
            [],
        )
    }

    us_codes = {
        str(
            item.get(
                "code",
                "",
            )
        )

        for key
        in (
            "scalp",
            "smart",
        )

        for item
        in us.get(
            key,
            [],
        )
    }

    domestic_code = (
        re.compile(
            r"^\d{6}$"
        )
    )

    us_has_domestic = any(
        domestic_code.fullmatch(
            code
        )

        for code
        in us_codes
    )

    kr_has_us_ticker = any(
        (
            code
            and not
            domestic_code.fullmatch(
                code
            )
        )

        for code
        in kr_codes
    )

    kr_labels = [
        item.get(
            "label"
        )

        for item
        in kr.get(
            "market",
            [],
        )
    ]

    us_labels = [
        item.get(
            "label"
        )

        for item
        in us.get(
            "market",
            [],
        )
    ]

    expected_kr = [
        "코스피",
        "코스닥",
        "코스피 야간선물",
        "나스닥 선물",
        "필라델피아 반도체지수",
    ]

    expected_us = [
        "S&P500",
        "나스닥",
        "나스닥 선물",
        "필라델피아 반도체지수",
    ]

    checks = {
        "kr_candidates_are_domestic":
            not kr_has_us_ticker,

        "us_candidates_have_no_domestic_codes":
            not us_has_domestic,

        "kr_index_order":
            kr_labels
            == expected_kr,

        "us_index_order":
            us_labels
            == expected_us,

        "nxt_not_in_index_cards":
            (
                "NXT"
                not in kr_labels
                and "NXT"
                not in us_labels
            ),

        "orders_sent_zero":
            (
                health_payload()[
                    "orders_sent"
                ]
                == 0
            ),
    }

    return {
        "ok":
            all(
                checks.values()
            ),

        "checks":
            checks,

        "kr_labels":
            kr_labels,

        "us_labels":
            us_labels,
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app:app",
        host=os.getenv(
            "HOST",
            "0.0.0.0",
        ),
        port=int(
            os.getenv(
                "PORT",
                "8787",
            )
        ),
        reload=False,
            )
