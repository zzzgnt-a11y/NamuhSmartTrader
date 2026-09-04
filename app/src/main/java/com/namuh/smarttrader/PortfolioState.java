package com.namuh.smarttrader;

import java.util.ArrayList;
import java.util.List;

/** 현재 앱 상태. 기존 계좌 보유종목은 보호, 봇이 신규 매수한 포지션만 자동매매 대상으로 관리한다. */
public final class PortfolioState {
    private final List<Position> positions = new ArrayList<>();
    private final List<TradeRecord> trades = new ArrayList<>();

    public List<Position> positions() { return positions; }
    public List<TradeRecord> trades() { return trades; }

    /** 전체 계좌 보유 원가. 표시용이며 오늘 자동매매 한도 계산에는 사용하지 않는다. */
    public long heldCostWon() {
        long sum = 0;
        for (Position p : positions) sum += p.costBasis();
        return sum;
    }

    /** 오늘 자동매매 엔진이 관리하는 신규 포지션의 원가만 합산한다. */
    public long managedHeldCostWon() {
        long sum = 0;
        for (Position p : positions) if (p.managedByBot) sum += p.costBasis();
        return sum;
    }

    public long protectedHeldCostWon() {
        long sum = 0;
        for (Position p : positions) if (p.isProtected()) sum += p.costBasis();
        return sum;
    }

    public boolean hasProtectedCode(String code) {
        for (Position p : positions) if (p.isProtected() && p.code.equals(code) && p.qty > 0) return true;
        return false;
    }

    public Position find(String code) {
        for (Position p : positions) if (p.code.equals(code)) return p;
        return null;
    }

    public long totalMarketValueWon() {
        long sum = 0;
        for (Position p : positions) sum += p.marketValue();
        return sum;
    }

    public long totalUnrealizedPnlWon() {
        long sum = 0;
        for (Position p : positions) sum += p.pnlWon();
        return sum;
    }

    public long realizedPnlWon() {
        long sum = 0;
        for (TradeRecord t : trades) sum += t.realizedPnlWon;
        return sum;
    }
}
