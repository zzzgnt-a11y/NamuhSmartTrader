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

    return max(
        minimum,
        min(maximum, value),
    )


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
        and last >= ma5 >= ma
