from __future__ import annotations

import os
import re
import threading
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from engine import PaperAccount, scalp_score, smart_score
from indicators import rsi
from nhfeed import NHFeed

load_dotenv()

KST = timezone(timedelta(hours=9))
MARKETS = ("KR", "US")

feed = NHFeed()
paper = PaperAccount()

protected = {
    x.strip()
    for x in os.getenv("PROTECTED_CODES", "").split(",")
    if x.strip()
}

cache_lock = threading.Lock()
started = False

CACHE = {
    "KR": {"sectors": [], "scalp": [], "smart": [], "updated_at": 0.0},
    "US": {"sectors": [], "scalp": [], "smart": [], "updated_at": 0.0},
}

SECTOR_FALLBACK = {
    "005930": "반도체",
    "000660": "반도체",
    "042700": "반도체",
    "035420": "인터넷/AI",
    "035720": "인터넷/AI",
    "068270": "바이오",
    "012450": "방산",
    "267260": "전력기기",
}


def normalize_market(value):
    return "US" if str(value).upper() == "US" else "KR"


def krw(value):
    return int(round(float(value or 0)))


def _int_env(name: str, default: int, minimum: int = 0, maximum: int = 100):
    try:
        value = int(os.getenv(name, str(default)))
    except Exception:
        value = default
    return max(minimum, min(maximum, value))


def buy_score_threshold(market: str):
    return (
        _int_env("US_BUY_SCORE", 70, 0, 100)
        if market == "US"
        else _int_env("KR_BUY_SCORE", 72, 0, 100)
    )


def trading_window(now: Optional[datetime] = None):
    now = now.astimezone(KST) if now else datetime.now(KST)
    h = now.hour + now.minute / 60

    if 8 <= h < 20 and now.weekday() < 5:
        return "KR"

    if h >= 20 and now.weekday() < 5:
        return "US"

    if (
        h < 6
        and (
            now - timedelta(days=1)
        ).weekday() < 5
    ):
        return "US"

    return None


def default_view_market(now: Optional[datetime] = None):
    now = now.astimezone(KST) if now else datetime.now(KST)

    return (
        "US"
        if (
            now.hour >= 20
            or now.hour < 6
        )
        else "KR"
    )


def trading_day_key(
    market: str,
    now: Optional[datetime] = None,
):
    now = now.astimezone(KST) if now else datetime.now(KST)

    if (
        market == "US"
        and now.hour < 6
    ):
        now -= timedelta(days=1)

    return now.strftime("%Y-%m-%d")


def schedule_payload(now: Optional[datetime] = None):
    now = now.astimezone(KST) if now else datetime.now(KST)

    active = trading_window(now)

    return {
        "kst": now.isoformat(),
        "active_market": active,
        "default_view": default_view_market(now),
        "kr_hours": "08:00~20:00 KST",
        "us_hours": "20:00~06:00 KST",
        "trading_enabled": active is not None,
        "label": (
            "국장 자동매매 시간"
            if active == "KR"
            else "미장 자동매매 시간"
            if active == "US"
            else "자동매매 대기시간"
        ),
    }


def build_sectors(market: str):
    agg = {}

    for q in list(
        feed.quotes_for(
            market
        ).values()
    ):
        if (
            q.price <= 0
            or q.open <= 0
        ):
            continue

        sector = (
            q.sector
            or (
                SECTOR_FALLBACK.get(
                    q.code,
                    "기타",
                )
                if market == "KR"
                else "미국주식"
            )
        )

        item = agg.setdefault(
            sector,
            {
                "sector": sector,
                "sum": 0.0,
                "n": 0,
                "money": 0.0,
                "leader": "",
                "best": -999.0,
            },
        )

        change = (
            q.price / q.open - 1
        ) * 100

        item["sum"] += change
        item["n"] += 1
        item["money"] += (
            q.price * q.volume
        )

        if change > item["best"]:
            item["best"] = change
            item["leader"] = q.name

    out = []

    for item in agg.values():
        if not item["n"]:
            continue

        avg = (
            item["sum"]
            / item["n"]
        )

        score = max(
            0,
            min(
                15,
                avg * 2
                + (
                    2
                    if item["money"] > 0
                    else 0
                ),
            ),
        )

        out.append(
            {
                "sector": item["sector"],
                "change_pct": avg,
                "leader": item["leader"],
                "score": score,
            }
        )

    return sorted(
        out,
        key=lambda x: x["score"],
        reverse=True,
    )[:8]


def _tail_avg(px, n):
    if len(px) < n:
        return None

    return sum(px[-n:]) / n


def us_scalp_score(q, sector_score=0):
    px = list(q.prices)

    if len(px) < 20:
        return (
            0,
            [
                f"미장 1분봉 준비 중 {len(px)}/20"
            ],
        )

    score, why = scalp_score(
        q,
        sector_score,
    )

    why = list(why)

    last = px[-1]
    ma5 = _tail_avg(px, 5)
    ma20 = _tail_avg(px, 20)

    if (
        ma5
        and ma20
        and last >= ma5 >= ma20
    ):
        score += 8
        why.append(
            "미장 단기추세"
        )

    if (
        len(px) >= 6
        and px[-6] > 0
    ):
        momentum = (
            last / px[-6] - 1
        ) * 100

        if (
            0.05
            <= momentum
            <= 3.0
        ):
            score += 6

            why.append(
                f"5분 모멘텀 {momentum:.2f}%"
            )

        elif momentum > 5.0:
            score -= 4

            why.append(
                "단기 과열 감점"
            )

    if q.open > 0:
        day_move = (
            q.price / q.open - 1
        ) * 100

        if (
            0
            <= day_move
            <= 4
        ):
            score += 5

            why.append(
                f"세션 추세 {day_move:.2f}%"
            )

        elif day_move > 7:
            score -= 5

            why.append(
                "세션 과열 감점"
            )

    if (
        0
        < q.per
        <= 40
    ):
        score += 4

        why.append(
            "PER 범위 양호"
        )

    return (
        max(
            0,
            min(
                100,
                round(score, 1),
            ),
        ),
        why,
    )


def us_smart_score(q):
    px = list(q.prices)

    score, why = smart_score(q)
    why = list(why)

    if len(px) < 20:
        if not why:
            why.append(
                f"미장 1분봉 준비 중 {len(px)}/20"
            )

        return (
            max(
                0,
                min(
                    100,
                    round(score, 1),
                ),
            ),
            why,
        )

    last = px[-1]
    ma5 = _tail_avg(px, 5)
    ma20 = _tail_avg(px, 20)
    rv = rsi(px)

    if (
        ma5
        and ma20
        and last >= ma5 >= ma20
    ):
        score += 12
        why.append(
            "미장 5>20 추세"
        )

    if (
        45
        <= rv
        <= 68
    ):
        score += 10
        why.append(
            f"RSI {rv:.0f}"
        )

    if px[-20] > 0:
        ret20 = (
            last / px[-20] - 1
        ) * 100

        if (
            0
            <= ret20
            <= 12
        ):
            score += 10
            why.append(
                f"20봉 누적 {ret20:.2f}%"
            )

        elif ret20 > 18:
            score -= 6
            why.append(
                "20봉 과열 감점"
            )

    if q.open > 0:
        day_move = (
            q.price / q.open - 1
        ) * 100

        if (
            -1
            <= day_move
            <= 5
        ):
            score += 6
            why.append(
                "세션 가격 안정"
            )

    if (
        0
        < q.per
        <= 40
    ):
        score += 8
        why.append(
            "미장 PER 범위"
        )

    if (
        0
        < q.pbr
        <= 5
    ):
        score += 4
        why.append(
            "미장 PBR 범위"
        )

    return (
        max(
            0,
            min(
                100,
                round(score, 1),
            ),
        ),
        why,
    )


def candidate(
    q,
    market: str,
    smart=False,
    secmap=None,
):
    sector = (
        q.sector
        or (
            SECTOR_FALLBACK.get(
                q.code,
                "기타",
            )
            if market == "KR"
            else "미국주식"
        )
    )

    sector_score = (
        secmap.get(
            sector,
            0,
        )
        if secmap
        else 0
    )

    if market == "US":
        (
            score,
            why,
        ) = (
            us_smart_score(q)
            if smart
            else us_scalp_score(
                q,
                sector_score,
            )
        )

    else:
        (
            score,
            why,
        ) = (
            smart_score(q)
            if smart
            else scalp_score(
                q,
                sector_score,
            )
        )

    vi_pre = (
        q.open
        * 1.10
        * 0.997
        if (
            market == "KR"
            and q.open
        )
        else None
    )

    return {
        "market":
            market,

        "code":
            q.code,

        "name":
            q.name or q.code,

        "sector":
            sector,

        "currency":
            (
                "KRW"
                if market == "KR"
                else "USD"
            ),

        "price":
            (
                krw(q.price)
                if market == "KR"
                else round(
                    float(q.price),
                    4,
                )
            ),

        "open":
            (
                krw(q.open)
                if market == "KR"
                else round(
                    float(q.open),
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
                if market == "KR"
                else None
            ),

        "institution_net":
            (
                q.institution_net
                if market == "KR"
                else None
            ),

        "vi_pre":
            (
                krw(vi_pre)
                if vi_pre
                else None
            ),

        "reasons":
            why,

        "series":
            [
                (
                    krw(x)
                    if market == "KR"
                    else round(
                        float(x),
                        4,
                    )
                )
                for x
                in list(
                    q.prices
                )[-60:]
            ],
    }


def rebuild_cache(market: str):
    market = normalize_market(
        market
    )

    sectors = build_sectors(
        market
    )

    secmap = {
        x["sector"]:
            x["score"]
        for x
        in sectors
    }

    quotes = [
        q
        for q
        in feed
        .quotes_for(
            market
        )
        .values()
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

        except Exception as exc:
            print(
                "CANDIDATE ERROR:",
                market,
                q.code,
                exc,
                flush=True,
            )

    scalp.sort(
        key=lambda x:
            x["score"],
        reverse=True,
    )

    smart.sort(
        key=lambda x:
            x["score"],
        reverse=True,
    )

    with cache_lock:
        CACHE[
            market
        ] = {
            "sectors":
                sectors,

            "scalp":
                scalp[:50],

            "smart":
                smart[:50],

            "updated_at":
                time.time(),
        }

    return scalp


def trade_market(
    market: str,
    candidates,
):
    day_key = trading_day_key(
        market
    )

    paper.ensure_budget_day(
        day_key
    )

    fx = (
        feed.usdkrw
        if market == "US"
        else 1.0
    )

    if (
        market == "US"
        and (
            not feed.usdkrw_tradeable
            or fx <= 0
        )
    ):
        return

    quotes = (
        feed.quotes_for(
            market
        )
    )

    score_map = {
        x["code"]:
            x["score"]
        for x
        in candidates
    }

    for p in list(
        paper.market_positions(
            market
        )
    ):
        q = quotes.get(
            p.code
        )

        if (
            not q
            or q.price <= 0
        ):
            continue

        paper.mark(
            market,
            p.code,
            q.price,
            fx,
        )

        score = score_map.get(
            p.code,
            50,
        )

        if (
            p.pnl_pct >= 2.5
            or p.pnl_pct <= -1.5
            or score < 46
        ):
            paper.sell(
                market,
                p.code,
                q.price,
                fx,
            )

    threshold = (
        buy_score_threshold(
            market
        )
    )

    for item in candidates:
        if (
            len(
                paper.market_positions(
                    market
                )
            ) >= 3
            or item["score"]
            < threshold
        ):
            break

        code = item["code"]

        if (
            market == "KR"
            and code in protected
        ):
            continue

        if (
            f"{market}:{code}"
            in paper.positions
        ):
            continue

        if (
            market == "KR"
            and item.get(
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

        unit_krw = (
            q.price
            * (
                fx
                if market == "US"
                else 1.0
            )
        )

        budget = (
            paper
            .effective_budget_krw(
                day_key
            )
        )

        remain = min(
            paper.cash_krw,
            (
                budget
                - paper.held_cost_krw()
            ),
        )

        if remain < unit_krw:
            continue

        target = min(
            remain,
            max(
                unit_krw,
                budget / 2,
            ),
        )

        qty = int(
            target
            // unit_krw
        )

        if qty >= 1:
            paper.buy(
                q,
                qty,
                market,
                fx,
                day_key,
            )


def ai_loop():
    while True:
        try:
            kr_candidates = (
                rebuild_cache(
                    "KR"
                )
            )

            us_candidates = (
                rebuild_cache(
                    "US"
                )
            )

            active = (
                trading_window()
            )

            if active == "KR":
                trade_market(
                    "KR",
                    kr_candidates,
                )

            elif active == "US":
                trade_market(
                    "US",
                    us_candidates,
                )

        except Exception as exc:
            print(
                "AI LOOP ERROR:",
                exc,
                flush=True,
            )

        time.sleep(5)


def nh_feed_bootstrap():
    from nhplug.auth import get_token

    delay = 2

    while True:
        try:
            get_token()

            print(
                "NH AUTH READY - "
                "starting market feeds",
                flush=True,
            )

            feed.start()

            return

        except Exception as exc:
            print(
                "NH AUTH WAIT:",
                str(exc),
                flush=True,
            )

            time.sleep(delay)

            delay = min(
                delay * 2,
                60,
            )


def start_background():
    global started

    if started:
        return

    started = True

    if (
        os.getenv(
            "NHPLUG_APP_KEY"
        )
        and os.getenv(
            "NHPLUG_APP_SECRET"
        )
    ):
        threading.Thread(
            target=
                nh_feed_bootstrap,
            daemon=True,
        ).start()

    threading.Thread(
        target=ai_loop,
        daemon=True,
    ).start()


@asynccontextmanager
async def lifespan(_app):
    start_background()

    yield


app = FastAPI(
    title=
        "GY 모의투자 시스템",
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
    h = feed.health()

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
            h["nh_realtime"],

        "realtime":
            h["realtime"],

        "errors":
            h["errors"],

        "orders_sent":
            0,

        "kr_tracked":
            h["kr_tracked"],

        "kr_priced":
            h["kr_priced"],

        "us_tracked":
            h["us_tracked"],

        "us_priced":
            h["us_priced"],

        "us_warmup_done":
            h.get(
                "us_warmup_done",
                0,
            ),

        "us_warmup_total":
            h.get(
                "us_warmup_total",
                0,
            ),

        "us_warmup_errors":
            h.get(
                "us_warmup_errors",
                {},
            ),

        "market_updated_at":
            h["market_updated_at"],

        "market_errors":
            h["market_errors"],

        "usdkrw":
            h["usdkrw"],

        "usdkrw_asof":
            h["usdkrw_asof"],

        "usdkrw_tradeable":
            h.get(
                "usdkrw_tradeable",
                False,
            ),

        "usdkrw_source":
            h.get(
                "usdkrw_source",
                "",
            ),

        "buy_score_threshold":
            {
                "KR":
                    buy_score_threshold(
                        "KR"
                    ),
                "US":
                    buy_score_threshold(
                        "US"
                    ),
            },

        "schedule":
            schedule_payload(),
    }


@app.get(
    "/api/health"
)
def health():
    return (
        health_payload()
    )


class BudgetRequest(
    BaseModel
):
    amount: Optional[
        int
    ] = None

    auto_max_if_unset: bool = True


@app.post(
    "/api/budget"
)
def set_budget(
    data: BudgetRequest,
):
    active = (
        trading_window()
        or default_view_market()
    )

    day_key = (
        trading_day_key(
            active
        )
    )

    paper.set_auto_max(
        data.auto_max_if_unset
    )

    paper.set_budget(
        data.amount,
        day_key,
    )

    effective = (
        paper
        .effective_budget_krw(
            day_key
        )
    )

    return {
        "ok":
            True,

        "budget_day":
            paper.budget_day,

        "explicit_budget":
            paper.explicit_budget_krw,

        "auto_max_if_unset":
            paper.auto_max_if_unset,

        "effective_budget":
            effective,

        "initial_cash":
            paper.initial_cash_krw,
    }


def paper_state(
    market: str,
):
    active_for_budget = (
        trading_window()
        or default_view_market()
    )

    day_key = (
        trading_day_key(
            active_for_budget
        )
    )

    effective_budget = (
        paper
        .effective_budget_krw(
            day_key
        )
    )

    positions = []

    for p in (
        paper.market_positions(
            market
        )
    ):
        positions.append(
            {
                "market":
                    p.market,

                "code":
                    p.code,

                "name":
                    p.name,

                "qty":
                    p.qty,

                "avg_price":
                    p.avg_price,

                "current_price":
                    p.current_price,

                "currency":
                    (
                        "USD"
                        if p.market == "US"
                        else "KRW"
                    ),

                "fx_buy":
                    (
                        p.fx_buy
                        if p.market == "US"
                        else None
                    ),

                "fx_current":
                    (
                        p.fx_current
                        if p.market == "US"
                        else None
                    ),

                "cost_krw":
                    krw(
                        p.cost_krw
                    ),

                "value_krw":
                    krw(
                        p.value_krw
                    ),

                "pnl":
                    krw(
                        p.pnl_krw
                    ),

                "pnl_pct":
                    p.pnl_pct,
            }
        )

    trades = [
        t
        for t
        in paper.trades
        if t.get(
            "market"
        ) == market
    ][:100]

    return {
        "initial_cash":
            paper.initial_cash_krw,

        "cash":
            krw(
                paper.cash_krw
            ),

        "equity":
            krw(
                paper.equity_krw()
            ),

        "budget_day":
            paper.budget_day,

        "explicit_budget":
            paper.explicit_budget_krw,

        "budget":
            effective_budget,

        "effective_budget":
            effective_budget,

        "auto_max_if_unset":
            paper.auto_max_if_unset,

        "held_cost":
            krw(
                paper.held_cost_krw()
            ),

        "market_held_cost":
            krw(
                paper.held_cost_krw(
                    market
                )
            ),

        "positions":
            positions,

        "trades":
            trades,

        "auto_trade_enabled":
            (
                trading_window()
                == market
            ),

        "usdkrw":
            feed.usdkrw,

        "usdkrw_asof":
            feed.usdkrw_asof,

        "usdkrw_tradeable":
            feed.usdkrw_tradeable,
    }


def market_separation_check(
    market: str,
    scalp,
    smart,
    positions,
):
    codes = [
        str(
            x.get(
                "code",
                "",
            )
        )
        for x
        in (
            scalp
            + smart
            + positions
        )
    ]

    if market == "US":
        bad = [
            c
            for c
            in codes
            if re.fullmatch(
                r"\d{6}",
                c,
            )
        ]

    else:
        bad = [
            c
            for c
            in codes
            if (
                c
                and not
                re.fullmatch(
                    r"\d{6}",
                    c,
                )
            )
        ]

    return {
        "ok":
            not bad,

        "market":
            market,

        "bad_codes":
            sorted(
                set(
                    bad
                )
            ),
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
        c = CACHE[
            market
        ]

        sectors = list(
            c["sectors"]
        )

        scalp = list(
            c["scalp"][
                :30
            ]
        )

        smart = list(
            c["smart"][
                :30
            ]
        )

        updated_at = (
            c["updated_at"]
        )

    pstate = (
        paper_state(
            market
        )
    )

    separation = (
        market_separation_check(
            market,
            scalp,
            smart,
            pstate[
                "positions"
            ],
        )
    )

    return {
        "mode":
            market,

        "health":
            health_payload(),

        "schedule":
            schedule_payload(),

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
            pstate,

        "protected_codes":
            (
                sorted(
                    protected
                )
                if market == "KR"
                else []
            ),

        "market_separation":
            separation,
    }


@app.get(
    "/api/market-check"
)
def market_check():
    out = {}

    for market in MARKETS:
        with cache_lock:
            c = CACHE[
                market
            ]

            scalp = list(
                c["scalp"][
                    :30
                ]
            )

            smart = list(
                c["smart"][
                    :30
                ]
            )

        positions = (
            paper_state(
                market
            )[
                "positions"
            ]
        )

        out[
            market
        ] = (
            market_separation_check(
                market,
                scalp,
                smart,
                positions,
            )
        )

    kr_labels = [
        x["label"]
        for x in feed.market_state(
            "KR"
        )
    ]

    us_labels = [
        x["label"]
        for x in feed.market_state(
            "US"
        )
    ]

    checks = {
        "market_separation":
            (
                out["KR"]["ok"]
                and out["US"]["ok"]
            ),

        "kr_index_order":
            kr_labels
            == [
                "코스피",
                "코스닥",
                "코스피 야간선물",
                "나스닥 선물",
                "필라델피아 반도체지수",
            ],

        "us_index_order":
            us_labels
            == [
                "S&P500",
                "나스닥",
                "나스닥 선물",
                "필라델피아 반도체지수",
            ],

        "nxt_not_index":
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

        "markets":
            out,

        "orders_sent":
            0,
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
