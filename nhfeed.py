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
        return float(str(value).replace(",", "").replace("+", "").strip())
    except Exception:
        return 0.0


def pick(data, keys: Iterable[str]):
    for obj in walk(data):
        for key in keys:
            if key in obj and obj[key] not in (None, ""):
                return num(obj[key])
    return 0.0


def pick_text(data, keys: Iterable[str]):
    for obj in walk(data):
        for key in keys:
            value = obj.get(key)
            if value not in (None, ""):
                return str(value).strip()
    return ""


def first_list(data, keys: Iterable[str]):
    for obj in walk(data):
        for key in keys:
            value = obj.get(key)
            if isinstance(value, list):
                return value
    return []


def signed_value(value, sign):
    value = abs(num(value))
    if str(sign) in ("4", "5", "8", "9", "-", "▼"):
        return -value
    return value


def dataframe_rows(frame):
    if frame is None:
        return []
    if hasattr(frame, "to_dict"):
        try:
            return frame.to_dict("records")
        except TypeError:
            pass
    return frame if isinstance(frame, list) else []


class NHFeed:
    def __init__(self):
        self.quotes: Dict[str, Dict[str, Quote]] = {"KR": {}, "US": {}}
        self.connected = {"KR": False, "US": False}
        self.errors = {"KR": "", "US": ""}
        self.scan_index = {"KR": 0, "US": 0}
        self.code_lists = {"KR": [], "US": []}
        self.fixed = {
            "KR": self._env_codes("TRACKED_CODES", KR_DEFAULT_CODES),
            "US": self._env_codes("US_TRACKED_CODES", US_DEFAULT_CODES),
        }

        self.market = {}
        self.market_errors = {}
        self.market_updated_at = 0.0

        self._usdkrw = 0.0
        self.usdkrw_asof = ""
        self.usdkrw_source = ""

        self.index_symbols = {
            "sp500": os.getenv("NH_SP500_SYMBOL", "").strip(),
            "nasdaq": os.getenv("NH_NASDAQ_SYMBOL", "").strip(),
            "sox": os.getenv("NH_SOX_SYMBOL", "").strip(),
            "usdkrw": os.getenv("NH_USDKRW_SYMBOL", "").strip(),
        }

        self.future_symbols = {
            "kospi_night": os.getenv("NH_KOSPI_NIGHT_SYMBOL", "").strip(),
            "nasdaq_future": os.getenv("NH_NASDAQ_FUTURE_SYMBOL", "").strip(),
            "nasdaq_future_exnm": os.getenv(
                "NH_NASDAQ_FUTURE_EXNM",
                "FCME",
            ).strip() or "FCME",
        }

        self.nxt = {
            "session": "CLOSED",
            "label": "NXT 장외시간",
            "open": False,
            "updated_at": 0.0,
        }

        self.krx_series = {
            "kospi": [],
            "kosdaq": [],
        }

        self._stop = threading.Event()

    @staticmethod
    def _env_codes(key, defaults):
        configured = [
            x.strip().upper()
            for x in os.getenv(key, "").split(",")
            if x.strip()
        ]
        return configured or list(defaults)

    def quotes_for(self, market: str):
        return self.quotes[
            "US"
            if str(market).upper() == "US"
            else "KR"
        ]

    def connected_any(self):
        return any(self.connected.values())

    def q(self, market: str, code: str):
        market = (
            "US"
            if str(market).upper() == "US"
            else "KR"
        )

        code = str(code).strip().upper()
        bucket = self.quotes[market]

        if code not in bucket:
            bucket[code] = Quote(
                code,
                code,
            )

        return bucket[code]

    # ---------- NXT ----------

    def update_nxt_session(self):
        now = datetime.now(KST)

        if now.weekday() >= 5:
            session, label, opened = (
                "CLOSED",
                "NXT 휴장",
                False,
            )

        else:
            mins = (
                now.hour * 60
                + now.minute
                + now.second / 60
            )

            if 480 <= mins < 530:
                session, label, opened = (
                    "PRE",
                    "NXT 프리마켓",
                    True,
                )

            elif 530 <= mins < 540.5:
                session, label, opened = (
                    "BREAK",
                    "NXT 메인마켓 대기",
                    False,
                )

            elif 540.5 <= mins < 920:
                session, label, opened = (
                    "MAIN",
                    "NXT 메인마켓",
                    True,
                )

            elif 920 <= mins < 940:
                session, label, opened = (
                    "AFTER_WAIT",
                    "NXT 애프터마켓 대기",
                    False,
                )

            elif 940 <= mins < 1200:
                session, label, opened = (
                    "AFTER",
                    "NXT 애프터마켓",
                    True,
                )

            else:
                session, label, opened = (
                    "CLOSED",
                    "NXT 장외시간",
                    False,
                )

        self.nxt = {
            "session": session,
            "label": label,
            "open": opened,
            "updated_at": time.time(),
        }

    def session_state(self, market: str):
        if str(market).upper() == "US":
            return None

        self.update_nxt_session()

        return {
            "name": "NXT",
            "session": self.nxt["session"],
            "label": self.nxt["label"],
            "open": self.nxt["open"],
            "status": (
                "거래중"
                if self.nxt["open"]
                else "대기/종료"
            ),
            "updated_at": self.nxt["updated_at"],
        }

    def _market_order(self):
        self.update_nxt_session()

        if self.nxt["session"] in (
            "PRE",
            "AFTER",
        ):
            return (
                "NXT",
                "KRX",
            )

        if self.nxt["session"] == "MAIN":
            return (
                "KRX",
                "NXT",
            )

        return ("KRX",)

    # ---------- strict US FX ----------

    @staticmethod
    def _expected_us_trade_date(now=None):
        now = (
            now.astimezone(KST)
            if now
            else datetime.now(KST)
        )

        if now.hour < 6:
            now -= timedelta(days=1)

        return now.strftime("%Y%m%d")

    def _usdkrw_is_tradeable(self, now=None):
        asof = str(
            self.usdkrw_asof
            or ""
        )[:8]

        return (
            800
            <= float(self._usdkrw or 0)
            <= 2500
            and len(asof) == 8
            and asof.isdigit()
            and asof
            == self._expected_us_trade_date(now)
        )

    @property
    def usdkrw(self):
        return (
            float(self._usdkrw)
            if self._usdkrw_is_tradeable()
            else 0.0
        )

    @usdkrw.setter
    def usdkrw(self, value):
        self._usdkrw = float(
            value
            or 0
        )

    @property
    def usdkrw_tradeable(self):
        return self._usdkrw_is_tradeable()

    def _update_us_fx_from_current(self, data):
        rate = pick(
            data,
            (
                "currency_prc",
                "fx_rate",
            ),
        )

        asof = pick_text(
            data,
            (
                "trade_date",
                "bsop_date",
                "date",
            ),
        )[:8]

        unit = pick_text(
            data,
            (
                "currency_unit",
                "cur_cd",
            ),
        ).upper()

        if unit and unit != "USD":
            return

        if not (
            800
            <= rate
            <= 2500
        ):
            return

        if (
            len(asof) != 8
            or not asof.isdigit()
        ):
            return

        self._usdkrw = float(rate)
        self.usdkrw_asof = asof
        self.usdkrw_source = (
            "NHPLUG 해외주식 현재가"
        )

    # ---------- quote parsing ----------

    def _apply_kr(self, code, data):
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
            q.execution_strength = strength

    def _apply_us(self, code, data):
        q = self.q(
            "US",
            code,
        )

        name = pick_text(
            data,
            (
                "kor_name",
                "hts_kor_isnm",
                "iem_nm",
            ),
        )

        if name:
            q.name = name

        sector = pick_text(
            data,
            (
                "industry_name",
                "industry_code",
            ),
        )

        if sector:
            q.sector = sector

        price = pick(
            data,
            (
                "trdprc",
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
                "acvol",
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
                    "open_prc",
                    "ovrs_oprc",
                    "open",
                ),
            )
            or q.open
        )

        q.high = (
            pick(
                data,
                (
                    "high",
                    "ovrs_hgpr",
                    "high_prc",
                ),
            )
            or q.high
        )

        q.low = (
            pick(
                data,
                (
                    "low",
                    "ovrs_lwpr",
                    "low_prc",
                ),
            )
            or q.low
        )

        q.per = (
            pick(
                data,
                (
                    "per_prc",
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

        self._update_us_fx_from_current(data)

    # ---------- masters ----------

    def _load_kr_master(self):
        try:
            from nhplug.instruments import load_master

            rows = dataframe_rows(
                load_master(
                    "m_new_stock"
                )
            )

            wanted = set(
                self.fixed["KR"]
            )

            for row in rows:
                raw = str(
                    row.get("shrn_iscd")
                    or row.get("sCode")
                    or row.get("code")
                    or ""
                ).strip()

                m = re.search(
                    r"(\d{6})",
                    raw,
                )

                if (
                    not m
                    or m.group(1)
                    not in wanted
                ):
                    continue

                code = m.group(1)

                q = self.q(
                    "KR",
                    code,
                )

                q.name = str(
                    row.get("hts_kor_isnm")
                    or row.get("name")
                    or row.get("sKorName")
                    or code
                ).lstrip(
                    "*#"
                ).strip()

                q.sector = str(
                    row.get("bstp_medm_div_code")
                    or row.get("industry_group")
                    or ""
                ).strip()

            self.code_lists["KR"] = (
                self.fixed["KR"][:]
            )

        except Exception as exc:
            self.errors["KR"] = (
                f"국내 종목마스터: {exc}"
            )[:300]

            self.code_lists["KR"] = (
                self.fixed["KR"][:]
            )

    def _load_us_master(self):
        try:
            from nhplug.instruments import load_master

            rows = dataframe_rows(
                load_master(
                    "m_gtsstock"
                )
            )

            wanted = set(
                self.fixed["US"]
            )

            for row in rows:
                symbol = str(
                    row.get("symbol")
                    or row.get("sSymbol")
                    or ""
                ).strip().upper()

                if symbol not in wanted:
                    continue

                q = self.q(
                    "US",
                    symbol,
                )

                q.name = str(
                    row.get("kor_name")
                    or row.get("eng_name")
                    or row.get("sKorName")
                    or row.get("sEngName")
                    or symbol
                ).strip()

                industry = str(
                    row.get("industry_group")
                    or row.get("gIndustryReuter")
                    or ""
                ).strip()

                q.sector = (
                    f"업종 {industry}"
                    if industry
                    else "미국주식"
                )

            self.code_lists["US"] = (
                self.fixed["US"][:]
            )

        except Exception as exc:
            self.errors["US"] = (
                f"해외 종목마스터: {exc}"
            )[:300]

            self.code_lists["US"] = (
                self.fixed["US"][:]
            )

    def _discover_futures(self):
        try:
            from nhplug.instruments import load_master

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
                        row.get("code")
                        or row.get("sCode")
                        or ""
                    ).strip().upper()

                    name = str(
                        row.get("name")
                        or row.get("sName")
                        or ""
                    ).strip()

                    if code.startswith("KA"):
                        fallback.append(code)

                    normalized = re.sub(
                        r"\s+",
                        "",
                        name,
                    ).upper()

                    if (
                        code.startswith("KA")
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
                    ] = fallback[0]

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
                        row.get("isym")
                        or row.get("InnerSymbol")
                        or row.get("symb")
                        or row.get("Symbol")
                        or ""
                    ).strip().upper()

                    name = str(
                        row.get("enam")
                        or row.get("EngName")
                        or ""
                    ).strip()

                    exnm = str(
                        row.get("exnm")
                        or row.get("ExchName")
                        or "FCME"
                    ).strip().upper() or "FCME"

                    lead = str(
                        row.get("ledm")
                        or row.get("Leadmonth")
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
                    ) = candidates[0]

                    self.future_symbols[
                        "nasdaq_future"
                    ] = symbol

                    self.future_symbols[
                        "nasdaq_future_exnm"
                    ] = exnm

        except Exception as exc:
            self.market_errors[
                "future_master"
            ] = str(exc)[:300]

    # ---------- scanners ----------

    def kr_scanner(self):
        self._load_kr_master()

        codes = (
            self.code_lists["KR"]
            or self.fixed["KR"]
        )

        from nhplug import call

        while not self._stop.is_set():
            code = codes[
                self.scan_index["KR"]
                % len(codes)
            ]

            self.scan_index["KR"] = (
                self.scan_index["KR"] + 1
            ) % len(codes)

            last_error = ""

            for market_cd in (
                self._market_order()
            ):
                try:
                    data = call(
                        "/krstock/quote/v1/currentPrice",
                        {
                            "iem_cd": code,
                            "market_cd": market_cd,
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
                        time.sleep(1.5)
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

            time.sleep(0.35)

    def us_scanner(self):
        self._load_us_master()

        codes = (
            self.code_lists["US"]
            or self.fixed["US"]
        )

        from nhplug import call

        while not self._stop.is_set():
            code = codes[
                self.scan_index["US"]
                % len(codes)
            ]

            self.scan_index["US"] = (
                self.scan_index["US"] + 1
            ) % len(codes)

            try:
                data = call(
                    "/gbstock/quote/v1/current",
                    {
                        "iem_cd": code
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
                    time.sleep(1.5)

            time.sleep(0.5)

    # ---------- market card ----------

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
            "label": label,
            "value": value,
            "change": change,
            "change_pct": change_pct,
            "status": status,
            "source": source,
            "series": list(
                series
                or []
            ),
            "asof": asof,
        }

    # ---------- KRX KOSPI/KOSDAQ ----------

    def _krx_home_text(self):
        urls = (
            "https://global.krx.co.kr/",
            "https://global.krx.co.kr/cn/main/main.jsp",
        )

        headers = {
            "User-Agent":
                (
                    "Mozilla/5.0 "
                    "(Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 "
                    "Chrome/131 Safari/537.36"
                ),

            "Accept-Language":
                "en-US,en;q=0.9,ko;q=0.8",
        }

        last_error = None

        for url in urls:
            try:
                response = requests.get(
                    url,
                    headers=headers,
                    timeout=8,
                )

                response.raise_for_status()

                text = (
                    html_lib.unescape(
                        re.sub(
                            r"<[^>]+>",
                            " ",
                            response.text,
                        )
                    )
                )

                text = re.sub(
                    r"\s+",
                    " ",
                    text,
                ).strip()

                if (
                    "KOSPI"
                    in text
                    and "KOSDAQ"
                    in text
                ):
                    return text

            except Exception as exc:
                last_error = exc

        raise RuntimeError(
            "KRX Global 홈페이지 조회 실패: "
            f"{last_error}"
        )

    @staticmethod
    def _parse_krx_home_index(
        text,
        label,
    ):
        pattern = re.compile(
            rf"\b{re.escape(label)}\b"
            r"\s*"
            r"([\d,]+(?:\.\d+)?)"
            r"\s*"
            r"([▲▼]?)"
            r"\s*"
            r"([\d,]+(?:\.\d+)?)?"
            r"\s*"
            r"(?:\s*([\d.]+)\s*)?",
            re.IGNORECASE,
        )

        m = pattern.search(text)

        if not m:
            raise RuntimeError(
                f"{label} 값 파싱 실패"
            )

        value = num(
            m.group(1)
        )

        sign = (
            m.group(2)
            or ""
        )

        change = num(
            m.group(3)
        )

        change_pct = num(
            m.group(4)
        )

        if sign == "▼":
            change = -abs(change)
            change_pct = -abs(
                change_pct
            )

        elif sign == "▲":
            change = abs(change)
            change_pct = abs(
                change_pct
            )

        if value <= 0:
            raise RuntimeError(
                f"{label} 값이 0 이하"
            )

        return (
            value,
            change,
            change_pct,
        )

    def _krx_status(self):
        now = datetime.now(KST)

        if (
            now.weekday() < 5
            and 540
            <= (
                now.hour * 60
                + now.minute
            )
            <= 930
        ):
            return "장중 공식값"

        return "최근 종가"

    def _update_krx_series(
        self,
        key,
        value,
        change,
    ):
        series = self.krx_series[key]

        if not series:
            previous = (
                value - change
                if change
                else value
            )

            if previous > 0:
                series.append(
                    round(
                        previous,
                        4,
                    )
                )

        if (
            not series
            or abs(
                series[-1]
                - value
            )
            > 1e-9
        ):
            series.append(
                round(
                    value,
                    4,
                )
            )

        self.krx_series[key] = (
            series[-60:]
        )

        return list(
            self.krx_series[key]
        )

    def _read_krx_indices(self):
        text = self._krx_home_text()
        status = self._krx_status()

        out = {}

        for (
            key,
            raw_label,
            display_label,
        ) in (
            (
                "kospi",
                "KOSPI",
                "코스피",
            ),
            (
                "kosdaq",
                "KOSDAQ",
                "코스닥",
            ),
        ):
            (
                value,
                change,
                change_pct,
            ) = (
                self._parse_krx_home_index(
                    text,
                    raw_label,
                )
            )

            series = (
                self._update_krx_series(
                    key,
                    value,
                    change,
                )
            )

            out[key] = (
                self._market_item(
                    display_label,
                    value,
                    change,
                    change_pct,
                    status,
                    "KRX 공식",
                    series,
                    "",
                )
            )

        return out

    def krx_loop(self):
        while not self._stop.is_set():
            try:
                self.market.update(
                    self._read_krx_indices()
                )

                self.market_errors.pop(
                    "krx_indices",
                    None,
                )

            except Exception as exc:
                self.market_errors[
                    "krx_indices"
                ] = str(exc)[:500]

            self.market_updated_at = (
                time.time()
            )

            time.sleep(60)

    # ---------- NHPLUG overseas indices ----------

    def _symbol_candidates(self, key):
        configured = (
            self.index_symbols.get(
                key,
                "",
            )
        )

        defaults = {
            "sp500": [
                "SPX",
                "N@SPX",
            ],

            "nasdaq": [
                "COMP",
                "IXIC",
                "NDX",
                "N@IXIC",
            ],

            "sox": [
                "SOX",
                "PHLXSOX",
                "N@SOX",
            ],

            "usdkrw": [
                "USDKRW",
                "KRW",
                "X@KRW",
            ],
        }

        values = (
            [configured]
            if configured
            else []
        )

        for item in defaults.get(
            key,
            [],
        ):
            if item not in values:
                values.append(item)

        return values

    def _read_symbol_period_one(
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
                "close_prc",
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

        change = signed_value(
            pick(
                data,
                (
                    "prdy_vrss",
                    "change",
                ),
            ),
            sign,
        )

        change_pct = signed_value(
            pick(
                data,
                (
                    "prdy_ctrt",
                    "change_rate",
                ),
            ),
            sign,
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
                row.get("close_prc")
                or row.get("ovrs_prpr")
                or row.get("close")
                or row.get("last")
            )

            if v:
                series.append(v)

            if not asof:
                raw_date = str(
                    row.get("bsop_date")
                    or row.get("xymd")
                    or row.get("date")
                    or row.get("bas_dt")
                    or row.get("stck_bsop_date")
                    or ""
                )

                if (
                    len(raw_date) >= 8
                    and raw_date[:8].isdigit()
                ):
                    asof = raw_date[:8]

        if not asof:
            raw_date = pick_text(
                data,
                (
                    "bsop_date",
                    "qry_date",
                ),
            )

            if (
                len(raw_date) >= 8
                and raw_date[:8].isdigit()
            ):
                asof = raw_date[:8]

        if (
            not value
            and series
        ):
            value = series[0]

        if value <= 0:
            raise RuntimeError(
                f"{label} value missing "
                f"for {symbol}"
            )

        if not asof:
            asof = today

        return self._market_item(
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
                reversed(series)
            ),
            asof,
        )

    def _read_symbol_period(
        self,
        key,
        label,
        status="종가 기준",
    ):
        errors = []

        for symbol in (
            self._symbol_candidates(key)
        ):
            try:
                item = (
                    self._read_symbol_period_one(
                        symbol,
                        label,
                        status,
                    )
                )

                self.index_symbols[
                    key
                ] = symbol

                return item

            except Exception as exc:
                errors.append(
                    f"{symbol}: "
                    f"{exc}"
                )

        raise RuntimeError(
            " | ".join(
                errors
            )[-900:]
        )

    def _read_sox_nasdaq(self):
        url = (
            "https://indexes.nasdaq.com/"
            "Index/Overview/SOX"
        )

        headers = {
            "User-Agent":
                (
                    "Mozilla/5.0 "
                    "(Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 "
                    "Chrome/131 Safari/537.36"
                ),

            "Accept-Language":
                "en-US,en;q=0.9",
        }

        response = requests.get(
            url,
            headers=headers,
            timeout=10,
        )

        response.raise_for_status()

        text = (
            html_lib.unescape(
                re.sub(
                    r"<[^>]+>",
                    " ",
                    response.text,
                )
            )
        )

        text = re.sub(
            r"\s+",
            " ",
            text,
        ).strip()

        m = re.search(
            r"DATA\s+AS\s+OF\s+"
            r"(\d{1,2}/\d{1,2}/\d{4})"
            r"\s+"
            r"([\d,]+(?:\.\d+)?)"
            r"\s+"
            r"([+-]?[\d,]+(?:\.\d+)?)"
            r"\s+"
            r"([+-]?[\d.]+)%",
            text,
            re.IGNORECASE,
        )

        if m:
            (
                date_text,
                raw_value,
                raw_change,
                raw_pct,
            ) = m.groups()

            value = num(raw_value)
            change = num(raw_change)
            change_pct = num(raw_pct)

        else:
            date_match = re.search(
                r"DATA\s+AS\s+OF\s+"
                r"(\d{1,2}/\d{1,2}/\d{4})",
                text,
                re.IGNORECASE,
            )

            value_match = re.search(
                r"\bLast\b"
                r"\s*\|?\s*"
                r"([\d,]+(?:\.\d+)?)",
                text,
                re.IGNORECASE,
            )

            change_match = re.search(
                r"\bNet\s+Change\b"
                r"(?!\s*%)"
                r"\s*\|?\s*"
                r"([+-]?[\d,]+(?:\.\d+)?)",
                text,
                re.IGNORECASE,
            )

            pct_match = re.search(
                r"Net\s+Change\s*%"
                r"\s*\|?\s*"
                r"([+-]?[\d.]+)%?",
                text,
                re.IGNORECASE,
            )

            if not (
                date_match
                and value_match
                and change_match
                and pct_match
            ):
                raise RuntimeError(
                    "Nasdaq SOX 공식값 파싱 실패"
                )

            date_text = (
                date_match.group(1)
            )

            value = num(
                value_match.group(1)
            )

            change = num(
                change_match.group(1)
            )

            change_pct = num(
                pct_match.group(1)
            )

        if value <= 0:
            raise RuntimeError(
                "Nasdaq SOX 값이 0 이하"
            )

        asof = datetime.strptime(
            date_text,
            "%m/%d/%Y",
        ).strftime(
            "%Y%m%d"
        )

        previous = (
            value - change
        )

        series = (
            [
                previous,
                value,
            ]
            if previous > 0
            else [
                value
            ]
        )

        return self._market_item(
            "필라델피아 반도체지수",
            value,
            change,
            change_pct,
            (
                "공식값 · "
                f"{asof[:4]}-"
                f"{asof[4:6]}-"
                f"{asof[6:]}"
            ),
            "Nasdaq 공식",
            series,
            asof,
        )

    def _read_fx(self):
        rate = self.usdkrw

        if rate <= 0:
            raise RuntimeError(
                "NHPLUG 미국 현재가의 "
                "당일 USD/KRW 환율 "
                "수신 대기 "
                f"(asof="
                f"{self.usdkrw_asof or '-'})"
            )

        return self._market_item(
            "USD/KRW",
            rate,
            None,
            None,
            (
                "당일 공식환율 · "
                f"{self.usdkrw_asof[:4]}-"
                f"{self.usdkrw_asof[4:6]}-"
                f"{self.usdkrw_asof[6:]}"
            ),
            (
                self.usdkrw_source
                or "NHPLUG"
            ),
            [],
            self.usdkrw_asof,
        )

    # ---------- futures ----------

    def _read_kospi_night(self):
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

        change = signed_value(
            pick(
                data,
                (
                    "vrss",
                ),
            ),
            sign,
        )

        change_pct = signed_value(
            pick(
                data,
                (
                    "ctrt",
                ),
            ),
            sign,
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
        )

        return self._market_item(
            "코스피 야간선물",
            value,
            change,
            change_pct,
            "실시간",
            "NHPLUG",
            (
                old
                + [
                    value
                ]
            )[-30:],
            datetime.now(
                KST
            ).strftime(
                "%Y%m%d"
            ),
        )

    def _read_nasdaq_future(self):
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

        change = signed_value(
            pick(
                data,
                (
                    "diff",
                ),
            ),
            sign,
        )

        change_pct = signed_value(
            pick(
                data,
                (
                    "rate",
                ),
            ),
            sign,
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
        )

        return self._market_item(
            "나스닥 선물",
            value,
            change,
            change_pct,
            "실시간",
            "NHPLUG",
            (
                old
                + [
                    value
                ]
            )[-30:],
            datetime.now(
                KST
            ).strftime(
                "%Y%m%d"
            ),
        )

    # ---------- loops ----------

    def reference_loop(self):
        while not self._stop.is_set():

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
            ):
                try:
                    self.market[
                        key
                    ] = (
                        self._read_symbol_period(
                            key,
                            label,
                        )
                    )

                    self.market_errors.pop(
                        key,
                        None,
                    )

                except Exception as exc:
                    self.market_errors[
                        key
                    ] = str(exc)[:500]

            try:
                try:
                    self.market[
                        "sox"
                    ] = (
                        self._read_symbol_period(
                            "sox",
                            "필라델피아 반도체지수",
                        )
                    )

                except Exception:
                    self.market[
                        "sox"
                    ] = (
                        self._read_sox_nasdaq()
                    )

                self.market_errors.pop(
                    "sox",
                    None,
                )

            except Exception as exc:
                self.market_errors[
                    "sox"
                ] = str(exc)[:500]

            try:
                self._read_fx()

                self.market_errors.pop(
                    "usdkrw",
                    None,
                )

            except Exception as exc:
                self.market_errors[
                    "usdkrw"
                ] = str(exc)[:500]

            self.market_updated_at = (
                time.time()
            )

            time.sleep(60)

    def futures_loop(self):
        self._discover_futures()

        while not self._stop.is_set():

            try:
                self.market[
                    "kospi_night"
                ] = (
                    self._read_kospi_night()
                )

                self.market_errors.pop(
                    "kospi_night",
                    None,
                )

            except Exception as exc:
                self.market_errors[
                    "kospi_night"
                ] = str(exc)[:300]

            try:
                self.market[
                    "nasdaq_future"
                ] = (
                    self._read_nasdaq_future()
                )

                self.market_errors.pop(
                    "nasdaq_future",
                    None,
                )

            except Exception as exc:
                self.market_errors[
                    "nasdaq_future"
                ] = str(exc)[:300]

            self.market_updated_at = (
                time.time()
            )

            time.sleep(15)

    # ---------- API state ----------

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

        status = (
            f"수신 오류 · "
            f"{err[:100]}"
            if err
            else "수신 대기"
        )

        return self._market_item(
            label,
            None,
            None,
            None,
            status,
            source,
            [],
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

    def health(self):
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
                    for q
                    in self.quotes[
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
                    for q
                    in self.quotes[
                        "US"
                    ].values()
                    if q.price > 0
                ),

            "market_updated_at":
                self.market_updated_at,

            "market_errors":
                dict(
                    self.market_errors
               
