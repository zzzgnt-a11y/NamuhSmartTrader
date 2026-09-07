from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

_INSTALLED = False


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    d = date(year, month, 1)
    delta = (weekday - d.weekday()) % 7
    return d + timedelta(days=delta + 7 * (n - 1))


def _last_weekday(year: int, month: int, weekday: int) -> date:
    if month == 12:
        d = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        d = date(year, month + 1, 1) - timedelta(days=1)
    return d - timedelta(days=(d.weekday() - weekday) % 7)


def _observed(d: date) -> date:
    if d.weekday() == 5:
        return d - timedelta(days=1)
    if d.weekday() == 6:
        return d + timedelta(days=1)
    return d


def _easter(year: int) -> date:
    # Anonymous Gregorian algorithm.
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def us_market_holidays(year: int) -> set[date]:
    out = {
        _observed(date(year, 1, 1)),
        _nth_weekday(year, 1, 0, 3),   # MLK Day
        _nth_weekday(year, 2, 0, 3),   # Presidents Day
        _easter(year) - timedelta(days=2),  # Good Friday
        _last_weekday(year, 5, 0),     # Memorial Day
        _observed(date(year, 6, 19)),  # Juneteenth
        _observed(date(year, 7, 4)),   # Independence Day
        _nth_weekday(year, 9, 0, 1),   # Labor Day
        _nth_weekday(year, 11, 3, 4),  # Thanksgiving
        _observed(date(year, 12, 25)), # Christmas
    }
    # If next New Year's Day is Saturday, NYSE observes it on Dec 31 of this year.
    nxt = date(year + 1, 1, 1)
    if nxt.weekday() == 5:
        out.add(date(year, 12, 31))
    return out


def is_us_market_holiday(dt_or_date=None) -> bool:
    if dt_or_date is None:
        d = datetime.now(ZoneInfo('America/New_York')).date()
    elif isinstance(dt_or_date, datetime):
        d = dt_or_date.astimezone(ZoneInfo('America/New_York')).date()
    else:
        d = dt_or_date
    return d in us_market_holidays(d.year)


def apply(ns: dict) -> bool:
    global _INSTALLED
    if _INSTALLED:
        return True
    core = ns.get('core')
    if core is None:
        return False

    old_window = core.trading_window
    def trading_window(now=None):
        result = old_window(now)
        if result != 'US':
            return result
        dt = now if isinstance(now, datetime) else datetime.now(core.KST)
        if is_us_market_holiday(dt):
            return None
        return result
    core.trading_window = trading_window
    core.is_us_market_holiday = is_us_market_holiday

    feed = getattr(core, 'feed', None)
    if feed is not None and hasattr(feed, 'market_open_for_key'):
        old_open = feed.market_open_for_key
        def market_open_for_key(key, now=None):
            k = str(key or '').lower()
            if k in ('sp500', 'nasdaq', 'sox'):
                dt = now if isinstance(now, datetime) else datetime.now(core.KST)
                if is_us_market_holiday(dt):
                    return False
            return old_open(key, now)
        feed.market_open_for_key = market_open_for_key

    _INSTALLED = True
    today_ny = datetime.now(ZoneInfo('America/New_York')).date()
    print(f'NAMUH US HOLIDAY PATCH active: ny_date={today_ny} holiday={is_us_market_holiday(today_ny)}', flush=True)
    return True
