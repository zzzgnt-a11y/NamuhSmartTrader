package com.namuh.smarttrader;

/** 주문 직전 마지막 안전장치: 오늘 운용한도 + 기존 보유 보호. */
public final class OrderGuard {
    private final BudgetPolicy budget;
    private final PortfolioState portfolio;

    public OrderGuard(BudgetPolicy budget, PortfolioState portfolio) {
        this.budget = budget;
        this.portfolio = portfolio;
    }

    public Decision checkBuy(String code, long price, int qty) {
        if (code == null || code.trim().isEmpty()) return Decision.reject("종목코드 오류");
        // 기존 보유와 자동매매 물량을 섞으면 매도 시 보호물량 침범 위험이 있으므로 신규매수도 차단.
        if (portfolio.hasProtectedCode(code)) {
            return Decision.reject("기존 보유 보호종목: 자동매수 금지");
        }
        if (price <= 0 || qty <= 0) return Decision.reject("가격/수량 오류");
        long amount;
        try {
            amount = Math.multiplyExact(price, (long) qty);
        } catch (ArithmeticException e) {
            return Decision.reject("주문금액 계산 초과");
        }
        if (!budget.canBuy(amount)) {
            return Decision.reject("일중 운용한도 초과: 남은 한도 " + budget.getRemainingWon() + "원");
        }
        return Decision.allow(amount);
    }

    public Decision checkSell(Position position, int qty) {
        if (position == null) return Decision.reject("보유종목 없음");
        if (position.isProtected()) return Decision.reject("기존 보유 보호종목: 자동매도 금지");
        if (qty <= 0 || qty > position.qty) return Decision.reject("매도수량 오류");
        return Decision.allow(position.avgPrice * (long) qty);
    }

    public static final class Decision {
        public final boolean allowed;
        public final long amountWon;
        public final String reason;

        private Decision(boolean allowed, long amountWon, String reason) {
            this.allowed = allowed;
            this.amountWon = amountWon;
            this.reason = reason;
        }
        static Decision allow(long amountWon) { return new Decision(true, amountWon, "OK"); }
        static Decision reject(String reason) { return new Decision(false, 0L, reason); }
    }
}
