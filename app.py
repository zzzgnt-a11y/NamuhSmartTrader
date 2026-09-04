from __future__ import annotations

import os
import threading
import time

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from engine import PaperAccount, scalp_score, smart_score
from nhfeed import NHFeed

load_dotenv()
app = FastAPI(title="GY 모의투자 시스템")
app.mount("/static", StaticFiles(directory="static"), name="static")
feed = NHFeed()
paper = PaperAccount()
protected = {x.strip() for x in os.getenv("PROTECTED_CODES", "").split(",") if x.strip()}
started = False

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

cache_lock = threading.Lock()
CACHE = {"sectors": [], "scalp": [], "smart": [], "updated_at": 0}


def krw(v):
    return int(round(float(v or 0)))


def build_sectors():
    agg = {}
    for q in list(feed.quotes.values()):
        if q.price <= 0 or q.open <= 0:
            continue
        sector = q.sector or SECTOR_FALLBACK.get(q.code, "기타")
        a = agg.setdefault(
            sector,
            {
                "sector": sector,
                "sum": 0,
                "n": 0,
                "money": 0,
                "leader": "",
                "best": -999,
            },
        )
        change = (q.price / q.open - 1) * 100
        a["sum"] += change
        a["n"] += 1
        a["money"] += q.price * q.volume
        if change > a["best"]:
            a["best"] = change
            a["leader"] = q.name

    out = []

    for a in agg.values():
        if not a["n"]:
            continue

        avg = a["sum"] / a["n"]

        score = max(
            0,
            min(
                15,
                avg * 2 + (2 if a["money"] > 0 else 0),
            ),
        )

        out.append(
            {
                "sector": a["sector"],
                "change_pct": avg,
                "leader": a["leader"],
                "score": score,
            }
        )

    return sorted(
        out,
        key=lambda x: x["score"],
        reverse=True,
    )[:8]


def candidate(q, smart=False, secmap=None):
    sector = q.sector or SECTOR_FALLBACK.get(q.code, "기타")

    if smart:
        score, why = smart_score(q)
    else:
        score, why = scalp_score(
            q,
            secmap.get(sector, 0) if secmap else 0,
        )

    return {
        "code": q.code,
        "name": q.name,
        "price": krw(q.price),
        "open": krw(q.open),
        "score": score,
        "execution_strength": q.execution_strength,
        "per": q.per,
        "pbr": q.pbr,
        "foreign_net": q.foreign_net,
        "institution_net": q.institution_net,
        "vi_pre": krw(q.open * 1.10 * 0.997) if q.open else 0,
        "reasons": why,
        "series": [krw(x) for x in list(q.prices)[-60:]],
    }


def rebuild_cache():
    sectors = build_sectors()

    secmap = {
        x["sector"]: x["score"]
        for x in sectors
    }

    quotes = [
        q
        for q in list(feed.quotes.values())
        if q.price > 0
    ]

    scalp = []
    smart = []

    for q in quotes:
        try:
            scalp.append(
                candidate(
                    q,
                    False,
                    secmap,
                )
            )

            smart.append(
                candidate(
                    q,
                    True,
                )
            )

        except Exception:
            continue

    scalp.sort(
        key=lambda x: x["score"],
        reverse=True,
    )

    smart.sort(
        key=lambda x: x["score"],
        reverse=True,
    )

    with cache_lock:
        CACHE["sectors"] = sectors
        CACHE["scalp"] = scalp[:50]
        CACHE["smart"] = smart[:50]
        CACHE["updated_at"] = time.time()

    return scalp


def trade_from_candidates(xs):
    score_map = {
        x["code"]: x["score"]
        for x in xs
    }

    for p in list(paper.positions.values()):
        q = feed.quotes.get(p.code)

        if not q or q.price <= 0:
            continue

        paper.mark(
            p.code,
            q.price,
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
                p.code,
                q.price,
            )

    for x in xs:
        if len(paper.positions) >= 3:
            break

        if x["score"] < 72:
            break

        code = x["code"]

        if code in protected:
            continue

        if code in paper.positions:
            continue

        if x["vi_pre"] and x["price"] >= x["vi_pre"]:
            continue

        q = feed.quotes.get(code)

        if not q or q.price <= 0:
            continue

        remain = min(
            paper.cash,
            paper.daily_budget - paper.held_cost(),
        )

        if remain < q.price:
            continue

        target = min(
            remain,
            max(
                q.price,
                paper.daily_budget / 2,
            ),
        )

        qty = int(
            target // q.price
        )

        if qty >= 1:
            paper.buy(
                q,
                qty,
            )


def ai_loop():
    while True:
        try:
            trade_from_candidates(
                rebuild_cache()
            )

        except Exception as e:
            print(
                "AI LOOP ERROR:",
                e,
            )

        time.sleep(5)


@app.on_event("startup")
def startup():
    global started

    if started:
        return

    started = True

    if (
        os.getenv("NHPLUG_APP_KEY")
        and os.getenv("NHPLUG_APP_SECRET")
    ):
        feed.start()

    threading.Thread(
        target=ai_loop,
        daemon=True,
    ).start()


@app.get("/")
def home():
    return FileResponse(
        "static/index.html"
    )


@app.get("/api/health")
def health():
    return {
        "ok": True,

        "nh_configured": bool(
            os.getenv("NHPLUG_APP_KEY")
            and os.getenv("NHPLUG_APP_SECRET")
        ),

        "nh_realtime": feed.connected,

        "error": feed.error,

        "orders_sent": 0,

        "scan_index": feed.scan_index,

        "tracked": len(feed.quotes),

        "priced": sum(
            1
            for q in feed.quotes.values()
            if q.price > 0
        ),

        "sample_prices": [
            {
                "code": q.code,
                "name": q.name,
                "price": krw(q.price),
            }
            for q in list(feed.quotes.values())
            if q.price > 0
        ][:5],

        "market_updated_at":
            feed.market_updated_at,

        "market_errors":
            feed.market_errors,
    }


class Budget(BaseModel):
    amount: int


@app.post("/api/budget")
def set_budget(x: Budget):
    amount = max(
        0,
        min(
            int(x.amount),
            paper.initial_cash,
        ),
    )

    paper.set_budget(
        amount
    )

    return {
        "ok": True,
        "budget": paper.daily_budget,
        "initial_cash": paper.initial_cash,
    }


@app.get("/api/state")
def state():
    with cache_lock:
        sectors = list(
            CACHE["sectors"]
        )

        scalp = list(
            CACHE["scalp"][:30]
        )

        smart = list(
            CACHE["smart"][:30]
        )

        updated_at = (
            CACHE["updated_at"]
        )

    positions = [
        {
            "code": p.code,
            "name": p.name,
            "qty": p.qty,
            "avg_price": krw(p.avg_price),
            "current_price": krw(p.current_price),
            "pnl": krw(p.pnl),
            "pnl_pct": p.pnl_pct,
        }
        for p in paper.positions.values()
    ]

    return {
        "health": health(),

        "market":
            feed.market_state(),

        "sectors":
            sectors,

        "scalp":
            scalp,

        "smart":
            smart,

        "cache_updated_at":
            updated_at,

        "paper": {
            "initial_cash":
                krw(paper.initial_cash),

            "cash":
                krw(paper.cash),

            "equity":
                krw(paper.equity()),

            "budget":
                krw(paper.daily_budget),

            "held_cost":
                krw(paper.held_cost()),

            "positions":
                positions,

            "trades":
                paper.trades[:100],
        },

        "protected_codes":
            sorted(protected),
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
