package com.namuh.smarttrader;

import java.util.List;

public final class IndicatorEngine {
    private IndicatorEngine() {}

    public static double sma(List<Ohlcv> x, int n) {
        if (x.size() < n) return Double.NaN;
        double s = 0;
        for (int i = x.size() - n; i < x.size(); i++) s += x.get(i).close;
        return s / n;
    }

    public static double emaClose(List<Ohlcv> x, int span) {
        if (x.isEmpty()) return Double.NaN;
        double a = 2.0 / (span + 1.0);
        double v = x.get(0).close;
        for (int i = 1; i < x.size(); i++) v = a * x.get(i).close + (1 - a) * v;
        return v;
    }

    public static double rsi(List<Ohlcv> x, int period) {
        if (x.size() < 2) return 50;
        int start = Math.max(1, x.size() - period);
        double up = 0, dn = 0;
        int count = 0;
        for (int i = start; i < x.size(); i++) {
            double d = x.get(i).close - x.get(i - 1).close;
            if (d > 0) up += d; else dn -= d;
            count++;
        }
        if (count == 0) return 50;
        if (dn == 0) return 100;
        double rs = (up / count) / (dn / count);
        return 100 - 100 / (1 + rs);
    }

    public static double williamsR(List<Ohlcv> x, int period) {
        int start = Math.max(0, x.size() - period);
        double hh = -Double.MAX_VALUE, ll = Double.MAX_VALUE;
        for (int i = start; i < x.size(); i++) {
            hh = Math.max(hh, x.get(i).high);
            ll = Math.min(ll, x.get(i).low);
        }
        double c = x.get(x.size() - 1).close;
        if (hh == ll) return -50;
        return -100.0 * (hh - c) / (hh - ll);
    }

    public static double volumeRatio(List<Ohlcv> x, int period) {
        if (x.size() < 2) return 1;
        int end = x.size() - 1;
        int start = Math.max(0, end - period);
        double s = 0;
        int n = 0;
        for (int i = start; i < end; i++) {
            s += x.get(i).volume;
            n++;
        }
        if (n == 0 || s == 0) return 1;
        return x.get(end).volume / (s / n);
    }

    public static double macd(List<Ohlcv> x) {
        return emaClose(x, 12) - emaClose(x, 26);
    }

    public static double macdSignalApprox(List<Ohlcv> x) {
        // 모바일 v0.1에서는 MACD 방향성 판정용 근사치.
        if (x.size() < 10) return macd(x);
        double sum = 0;
        int n = 0;
        for (int cut = Math.max(26, x.size() - 9); cut <= x.size(); cut++) {
            sum += macd(x.subList(0, cut));
            n++;
        }
        return n == 0 ? macd(x) : sum / n;
    }

    public static double mfiApprox(List<Ohlcv> x, int period) {
        int start = Math.max(1, x.size() - period);
        double pos = 0, neg = 0;
        for (int i = start; i < x.size(); i++) {
            Ohlcv a = x.get(i - 1), b = x.get(i);
            double tpa = (a.high + a.low + a.close) / 3.0;
            double tpb = (b.high + b.low + b.close) / 3.0;
            double flow = tpb * b.volume;
            if (tpb > tpa) pos += flow;
            else if (tpb < tpa) neg += flow;
        }
        if (neg == 0) return pos > 0 ? 100 : 50;
        double r = pos / neg;
        return 100 - 100 / (1 + r);
    }

    public static double obvChange(List<Ohlcv> x, int lookback) {
        if (x.size() < 2) return 0;
        double obv = 0;
        double base = 0;
        int mark = Math.max(1, x.size() - lookback);
        for (int i = 1; i < x.size(); i++) {
            double d = x.get(i).close - x.get(i - 1).close;
            if (d > 0) obv += x.get(i).volume;
            else if (d < 0) obv -= x.get(i).volume;
            if (i == mark) base = obv;
        }
        return obv - base;
    }
}
