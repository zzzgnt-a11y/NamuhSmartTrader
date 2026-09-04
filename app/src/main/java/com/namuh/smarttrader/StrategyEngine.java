package com.namuh.smarttrader;

import java.util.List;

public final class StrategyEngine {
    private StrategyEngine() {}

    public static StockCandidate scalp(String code, String name, List<Ohlcv> df,
                                       double executionStrength, double sectorScore) {
        StockCandidate r = new StockCandidate();
        r.code = code; r.name = name;
        Ohlcv x = df.get(df.size() - 1);
        r.price = x.close;
        r.executionStrength = executionStrength;
        r.sectorScore = sectorScore;
        r.viPre = x.open * 1.10 * (1.0 - 0.003);

        double score = 0;
        double macd = IndicatorEngine.macd(df);
        double sig = IndicatorEngine.macdSignalApprox(df);
        double rsi = IndicatorEngine.rsi(df, 14);
        double wr = IndicatorEngine.williamsR(df, 14);
        double ma5 = IndicatorEngine.sma(df, 5);
        double ma10 = IndicatorEngine.sma(df, 10);
        double ma20 = IndicatorEngine.sma(df, 20);
        double vr = IndicatorEngine.volumeRatio(df, 20);

        if (macd > sig) { score += 10; r.reasons.add("MACD 우위"); }
        if (rsi >= 50 && rsi <= 72) { score += 10; r.reasons.add("RSI 상승구간"); }
        else if (rsi > 80) score -= 5;
        if (wr >= -70 && wr <= -15) { score += 5; r.reasons.add("Williams %R 양호"); }
        if (ma5 > ma10 && ma10 > ma20) { score += 15; r.reasons.add("5>10>20 정배열"); }
        if (vr >= 1.5) { score += 10; r.reasons.add(String.format("거래량 %.1f배", vr)); }
        if (executionStrength >= 105) { score += 10; r.reasons.add(String.format("체결강도 %.0f", executionStrength)); }
        if (sectorScore > 0) {
            score += Math.max(0, Math.min(15, sectorScore));
            r.reasons.add(String.format("KRX 수급/호재 섹터 +%.0f", sectorScore));
        }
        // DMI/볼린저/골든크로스는 Android v0.2에서 Python 엔진과 수치 동등성 테스트 후 확장.
        r.score = Math.max(0, Math.min(100, Math.round(score * 10.0) / 10.0));
        return r;
    }

    public static StockCandidate smart(String code, String name, List<Ohlcv> df,
                                       double per, double pbr, double sectorPer, double sectorPbr,
                                       double foreignNet, double institutionNet) {
        StockCandidate r = new StockCandidate();
        r.code = code; r.name = name;
        Ohlcv x = df.get(df.size() - 1);
        r.price = x.close;
        r.per = per; r.pbr = pbr;
        r.foreignNet = foreignNet; r.institutionNet = institutionNet;

        double score = 0;
        if (per > 0 && per <= 15) { score += 15; r.reasons.add(String.format("PER %.2f", per)); }
        if (pbr > 0 && pbr <= 1.5) { score += 15; r.reasons.add(String.format("PBR %.2f", pbr)); }
        if (per > 0 && sectorPer > 0 && per < sectorPer * 0.85) { score += 8; r.reasons.add("업종 PER 대비 할인"); }
        if (pbr > 0 && sectorPbr > 0 && pbr < sectorPbr * 0.85) { score += 7; r.reasons.add("업종 PBR 대비 할인"); }
        if (IndicatorEngine.obvChange(df, 5) > 0) { score += 10; r.reasons.add("OBV 누적 상승"); }
        if (IndicatorEngine.mfiApprox(df, 14) >= 50) { score += 8; r.reasons.add("MFI 자금유입"); }
        if (foreignNet > 0) { score += 12; r.reasons.add("외국인 순매수"); }
        if (institutionNet > 0) { score += 12; r.reasons.add("기관 순매수"); }

        double ma5 = IndicatorEngine.sma(df, 5);
        double ma20 = IndicatorEngine.sma(df, 20);
        double rsi = IndicatorEngine.rsi(df, 14);
        if (ma5 >= ma20 && rsi < 72) { score += 8; r.reasons.add("과열 전 완만한 추세"); }

        int prevIndex = Math.max(0, df.size() - 6);
        double prevClose = df.get(prevIndex).close;
        double gain = prevClose == 0 ? 0 : (x.close / prevClose - 1) * 100;
        if (IndicatorEngine.obvChange(df, 5) > 0 && gain < 8) { score += 5; r.reasons.add("가격 급등 전 누적수급"); }

        r.score = Math.max(0, Math.min(100, Math.round(score * 10.0) / 10.0));
        return r;
    }
}
