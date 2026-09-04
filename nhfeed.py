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
        return float(str(v).replace(",", "").replace("+", "").strip())
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
        for k in ("iem_cd", "stck_shrn_iscd", "code", "symbol", "tr_key"):
            m = re.search(r"\b(\d{6})\b", str(d.get(k, "")))
            if m:
                return m.group(1)
    return ""


def signed_value(value, sign):
    value = abs(num(value))
    if str(sign) in ("4", "5", "8", "9"):
        return -value
    return value


def _plain_html(raw: str) -> str:
    raw = re.sub(r"(?is)<script.*?</script>", " ", raw)
    raw = re.sub(r"(?is)<style.*?</style>", " ", raw)
    raw = re.sub(r"(?s)<[^>]+>", " ", raw)
    raw = html.unescape(raw)
    return re.sub(r"\s+", " ", raw).strip()


def _parse_krx_index(text: str, label: str):
    pattern = re.compile(
        rf"\b{re.escape(label)}\b\s*"
        r"([\d,]+(?:\.\d+)?)\s*"
        r"([▲▼])\s*"
        r"([\d,]+(?:\.\d+)?)\s*"
        r"\(\s*([\d.]+)\s*\)"
    )

    m = pattern.search(text)

    if not m:
        return None

    value = num(m.group(1))
    sign = -1 if m.group(2) == "▼" else 1
    change = sign * num(m.group(3))
    change_pct = sign * num(m.group(4))

    return value, change, change_pct


class NHFeed:
    def __init__(self):
        self.quotes: Dict[str, Quote] = {}
        self.connected = False
        self.error = ""

        configured = [
            x.strip()
            for x in os.getenv("TRACKED_CODES", "").split(",")
            if x.strip()
        ]

        self.fixed = configured or DEFAULT_CODES[:]
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

    def update_nxt_session(self):
        now = datetime.now(KST)

        if now.weekday() >= 5:
            self.nxt = {
                "session": "CLOSED",
                "label": "NXT 휴장",
                "open": False,
                "updated_at": time.time(),
            }
            return

        mins = now.hour * 60 + now.minute + now.second / 60

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

    def q(self, code):
        if code not in self.quotes:
            self.quotes[code] = Quote(code, code)

        return self.quotes[code]

    def _apply(self, code, data):
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
            q.execution_strength = strength

    def load_master(self):
        try:
            from nhplug.instruments import load_master

            df = load_master("m_new_stock")

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
                for _, row in df.iterrows():
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

                    code = m.group(1)
                    q = self.q(code)

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

                    arr.append(code)

            self.all_codes = (
                list(
                    dict.fromkeys(
                        arr
                    )
                )
                or self.fixed[:]
            )

        except Exception as e:
            self.error = f"master: {e}"
            self.all_codes = self.fixed[:]

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
                self.scan_index + 1
            ) % len(codes)

            success = False
            last_error = ""

            for market_cd in self._market_order():
                try:
                    data = call(
                        "/krstock/quote/v1/currentPrice",
                        {
                            "iem_cd": code,
                            "market_cd": market_cd,
                        },
                    )

                    self._apply(
                        code,
                        data,
                    )

                    if self.q(code).price > 0:
                        self.error = ""
                        success = True
                        break

                except Exception as e:
                    last_error = (
                        f"{market_cd} {code}: {e}"
                    )[:300]

                    if "429" in last_error:
                        time.sleep(1)
                        break

            if (
                not success
                and last_error
            ):
                self.error = last_error

            time.sleep(0.28)

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

        rows.sort(reverse=True)

        out = [
            code
            for _, code
            in rows[:20]
        ]

        for code in self.fixed:
            if code not in out:
                out.append(code)

            if len(out) >= 20:
                break

        return out[:20]

    def on_tick(self, msg):
        code = code_of(msg)

        if not code:
            return

        self._apply(
            code,
            msg,
        )

        self.connected = True

    def websocket(self):
        try:
            from nhplug.realtime import subscribe

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
                self.connected = False
                self.error = str(e)[:300]
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
            "label": label,
            "value": value,
            "change": change,
            "change_pct": change_pct,
            "status": status,
        }

    def _read_krx_indices(self):
        response = requests.get(
            "https://index.krx.co.kr/",
            timeout=10,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Linux; Android 14) "
                    "AppleWebKit/537.36 Chrome/126 Safari/537.36"
                ),
                "Accept-Language":
                    "ko-KR,ko;q=0.9,en;q=0.8",
            },
        )

        response.raise_for_status()

        text = _plain_html(
            response.text
        )

        out = {}

        for (
            key,
            label,
        ) in (
            (
                "kospi",
                "KOSPI",
            ),
            (
                "kosdaq",
                "KOSDAQ",
            ),
        ):
            parsed = _parse_krx_index(
                text,
                label,
            )

            if not parsed:
                raise RuntimeError(
                    f"KRX {label} parse failed"
                )

            (
                value,
                change,
                change_pct,
            ) = parsed

            out[key] = self._market_item(
                (
                    "코스피"
                    if key == "kospi"
                    else "코스닥"
                ),
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
                "iem_cd": symbol,
                "end_dt": today,
                "array_cnt": "0002",
                "maxavg": "020",
                "gubun": "1",
                "xtick": "001",
                "today_cls": "0",
                "scale_change": "0",
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

        change_pct = signed_value(
            pick(
                data,
                (
                    "prdy_ctrt",
                ),
            ),
            sign,
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

    def market_loop(self):
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
                    ] = str(e)[:200]

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
                        ] = str(e)[:200]

                self.market.update(
                    new_market
                )

                self.market_errors = errors
                self.market_updated_at = (
                    time.time()
                )

            except Exception as e:
                self.market_errors[
                    "market_loop"
                ] = str(e)[:200]

            time.sleep(30)

    def market_state(self):
        self.update_nxt_session()

        nxt_status = (
            self.nxt["label"]
            + (
                " · 거래중"
                if self.nxt["open"]
                else " · 대기/종료"
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
                "KRX 지수 수신 대기",
            ),

            self.market.get(
                "kosdaq"
            )
            or self._market_item(
                "코스닥",
                None,
                None,
                None,
                "KRX 지수 수신 대기",
            ),

            self._market_item(
                "NXT",
                self.nxt["session"],
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
