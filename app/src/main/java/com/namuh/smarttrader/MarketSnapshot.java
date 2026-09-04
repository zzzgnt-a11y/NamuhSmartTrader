package com.namuh.smarttrader;

import java.util.ArrayList;
import java.util.List;

public class MarketSnapshot {
    public String label;
    public String symbol;
    public Double value;
    public Double changePct;
    public List<Double> sparkline = new ArrayList<>();
    public long updatedAtMs;
    public boolean realtime;

    public MarketSnapshot(String label, String symbol) {
        this.label = label;
        this.symbol = symbol;
    }
}
