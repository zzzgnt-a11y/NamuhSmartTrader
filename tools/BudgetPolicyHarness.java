package com.namuh.smarttrader;

public class BudgetPolicyHarness {
    private static int pass = 0;
    private static void check(boolean ok, String name) {
        if (!ok) throw new RuntimeException("FAIL: " + name);
        pass++; System.out.println("PASS: " + name);
    }

    public static void main(String[] args) {
        PortfolioState p = new PortfolioState();
        p.positions().add(new Position("005930", "기존보유", 10, 70000, 71000)); // protected by default

        BudgetPolicy b = new BudgetPolicy(200_000L);
        b.syncHeldCost(p.managedHeldCostWon());
        OrderGuard g = new OrderGuard(b, p);

        check(b.getHeldCostWon() == 0L, "기존 보유원가는 오늘 자동매매 한도에서 제외");
        check(b.getRemainingWon() == 200_000L, "기존 보유가 있어도 오늘 한도 20만원 전액 사용 가능");
        check(!g.checkBuy("005930", 70000L, 1).allowed, "기존 보유 종목 추가 자동매수 금지");
        check(!g.checkSell(p.find("005930"), 1).allowed, "기존 보유 종목 자동매도 금지");

        Position bot = new Position("000660", "신규자동매매", 2, 80000, 81000, true);
        p.positions().add(bot);
        b.syncHeldCost(p.managedHeldCostWon());
        check(b.getHeldCostWon() == 160_000L, "봇 신규매수 포지션만 한도에 포함");
        check(b.getRemainingWon() == 40_000L, "잔여 한도 계산");
        check(g.checkSell(bot, 1).allowed, "봇 보유물량 자동매도 허용");
        check(!g.checkBuy("035420", 50_000L, 1).allowed, "한도 초과 신규매수 차단");
        check(g.checkBuy("035420", 40_000L, 1).allowed, "잔여한도 이내 신규매수 허용");

        b.releaseSellCost(80_000L);
        check(b.getRemainingWon() == 120_000L, "봇 물량 매도 후 해당 원가만큼 한도 복원");

        System.out.println("TOTAL PASS=" + pass);
    }
}
