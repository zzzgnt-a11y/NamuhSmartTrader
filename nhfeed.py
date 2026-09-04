from __future__ import annotations

import html as html_lib
import os
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, Iterable

import requests

from engine import Quote

KST = timezone(timedelta(hours=9))

KR_DEFAULT_CODES = [
    "005930", "000660", "035420", "035720", "068270", "012450", "267260",
    "042700", "005380", "000270", "105560", "055550", "086790", "028260",
    "207940",
]

US_DEFAULT_CODES = [
    "AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "TSLA", "AVGO", "AMD",
    "NFLX", "COST", "PLTR", "JPM", "BAC", "WMT", "LLY", "UNH", "XOM", "CVX",
    "ORCL", "CRM", "ADBE", "QCOM", "MU", "INTC", "ARM", "TSM",
]


def walk(value):
    if isinstance(value, dict):
        yield value

        for child in value.values():
            yield from walk(child)

    elif isinstance(value, list):
        for child in value:
            yield from walk(child)


def num(value):
    try:
        return float(
            str(value)
            .replace(",", "")
            .replace("+", "")
            .strip()
        )

    except Exception:
        return 0.0


def pick(
    data,
    keys: Iterable[str],
):
    for obj in walk(data):
        for key in keys:
            if (
                key in obj
                and obj[key] not in (
                    None,
                    "",
                )
            ):
                return num(
                    obj[key]
                )

    return 0.0


def pick_text(
    data,
    keys: Iterable[str],
):
    for obj in walk(data):
        for key in keys:
            value = obj.get(
                key
            )

            if value not in (
                None,
                "",
            ):
                return str(
                    value
                ).strip()

    return ""


def first_list(
    data,
    keys: Iterable[str],
):
    for obj in walk(data):
        for key in keys:
            value = obj.get(
                key
            )

            if isinstance(
                value,
                list,
            ):
                return value

    return []


def signed_value(
    value,
    sign,
):
    value = abs(
        num(value)
    )

    if str(sign) in (
        "4",
        "5",
        "8",
        "9",
        "-",
        "▼",
    ):
        return -value

    return value


def dataframe_rows(
    frame,
):
    if frame is None:
        return []

    if hasattr(
        frame,
        "to_dict",
    ):
        try:
            return frame.to_dict(
                "records"
            )

        except TypeError:
            pass

    if isinstance(
        frame,
        list,
    ):
        return frame

    return []


class NHFeed:
    def __init__(
        self,
    ):
        self.quotes: Dict[
            str,
            Dict[
                str,
                Quote,
            ],
        ] = {
            "KR": {},
            "US": {},
        }

        self.connected = {
            "KR": False,
            "US": False,
        }

        self.errors = {
            "KR": "",
            "US": "",
        }

        self.scan_index = {
            "KR": 0,
            "US": 0,
        }

        self.code_lists = {
            "KR": [],
            "US": [],
        }

        self.fixed = {
            "KR":
                self._env_codes(
                    "TRACKED_CODES",
                    KR_DEFAULT_CODES,
                ),

            "US":
                self._env_codes(
                    "US_TRACKED_CODES",
                    US_DEFAULT_CODES,
                ),
        }

        self.market = {}

        self.market_errors = {}

        self.market_updated_at = (
            0.0
        )

        # 미국 PAPER 매매용 환율.
        # NHPLUG 해외주식 현재가 응답의
        # currency_prc + trade_date만 사용.
        self._usdkrw = (
            0.0
        )

        self.usdkrw_asof = (
            ""
        )

        self.usdkrw_source = (
            ""
        )

        self.index_symbols = {
            "sp500":
                os.getenv(
                    "NH_SP500_SYMBOL",
                    "",
                ).strip(),

            "nasdaq":
                os.getenv(
                    "NH_NASDAQ_SYMBOL",
                    "",
                ).strip(),

            "sox":
                os.getenv(
                    "NH_SOX_SYMBOL",
                    "",
                ).strip(),

            "usdkrw":
                os.getenv(
                    "NH_USDKRW_SYMBOL",
                    "",
                ).strip(),
        }

        self.future_symbols = {
            "kospi_night":
                os.getenv(
                    "NH_KOSPI_NIGHT_SYMBOL",
                    "",
                ).strip(),

            "nasdaq_future":
                os.getenv(
                    "NH_NASDAQ_FUTURE_SYMBOL",
                    "",
                ).strip(),

            "nasdaq_future_exnm":
                (
                    os.getenv(
                        "NH_NASDAQ_FUTURE_EXNM",
                        "FCME",
                    ).strip()
                    or "FCME"
                ),
        }

        self.nxt = {
            "session":
                "CLOSED",

            "label":
                "NXT 장외시간",

            "open":
                False,

            "updated_at":
                0.0,
        }

        self.krx_series = {
            "kospi": [],
            "kosdaq": [],
        }

        self._stop = (
            threading.Event()
        )

    @staticmethod
    def _env_codes(
        key,
        defaults,
    ):
        configured = [
            x.strip().upper()

            for x in os.getenv(
                key,
                "",
            ).split(",")

            if x.strip()
        ]

        return (
            configured
            or list(defaults)
        )

    def quotes_for(
        self,
        market: str,
    ):
        return self.quotes[
            "US"
            if str(
                market
            ).upper() == "US"
            else "KR"
        ]

    def connected_any(
        self,
    ):
        return any(
            self.connected.values()
        )

    def q(
        self,
        market: str,
        code: str,
    ):
        market = (
            "US"
            if str(
                market
            ).upper() == "US"
            else "KR"
        )

        code = (
            str(code)
            .strip()
            .upper()
        )

        bucket = (
            self.quotes[
                market
            ]
        )

        if code not in bucket:
            bucket[
                code
            ] = Quote(
                code,
                code,
            )

        return bucket[
            code
        ]

    # ==============================
    # NXT 상태
    # ==============================

    def update_nxt_session(
        self,
    ):
        now = datetime.now(
            KST
        )

        if now.weekday() >= 5:
            (
                session,
                label,
                opened,
            ) = (
                "CLOSED",
                "NXT 휴장",
                False,
            )

        else:
            mins = (
                now.hour
                * 60
                + now.minute
                + now.second
                / 60
            )

            if (
                480
                <= mins
                < 530
            ):
                (
                    session,
                    label,
                    opened,
                ) = (
                    "PRE",
                    "NXT 프리마켓",
                    True,
                )

            elif (
                530
                <= mins
                < 540.5
            ):
                (
                    session,
                    label,
                    opened,
                ) = (
                    "BREAK",
                    "NXT 메인마켓 대기",
                    False,
                )

            elif (
                540.5
                <= mins
                < 920
            ):
                (
                    session,
                    label,
                    opened,
                ) = (
                    "MAIN",
                    "NXT 메인마켓",
                    True,
                )

            elif (
                920
                <= mins
                < 940
            ):
                (
                    session,
                    label,
                    opened,
                ) = (
                    "AFTER_WAIT",
                    "NXT 애프터마켓 대기",
                    False,
                )

            elif (
                940
                <= mins
                < 1200
           
