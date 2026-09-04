from __future__ import annotations

import os
import re
import threading
import time

from datetime import (
    datetime,
    timedelta,
    timezone,
)

from typing import (
    Dict,
    Iterable,
)

import requests

from engine import Quote


KST = timezone(
    timedelta(
        hours=9
    )
)


KR_DEFAULT_CODES = [
    "005930",
    "000660",
    "035420",
    "035720",
    "068270",
    "012450",
    "267260",
    "042700",
    "005380",
    "000270",
    "105560",
    "055550",
    "086790",
    "028260",
    "207940",
]


US_DEFAULT_CODES = [
    "AAPL",
    "MSFT",
    "NVDA",
    "AMZN",
    "META",
    "GOOGL",
    "TSLA",
    "AVGO",
    "AMD",
    "NFLX",
    "COST",
    "PLTR",
    "JPM",
    "BAC",
    "WMT",
    "LLY",
    "UNH",
    "XOM",
    "CVX",
    "ORCL",
    "CRM",
    "ADBE",
    "QCOM",
    "MU",
    "INTC",
    "ARM",
    "TSM",
]


def walk(
    value
):
    if isinstance(
        value,
        dict,
    ):
        yield value

        for child in (
            value.values()
        ):
            yield from walk(
                child
            )

    elif isinstance(
        value,
        list,
    ):
        for child in value:
            yield from walk(
                child
            )


def num(
    value
):
    try:
        return float(
            str(
                value
            )
            .replace(
                ",",
                "",
            )
            .replace(
                "+",
                "",
            )
            .strip()
        )

    except Exception:
        return 0.0


def pick(
    data,
    keys: Iterable[str],
):
    for obj in walk(
        data
    ):
        for key in keys:

            if (
                key in obj
                and obj[
                    key
                ]
                not in (
                    None,
                    "",
                )
            ):
                return num(
                    obj[
                        key
                    ]
                )

    return 0.0


def pick_text(
    data,
    keys: Iterable[str],
):
    for obj in walk(
        data
    ):
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
    for obj in walk(
        data
    ):
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
        num(
            value
        )
    )

    if str(
        sign
    ) in (
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
    frame
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
        self
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

        self.usdkrw = (
            0.0
        )

        self.usdkrw_asof = ""

        self.index_symbols = {
            "sp500":
                os.getenv(
                    "NH_SP500_SYMBOL",
                    "N@SPX",
                ).strip()
                or "N@SPX",

            "nasdaq":
                os.getenv(
                    "NH_NASDAQ_SYMBOL",
                    "N@IXIC",
                ).strip()
                or "N@IXIC",

            "sox":
                os.getenv(
                    "NH_SOX_SYMBOL",
                    "N@SOX",
                ).strip()
                or "N@SOX",

            "usdkrw":
                os.getenv(
                    "NH_USDKRW_SYMBOL",
                    "X@KRW",
                ).strip()
                or "X@KRW",
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
                os.getenv(
                    "NH_NASDAQ_FUTURE_EXNM",
                    "FCME",
                ).strip()
                or "FCME",
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

            for x
            in os.getenv(
                key,
                "",
            ).split(
                ","
            )

            if x.strip()
        ]

        return (
            configured
            or list(
                defaults
            )
        )

    def quotes_for(
        self,
        market: str,
    ):
        return self.quotes[
            "US"
            if str(
                market
            ).upper()
            == "US"
            else "KR"
        ]

    def connected_any(
        self
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
            ).upper()
            == "US"
            else "KR"
        )

        code = (
            str(
                code
            )
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

    def update_nxt_session(
        self
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
            ):
                (
                    session,
                    label,
                    opened,
                ) = (
                    "AFTER",
                    "NXT 애프터마켓",
                    True,
                )

            else:
                (
                    session,
                    label,
                    opened,
                ) = (
                    "CLOSED",
                    "NXT 장외시간",
                    False,
                )

        self.nxt = {
            "session":
                session,

            "label":
                label,

            "open":
                opened,

            "updated_at":
                time.time(),
        }

    def session_state(
        self,
        market: str,
    ):
        if (
            str(
                market
            ).upper()
            == "US"
        ):
            return None

        self.update_nxt_session()

        return {
            "name":
                "NXT",

            "session":
                self.nxt[
                    "session"
                ],

            "label":
                self.nxt[
                    "label"
                ],

            "open":
                self.nxt[
                    "open"
                ],

            "status":
                (
                    "거래중"
                    if self.nxt[
                        "open"
                    ]
                    else "대기/종료"
                ),

            "updated_at":
                self.nxt[
                    "updated_at"
                ],
        }

    def _apply_kr(
        self,
        code,
        data,
    ):
        q = self.q(
            "KR",
            code,
        )

        price = pick(
            data,
            (
                "stck_prpr",
                "prpr",
                "price",
                "cur_pr",
                "now_pr",
            ),
        )

        volume = pick(
            data,
            (
                "acml_vol",
                "volume",
                "vol",
            ),
        )

        if price:

            q.mark(
                round(
                    price
                ),
                volume,
            )

        q.open = round(
            pick(
                data,
                (
                    "stck_oprc",
                    "open",
                ),
            )
            or q.open
        )

        q.high = round(
            pick(
                data,
                (
                    "stck_hgpr",
                    "high",
                ),
            )
            or q.high
        )

        q.low = round(
            pick(
                data,
                (
                    "stck_lwpr",
                    "low",
                ),
            )
            or q.low
        )

        q.per = (
            pick(
                data,
                (
                    "per",
                    "per_val",
                ),
            )
            or q.per
        )

        q.pbr = (
            pick(
                data,
                (
                    "pbr",
                    "pbr_val",
                ),
            )
            or q.pbr
        )

        q.foreign_net = (
            pick(
                data,
                (
                    "frgn_ntby_qty",
                    "invest",
                ),
            )
            or q.foreign_net
        )

        q.institution_net = (
            pick(
                data,
                (
                    "gigwan",
                    "orgn_ntby_qty",
                ),
            )
            or q.institution_net
        )

        strength = pick(
            data,
            (
                "cttr",
                "volpower",
                "execution_strength",
            ),
        )

        if strength:
            q.execution_strength = (
                strength
            )

    def _apply_us(
        self,
        code,
        data,
    ):
        q = self.q(
            "US",
            code,
        )

        price = pick(
            data,
            (
                "ovrs_prpr",
                "last",
                "prc",
                "price",
                "close",
            ),
        )

        volume = pick(
            data,
            (
                "acml_vol",
                "tvol",
                "volume",
                "vol",
            ),
        )

        if price:

            q.mark(
                price,
                volume,
            )

        q.open = (
            pick(
                data,
                (
                    "ovrs_oprc",
                    "open_prc",
                    "open",
                ),
            )
            or q.open
        )

        q.high = (
            pick(
                data,
                (
                    "ovrs_hgpr",
                    "high_prc",
                    "high",
                ),
            )
            or q.high
        )

        q.low = (
            pick(
                data,
                (
                    "ovrs_lwpr",
                    "low_prc",
                    "low",
                ),
            )
            or q.low
        )

        q.per = (
            pick(
                data,
                (
                    "per",
                    "per_val",
                ),
            )
            or q.per
        )

        q.pbr = (
            pick(
                data,
                (
                    "pbr",
                    "pbr_val",
                ),
            )
            or q.pbr
        )

    def _load_kr_master(
        self
    ):
        try:
            from nhplug.instruments import (
                load_master,
            )

            rows = dataframe_rows(
                load_master(
                    "m_new_stock"
                )
            )

            wanted = set(
                self.fixed[
                    "KR"
                ]
            )

            for row in rows:

                code = str(
                    row.get(
                        "shrn_iscd"
                    )
                    or row.get(
                        "sCode"
                    )
                    or row.get(
                        "code"
                    )
                    or ""
                ).strip()

                match = re.search(
                    r"(\d{6})",
                    code,
                )

                if not match:
                    continue

                code = match.group(
                    1
                )

                if code not in wanted:
                    continue

                q = self.q(
                    "KR",
                    code,
                )

                q.name = str(
                    row.get(
                        "hts_kor_isnm"
                    )
                    or row.get(
                        "name"
                    )
                    or row.get(
                        "sKorName"
                    )
                    or code
                ).lstrip(
                    "*#"
                ).strip()

                q.sector = str(
                    row.get(
                        "bstp_medm_div_code"
                    )
                    or row.get(
                        "industry_group"
                    )
                    or ""
                ).strip()

            self.code_lists[
                "KR"
            ] = self.fixed[
                "KR"
            ][:]

        except Exception as exc:

            self.errors[
                "KR"
            ] = (
                "국내 종목마스터: "
                f"{exc}"
            )[:300]

            self.code_lists[
                "KR"
            ] = self.fixed[
                "KR"
            ][:]

    def _load_us_master(
        self
    ):
        try:
            from nhplug.instruments import (
                load_master,
            )

            rows = dataframe_rows(
                load_master(
                    "m_gtsstock"
                )
            )

            wanted = set(
                self.fixed[
                    "US"
                ]
            )

            for row in rows:

                symbol = str(
                    row.get(
                        "symbol"
                    )
                    or row.get(
                        "sSymbol"
                    )
                    or ""
                ).strip().upper()

                if symbol not in wanted:
                    continue

                q = self.q(
                    "US",
                    symbol,
                )

                q.name = str(
                    row.get(
                        "kor_name"
                    )
                    or row.get(
                        "eng_name"
                    )
                    or row.get(
                        "sKorName"
                    )
                    or row.get(
                        "sEngName"
                    )
                    or symbol
                ).strip()

                industry = str(
                    row.get(
                        "industry_group"
                    )
                    or row.get(
                        "gIndustryReuter"
                    )
                    or ""
                ).strip()

                q.sector = (
                    f"업종 {industry}"
                    if industry
                    else "미국주식"
                )

            self.code_lists[
                "US"
            ] = self.fixed[
                "US"
            ][:]

        except Exception as exc:

            self.errors[
                "US"
            ] = (
                "해외 종목마스터: "
                f"{exc}"
            )[:300]

            self.code_lists[
                "US"
            ] = self.fixed[
                "US"
            ][:]

    def _discover_futures(
        self
    ):
        try:
            from nhplug.instruments import (
                load_master,
            )

            if not self.future_symbols[
                "kospi_night"
            ]:

                fallback = []

                for row in dataframe_rows(
                    load_master(
                        "m_future"
                    )
                ):

                    code = str(
                        row.get(
                            "code"
                        )
                        or row.get(
                            "sCode"
                        )
                        or ""
                    ).strip().upper()

                    name = str(
                        row.get(
                            "name"
                        )
                        or row.get(
                            "sName"
                        )
                        or ""
                    ).strip()

                    if code.startswith(
                        "KA"
                    ):
                        fallback.append(
                            code
                        )

                    normalized = re.sub(
                        r"\s+",
                        "",
                        name,
                    ).upper()

                    if (
                        code.startswith(
                            "KA"
                        )
                        and (
                            "KOSPI200"
                            in normalized
                            or "코스피200"
                            in name
                        )
                    ):
                        self.future_symbols[
                            "kospi_night"
                        ] = code

                        break

                if (
                    not self.future_symbols[
                        "kospi_night"
                    ]
                    and fallback
                ):
                    self.future_symbols[
                        "kospi_night"
                    ] = fallback[
                        0
                    ]

            if not self.future_symbols[
                "nasdaq_future"
            ]:

                candidates = []

                for row in dataframe_rows(
                    load_master(
                        "fucode_h"
                    )
                ):

                    symbol = str(
                        row.get(
                            "isym"
                        )
                        or row.get(
                            "InnerSymbol"
                        )
                        or row.get(
                            "symb"
                        )
                        or row.get(
                            "Symbol"
                        )
                        or ""
                    ).strip().upper()

                    name = str(
                        row.get(
                            "enam"
                        )
                        or row.get(
                            "EngName"
                        )
                        or ""
                    ).strip()

                    exnm = str(
                        row.get(
                            "exnm"
                        )
                        or row.get(
                            "ExchName"
                        )
                        or "FCME"
                    ).strip().upper()
                    or "FCME"

                    lead = str(
                        row.get(
                            "ledm"
                        )
                        or row.get(
                            "Leadmonth"
                        )
                        or ""
                    ).strip()

                    if (
                        "NASDAQ"
                        in name.upper()
                        and symbol
                    ):
                        candidates.append(
                            (
                                10
                                if lead == "1"
                                else 0,
                                symbol,
                                exnm,
                            )
                        )

                if candidates:

                    candidates.sort(
                        reverse=True
                    )

                    (
                        _,
                        symbol,
                        exnm,
                    ) = candidates[
                        0
                    ]

                    self.future_symbols[
                        "nasdaq_future"
                    ] = symbol

                    self.future_symbols[
                        "nasdaq_future_exnm"
                    ] = exnm

        except Exception as exc:

            self.market_errors[
                "future_master"
            ] = str(
                exc
            )[:300]

    def _market_order(
        self
    ):
        self.update_nxt_session()

        if self.nxt[
            "session"
        ] in (
            "PRE",
            "AFTER",
        ):
            return (
                "NXT",
                "KRX",
            )

        if (
            self.nxt[
                "session"
            ]
            == "MAIN"
        ):
            return (
                "KRX",
                "NXT",
            )

        return (
            "KRX",
        )

    def kr_scanner(
        self
    ):
        self._load_kr_master()

        codes = (
            self.code_lists[
                "KR"
            ]
            or self.fixed[
                "KR"
            ]
        )

        from nhplug import call

        while not self._stop.is_set():

            code = codes[
                self.scan_index[
                    "KR"
                ]
                % len(
                    codes
                )
            ]

            self.scan_index[
                "KR"
            ] = (
                self.scan_index[
                    "KR"
                ]
                + 1
            ) % len(
                codes
            )

            last_error = ""

            for market_cd in (
                self._market_order()
            ):
                try:
                    data = call(
                        "/krstock/quote/v1/currentPrice",
                        {
                            "iem_cd":
                                code,

                            "market_cd":
                                market_cd,
                        },
                    )

                    self._apply_kr(
                        code,
                        data,
                    )

                    if (
                        self.q(
                            "KR",
                            code,
                        ).price
                        > 0
                    ):
                        self.connected[
                            "KR"
                        ] = True

                        self.errors[
                            "KR"
                        ] = ""

                        break

                except Exception as exc:

                    last_error = (
                        f"{market_cd} "
                        f"{code}: "
                        f"{exc}"
                    )[:300]

                    if (
                        "429"
                        in last_error
                    ):
                        time.sleep(
                            1.5
                        )

                        break

            if (
                last_error
                and self.q(
                    "KR",
                    code,
                ).price
                <= 0
            ):
                self.errors[
                    "KR"
                ] = last_error

            time.sleep(
                0.35
            )

    def us_scanner(
        self
    ):
        self._load_us_master()

        codes = (
            self.code_lists[
                "US"
            ]
            or self.fixed[
                "US"
            ]
        )

        from nhplug import call

        while not self._stop.is_set():

            code = codes[
                self.scan_index[
                    "US"
                ]
                % len(
                    codes
                )
            ]

            self.scan_index[
                "US"
            ] = (
                self.scan_index[
                    "US"
                ]
                + 1
            ) % len(
                codes
            )

            try:

                data = call(
                    "/gbstock/quote/v1/current",
                    {
                        "iem_cd":
                            code
                    },
                )

                self._apply_us(
                    code,
                    data,
                )

                if (
                    self.q(
                        "US",
                        code,
                    ).price
                    > 0
                ):
                    self.connected[
                        "US"
                    ] = True

                    self.errors[
                        "US"
                    ] = ""

            except Exception as exc:

                self.errors[
                    "US"
                ] = (
                    f"{code}: "
                    f"{exc}"
                )[:300]

                if (
                    "429"
                    in self.errors[
                        "US"
                    ]
                ):
                    time.sleep(
                        1.5
                    )

            time.sleep(
                0.5
            )

    @staticmethod
    def _market_item(
        label,
        value,
        change,
        change_pct,
        status,
        source="",
        series=None,
        asof="",
    ):
        return {
            "label":
                label,

            "value":
                value,

            "change":
                change,

            "change_pct":
                change_pct,

            "status":
                status,

            "source":
                source,

            "series":
                list(
                    series
                    or []
                ),

            "asof":
                asof,
        }

    def _krx_rows(
        self,
        market_code,
        trade_date,
    ):
        payload = {
            "bld":
                (
                    "dbms/MDC/STAT/"
                    "standard/"
                    "MDCSTAT00101"
                ),

            "trdDd":
                trade_date,

            "idxIndMidclssCd":
                market_code,

            "share":
                "2",

            "money":
                "3",

            "csvxls_isNo":
                "false",
        }

        urls = [
            (
                "http://data.krx.co.kr/"
                "comm/bldAttendant/"
                "getJsonData.cmd"
            ),
            (
                "https://data.krx.co.kr/"
                "comm/bldAttendant/"
                "getJsonData.cmd"
            ),
        ]

        last = None

        for url in urls:

            try:

                r = requests.post(
                    url,
                    data=payload,
                    timeout=10,
                    headers={
                        "User-Agent":
                            "Mozilla/5.0"
                    },
                )

                r.raise_for_status()

                if (
                    not r.text.strip()
                    or r.text
                    .strip()
                    .upper()
                    == "LOGOUT"
                ):
                    raise RuntimeError(
                        "KRX empty/LOGOUT"
                    )

                data = r.json()

                rows = (
                    data.get(
                        "output"
                    )
                    or data.get(
                        "OutBlock_1"
                    )
                    or data.get(
                        "block1"
                    )
                    or []
                )

                if not isinstance(
                    rows,
                    list,
                ):
                    raise RuntimeError(
                        "KRX index response "
                        "has no row list"
                    )

                return rows

            except Exception as exc:

                last = exc

        raise RuntimeError(
            str(
                last
            )
        )

    @staticmethod
    def _find_index_row(
        rows,
        names,
    ):
        targets = {
            re.sub(
                r"\s+",
                "",
                x,
            ).upper()

            for x in names
        }

        for row in rows:

            name = str(
                row.get(
                    "IDX_NM"
                )
                or row.get(
                    "IDX_NM_KOR"
                )
                or row.get(
                    "idx_nm"
                )
                or ""
            )

            if (
                re.sub(
                    r"\s+",
                    "",
                    name,
                ).upper()
                in targets
            ):
                return row

        return None

    @staticmethod
    def _parse_krx_row(
        row
    ):
        value = num(
            row.get(
                "CLSPRC_IDX"
            )
            or row.get(
                "TDD_CLSPRC"
            )
            or row.get(
                "close"
            )
        )

        change = num(
            row.get(
                "CMPPREVDD_IDX"
            )
            or row.get(
                "CMPPREVDD_PRC"
            )
            or row.get(
                "change"
            )
        )

        change_pct = num(
            row.get(
                "FLUC_RT"
            )
            or row.get(
                "change_rate"
            )
        )

        sign = str(
            row.get(
                "FLUC_TP_CD"
            )
            or row.get(
                "fluc_tp_cd"
            )
            or ""
        )

        if sign in (
            "4",
            "5",
            "8",
            "9",
            "-",
            "▼",
        ):
            change = (
                -abs(
                    change
                )
            )

            change_pct = (
                -abs(
                    change_pct
                )
            )

        elif sign in (
            "1",
            "2",
            "6",
            "7",
            "+",
            "▲",
        ):
            change = (
                abs(
                    change
                )
            )

            change_pct = (
                abs(
                    change_pct
                )
            )

        return (
            value,
            change,
            change_pct,
        )

    def _read_krx_history(
        self
    ):
        today = datetime.now(
            KST
        ).date()

        history = {
            "kospi": [],
            "kosdaq": [],
        }

        latest = {
            "kospi": None,
            "kosdaq": None,
        }

        last_error = None

        for offset in range(
            18
        ):
            day = (
                today
                - timedelta(
                    days=offset
                )
            )

            if day.weekday() >= 5:
                continue

            trade_date = (
                day.strftime(
                    "%Y%m%d"
                )
            )

            try:

                kp_rows = (
                    self._krx_rows(
                        "02",
                        trade_date,
                    )
                )

                kq_rows = (
                    self._krx_rows(
                        "03",
                        trade_date,
                    )
                )

                kp = (
                    self._find_index_row(
                        kp_rows,
                        (
                            "코스피",
                            "KOSPI",
                        ),
                    )
                )

                kq = (
                    self._find_index_row(
                        kq_rows,
                        (
                            "코스닥",
                            "KOSDAQ",
                        ),
                    )
                )

                if (
                    not kp
                    or not kq
                ):
                    raise RuntimeError(
                        "KOSPI/KOSDAQ "
                        "representative row "
                        "not found"
                    )

                for (
                    key,
                    row,
                ) in (
                    (
                        "kospi",
                        kp,
                    ),
                    (
                        "kosdaq",
                        kq,
                    ),
                ):

                    (
                        value,
                        change,
                        change_pct,
                    ) = (
                        self._parse_krx_row(
                            row
                        )
                    )

                    if value <= 0:
                        continue

                    history[
                        key
                    ].append(
                        (
                            trade_date,
                            value,
                        )
                    )

                    if (
                        latest[
                            key
                        ]
                        is None
                    ):
                        latest[
                            key
                        ] = (
                            trade_date,
                            value,
                            change,
                            change_pct,
                        )

                if (
                    len(
                        history[
                            "kospi"
                        ]
                    ) >= 10
                    and len(
                        history[
                            "kosdaq"
                        ]
                    ) >= 10
                ):
                    break

            except Exception as exc:

                last_error = exc

            time.sleep(
                0.08
            )

        if (
            not latest[
                "kospi"
            ]
            or not latest[
                "kosdaq"
            ]
        ):
            raise RuntimeError(
                "KRX index load "
                f"failed: {last_error}"
            )

        out = {}

        for (
            key,
            label,
        ) in (
            (
                "kospi",
                "코스피",
            ),
            (
                "kosdaq",
                "코스닥",
            ),
        ):

            (
                asof,
                value,
                change,
                change_pct,
            ) = latest[
                key
            ]

            series = [
                v

                for _,
                v
                in reversed(
                    history[
                        key
                    ]
                )
            ]

            out[
                key
            ] = (
                self._market_item(
                    label,
                    value,
                    change,
                    change_pct,
                    (
                        "종가 기준 · "
                        f"{asof[:4]}-"
                        f"{asof[4:6]}-"
                        f"{asof[6:]}"
                    ),
                    "KRX 공식",
                    series,
                    asof,
                )
            )

        return out

    def _read_symbol_period(
        self,
        symbol,
        label,
        status="종가 기준",
    ):
        from nhplug import call

        today = datetime.now(
            KST
        ).strftime(
            "%Y%m%d"
        )

        data = call(
            "/gbstock/quote/v1/symbolIndexFxPeriod",
            {
                "iem_cd":
                    symbol,

                "end_dt":
                    today,

                "array_cnt":
                    "0012",

                "maxavg":
                    "005",

                "gubun":
                    "1",

                "xtick":
                    "001",

                "today_cls":
                    "0",

                "scale_change":
                    "0",
            },
        )

        value = pick(
            data,
            (
                "ovrs_prpr",
                "last",
                "close",
                "prpr",
            ),
        )

        sign = pick_text(
            data,
            (
                "prdy_vrss_sign",
                "sign",
            ),
        )

        change = (
            signed_value(
                pick(
                    data,
                    (
                        "prdy_vrss",
                        "change",
                    ),
                ),
                sign,
            )
        )

        change_pct = (
            signed_value(
                pick(
                    data,
                    (
                        "prdy_ctrt",
                        "change_rate",
                    ),
                ),
                sign,
            )
        )

        rows = first_list(
            data,
            (
                "Output_1",
                "output_1",
                "output1",
                "Output1",
            ),
        )

        series = []

        asof = ""

        for row in rows:

            v = num(
                row.get(
                    "ovrs_prpr"
                )
                or row.get(
                    "close"
                )
                or row.get(
                    "last"
                )
            )

            if v:
                series.append(
                    v
                )

            if not asof:

                raw_date = str(
                    row.get(
                        "xymd"
                    )
                    or row.get(
                        "date"
                    )
                    or row.get(
                        "bas_dt"
                    )
                    or row.get(
                        "stck_bsop_date"
                    )
                    or ""
                )

                if (
                    len(
                        raw_date
                    ) >= 8
                    and raw_date[
                        :8
                    ].isdigit()
                ):
                    asof = (
                        raw_date[
                            :8
                        ]
                    )

        if (
            not value
            and series
        ):
            value = (
                series[
                    0
                ]
            )

        if value <= 0:
            raise RuntimeError(
                f"{label} value "
                f"missing for {symbol}"
            )

        if not asof:
            asof = today

        return (
            self._market_item(
                label,
                value,
                change,
                change_pct,
                (
                    f"{status} · "
                    f"{asof[:4]}-"
                    f"{asof[4:6]}-"
                    f"{asof[6:]}"
                ),
                "NHPLUG",
                list(
                    reversed(
                        series
                    )
                ),
                asof,
            )
        )

    def _read_fx(
        self
    ):
        item = (
            self._read_symbol_period(
                self.index_symbols[
                    "usdkrw"
                ],
                "USD/KRW",
                "환율 기준",
            )
        )

        self.usdkrw = float(
            item[
                "value"
            ]
            or 0
        )

        self.usdkrw_asof = (
            item.get(
                "asof",
                "",
            )
        )

        return item

    def _read_kospi_night(
        self
    ):
        from nhplug import call

        symbol = (
            self.future_symbols.get(
                "kospi_night",
                "",
            )
        )

        if not symbol:
            raise RuntimeError(
                "코스피 야간선물 "
                "종목코드 자동탐색 실패"
            )

        data = call(
            "/krfuture/quote/v1/night",
            {
                "iem_cd":
                    symbol
            },
        )

        value = pick(
            data,
            (
                "prpr",
            ),
        )

        sign = pick_text(
            data,
            (
                "sign",
            ),
        )

        change = (
            signed_value(
                pick(
                    data,
                    (
                        "vrss",
                    ),
                ),
                sign,
            )
        )

        change_pct = (
            signed_value(
                pick(
                    data,
                    (
                        "ctrt",
                    ),
                ),
                sign,
            )
        )

        if value <= 0:
            raise RuntimeError(
                f"{symbol} "
                "야간선물 현재가 없음"
            )

        old = (
            self.market.get(
                "kospi_night",
                {},
            ).get(
                "series",
                [],
            )
            if self.market.get(
                "kospi_night"
            )
            else []
        )

        series = (
            old
            + [
                value
            ]
        )[-30:]

        return (
            self._market_item(
                "코스피 야간선물",
                value,
                change,
                change_pct,
                "실시간",
                "NHPLUG",
                series,
                datetime.now(
                    KST
                ).strftime(
                    "%Y%m%d"
                ),
            )
        )

    def _read_nasdaq_future(
        self
    ):
        from nhplug import call

        symbol = (
            self.future_symbols.get(
                "nasdaq_future",
                "",
            )
        )

        exnm = (
            self.future_symbols.get(
                "nasdaq_future_exnm",
                "FCME",
            )
            or "FCME"
        )

        if not symbol:
            raise RuntimeError(
                "NASDAQ 선물 "
                "선도월물 자동탐색 실패"
            )

        data = call(
            "/gbfuture/quote/v1/current",
            {
                "exnm":
                    exnm,

                "iem_cd":
                    symbol,
            },
        )

        value = pick(
            data,
            (
                "last",
            ),
        )

        sign = pick_text(
            data,
            (
                "sign",
            ),
        )

        change = (
            signed_value(
                pick(
                    data,
                    (
                        "diff",
                    ),
                ),
                sign,
            )
        )

        change_pct = (
            signed_value(
                pick(
                    data,
                    (
                        "rate",
                    ),
                ),
                sign,
            )
        )

        if value <= 0:
            raise RuntimeError(
                f"{symbol} "
                "나스닥 선물 현재가 없음"
            )

        old = (
            self.market.get(
                "nasdaq_future",
                {},
            ).get(
                "series",
                [],
            )
            if self.market.get(
                "nasdaq_future"
            )
            else []
        )

        series = (
            old
            + [
                value
            ]
        )[-30:]

        return (
            self._market_item(
                "나스닥 선물",
                value,
                change,
                change_pct,
                "실시간",
                "NHPLUG",
                series,
                datetime.now(
                    KST
                ).strftime(
                    "%Y%m%d"
                ),
            )
        )

    def reference_loop(
        self
    ):
        last_krx = 0.0

        while not self._stop.is_set():

            errors = dict(
                self.market_errors
            )

            if (
                time.time()
                - last_krx
                > 600
            ):
                try:

                    self.market.update(
                        self._read_krx_history()
                    )

                    errors.pop(
                        "krx_indices",
                        None,
                    )

                    last_krx = (
                        time.time()
                    )

                except Exception as exc:

                    errors[
                        "krx_indices"
                    ] = str(
                        exc
                    )[:500]

            for (
                key,
                label,
            ) in (
                (
                    "sp500",
                    "S&P500",
                ),
                (
                    "nasdaq",
                    "나스닥",
                ),
                (
                    "sox",
                    "필라델피아 반도체지수",
                ),
            ):

                try:

                    self.market[
                        key
                    ] = (
                        self._read_symbol_period(
                            self.index_symbols[
                                key
                            ],
                            label,
                        )
                    )

                    errors.pop(
                        key,
                        None,
                    )

                except Exception as exc:

                    errors[
                        key
                    ] = str(
                        exc
                    )[:300]

            try:

                self._read_fx()

                errors.pop(
                    "usdkrw",
                    None,
                )

            except Exception as exc:

                errors[
                    "usdkrw"
                ] = str(
                    exc
                )[:300]

            self.market_errors = (
                errors
            )

            self.market_updated_at = (
                time.time()
            )

            time.sleep(
                60
            )

    def futures_loop(
        self
    ):
        self._discover_futures()

        while not self._stop.is_set():

            errors = dict(
                self.market_errors
            )

            try:

                self.market[
                    "kospi_night"
                ] = (
                    self._read_kospi_night()
                )

                errors.pop(
                    "kospi_night",
                    None,
                )

            except Exception as exc:

                errors[
                    "kospi_night"
                ] = str(
                    exc
                )[:300]

            try:

                self.market[
                    "nasdaq_future"
                ] = (
                    self._read_nasdaq_future()
                )

                errors.pop(
                    "nasdaq_future",
                    None,
                )

            except Exception as exc:

                errors[
                    "nasdaq_future"
                ] = str(
                    exc
                )[:300]

            self.market_errors = (
                errors
            )

            self.market_updated_at = (
                time.time()
            )

            time.sleep(
                15
            )

    def _pending(
        self,
        key,
        label,
        source="NHPLUG",
    ):
        err = (
            self.market_errors.get(
                key
            )
        )

        return (
            self._market_item(
                label,
                None,
                None,
                None,
                (
                    "수신 오류 · "
                    f"{err[:100]}"
                    if err
                    else "수신 대기"
                ),
                source,
                [],
            )
        )

    def market_state(
        self,
        market: str,
    ):
        market = (
            "US"
            if str(
                market
            ).upper()
            == "US"
            else "KR"
        )

        if market == "KR":

            return [
                (
                    self.market.get(
                        "kospi"
                    )
                    or self._pending(
                        "krx_indices",
                        "코스피",
                        "KRX 공식",
                    )
                ),

                (
                    self.market.get(
                        "kosdaq"
                    )
                    or self._pending(
                        "krx_indices",
                        "코스닥",
                        "KRX 공식",
                    )
                ),

                (
                    self.market.get(
                        "kospi_night"
                    )
                    or self._pending(
                        "kospi_night",
                        "코스피 야간선물",
                    )
                ),

                (
                    self.market.get(
                        "nasdaq_future"
                    )
                    or self._pending(
                        "nasdaq_future",
                        "나스닥 선물",
                    )
                ),

                (
                    self.market.get(
                        "sox"
                    )
                    or self._pending(
                        "sox",
                        "필라델피아 반도체지수",
                    )
                ),
            ]

        return [
            (
                self.market.get(
                    "sp500"
                )
                or self._pending(
                    "sp500",
                    "S&P500",
                )
            ),

            (
                self.market.get(
                    "nasdaq"
                )
                or self._pending(
                    "nasdaq",
                    "나스닥",
                )
            ),

            (
                self.market.get(
                    "nasdaq_future"
                )
                or self._pending(
                    "nasdaq_future",
                    "나스닥 선물",
                )
            ),

            (
                self.market.get(
                    "sox"
                )
                or self._pending(
                    "sox",
                    "필라델피아 반도체지수",
                )
            ),
        ]

    def health(
        self
    ):
        return {
            "nh_realtime":
                self.connected_any(),

            "realtime":
                dict(
                    self.connected
                ),

            "errors":
                dict(
                    self.errors
                ),

            "kr_tracked":
                len(
                    self.fixed[
                        "KR"
                    ]
                ),

            "kr_priced":
                sum(
                    1

                    for q in
                    self.quotes[
                        "KR"
                    ].values()

                    if q.price > 0
                ),

            "us_tracked":
                len(
                    self.fixed[
                        "US"
                    ]
                ),

            "us_priced":
                sum(
                    1

                    for q in
                    self.quotes[
                        "US"
                    ].values()

                    if q.price > 0
                ),

            "market_updated_at":
                self.market_updated_at,

            "market_errors":
                dict(
                    self.market_errors
                ),

            "usdkrw":
                self.usdkrw,

            "usdkrw_asof":
                self.usdkrw_asof,
        }

    def start(
        self
    ):
        for target in (
            self.kr_scanner,
            self.us_scanner,
            self.reference_loop,
            self.futures_loop,
        ):

            threading.Thread(
                target=target,
                daemon=True,
            ).start()
