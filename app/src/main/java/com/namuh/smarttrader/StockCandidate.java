package com.namuh.smarttrader;

import java.util.ArrayList;
import java.util.List;

public class StockCandidate {
    public String code;
    public String name;
    public double price;
    public double score;
    public double executionStrength;
    public double sectorScore;
    public double viPre;
    public double per;
    public double pbr;
    public double foreignNet;
    public double institutionNet;
    public List<String> reasons = new ArrayList<>();
    public List<Double> priceSeries = new ArrayList<>();

    public String subtitleScalp() {
        return String.format("현재가 %,.0f원  |  점수 %.1f  |  체결강도 %.0f  |  VI직전 %.0f원",
                price, score, executionStrength, viPre);
    }

    public String subtitleSmart() {
        return String.format("현재가 %,.0f원  |  점수 %.1f  |  PER %.2f  |  PBR %.2f",
                price, score, per, pbr);
    }

    public String reasonText() {
        return String.join(" · ", reasons);
    }
}
