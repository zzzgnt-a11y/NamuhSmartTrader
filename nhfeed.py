from __future__ import annotations

import html
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
    "005930",
    "000660",
    "035420",
    "035720",
    "068270",
    "012450",
    "267260",
    "042700",
]


def walk(o):
    if isinstance(o, dict):
        yield o
        for v in o.values():
            yield from walk(v)
    elif isinstance(o, list):
        for v in o:
            yield from walk(v)


def num(v):
    try:
        return float(
            str(v)
            .replace(",", "")
            .replace("+", "")
            .strip()
        )
    except Exception:
        return 0.0


def pick(data, keys):
    for d in walk(data):
        for k in keys:
            if k in d and d[k] not in (None, ""):
                return num(d[k])
    return 0.0


def pick_text(data, keys):
    for d in walk(data):
        for k in keys:
            v = d.get(k)
            if v not in (None, ""):
                return str(v)
    return ""


def code_of(data):
    for d in walk(data):
        for k in (
            "iem_cd",
            "stck_shrn_iscd",
            "code",
            "symbol",
            "tr_key",
        ):
            m = re.search(
                r"\b(\d{6})\b",
                str(d.get(k, "")),
            )
            if m:
                return m.group(1)
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


def _normalize_krx_text(raw: str) -> str:
    raw = html.unescape(raw or "")

    raw = raw.replace(
        "\\u25b2",
        "▲",
    )

    raw = raw.replace(
        "\\u25bc",
        "▼",
    )

    raw = raw.replace(
        "\\n",
        " ",
    )

    raw = raw.replace(
        "\\r",
        " ",
    )

    raw = raw.replace(
        "\\t",
        " ",
    )

    raw = re.sub(
        r"(?s)<[^>]+>",
        " ",
        raw,
    )

    raw = raw.replace(
        '"',
        " ",
    )

    raw = raw.replace(
        "'",
        " ",
    )

    raw = raw.replace(
        ":",
        " ",
    )

    raw = raw.replace(
        "=",
        " ",
    )

    return re.sub(
        r"\s+",
        " ",
        raw,
    ).strip()


def _parse_krx_index(
    text: str,
    label: str,
):
    text = _normalize_krx_text(
        text
    )

    patterns = [
        re.compile(
            rf"\b{re.escape(label)}\b"
            r".{0,80}?"
            r"([\d,]+(?:\.\d+)?)"
            r".{0,20}?"
            r"([▲▼+\-])"
            r"\s*([\d,]+(?:\.\d+)?)"
            r".{0,20}?"
            r"\(?\s*([\d.]+)\s*\)?",
            re.I,
        ),

        re.compile(
            rf"\b{re.escape(label)}\b"
            r".{0,120}?"
            r"([\d,]+(?:\.\d+)?)"
            r".{0,80}?"
            r"([+\-])"
            r"\s*([\d,]+(?:\.\d+)?)"
            r".{0,80}?"
            r"([\d.]+)",
            re.I,
        ),
    ]

    for pattern in patterns:
        m = pattern.search(
            text
        )

        if not m:
            continue

        value = num(
            m.group(1)
        )

        sign_token = (
            m.group(2)
        )

        change = abs(
            num(
                m.group(3)
            )
        )

        change_pct = abs(
            num(
                m.group(4)
            )
        )

        if sign_token in (
            "▼",
            "-",
        ):
            change = -change
            change_pct = (
                -change_pct
            )

        if value > 0:
            return (
                value,
                change,
                change_pct,
            )

    return None


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


    def update_nxt_session(
        self,
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
            now.hour * 60
            + now.minute
            + now.second / 60
        )

        if (
            480
            <= mins
            < 530
        ):
            session = "PRE"
            label = (
                "NXT 프리마켓"
            )
            opened = True

        elif (
            530
            <= mins
            < 540.5
        ):
            session = "BREAK"
            label = (
                "NXT 메인마켓 대기"
            )
            opened = False

        elif (
            540.5
            <= mins
            < 920
        ):
            session = "MAIN"
            label = (
                "NXT 메인마켓"
            )
            opened = True

        elif (
            920
            <= mins
            < 940
        ):
            session = (
                "AFTER_WAIT"
            )
            label = (
                "NXT 애프터마켓 대기"
            )
            opened = False

        elif (
            940
            <= mins
            < 1200
        ):
            session = "AFTER"
            label = (
                "NXT 애프터마켓"
            )
            opened = True

        else:
            session = "CLOSED"
            label = (
                "NXT 장외시간"
            )
            opened = False

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


    def q(
        self,
        code,
    ):

        if (
            code
            not in self.quotes
        ):
            self.quotes[
                code
            ] = Quote(
                code,
                code,
            )

        return self.quotes[
            code
        ]


    def _apply(
        self,
        code,
        data,
    ):

        q = self.q(
            code
        )

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


    def load_master(
        self,
    ):

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
                        "code"
                        in c.lower()
                        or "단축"
                        in c
                        or "종목코드"
                        in c
                    )
                ),
                None,
            )

            name_col = next(
                (
                    c
                    for c in cols
                    if (
                        "name"
                        in c.lower()
                        or "종목명"
                        in c
                        or "한글"
                        in c
                    )
                ),
                None,
            )

            sector_col = next(
                (
                    c
                    for c in cols
                    if (
                        "업종"
                        in c
                        or "sector"
                        in c.lower()
                        or "industry"
                        in c.lower()
                    )
                ),
                None,
            )

            arr = []

            if code_col:

                for _, row in (
                    df.iterrows()
                ):

                    m = re.search(
                        r"(\d{6})",
                        str(
                            row.get(
                                code_col,
                                "",
                            )
                        ),
                    )

                    if not m:
                        continue

                    code = (
                        m.group(1)
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

        except Exception as e:

            self.error = (
                f"master: {e}"
            )

            self.all_codes = (
                self.fixed[:]
            )


    def _market_order(
        self,
    ):

        self.update_nxt_session()

        if (
            self.nxt[
                "session"
            ]
            in (
                "PRE",
                "AFTER",
            )
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


    def scanner(
        self,
    ):

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

                except Exception as e:

                    last_error = (
                        f"{market_cd} "
                        f"{code}: {e}"
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


    def priority(
        self,
    ):

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


    def websocket(
        self,
    ):

        try:

            from nhplug.realtime import (
                subscribe,
            )

        except Exception as e:

            self.error = (
                f"realtime import: {e}"
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

            except Exception as e:

                self.connected = (
                    False
                )

                self.error = (
                    str(e)[:300]
                )

                time.sleep(2)


    def _market_item(
        self,
        label,
        value,
        change,
        change_pct,
        status="NHPLUG",
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
        }


    def _fetch_krx_page(
        self,
    ):

        urls = (
            "https://index.krx.co.kr/",
            "https://index.krx.co.kr/main/main.jsp",
        )

        headers = {

            "User-Agent":
                (
                    "Mozilla/5.0 "
                    "(Linux; Android 16; Mobile) "
                    "AppleWebKit/537.36 "
                    "(KHTML, like Gecko) "
                    "Chrome/140.0 "
                    "Mobile Safari/537.36"
                ),

            "Accept":
                (
                    "text/html,"
                    "application/xhtml+xml,"
                    "application/xml;q=0.9,"
                    "image/avif,"
                    "image/webp,"
                    "*/*;q=0.8"
                ),

            "Accept-Language":
                "ko-KR,ko;q=0.9,en;q=0.8",

            "Cache-Control":
                "no-cache",

            "Pragma":
                "no-cache",

            "Referer":
                "https://index.krx.co.kr/",
        }

        errors = []

        with requests.Session() as session:

            for url in urls:

                try:

                    r = session.get(
                        url,
                        headers=headers,
                        timeout=12,
                        allow_redirects=True,
                    )

                    r.raise_for_status()

                    if (
                        not r.encoding
                        or (
                            r.encoding.lower()
                            == "iso-8859-1"
                        )
                    ):
                        r.encoding = (
                            r.apparent_encoding
                            or "utf-8"
                        )

                    text = (
                        r.text
                        or ""
                    )

                    if (
                        "KOSPI"
                        in text
                        and "KOSDAQ"
                        in text
                    ):
                        return text

                    errors.append(
                        (
                            f"{url} "
                            "no-index-text"
                        )
                    )

                except Exception as e:

                    errors.append(
                        (
                            f"{url} "
                            f"{type(e).__name__}: "
                            f"{e}"
                        )
                    )

        raise RuntimeError(
            " | ".join(
                errors
            )[:500]
        )


    def _read_krx_indices(
        self,
    ):

        raw = (
            self._fetch_krx_page()
        )

        kospi = _parse_krx_index(
            raw,
            "KOSPI",
        )

        kosdaq = _parse_krx_index(
            raw,
            "KOSDAQ",
        )

        if (
            not kospi
            or not kosdaq
        ):

            normalized = (
                _normalize_krx_text(
                    raw
                )
            )

            raise RuntimeError(
                (
                    "KRX parse failed: "
                    + normalized[:1200]
                )
            )

        out = {}

        for (
            key,
            label,
            parsed,
        ) in (
            (
                "kospi",
                "코스피",
                kospi,
            ),
            (
                "kosdaq",
                "코스닥",
                kosdaq,
            ),
        ):

            (
                value,
                change,
                change_pct,
            ) = parsed

            out[
                key
            ] = self._market_item(
                label,
                value,
                change,
                change_pct,
                "KRX 공식",
            )

        return out


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
            "/gbstock/quote/v1/symbolIndexFxPeriod",
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
            "NHPLUG 해외지수",
        )


    def market_loop(
        self,
    ):

        while True:

            try:

                self.update_nxt_session()

                new_market = {}
                errors = {}

                try:

                    new_market.update(
                        self._read_krx_indices()
                    )

                except Exception as e:

                    errors[
                        "krx_indices"
                    ] = str(e)[:500]

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

                    except Exception as e:

                        errors[
                            key
                        ] = str(e)[:300]

                self.market.update(
                    new_market
                )

                self.market_errors = (
                    errors
                )

                self.market_updated_at = (
                    time.time()
                )

            except Exception as e:

                self.market_errors[
                    "market_loop"
                ] = str(e)[:500]

            time.sleep(
                20
            )


    def market_state(
        self,
    ):

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
                "krx_indices",
                "",
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


    def start(
        self,
    ):

        for target in (
            self.scanner,
            self.websocket,
            self.market_loop,
        ):

            threading.Thread(
                target=target,
                daemon=True,
            ).start()
