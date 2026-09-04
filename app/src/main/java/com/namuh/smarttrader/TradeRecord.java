package com.namuh.smarttrader;

public class TradeRecord {
    public String time;
    public String code;
    public String name;
    public String side;
    public int qty;
    public long price;
    public long realizedPnlWon;
    public double realizedPnlPct;

    public TradeRecord(String time, String code, String name, String side, int qty, long price,
                       long realizedPnlWon, double realizedPnlPct) {
        this.time = time;
        this.code = code;
        this.name = name;
        this.side = side;
        this.qty = qty;
        this.price = price;
        this.realizedPnlWon = realizedPnlWon;
        this.realizedPnlPct = realizedPnlPct;
    }
}
