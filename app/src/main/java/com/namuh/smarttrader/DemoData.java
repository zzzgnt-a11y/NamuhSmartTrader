package com.namuh.smarttrader;

import java.util.*;

public final class DemoData {
    private DemoData() {}

    private static final String[][] STOCKS = {
            {"005930","삼성전자"}, {"000660","SK하이닉스"}, {"035420","NAVER"}, {"035720","카카오"},
            {"068270","셀트리온"}, {"012450","한화에어로스페이스"}, {"042700","한미반도체"}, {"267260","HD현대일렉트릭"}
    };

    public static List<Ohlcv> series(String code) {
        Random rnd = new Random(Integer.parseInt(code.substring(code.length()-4)));
        ArrayList<Ohlcv> out = new ArrayList<>();
        double close = 30000 + Integer.parseInt(code.substring(code.length()-4)) * 7.0;
        for (int i=0;i<80;i++) {
            double ret = rnd.nextGaussian() * 0.015 + 0.0012;
            close = Math.max(1000, close * (1 + ret));
            double open = close * (1 + rnd.nextGaussian() * 0.004);
            double high = Math.max(open, close) * (1 + 0.004 + rnd.nextDouble() * 0.015);
            double low = Math.min(open, close) * (1 - 0.004 - rnd.nextDouble() * 0.015);
            double vol = 100000 + rnd.nextDouble() * 1800000;
            if (i == 79) vol *= 1.2 + rnd.nextDouble() * 2.0;
            out.add(new Ohlcv(open, high, low, close, vol));
        }
        return out;
    }

    public static List<StockCandidate> scalpList() {
        ArrayList<StockCandidate> out = new ArrayList<>();
        for (String[] s : STOCKS) {
            int seed = Integer.parseInt(s[0].substring(s[0].length()-4));
            Random r = new Random(seed);
            double strength = 92 + r.nextDouble()*53;
            double sector = r.nextDouble()*15;
            out.add(StrategyEngine.scalp(s[0], s[1], series(s[0]), strength, sector));
        }
        out.sort((a,b)->Double.compare(b.score,a.score));
        return out;
    }

    public static List<StockCandidate> smartList() {
        ArrayList<StockCandidate> out = new ArrayList<>();
        for (String[] s : STOCKS) {
            int seed = Integer.parseInt(s[0].substring(s[0].length()-4));
            Random r = new Random(seed + 77);
            double per = 4+r.nextDouble()*21;
            double pbr = 0.4+r.nextDouble()*2.6;
            double sper = 12+r.nextDouble()*16;
            double spbr = 1.2+r.nextDouble()*2.3;
            double f = -5e9+r.nextDouble()*13e9;
            double inst = -5e9+r.nextDouble()*13e9;
            out.add(StrategyEngine.smart(s[0], s[1], series(s[0]), per,pbr,sper,spbr,f,inst));
        }
        out.sort((a,b)->Double.compare(b.score,a.score));
        return out;
    }
}
