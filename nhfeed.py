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
    keys: Iterable[
        str
    ],
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
    keys: Iterable[
        str
    ],
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
    keys: Iterable[
        str
    ],
):
    if not isinstance(
        data,
        dict,
    ):
        return []

    for key in keys:
        value = data.get(
            key
        )

        if isinstance(
            value,
            list,
        ):
            return value

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
    ):
        return -value

    return value


def normalize_text(
    value
):
    return re.sub(
        r"\s+",
        "",
        str(
            value
            or ""
        ),
    ).upper()


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

        self.index_symbols = {
            "sp500":
                os.getenv(
                    "NH_SP500_SYMBOL",
                    "SPX",
                )
                .strip()
                or "SPX",

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
                )
                .strip()
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
        market = (
            "US"
            if str(
                market
            ).upper()
            == "US"
            else "KR"
        )

        return self.quotes[
            market
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
            self.nxt = {
                "session":
                    "CLOSED",

                "label":
                    "NXT 휴장",

                "open":
                    False,

                "updated_at":
                    time.time(),
            }

            return

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
        market = (
            "US"
            if str(
                market
            ).upper()
            == "US"
            else "KR"
        )

        if market == "US":
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
            if (
                q.volume
                and volume
                > q.volume
            ):
                q.prev_volume = (
                    q.volume
                )

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
            if (
                q.volume
                and volume
                > q.volume
            ):
                q.prev_volume = (
                    q.volume
                )

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

            codes = []

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

                sector_code = str(
                    row.get(
                        "bstp_medm_div_code"
                    )
                    or row.get(
                        "industry_group"
                    )
                    or ""
                ).strip()

                if (
                    sector_code
                    and sector_code
                    != "000000"
                ):
                    q.sector = (
                        sector_code
                    )

                codes.append(
                    code
                )

            self.code_lists[
                "KR"
            ] = (
                list(
                    dict.fromkeys(
                        codes
                    )
                )
                or self.fixed[
                    "KR"
                ][:]
            )

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

            metadata = {}
            all_usa = []

            for row in rows:
                country = str(
                    row.get(
                        "country_code"
                    )
                    or row.get(
                        "sNationCode"
                    )
                    or ""
                ).strip().upper()

                symbol = str(
                    row.get(
                        "symbol"
                    )
                    or row.get(
                        "sSymbol"
                    )
                    or ""
                ).strip().upper()

                if not symbol:
                    continue

                if (
                    country
                    and country
                    != "USA"
                ):
                    continue

                name = str(
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

                metadata[
                    symbol
                ] = (
                    name,
                    industry,
                )

                all_usa.append(
                    symbol
                )

            use_all = (
                os.getenv(
                    "US_SCAN_ALL",
                    "0",
                ).strip()
                == "1"
            )

            selected = (
                all_usa
                if use_all
                else self.fixed[
                    "US"
                ]
            )

            valid = []

            for symbol in selected:
                if (
                    symbol
                    in metadata
                ):
                    (
                        name,
                        industry,
                    ) = metadata[
                        symbol
                    ]

                    q = self.q(
                        "US",
                        symbol,
                    )

                    q.name = (
                        name
                        or symbol
                    )

                    q.sector = (
                        f"업종 {industry}"
                        if industry
                        else "미국주식"
                    )

                    valid.append(
                        symbol
                    )

                elif not metadata:
                    valid.append(
                        symbol
                    )

            self.code_lists[
                "US"
            ] = (
                list(
                    dict.fromkeys(
                        valid
                    )
                )
                or self.fixed[
                    "US"
                ][:]
            )

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
                fallback_ka = []

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
                        fallback_ka.append(
                            code
                        )

                    name_norm = (
                        normalize_text(
                            name
                        )
                    )

                    if (
                        code.startswith(
                            "KA"
                        )
                        and (
                            "KOSPI200"
                            in name_norm
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
                    and fallback_ka
                ):
                    self.future_symbols[
                        "kospi_night"
                    ] = fallback_ka[
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
                            "symb"
                        )
                        or row.get(
                            "Symbol"
                        )
                        or ""
                    ).strip().upper()

                    inner = str(
                        row.get(
                            "isym"
                        )
                        or row.get(
                            "InnerSymbol"
                        )
                        or symbol
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

                    section = str(
                        row.get(
                            "sect"
                        )
                        or row.get(
                            "Section"
                        )
                        or ""
                    ).strip()

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
                        not in name.upper()
                    ):
                        continue

                    score = (
                        (
                            10
                            if lead
                            == "1"
                            else 0
                        )
                        + (
                            2
                            if section
                            == "30"
                            else 0
                        )
                    )

                    candidates.append(
                        (
                            score,
                            inner
                            or symbol,
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
                    ] = (
                        exnm
                        or "FCME"
                    )

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

        if not codes:
            return

        from nhplug import call

        while True:
            idx = (
                self.scan_index[
                    "KR"
                ]
                % len(
                    codes
                )
            )

            code = codes[
                idx
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

            success = False
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

                        success = True

                        break

                except Exception as exc:
                    last_error = (
                        f"{market_cd} "
                        f"{code}: {exc}"
                    )[:300]

                    if (
                        "429"
                        in last_error
                    ):
                        time.sleep(
                            1.0
                        )

                        break

            if (
                success
                and idx % 6
                == 0
            ):
                try:
                    investor = call(
                        "/krstock/quote/v1/currentInvestor",
                        {
                            "market_cd":
                                "KRX",

                            "iem_cd":
                                code,

                            "array_cnt":
                                "002",
                        },
                    )

                    self._apply_kr(
                        code,
                        investor,
                    )

                except Exception as exc:
                    if (
                        "429"
                        in str(
                            exc
                        )
                    ):
                        time.sleep(
                            0.8
                        )

            elif last_error:
                self.errors[
                    "KR"
                ] = last_error

            time.sleep(
                0.28
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

        if not codes:
            return

        from nhplug import call

        while True:
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
                        1.0
                    )

            time.sleep(
                0.38
            )

    def _priority_kr(
        self
    ):
        rows = []

        for (
            code,
            q,
        ) in list(
            self.quotes[
                "KR"
            ].items()
        ):
            if q.price <= 0:
                continue

            change = (
                abs(
                    (
                        q.price
                        / q.open
                        - 1
                    )
                    * 100
                )
                if q.open
                else 0
            )

            rows.append(
                (
                    change,
                    code,
                )
            )

        rows.sort(
            reverse=True
        )

        out = [
            code
            for _,
            code
            in rows[:20]
        ]

        for code in (
            self.fixed[
                "KR"
            ]
        ):
            if code not in out:
                out.append(
                    code
                )

            if len(out) >= 20:
                break

        return out[
            :20
        ]

    def _kr_realtime_tick(
        self,
        message,
    ):
        code = pick_text(
            message,
            (
                "iem_cd",
                "stck_shrn_iscd",
                "tr_key",
            ),
        )

        match = re.search(
            r"(\d{6})",
            code,
        )

        if not match:
            return

        self._apply_kr(
            match.group(
                1
            ),
            message,
        )

        self.connected[
            "KR"
        ] = True

    def kr_websocket(
        self
    ):
        try:
            from nhplug.realtime import (
                subscribe,
            )

        except Exception as exc:
            self.errors[
                "KR"
            ] = (
                "realtime import: "
                f"{exc}"
            )[:300]

            return

        while True:
            keys = (
                self._priority_kr()
            )

            if not keys:
                time.sleep(
                    2
                )

                continue

            try:
                subscribe(
                    keys,
                    self._kr_realtime_tick,
                    max_messages=300,
                )

            except Exception as exc:
                self.errors[
                    "KR"
                ] = (
                    "realtime: "
                    f"{exc}"
                )[:300]

                time.sleep(
                    2
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
        }

    def _krx_rows(
        self,
        market_code,
        trade_date,
    ):
        url = (
            "https://data.krx.co.kr/"
            "comm/bldAttendant/"
            "getJsonData.cmd"
        )

        headers = {
            "User-Agent":
                "Mozilla/5.0",

            "Accept":
                "application/json, "
                "text/plain, */*",

            "Accept-Language":
                "ko-KR,ko;q=0.9",

            "Origin":
                "https://data.krx.co.kr",

            "Referer":
                (
                    "https://data.krx.co.kr/"
                    "contents/MDC/MDI/"
                    "mdiLoader/index.cmd"
                ),
        }

        payload = {
            "bld":
                (
                    "dbms/MDC/STAT/"
                    "standard/"
                    "MDCSTAT00101"
                ),

            "locale":
                "ko_KR",

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

        response = requests.post(
            url,
            headers=headers,
            data=payload,
            timeout=12,
        )

        response.raise_for_status()

        if (
            not response.text.strip()
            or response.text
            .strip()
            .upper()
            == "LOGOUT"
        ):
            raise RuntimeError(
                "KRX data endpoint "
                "returned empty/LOGOUT"
            )

        data = response.json()

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

    @staticmethod
    def _find_index_row(
        rows,
        names,
    ):
        targets = {
            normalize_text(
                x
            )
            for x
            in names
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
                normalize_text(
                    name
                )
                in targets
            ):
                return row

        return None

    def _parse_krx_index(
        self,
        row,
        label,
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

        if value <= 0:
            raise RuntimeError(
                f"{label} value missing"
            )

        return (
            self._market_item(
                label,
                value,
                change,
                change_pct,
                "수신완료",
                "KRX 공식",
            )
        )

    def _read_krx_indices(
        self
    ):
        today = datetime.now(
            KST
        ).date()

        last_error = None

        for offset in range(
            0,
            8,
        ):
            day = (
                today
                - timedelta(
                    days=offset
                )
            )

            if (
                day.weekday()
                >= 5
            ):
                continue

            trade_date = (
                day.strftime(
                    "%Y%m%d"
                )
            )

            try:
                kospi_rows = (
                    self._krx_rows(
                        "02",
                        trade_date,
                    )
                )

                kosdaq_rows = (
                    self._krx_rows(
                        "03",
                        trade_date,
                    )
                )

                kospi = (
                    self._find_index_row(
                        kospi_rows,
                        (
                            "코스피",
                            "KOSPI",
                        ),
                    )
                )

                kosdaq = (
                    self._find_index_row(
                        kosdaq_rows,
                        (
                            "코스닥",
                            "KOSDAQ",
                        ),
                    )
                )

                if (
                    kospi is None
                    or kosdaq is None
                ):
                    raise RuntimeError(
                        "KOSPI/KOSDAQ "
                        "representative row "
                        "not found"
                    )

                return {
                    "kospi":
                        self._parse_krx_index(
                            kospi,
                            "코스피",
                        ),

                    "kosdaq":
                        self._parse_krx_index(
                            kosdaq,
                            "코스닥",
                        ),
                }

            except Exception as exc:
                last_error = exc

        raise RuntimeError(
            "KRX index load failed: "
            f"{last_error}"
        )

    def _read_index_period(
        self,
        symbol,
        label,
        name_tokens=(),
    ):
        from nhplug import call

        data = call(
            "/gbstock/quote/v1/symbolIndexFxPeriod",
            {
                "iem_cd":
                    symbol,

                "end_dt":
                    datetime.now(
                        KST
                    ).strftime(
                        "%Y%m%d"
                    ),

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

        actual_name = (
            pick_text(
                data,
                (
                    "hts_kor_isnm",
                    "iem_nm",
                    "name",
                ),
            )
        )

        if (
            name_tokens
            and actual_name
        ):
            normalized = (
                actual_name.upper()
            )

            if not any(
                token.upper()
                in normalized

                for token
                in name_tokens
            ):
                raise RuntimeError(
                    f"{symbol} returned "
                    "unexpected index: "
                    f"{actual_name}"
                )

        value = pick(
            data,
            (
                "ovrs_prpr",
            ),
        )

        sign = pick_text(
            data,
            (
                "prdy_vrss_sign",
            ),
        )

        change = (
            signed_value(
                pick(
                    data,
                    (
                        "prdy_vrss",
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
            ),
        )

        series = []

        for row in rows:
            price = num(
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

            if price:
                series.append(
                    price
                )

        if (
            not value
            and series
        ):
            value = series[
                0
            ]

        if not value:
            raise RuntimeError(
                f"{label} value "
                "missing for symbol "
                f"{symbol}"
            )

        return (
            self._market_item(
                label,
                value,
                change,
                change_pct,
                "수신완료",
                "NHPLUG",
                series[::-1],
            )
        )

    def _probe_index(
        self,
        key,
        label,
        candidates,
        tokens,
    ):
        configured = (
            self.index_symbols.get(
                key,
                "",
            )
        )

        symbols = (
            [configured]
            if configured
            else []
        )

        symbols.extend(
            x
            for x
            in candidates

            if (
                x
                and x
                not in symbols
            )
        )

        last_error = None

        for symbol in symbols:
            try:
                item = (
                    self._read_index_period(
                        symbol,
                        label,
                        tokens,
                    )
                )

                self.index_symbols[
                    key
                ] = symbol

                return item

            except Exception as exc:
                last_error = exc

        raise RuntimeError(
            f"{label}: "
            f"{last_error}"
        )

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
                "코스피200 야간선물 "
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

        if not value:
            raise RuntimeError(
                f"{symbol} "
                "야간선물 현재가 없음"
            )

        return (
            self._market_item(
                "코스피 야간선물",
                value,
                change,
                change_pct,
                "수신완료",
                "NHPLUG",
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

        if not value:
            raise RuntimeError(
                f"{symbol} "
                "나스닥 선물 "
                "현재가 없음"
            )

        return (
            self._market_item(
                "나스닥 선물",
                value,
                change,
                change_pct,
                "수신완료",
                "NHPLUG",
            )
        )

    def market_loop(
        self
    ):
        self._discover_futures()

        while True:
            self.update_nxt_session()

            errors = {}
            fresh = {}

            try:
                fresh.update(
                    self._read_krx_indices()
                )

            except Exception as exc:
                errors[
                    "krx_indices"
                ] = str(
                    exc
                )[:500]

            try:
                fresh[
                    "sp500"
                ] = self._probe_index(
                    "sp500",
                    "S&P500",
                    (
                        "SPX",
                    ),
                    (
                        "S&P",
                        "STANDARD&POOR",
                    ),
                )

            except Exception as exc:
                errors[
                    "sp500"
                ] = str(
                    exc
                )[:300]

            try:
                fresh[
                    "nasdaq"
                ] = self._probe_index(
                    "nasdaq",
                    "나스닥",
                    (
                        "COMP",
                        "IXIC",
                        "NDX",
                    ),
                    (
                        "나스닥",
                        "NASDAQ",
                    ),
                )

            except Exception as exc:
                errors[
                    "nasdaq"
                ] = str(
                    exc
                )[:300]

            try:
                fresh[
                    "sox"
                ] = self._probe_index(
                    "sox",
                    "필라델피아 반도체지수",
                    (
                        "SOX",
                        "PHLXSOX",
                    ),
                    (
                        "반도체",
                        "SEMICONDUCTOR",
                        "SOX",
                    ),
                )

            except Exception as exc:
                errors[
                    "sox"
                ] = str(
                    exc
                )[:300]

            try:
                fresh[
                    "kospi_night"
                ] = (
                    self._read_kospi_night()
                )

            except Exception as exc:
                errors[
                    "kospi_night"
                ] = str(
                    exc
                )[:300]

            try:
                fresh[
                    "nasdaq_future"
                ] = (
                    self._read_nasdaq_future()
                )

            except Exception as exc:
                errors[
                    "nasdaq_future"
                ] = str(
                    exc
                )[:300]

            self.market.update(
                fresh
            )

            self.market_errors = (
                errors
            )

            self.market_updated_at = (
                time.time()
            )

            time.sleep(
                30
            )

    def _pending(
        self,
        key,
        label,
        source="NHPLUG",
    ):
        error = (
            self.market_errors.get(
                key
            )
        )

        if error:
            status = (
                "수신 오류 · "
                f"{error[:90]}"
            )

        else:
            status = (
                "수신 대기"
            )

        return (
            self._market_item(
                label,
                None,
                None,
                None,
                status,
                source,
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

    def start(
        self
    ):
        for target in (
            self.kr_scanner,
            self.us_scanner,
            self.kr_websocket,
            self.market_loop,
        ):
            threading.Thread(
                target=target,
                daemon=True,
            ).start()
