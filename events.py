
from __future__ import annotations

import io
import os
import threading
import time
import zipfile
import xml.etree.ElementTree as ET

from datetime import (
    datetime,
    timedelta,
    timezone,
)

import requests


KST = timezone(
    timedelta(
        hours=9
    )
)


POSITIVE_STRONG = (
    "단일판매",
    "공급계약",
    "수주",
    "수주계약",
    "기술수출",
    "품목허가",
    "허가승인",
    "임상시험 승인",
    "자사주 소각",
    "자기주식 소각",
    "무상증자",
    "업무협약",
    "MOU",
    "협약",
)

POSITIVE = (
    "신규시설투자",
    "신규사업",
    "특허",
    "판매계약",
    "공동개발",
    "파트너십",
    "실적 개선",
    "매출액 또는 손익구조",
    "영업이익 증가",
)

NEGATIVE_BLOCK = (
    "횡령",
    "배임",
    "상장폐지",
    "거래정지",
    "감사의견 거절",
    "감사의견 부적정",
    "회생절차",
    "파산",
    "계약해지",
    "불성실공시",
)

NEGATIVE = (
    "유상증자",
    "전환사채",
    "신주인수권부사채",
    "교환사채",
    "소송",
    "제재",
    "과징금",
    "최대주주 변경",
    "영업정지",
    "실적 감소",
)


def classify_event(
    title,
):
    text = str(
        title or ""
    ).strip()

    up = text.upper()

    if any(
        k.upper() in up
        for k in NEGATIVE_BLOCK
    ):
        return {
            "sentiment":
                "negative",
            "impact":
                "strong",
            "score":
                0.0,
            "blocked":
                True,
            "label":
                "강한 악재",
        }

    if any(
        k.upper() in up
        for k in NEGATIVE
    ):
        return {
            "sentiment":
                "negative",
            "impact":
                "medium",
            "score":
                0.0,
            "blocked":
                False,
            "label":
                "악재",
        }

    if any(
        k.upper() in up
        for k in POSITIVE_STRONG
    ):
        return {
            "sentiment":
                "positive",
            "impact":
                "strong",
            "score":
                10.0,
            "blocked":
                False,
            "label":
                "강한 호재",
        }

    if any(
        k.upper() in up
        for k in POSITIVE
    ):
        return {
            "sentiment":
                "positive",
            "impact":
                "medium",
            "score":
                6.0,
            "blocked":
                False,
            "label":
                "호재",
        }

    return {
        "sentiment":
            "neutral",
        "impact":
            "low",
        "score":
            0.0,
        "blocked":
            False,
        "label":
            "중립",
    }


def age_weight(
    date_text,
    now=None,
):
    now = (
        now
        or datetime.now(KST)
    ).astimezone(
        KST
    )

    raw = (
        str(
            date_text or ""
        )
        .replace("-", "")
        .replace("/", "")
    )[:8]

    try:
        d = datetime.strptime(
            raw,
            "%Y%m%d",
        ).date()

    except Exception:
        return 0.0

    age = (
        now.date()
        - d
    ).days

    if age <= 0:
        return 1.0

    if age == 1:
        return 0.8

    if age == 2:
        return 0.6

    return 0.0


class DisclosureFeed:
    def __init__(
        self,
        quote_provider=None,
        api_key=None,
    ):
        self.api_key = (
            api_key
            if api_key is not None
            else os.getenv(
                "DART_API_KEY",
                "",
            )
        ).strip()

        self.quote_provider = (
            quote_provider
        )

        self.events = []

        self.status = (
            "DART_API_KEY 미설정"
            if not self.api_key
            else "DART 대기"
        )

        self.updated_at = 0.0
        self._corp_by_stock = {}
        self._stop = threading.Event()

    def _load_corp_map(
        self,
    ):
        if (
            self._corp_by_stock
            or not self.api_key
        ):
            return

        r = requests.get(
            "https://opendart.fss.or.kr/api/corpCode.xml",
            params={
                "crtfc_key":
                    self.api_key
            },
            timeout=15,
        )

        r.raise_for_status()

        with zipfile.ZipFile(
            io.BytesIO(
                r.content
            )
        ) as z:
            name = z.namelist()[0]

            root = ET.fromstring(
                z.read(name)
            )

        out = {}

        for node in root.findall(
            ".//list"
        ):
            stock = (
                node.findtext(
                    "stock_code"
                )
                or ""
            ).strip()

            corp = (
                node.findtext(
                    "corp_code"
                )
                or ""
            ).strip()

            name = (
                node.findtext(
                    "corp_name"
                )
                or ""
            ).strip()

            if (
                len(stock) == 6
                and stock.isdigit()
                and corp
            ):
                out[
                    stock
                ] = (
                    corp,
                    name,
                )

        self._corp_by_stock = out

    def _query(
        self,
        code,
        corp_code,
        now,
    ):
        begin = (
            now.date()
            - timedelta(
                days=2
            )
        ).strftime(
            "%Y%m%d"
        )

        end = now.date().strftime(
            "%Y%m%d"
        )

        r = requests.get(
            "https://opendart.fss.or.kr/api/list.json",
            params={
                "crtfc_key":
                    self.api_key,
                "corp_code":
                    corp_code,
                "bgn_de":
                    begin,
                "end_de":
                    end,
                "page_count":
                    "30",
            },
            timeout=12,
        )

        r.raise_for_status()

        data = r.json()

        if str(
            data.get(
                "status",
                "",
            )
        ) not in (
            "000",
            "013",
        ):
            raise RuntimeError(
                data.get(
                    "message"
                )
                or data.get(
                    "status"
                )
            )

        out = []

        for x in (
            data.get(
                "list"
            )
            or []
        ):
            title = (
                x.get(
                    "report_nm"
                )
                or ""
            )

            cls = classify_event(
                title
            )

            date = (
                x.get(
                    "rcept_dt"
                )
                or ""
            )

            w = age_weight(
                date,
                now,
            )

            out.append(
                {
                    "market":
                        "KR",
                    "code":
                        code,
                    "corp_name":
                        (
                            x.get(
                                "corp_name"
                            )
                            or ""
                        ),
                    "title":
                        title,
                    "date":
                        date,
                    "time":
                        "",
                    "source":
                        "DART 공식",
                    "url":
                        (
                            "https://dart.fss.or.kr/"
                            "dsaf001/main.do?rcpNo="
                            + str(
                                x.get(
                                    "rcept_no"
                                )
                                or ""
                            )
                        ),
                    "sentiment":
                        cls[
                            "sentiment"
                        ],
                    "impact":
                        cls[
                            "impact"
                        ],
                    "label":
                        cls[
                            "label"
                        ],
                    "score":
                        round(
                            cls[
                                "score"
                            ]
                            * w,
                            1,
                        ),
                    "blocked":
                        cls[
                            "blocked"
                        ],
                }
            )

        return out

    def poll_once(
        self,
        now=None,
    ):
        if not self.api_key:
            self.status = (
                "DART_API_KEY 미설정"
            )

            return []

        now = (
            now
            or datetime.now(KST)
        ).astimezone(
            KST
        )

        self._load_corp_map()

        quotes = (
            self.quote_provider()
            if self.quote_provider
            else {}
        )

        all_events = []

        for code, q in list(
            quotes.items()
        ):
            corp = (
                self._corp_by_stock.get(
                    code
                )
            )

            if not corp:
                continue

            try:
                evs = self._query(
                    code,
                    corp[0],
                    now,
                )

                all_events.extend(
                    evs
                )

                q.events = evs

                q.event_score = max(
                    [
                        e["score"]
                        for e in evs
                        if (
                            e[
                                "sentiment"
                            ]
                            == "positive"
                        )
                    ]
                    or [0]
                )

                q.event_blocked = any(
                    e["blocked"]
                    for e in evs
                )

            except Exception:
                continue

        all_events.sort(
            key=lambda x:
                (
                    x["date"],
                    x["score"],
                ),
            reverse=True,
        )

        self.events = (
            all_events[
                :100
            ]
        )

        self.updated_at = (
            time.time()
        )

        self.status = (
            "DART 공식 수신"
            if self.events
            else "최근 2일 공시 없음"
        )

        return self.events

    def state(
        self,
        market="KR",
    ):
        if (
            str(
                market
            ).upper()
            != "KR"
        ):
            return {
                "items":
                    [],
                "status":
                    "미장 이벤트 분석 미사용",
                "updated_at":
                    self.updated_at,
            }

        return {
            "items":
                list(
                    self.events[
                        :30
                    ]
                ),
            "status":
                self.status,
            "updated_at":
                self.updated_at,
        }

    def loop(
        self,
    ):
        while not self._stop.is_set():
            try:
                self.poll_once()

            except Exception as exc:
                self.status = (
                    "DART 오류 · "
                    + str(
                        exc
                    )[:120]
                )

            self._stop.wait(
                120
            )

    def start(
        self,
    ):
        threading.Thread(
            target=self.loop,
            daemon=True,
        ).start()

    def stop(
        self,
    ):
        self._stop.set()
