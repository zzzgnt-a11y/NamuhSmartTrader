package com.namuh.smarttrader;

/**
 * 일중 운용한도 정책.
 * 한도는 누적 매수금액이 아니라 '현재 보유 포지션의 매입원가 합계' 기준이다.
 * 따라서 매도하면 해당 매입원가만큼 한도가 즉시 복원되고 재매수가 가능하다.
 */
public final class BudgetPolicy {
    private long limitWon;
    private long heldCostWon;

    public BudgetPolicy(long limitWon) {
        setLimitWon(limitWon);
        this.heldCostWon = 0L;
    }

    public void setLimitWon(long limitWon) {
        if (limitWon < 0) throw new IllegalArgumentException("limitWon must be >= 0");
        this.limitWon = limitWon;
    }

    public long getLimitWon() { return limitWon; }
    public long getHeldCostWon() { return heldCostWon; }
    public long getRemainingWon() { return Math.max(0L, limitWon - heldCostWon); }

    public boolean canBuy(long orderAmountWon) {
        return orderAmountWon > 0 && heldCostWon + orderAmountWon <= limitWon;
    }

    public void reserveBuy(long orderAmountWon) {
        if (!canBuy(orderAmountWon)) {
            throw new IllegalStateException("daily position budget exceeded");
        }
        heldCostWon += orderAmountWon;
    }

    public void releaseSellCost(long soldCostBasisWon) {
        if (soldCostBasisWon < 0) throw new IllegalArgumentException("soldCostBasisWon must be >= 0");
        heldCostWon = Math.max(0L, heldCostWon - soldCostBasisWon);
    }

    public void syncHeldCost(long heldCostWon) {
        if (heldCostWon < 0) throw new IllegalArgumentException("heldCostWon must be >= 0");
        this.heldCostWon = heldCostWon;
    }
}
