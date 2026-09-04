from __future__ import annotations

import os
import time
import threading
import re
from datetime import datetime, timezone, timedelta
from typing import Dict

from engine import Quote


KST = timezone(timedelta(hours=9))


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

            if (
                k in d
                and d[k] not in (None, "")
            ):
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

            v = str(
                d.get(k, "")
            )

            m = re.search(
                r"\b(\d{6})\b",
                v,
            )

            if m:
                return m.group(1)

    return ""


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


        # KRX + NXT 통합시세
        self.stock_market_cd = (
            os.getenv(
                "NH_STOCK_MARKET_CD",
                "UNT",
            )
            .strip()
            .upper()
        )

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


    # ====================================================
    # NXT
    # ====================================================

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


        # 08:00 ~ 08:50
        if (
            8 * 60
            <= mins
            < 8 * 60 + 50
        ):

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


        # 09:00:30 ~ 15:20
        elif (
            9 * 60 + 0.5
            <= mins
            < 15 * 60 + 20
        ):

            session = "MAIN"
            label = "NXT 메인마켓"
            opened = True


        # 15:20 ~ 15:40
        elif (
            15 * 60 + 20
            <= mins
            < 15 * 60 + 40
        ):

            session = "AFTER_WAIT"
            label = "NXT 애프터마켓 대기"
            opened = False


        # 15:40 ~ 20:00
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


    # ====================================================
    # STOCK
    # ====================================================

    def q(
        self,
        code,
    ):

        if code not in self.quotes:

            self.quotes[code] = Quote(
                code,
                code,
            )

        return self.quotes[code]


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


            self.all_codes = list(
                dict.fromkeys(
                    arr
                )
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

                data = call(
                    "/krstock/quote/v1/currentPrice",
                    {
                        "iem_cd": code,
                        "market_cd":
                            self.stock_market_cd,
                    },
                )


                self._apply(
                    code,
                    data,
                )


            except Exception as e:

                self.error = (
                    str(e)[:300]
                )


                if "429" in self.error:
                    time.sleep(1)


            time.sleep(0.28)


    def priority(self):

        rows = []


        for code, q in list(
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
                out.append(code)


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

                self.error = (
                    str(e)[:300]
                )

                time.sleep(2)


    # ====================================================
    # MARKET INDEX
    # ====================================================

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
