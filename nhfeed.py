from __future__ import annotations

import os
import time
import threading
import re
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Dict

from engine import Quote


KST = ZoneInfo("Asia/Seoul")


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
            v = str(d.get(k, ""))

            m = re.search(
                r"\b(\d{6})\b",
                v,
            )

            if m:
                return m.group(1)

    return ""


def signed_value(value, sign):
    value = abs(num(value))

    if str(sign) in ("4", "5", "8", "9"):
        return -value

    return value


class NHFeed:

    def __init__(self):

        self.quotes: Dict[str, Quote] = {}

        self.connected = False
        self.error = ""

        self.fixed = [
            x.strip()
            for x in os.getenv(
                "TRACKED_CODES",
                "",
            ).split(",")
            if x.strip()
        ]

        self.all_codes = []
        self.scan_index = 0

        # UNT = KRX + NXT 통합시세
        self.stock_market_cd = os.getenv(
            "NH_STOCK_MARKET_CD",
            "UNT",
        ).strip().upper()

        if self.stock_market_cd not in (
            "KRX",
            "NXT",
            "UNT",
        ):
            self.stock_market_cd = "UNT"

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


    # ----------------------------------------------------
    # NXT SESSION
    # ----------------------------------------------------

    def update_nxt_session(self):

        now = datetime.now(KST)

        # 주말
        if now.weekday() >= 5:
            self.nxt = {
                "session": "CLOSED",
                "label": "NXT 휴장",
                "open": False,
                "updated_at": time.time(),
            }
            return

        mins = (
            now.hour * 60
            + now.minute
            + now.second / 60
        )

        # 프리마켓
        if 8 * 60 <= mins < 8 * 60 + 50:

            session = "PRE"
            label = "NXT 프리마켓"
            opened = True

        # 08:50 ~ 09:00:30
        elif (
            8 * 60 + 50
            <= mins
            < 9 * 60 + 0.5
        ):

            session = "BREAK"
            label = "NXT 메인마켓 대기"
            opened = False

        # 메인마켓
        elif (
            9 * 60 + 0.5
            <= mins
            < 15 * 60 + 20
        ):

            session = "MAIN"
            label = "NXT 메인마켓"
            opened = True

        # 애프터 호가접수/대기
        elif (
            15 * 60 + 20
            <= mins
            < 15 * 60 + 40
        ):

            session = "AFTER_WAIT"
            label = "NXT 애프터마켓 대기"
            opened = False

        # 애프터마켓
        elif (
            15 * 60 + 40
            <= mins
            < 20 * 60
        ):

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


    # ----------------------------------------------------
    # STOCK
    # ----------------------------------------------------

    def q(self, code):

        if code not in self.quotes:
            self.quotes[code] = Quote(
                code,
                code,
            )

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
                price,
                volume,
            )

        q.open = (
            pick(
                data,
                (
                    "stck_oprc",
                    "open",
                ),
            )
            or q.open
        )

        q.high = (
            pick(
                data,
                (
                    "stck_hgpr",
                    "high",
                ),
            )
            or q.high
        )

        q.low = (
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
                    if "code" in c.lower()
                    or "단축" in c
                    or "종목코드" in c
                ),
                None,
            )

            name_col = next(
                (
                    c
                    for c in cols
                    if "name" in c.lower()
                    or "종목명" in c
                    or "한글" in c
                ),
                None,
            )

            sector_col = next(
                (
                    c
                    for c in cols
                    if "업종" in c
                    or "sector" in c.lower()
                    or "industry" in c.lower()
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

            self.all_codes = list(
                dict.fromkeys(arr)
            )

        except Exception as e:

            self.error = (
                f"master: {e}"
            )

            self.all_codes = (
                self.fixed[:]
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
                self.scan_index + 1
            ) % len(codes)

            try:

                # UNT = KRX / NXT 통합시세
                data = call(
                    "/krstock/quote/v1/currentPrice",
                    {
                        "iem_cd": code,
                        "market_cd": self.stock_market_cd,
                    },
                )

                self._apply(
                    code,
                    data,
                )

            except Exception as e:

                self.error = str(e)[:300]

                if "429" in self.error:
                    time.sleep(1)

            time.sleep(0.28)


    def priority(self):

        rows = []

        # dict 변경 중 iteration 오류 방지
        for code, q in list(
            self.quotes.items()
        ):

            if q.price <= 0:
                continue

            change = (
                abs(
                    (
                        q.price / q.open
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

        from nhplug.realtime import subscribe

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


    # ----------------------------------------------------
    # INDEX
    # ----------------------------------------------------

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

            self.update_nxt_session()

            new_market = {}
            errors = {}

            nasdaq_symbol = os.getenv(
                "NH_NASDAQ_SYMBOL",
                "",
            ).strip()

            sox_symbol = os.getenv(
                "NH_SOX_SYMBOL",
                "",
            ).strip()

            nasdaq_future_symbol = os.getenv(
                "NH_NASDAQ_FUTURE_SYMBOL",
                "",
            ).strip()

            kospi_night_symbol = os.getenv(
                "NH_KOSPI_NIGHT_SYMBOL",
                "",
            ).strip()

            if nasdaq_symbol:
                try:

                    new_market["nasdaq"] = (
                        self._read_overseas_index(
                            nasdaq_symbol,
                            "나스닥",
                        )
                    )

                except Exception as e:
                    errors["nasdaq"] = (
                        str(e)[:200]
                    )

            if sox_symbol:
                try:

                    new_market["sox"] = (
                        self._read_overseas_index(
                            sox_symbol,
                            "필라델피아 반도체",
                        )
                    )

                except Exception as e:
                    errors["sox"] = (
                        str(e)[:200]
                    )

            if nasdaq_future_symbol:
                try:

                    new_market["nasdaq_future"] = (
                        self._read_overseas_index(
                            nasdaq_future_symbol,
                            "나스닥 선물",
                        )
                    )

                except Exception as e:
                    errors[
                        "nasdaq_future"
                    ] = str(e)[:200]

            if kospi_night_symbol:
                try:

                    new_market["kospi_night"] = (
                        self._read_overseas_index(
                            kospi_night_symbol,
                            "코스피 야간선물",
                        )
                    )

                except Exception as e:
                    errors[
                        "kospi_night"
                    ] = str(e)[:200]

            self.market.update(
                {
                    k: v
                    for k, v
                    in new_market.items()
                    if v
                }
            )

            self.market_errors = errors
            self.market_updated_at = time.time()

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

            self.market.get("kospi")
            or self._market_item(
                "코스피",
                None,
                None,
                None,
                "NHPLUG 국내지수 연결 준비",
            ),

            self.market.get("kosdaq")
            or self._market_item(
                "코스닥",
                None,
                None,
                None,
                "NHPLUG 국내지수 연결 준비",
            ),

            # NXT 상태 카드
            self._market_item(
                "NXT",
                self.nxt["session"],
                None,
                None,
                nxt_status,
            ),

            self.market.get("kospi_night")
            or self._market_item(
                "코스피 야간선물",
                None,
                None,
                None,
                "NHPLUG 야간선물 심볼 확인중",
            ),

            self.market.get("nasdaq")
            or self._market_item(
                "나스닥",
                None,
                None,
                None,
                "NHPLUG 지수 심볼 설정 필요",
            ),

            self.market.get("sox")
            or self._market_item(
                "필라델피아 반도체",
                None,
                None,
                None,
                "NHPLUG 지수 심볼 설정 필요",
            ),

            self.market.get("nasdaq_future")
            or self._market_item(
                "나스닥 선물",
                None,
                None,
                None,
                "NHPLUG 선물 심볼 설정 필요",
            ),
        ]


    # ----------------------------------------------------
    # START
    # ----------------------------------------------------

    def start(self):

        threading.Thread(
            target=self.scanner,
            daemon=True,
        ).start()

        threading.Thread(
            target=self.websocket,
            daemon=True,
        ).start()

        threading.Thread(
            target=self.market_loop,
            daemon=True,
        ).start()
