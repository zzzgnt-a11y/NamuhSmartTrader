from __future__ import annotations

import os
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Dict

import requests

from engine import Quote

KST = timezone(timedelta(hours=9))

DEFAULT_CODES = [
    "005930", "000660", "035420", "035720",
    "068270", "012450", "267260", "042700",
]


def walk(obj):
    if isinstance(obj, dict):
        yield obj
        for value in obj.values():
            yield from walk(value)
    elif isinstance(obj, list):
        for value in obj:
            yield from walk(value)


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


def pick(data, keys):
    for item in walk(data):
        for key in keys:
            if (
                key in item
                and item[key] not in (None, "")
            ):
                return num(item[key])
    return 0.0


def pick_text(data, keys):
    for item in walk(data):
        for key in keys:
            value = item.get(key)
            if value not in (None, ""):
                return str(value)
    return ""


def code_of(data):
    for item in walk(data):
        for key in (
            "iem_cd",
            "stck_shrn_iscd",
            "code",
            "symbol",
            "tr_key",
        ):
            match = re.search(
                r"\b(\d{6})\b",
                str(item.get(key, "")),
            )

            if match:
                return match.group(1)

    return ""


def signed_value(value, sign):
    value = abs(num(value))

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


class NHFeed:

    def __init__(self):
        self.quotes: Dict[
            str,
            Quote,
        ] = {}

        self.connected = False
        self.error = ""

        configured = [
            x.strip()
            for x in os.getenv(
                "TRACKED_CODES",
                "",
            ).split(",")
            if x.strip()
        ]

        self.fixed = (
            configured
            or DEFAULT_CODES[:]
        )

        self.all_codes = []
        self.scan_index = 0

        self.market = {
            "kospi": None,
            "kosdaq": None,
            "kospi_night": None,
            "nasdaq": None,
            "sox": None,
            "nasdaq_future": None,
        }

        self.market_errors = {}
        self.market_updated_at = 0

        self.nxt = {
            "session": "CLOSED",
            "label": "NXT 장외시간",
            "open": False,
            "updated_at": 0,
        }


    def q(self, code):
        if code not in self.quotes:
            self.quotes[
                code
            ] = Quote(
                code,
                code,
            )

        return self.quotes[
            code
        ]


    def update_nxt_session(self):
        now = datetime.now(
            KST
        )

        if now.weekday() >= 5:
            session = "CLOSED"
            label = "NXT 휴장"
            opened = False

        else:
            mins = (
                now.hour * 60
                + now.minute
                + now.second / 60
            )

            if 480 <= mins < 530:
                session = "PRE"
                label = "NXT 프리마켓"
                opened = True

            elif 530 <= mins < 540.5:
                session = "BREAK"
                label = "NXT 메인마켓 대기"
                opened = False

            elif 540.5 <= mins < 920:
                session = "MAIN"
                label = "NXT 메인마켓"
                opened = True

            elif 920 <= mins < 940:
                session = "AFTER_WAIT"
                label = "NXT 애프터마켓 대기"
                opened = False

            elif 940 <= mins < 1200:
                session = "AFTER"
                label = "NXT 애프터마켓"
                opened = True

            else:
                session = "CLOSED"
                label = "NXT 장외시간"
                opened = False

        self.nxt = {
            "session": session,
            "label": label,
            "open": opened,
            "updated_at": time.time(),
        }


    def _apply(
        self,
        code,
        data,
    ):
        q = self.q(code)

        price = pick(
            data,
            (
                "stck_prpr",
                "price",
                "prc",
                "cur_pr",
                "now_pr",
                "last_price",
            ),
        )

        volume = pick(
            data,
            (
                "acml_vol",
                "new_volume",
                "volume",
                "vol",
            ),
        )

        if price:
            q.mark(
                round(price),
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
                    "foreign_net",
                ),
            )
            or q.foreign_net
        )

        q.institution_net = (
            pick(
                data,
                (
                    "orgn_ntby_qty",
                    "gigwan",
                    "institution_net",
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


    def load_master(self):
        try:
            from nhplug.instruments import (
                load_master,
            )

            df = load_master(
                "m_new_stock"
            )

            cols = list(
                map(
                    str,
                    df.columns,
                )
            )

            code_col = next(
                (
                    c
                    for c in cols
                    if (
                        "code" in c.lower()
                        or "단축" in c
                        or "종목코드" in c
                    )
                ),
                None,
            )

            name_col = next(
                (
                    c
                    for c in cols
                    if (
                        "name" in c.lower()
                        or "종목명" in c
                        or "한글" in c
                    )
                ),
                None,
            )

            sector_col = next(
                (
                    c
                    for c in cols
                    if (
                        "업종" in c
                        or "sector" in c.lower()
                        or "industry" in c.lower()
                    )
                ),
                None,
            )

            arr = []

            if code_col:
                for _, row in (
                    df.iterrows()
                ):
                    match = re.search(
                        r"(\d{6})",
                        str(
                            row.get(
                                code_col,
                                "",
                            )
                        ),
                    )

                    if not match:
                        continue

                    code = (
                        match.group(1)
                    )

                    q = self.q(
                        code
                    )

                    if name_col:
                        q.name = str(
                            row.get(
                                name_col,
                                "",
                            )
                            or code
                        )

                    if sector_col:
                        q.sector = str(
                            row.get(
                                sector_col,
                                "",
                            )
                            or ""
                        )

                    arr.append(
                        code
                    )

            self.all_codes = (
                list(
                    dict.fromkeys(
                        arr
                    )
                )
                or self.fixed[:]
            )

        except Exception as exc:
            self.error = (
                f"master: {exc}"
            )

            self.all_codes = (
                self.fixed[:]
            )


    def _market_order(self):
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


    def scanner(self):
        self.load_master()

        codes = (
            self.all_codes
            or self.fixed
        )

        if not codes:
            return

        from nhplug import call

        while True:
            code = codes[
                self.scan_index
                % len(codes)
            ]

            self.scan_index = (
                self.scan_index
                + 1
            ) % len(codes)

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

                    self._apply(
                        code,
                        data,
                    )

                    if (
                        self.q(
                            code
                        ).price
                        > 0
                    ):
                        self.error = ""
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
                        time.sleep(1)
                        break

            if (
                not success
                and last_error
            ):
                self.error = (
                    last_error
                )

            time.sleep(
                0.28
            )


    def priority(self):
        rows = []

        for (
            code,
            q,
        ) in list(
            self.quotes.items()
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
            for _, code
            in rows[:20]
        ]

        for code in self.fixed:
            if code not in out:
                out.append(
                    code
                )

            if len(out) >= 20:
                break

        return out[:20]


    def on_tick(
        self,
        msg,
    ):
        code = code_of(
            msg
        )

        if not code:
            return

        self._apply(
            code,
            msg,
        )

        self.connected = True


    def websocket(self):
        try:
            from nhplug.realtime import (
                subscribe,
            )

        except Exception as exc:
            self.error = (
                f"realtime import: {exc}"
            )
            return

        while True:
            keys = (
                self.priority()
                or self.fixed[:20]
            )

            if not keys:
                time.sleep(2)
                continue

            try:
                subscribe(
                    keys,
                    self.on_tick,
                    max_messages=300,
                )

            except Exception as exc:
                self.connected = False
                self.error = str(
                    exc
                )[:300]

                time.sleep(2)


    def _market_item(
        self,
        label,
        value,
        change,
        change_pct,
        status,
    ):
        return {
            "label": label,
            "value": value,
            "change": change,
            "change_pct": change_pct,
            "status": status,
        }


    def _krx_rows(
        self,
        market_code,
        trd_dd,
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
                trd_dd,

            "idxIndMidclssCd":
                market_code,
        }

        response = requests.post(
            url,
            headers=headers,
            data=payload,
            timeout=12,
        )

        response.raise_for_status()

        text = (
            response.text.strip()
        )

        if (
            not text
            or text.upper()
            == "LOGOUT"
        ):
            raise RuntimeError(
                "KRX data endpoint "
                "returned LOGOUT/empty"
            )

        data = response.json()

        rows = (
            data.get("output")
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
        exact_name,
    ):
        normalized = re.sub(
            r"\s+",
            "",
            exact_name,
        ).upper()

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

            name_norm = re.sub(
                r"\s+",
                "",
                name,
            ).upper()

            if (
                name_norm
                == normalized
            ):
                return row

        return None


    def _parse_index_row(
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
            "2",
            "4",
            "5",
            "-",
            "▼",
        ):
            change = (
                -abs(change)
            )

            change_pct = (
                -abs(
                    change_pct
                )
            )

        elif sign in (
            "1",
            "3",
            "+",
            "▲",
        ):
            change = (
                abs(change)
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

        return self._market_item(
            label,
            value,
            change,
            change_pct,
            "KRX 공식",
        )


    def _read_krx_indices(
        self,
    ):
        last_error = None

        today = datetime.now(
            KST
        ).date()

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

            if day.weekday() >= 5:
                continue

            trd_dd = day.strftime(
                "%Y%m%d"
            )

            try:
                kospi_rows = (
                    self._krx_rows(
                        "02",
                        trd_dd,
                    )
                )

                kosdaq_rows = (
                    self._krx_rows(
                        "03",
                        trd_dd,
                    )
                )

                kospi_row = (
                    self._find_index_row(
                        kospi_rows,
                        "코스피",
                    )
                )

                if kospi_row is None:
                    kospi_row = (
                        self._find_index_row(
                            kospi_rows,
                            "KOSPI",
                        )
                    )

                kosdaq_row = (
                    self._find_index_row(
                        kosdaq_rows,
                        "코스닥",
                    )
                )

                if kosdaq_row is None:
                    kosdaq_row = (
                        self._find_index_row(
                            kosdaq_rows,
                            "KOSDAQ",
                        )
                    )

                if (
                    kospi_row is None
                    or kosdaq_row is None
                ):
                    raise RuntimeError(
                        "KRX KOSPI/KOSDAQ "
                        "representative row "
                        "not found"
                    )

                return {
                    "kospi":
                        self._parse_index_row(
                            kospi_row,
                            "코스피",
                        ),

                    "kosdaq":
                        self._parse_index_row(
                            kosdaq_row,
                            "코스닥",
                        ),
                }

            except Exception as exc:
                last_error = exc

        raise RuntimeError(
            "KRX index load failed: "
            f"{last_error}"
        )


    def _read_overseas_index(
        self,
        symbol,
        label,
    ):
        from nhplug import call

        today = datetime.now(
            KST
        ).strftime(
            "%Y%m%d"
        )

        data = call(
            "/gbstock/quote/v1/"
            "symbolIndexFxPeriod",
            {
                "iem_cd":
                    symbol,

                "end_dt":
                    today,

                "array_cnt":
                    "0002",

                "maxavg":
                    "020",

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
            ),
        )

        sign = pick_text(
            data,
            (
                "prdy_vrss_sign",
            ),
        )

        change = signed_value(
            pick(
                data,
                (
                    "prdy_vrss",
                ),
            ),
            sign,
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

        if not value:
            return None

        return self._market_item(
            label,
            value,
            change,
            change_pct,
            "NHPLUG",
        )


    def market_loop(self):
        while True:
            self.update_nxt_session()

            new_market = {}
            errors = {}

            try:
                new_market.update(
                    self._read_krx_indices()
                )

            except Exception as exc:
                errors[
                    "krx_indices"
                ] = str(
                    exc
                )[:500]

            symbols = (
                (
                    "nasdaq",
                    "NH_NASDAQ_SYMBOL",
                    "나스닥",
                ),

                (
                    "sox",
                    "NH_SOX_SYMBOL",
                    "필라델피아 반도체",
                ),

                (
                    "nasdaq_future",
                    "NH_NASDAQ_FUTURE_SYMBOL",
                    "나스닥 선물",
                ),

                (
                    "kospi_night",
                    "NH_KOSPI_NIGHT_SYMBOL",
                    "코스피 야간선물",
                ),
            )

            for (
                key,
                env_key,
                label,
            ) in symbols:

                symbol = os.getenv(
                    env_key,
                    "",
                ).strip()

                if not symbol:
                    continue

                try:
                    item = (
                        self._read_overseas_index(
                            symbol,
                            label,
                        )
                    )

                    if item:
                        new_market[
                            key
                        ] = item

                except Exception as exc:
                    errors[
                        key
                    ] = str(
                        exc
                    )[:300]

            self.market.update(
                new_market
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


    def market_state(self):
        self.update_nxt_session()

        nxt_status = (
            self.nxt[
                "label"
            ]
            + (
                " · 거래중"
                if self.nxt[
                    "open"
                ]
                else " · 대기/종료"
            )
        )

        krx_error = (
            self.market_errors.get(
                "krx_indices"
            )
        )

        return [
            self.market.get(
                "kospi"
            )
            or self._market_item(
                "코스피",
                None,
                None,
                None,
                (
                    "KRX 수신 오류"
                    if krx_error
                    else "KRX 지수 수신 대기"
                ),
            ),

            self.market.get(
                "kosdaq"
            )
            or self._market_item(
                "코스닥",
                None,
                None,
                None,
                (
                    "KRX 수신 오류"
                    if krx_error
                    else "KRX 지수 수신 대기"
                ),
            ),

            self._market_item(
                "NXT",
                self.nxt[
                    "session"
                ],
                None,
                None,
                nxt_status,
            ),

            self.market.get(
                "kospi_night"
            )
            or self._market_item(
                "코스피 야간선물",
                None,
                None,
                None,
                "NHPLUG 야간선물 심볼 설정 필요",
            ),

            self.market.get(
                "nasdaq"
            )
            or self._market_item(
                "나스닥",
                None,
                None,
                None,
                "NHPLUG 지수 심볼 설정 필요",
            ),

            self.market.get(
                "sox"
            )
            or self._market_item(
                "필라델피아 반도체",
                None,
                None,
                None,
                "NHPLUG 지수 심볼 설정 필요",
            ),

            self.market.get(
                "nasdaq_future"
            )
            or self._market_item(
                "나스닥 선물",
                None,
                None,
                None,
                "NHPLUG 선물 심볼 설정 필요",
            ),
        ]


    def start(self):
        for target in (
            self.scanner,
            self.websocket,
            self.market_loop,
        ):
            threading.Thread(
                target=target,
                daemon=True,
            ).start()
