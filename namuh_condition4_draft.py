"""Condition 4 draft only.

NOT imported by sitecustomize/runtime and therefore NOT active in trading.

Rules supplied by the user:
- Hull Suite: HMA/WMA based, Length=26, Source=hl2
- TFS Volume Oscillator: OBV with 7-period moving-average baseline
- Long: BUY signal + bullish candle + TFS below baseline
- Short: SELL signal + bearish candle + TFS above baseline
- Stop: previous swing low/high
- Take profit: reward:risk >= 1:1

The live stock engine is long-only paper trading today, so the short rule is
represented here for analysis but intentionally not wired to an order path.
"""
from __future__ import annotations
import math


def _f(v):
    try:
        return float(v)
    except Exception:
        return 0.0


def wma(values, length):
    values = list(map(_f, values))
    n = max(1, int(length))
    out = [None] * len(values)
    den = n * (n + 1) / 2.0
    for i in range(n - 1, len(values)):
        w = values[i - n + 1:i + 1]
        out[i] = sum((j + 1) * w[j] for j in range(n)) / den
    return out


def hma(values, length=26):
    vals = list(map(_f, values))
    half = wma(vals, max(1, length // 2))
    full = wma(vals, length)
    raw = [None if a is None or b is None else 2 * a - b for a, b in zip(half, full)]
    root = max(1, int(round(math.sqrt(length))))
    out = [None] * len(vals)
    den = root * (root + 1) / 2.0
    for i in range(root - 1, len(vals)):
        w = raw[i - root + 1:i + 1]
        if any(x is None for x in w):
            continue
        out[i] = sum((j + 1) * w[j] for j in range(root)) / den
    return out


def evaluate(bars):
    rows = [dict(x) for x in bars or [] if isinstance(x, dict)]
    if len(rows) < 35:
        return {"ready": False}
    src = [(_f(x.get("high")) + _f(x.get("low"))) / 2.0 for x in rows]
    close = [_f(x.get("close")) for x in rows]
    vol = [_f(x.get("volume")) for x in rows]
    hv = hma(src, 26)
    if any(hv[-i] is None for i in (1, 2, 3)):
        return {"ready": False}

    obv = [0.0]
    for i in range(1, len(rows)):
        obv.append(obv[-1] + (vol[i] if close[i] > close[i - 1] else -vol[i] if close[i] < close[i - 1] else 0.0))
    tfs_base = sum(obv[-7:]) / 7.0
    tfs = obv[-1] - tfs_base

    buy_signal = hv[-2] <= hv[-3] and hv[-1] > hv[-2]
    sell_signal = hv[-2] >= hv[-3] and hv[-1] < hv[-2]
    bullish = close[-1] > _f(rows[-1].get("open"))
    bearish = close[-1] < _f(rows[-1].get("open"))

    lows = [_f(x.get("low")) for x in rows]
    highs = [_f(x.get("high")) for x in rows]
    previous_low = min(x for x in lows[-6:] if x > 0)
    previous_high = max(highs[-6:])
    entry = close[-1]
    long_risk = max(0.0, entry - previous_low)
    short_risk = max(0.0, previous_high - entry)

    return {
        "ready": True,
        "long_entry": bool(buy_signal and bullish and tfs < 0),
        "short_entry": bool(sell_signal and bearish and tfs > 0),
        "tfs": tfs,
        "hma": hv[-1],
        "long_stop": previous_low,
        "long_target_1r": entry + long_risk if long_risk > 0 else None,
        "short_stop": previous_high,
        "short_target_1r": entry - short_risk if short_risk > 0 else None,
    }
