package com.namuh.smarttrader;

public class Ohlcv {
    public final double open;
    public final double high;
    public final double low;
    public final double close;
    public final double volume;

    public Ohlcv(double open, double high, double low, double close, double volume) {
        this.open = open;
        this.high = high;
        this.low = low;
        this.close = close;
        this.volume = volume;
    }
}
