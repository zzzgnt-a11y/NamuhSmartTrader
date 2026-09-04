package com.namuh.smarttrader;

public final class PaperAccountHarness {
    private static int pass = 0;
    private static void ok(boolean v, String name) {
        if (!v) throw new AssertionError(name);
        pass++;
        System.out.println("PASS " + name);
    }
    public static void main(String[] args) {
        PaperAccount a = new PaperAccount(1_000_000);
        ok(a.cashWon()==1_000_000, "initial cash");
        a.buy("09:10:00","000001","TEST",10,20_000);
        ok(a.cashWon()==800_000, "buy reduces cash");
        ok(a.heldCostWon()==200_000, "buy creates cost basis");
        a.mark("000001",21_000);
        ok(a.unrealizedPnlWon()==10_000, "real price mark updates pnl");
        a.sell("09:20:00","000001",5,22_000);
        ok(a.cashWon()==910_000, "sell restores cash plus pnl");
        ok(a.realizedPnlWon()==10_000, "realized pnl");
        ok(a.find("000001").qty==5, "partial sell quantity");
        a.sell("09:30:00","000001",5,19_000);
        ok(a.find("000001")==null, "full sell removes position");
        ok(a.cashWon()==1_005_000, "final paper cash");
        ok(a.trades().size()==3, "trade history");
        System.out.println("RESULT " + pass + "/10 PASS");
    }
}
