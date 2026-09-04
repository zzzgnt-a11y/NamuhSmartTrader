package com.namuh.smarttrader;

import java.text.SimpleDateFormat;
import java.util.*;

public final class AutoPaperTrader {
    public interface Listener { void onTrade(String message); }

    private final PaperAccount paper;
    private final BudgetPolicy budget;
    private final PortfolioState protectedPortfolio;
    private final Listener listener;

    // 테스트용 기본값. 앱 화면에 명확히 표시한다.
    private double buyScore = 72.0;
    private double sellScore = 46.0;
    private double takeProfitPct = 2.5;
    private double stopLossPct = -1.5;
    private int maxPositions = 3;
    private final Map<String, Double> lastScores = new HashMap<>();

    public AutoPaperTrader(PaperAccount paper, BudgetPolicy budget,
                           PortfolioState protectedPortfolio, Listener listener) {
        this.paper = paper;
        this.budget = budget;
        this.protectedPortfolio = protectedPortfolio;
        this.listener = listener;
    }

    public void onScalpCandidates(List<StockCandidate> xs) {
        if (xs == null) return;
        for (StockCandidate x : xs) {
            if (x.price > 0) paper.mark(x.code, (long)x.price);
            lastScores.put(x.code, x.score);
        }

        // 먼저 매도 판단
        List<Position> held = new ArrayList<>(paper.positions());
        for (Position p : held) {
            double score = lastScores.containsKey(p.code) ? lastScores.get(p.code) : 50.0;
            double pnl = p.pnlPct();
            boolean sell = pnl >= takeProfitPct || pnl <= stopLossPct || score < sellScore;
            if (sell && p.currentPrice > 0) {
                TradeRecord t = paper.sell(now(), p.code, p.qty, p.currentPrice);
                budget.syncHeldCost(paper.heldCostWon());
                if (listener != null) listener.onTrade("AI PAPER 매도 " + p.name +
                        " " + p.qty + "주 · " + String.format(Locale.KOREA, "%+.2f%%", t.realizedPnlPct));
            }
        }

        // 그 다음 신규매수
        if (paper.positions().size() >= maxPositions) return;
        for (StockCandidate x : xs) {
            if (paper.positions().size() >= maxPositions) break;
            if (x.price <= 0 || x.score < buyScore) continue;
            if (x.viPre > 0 && x.price >= x.viPre) continue; // 상승 VI 직전가 이상 신규진입 금지
            if (protectedPortfolio.hasProtectedCode(x.code)) continue;
            if (paper.find(x.code) != null) continue;

            budget.syncHeldCost(paper.heldCostWon());
            long remain = Math.min(budget.getRemainingWon(), paper.cashWon());
            if (remain <= 0) break;

            long price = (long)x.price;
            // 한 종목에 남은 한도의 최대 1/2, 최소 1주.
            long target = Math.max(price, Math.min(remain, Math.max(1, budget.getLimitWon()/2)));
            int qty = (int)Math.max(0, target / price);
            if (qty < 1) continue;
            long amount = price * (long)qty;
            if (amount > remain) qty = (int)(remain / price);
            if (qty < 1) continue;

            paper.buy(now(), x.code, x.name, qty, price);
            budget.syncHeldCost(paper.heldCostWon());
            if (listener != null) listener.onTrade("AI PAPER 매수 " + x.name + " " +
                    qty + "주 × " + price + "원 · 점수 " + x.score);
        }
    }

    private static String now() {
        return new SimpleDateFormat("HH:mm:ss", Locale.KOREA).format(new Date());
    }

    public String ruleSummary() {
        return "매수점수 " + buyScore + "↑ · 익절 +" + takeProfitPct + "% · 손절 " +
                stopLossPct + "% · 점수 " + sellScore + "↓ 매도 · 최대 " + maxPositions + "종목";
    }
}
