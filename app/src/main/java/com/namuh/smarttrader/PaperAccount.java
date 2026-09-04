package com.namuh.smarttrader;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

/**
 * 실제 시세를 입력값으로 사용하되 증권사 주문은 전혀 전송하지 않는 로컬 모의계좌.
 * 체결가는 호출 시점의 전달 가격이며 수수료/세금/슬리피지는 v0.3에서 0으로 둔다.
 */
public final class PaperAccount {
    private final long initialCashWon;
    private long cashWon;
    private final List<Position> positions = new ArrayList<>();
    private final List<TradeRecord> trades = new ArrayList<>();

    public PaperAccount(long initialCashWon) {
        if (initialCashWon <= 0) throw new IllegalArgumentException("initialCashWon must be > 0");
        this.initialCashWon = initialCashWon;
        this.cashWon = initialCashWon;
    }

    public long initialCashWon() { return initialCashWon; }
    public long cashWon() { return cashWon; }
    public List<Position> positions() { return Collections.unmodifiableList(positions); }
    public List<TradeRecord> trades() { return Collections.unmodifiableList(trades); }

    public Position find(String code) {
        for (Position p : positions) if (p.code.equals(code)) return p;
        return null;
    }

    public long heldCostWon() {
        long sum = 0;
        for (Position p : positions) sum += p.costBasis();
        return sum;
    }

    public long marketValueWon() {
        long sum = 0;
        for (Position p : positions) sum += p.marketValue();
        return sum;
    }

    public long totalAssetWon() { return cashWon + marketValueWon(); }

    public long realizedPnlWon() {
        long sum = 0;
        for (TradeRecord t : trades) if ("SELL".equalsIgnoreCase(t.side)) sum += t.realizedPnlWon;
        return sum;
    }

    public long unrealizedPnlWon() {
        long sum = 0;
        for (Position p : positions) sum += p.pnlWon();
        return sum;
    }

    public void mark(String code, long currentPrice) {
        if (currentPrice <= 0) return;
        Position p = find(code);
        if (p != null) p.currentPrice = currentPrice;
    }

    public TradeRecord buy(String time, String code, String name, int qty, long price) {
        if (qty <= 0 || price <= 0) throw new IllegalArgumentException("invalid order");
        long amount = price * (long) qty;
        if (amount > cashWon) throw new IllegalStateException("insufficient paper cash");

        Position p = find(code);
        if (p == null) {
            p = new Position(code, name, qty, price, price, true);
            positions.add(p);
        } else {
            long oldCost = p.avgPrice * (long) p.qty;
            long newCost = oldCost + amount;
            p.qty += qty;
            p.avgPrice = newCost / p.qty;
            p.currentPrice = price;
        }
        cashWon -= amount;
        TradeRecord t = new TradeRecord(time, code, name, "BUY", qty, price, 0, 0);
        trades.add(0, t);
        return t;
    }

    public TradeRecord sell(String time, String code, int qty, long price) {
        if (qty <= 0 || price <= 0) throw new IllegalArgumentException("invalid order");
        Position p = find(code);
        if (p == null || qty > p.qty) throw new IllegalStateException("insufficient paper position");

        long cost = p.avgPrice * (long) qty;
        long proceeds = price * (long) qty;
        long pnl = proceeds - cost;
        double pct = cost == 0 ? 0 : pnl * 100.0 / cost;
        String name = p.name;
        p.qty -= qty;
        p.currentPrice = price;
        if (p.qty == 0) positions.remove(p);
        cashWon += proceeds;
        TradeRecord t = new TradeRecord(time, code, name, "SELL", qty, price, pnl, pct);
        trades.add(0, t);
        return t;
    }
}
