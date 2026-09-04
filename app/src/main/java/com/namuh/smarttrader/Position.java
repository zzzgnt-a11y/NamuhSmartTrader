package com.namuh.smarttrader;

public class Position {
    public String code;
    public String name;
    public int qty;
    public long avgPrice;
    public long currentPrice;
    /** true = 이 자동매매 프로그램이 오늘 신규 매수해 관리하는 포지션. false = 기존 보유 보호종목. */
    public boolean managedByBot;

    /** 계좌에서 처음 불러온 기존 보유종목은 기본적으로 보호한다. */
    public Position(String code, String name, int qty, long avgPrice, long currentPrice) {
        this(code, name, qty, avgPrice, currentPrice, false);
    }

    public Position(String code, String name, int qty, long avgPrice, long currentPrice, boolean managedByBot) {
        this.code = code;
        this.name = name;
        this.qty = qty;
        this.avgPrice = avgPrice;
        this.currentPrice = currentPrice;
        this.managedByBot = managedByBot;
    }

    public long costBasis() { return avgPrice * (long) qty; }
    public long marketValue() { return currentPrice * (long) qty; }
    public long pnlWon() { return marketValue() - costBasis(); }
    public double pnlPct() { return costBasis() == 0 ? 0 : pnlWon() * 100.0 / costBasis(); }
    public boolean isProtected() { return !managedByBot; }
}
