package com.namuh.smarttrader;

import android.app.*;
import android.os.Bundle;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.text.InputType;
import android.view.*;
import android.widget.*;

import java.text.NumberFormat;
import java.util.*;

public class MainActivity extends Activity {
    private final NumberFormat won = NumberFormat.getIntegerInstance(Locale.KOREA);

    private LinearLayout root;
    private LinearLayout marketGrid;
    private LinearLayout sectorBox;
    private LinearLayout contentBox;
    private TextView liveStatus;
    private TextView budgetSummary;
    private TextView paperSummary;
    private EditText budgetInput;
    private Button scalpBtn, smartBtn, tradesBtn;

    private LiveDataProvider live;
    private BackendSettings backendSettings;
    private AutoPaperTrader autoTrader;
    private final android.os.Handler refreshHandler = new android.os.Handler(android.os.Looper.getMainLooper());
    private final PortfolioState portfolio = new PortfolioState();
    private final PaperAccount paper = new PaperAccount(1_000_000L);
    private BudgetStore budgetStore;
    private BudgetPolicy budgetPolicy;
    private OrderGuard orderGuard;
    private final NamuhGateway gateway = new NamuhGateway();
    private int tab = 1;

    @Override public void onCreate(Bundle b) {
        super.onCreate(b);
        backendSettings = new BackendSettings(this);
        live = new BackendLiveDataProvider(backendSettings);
        budgetStore = new BudgetStore(this);
        budgetPolicy = new BudgetPolicy(budgetStore.loadLimitWon());
        orderGuard = new OrderGuard(budgetPolicy, portfolio);
        autoTrader = new AutoPaperTrader(paper, budgetPolicy, portfolio, m -> runOnUiThread(() -> Toast.makeText(this, m, Toast.LENGTH_LONG).show()));
        buildUi();
        refreshAll();
        refreshHandler.postDelayed(new Runnable() {
            @Override public void run() {
                refreshAll();
                refreshHandler.postDelayed(this, 1500);
            }
        }, 1500);
    }

    @Override protected void onDestroy() {
        super.onDestroy();
        refreshHandler.removeCallbacksAndMessages(null);
    }

    private int dp(int v) { return (int)(v * getResources().getDisplayMetrics().density + .5f); }

    private GradientDrawable bg(int color, int radius) {
        GradientDrawable d = new GradientDrawable();
        d.setColor(color);
        d.setCornerRadius(dp(radius));
        return d;
    }

    private TextView tv(String s, int sp, boolean bold, int color) {
        TextView v = new TextView(this);
        v.setText(s);
        v.setTextSize(sp);
        v.setTextColor(color);
        v.setTypeface(null, bold ? Typeface.BOLD : Typeface.NORMAL);
        return v;
    }

    private Button btn(String s) {
        Button b = new Button(this);
        b.setText(s);
        b.setTextSize(13);
        b.setAllCaps(false);
        b.setMinHeight(0);
        b.setPadding(dp(8), dp(7), dp(8), dp(7));
        return b;
    }

    private LinearLayout card() {
        LinearLayout c = new LinearLayout(this);
        c.setOrientation(LinearLayout.VERTICAL);
        c.setPadding(dp(16), dp(14), dp(16), dp(14));
        c.setBackground(bg(Color.WHITE, 18));
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(-1, -2);
        lp.setMargins(0, 0, 0, dp(12));
        c.setLayoutParams(lp);
        c.setElevation(dp(2));
        return c;
    }

    private void buildUi() {
        ScrollView scroll = new ScrollView(this);
        scroll.setFillViewport(true);
        scroll.setBackgroundColor(Color.rgb(245, 247, 251));
        root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setPadding(dp(14), dp(18), dp(14), dp(28));
        scroll.addView(root);
        setContentView(scroll);

        // Header
        LinearLayout hero = card();
        hero.setBackground(bg(Color.rgb(19, 31, 61), 22));
        LinearLayout top = new LinearLayout(this);
        top.setGravity(Gravity.CENTER_VERTICAL);
        TextView title = tv("Namuh Smart Trader", 24, true, Color.WHITE);
        top.addView(title, new LinearLayout.LayoutParams(0, -2, 1));
        Button settingsBtn = btn("연결설정");
        settingsBtn.setTextColor(Color.WHITE);
        settingsBtn.setBackground(bg(Color.rgb(42, 58, 94), 12));
        settingsBtn.setOnClickListener(v -> showBackendSettings());
        top.addView(settingsBtn, new LinearLayout.LayoutParams(dp(92), dp(42)));
        hero.addView(top);
        liveStatus = tv("AI PAPER · KRX 실시간 백엔드 연결 확인 중 · 실제 주문 0건", 12, false, Color.rgb(196, 207, 231));
        liveStatus.setPadding(0, dp(4), 0, 0);
        hero.addView(liveStatus);
        root.addView(hero);

        // Paper account summary: actual market data + virtual cash only
        LinearLayout paperCard = card();
        paperCard.addView(tv("AI 모의투자 계좌", 18, true, Color.rgb(24, 30, 43)));
        TextView paperExplain = tv("가상자금 1,000,000원. NH/KRX 실시간 가격과 지표를 보고 AI 규칙엔진이 자동으로 사고팝니다. 실제 증권사 주문은 전혀 전송하지 않습니다.\n" + autoTrader.ruleSummary(), 12, false, Color.rgb(87, 95, 112));
        paperExplain.setPadding(0, dp(5), 0, dp(8));
        paperCard.addView(paperExplain);
        paperSummary = tv("", 14, true, Color.rgb(42, 50, 69));
        paperCard.addView(paperSummary);
        root.addView(paperCard);

        // Daily budget control
        LinearLayout budget = card();
        budget.addView(tv("오늘 운용금액", 18, true, Color.rgb(24, 30, 43)));
        TextView explain = tv("이 한도는 계좌 예수금과 별개입니다. 현재 보유종목의 매입원가 합계가 한도에 도달하면 추가 매수를 막고, 매도한 원가만큼 한도가 다시 열립니다.", 12, false, Color.rgb(87, 95, 112));
        explain.setPadding(0, dp(5), 0, dp(10));
        budget.addView(explain);
        LinearLayout row = new LinearLayout(this);
        row.setGravity(Gravity.CENTER_VERTICAL);
        budgetInput = new EditText(this);
        budgetInput.setInputType(InputType.TYPE_CLASS_NUMBER);
        budgetInput.setSingleLine(true);
        budgetInput.setText(String.valueOf(budgetPolicy.getLimitWon()));
        budgetInput.setHint("예: 200000");
        budgetInput.setTextSize(18);
        row.addView(budgetInput, new LinearLayout.LayoutParams(0, dp(52), 1));
        Button save = btn("저장");
        save.setBackground(bg(Color.rgb(61, 104, 255), 14));
        save.setTextColor(Color.WHITE);
        LinearLayout.LayoutParams slp = new LinearLayout.LayoutParams(dp(92), dp(48));
        slp.setMargins(dp(10), 0, 0, 0);
        row.addView(save, slp);
        budget.addView(row);
        budgetSummary = tv("", 13, true, Color.rgb(42, 50, 69));
        budgetSummary.setPadding(0, dp(8), 0, 0);
        budget.addView(budgetSummary);
        save.setOnClickListener(v -> saveBudget());
        root.addView(budget);

        // Market dashboard
        LinearLayout marketCard = card();
        marketCard.addView(sectionTitle("실시간 시장 대시보드", "KOSPI · KOSDAQ · 야간선물 · NASDAQ · SOX · NASDAQ 선물"));
        marketGrid = new LinearLayout(this);
        marketGrid.setOrientation(LinearLayout.VERTICAL);
        marketCard.addView(marketGrid);
        root.addView(marketCard);

        // Leading sectors
        LinearLayout sectorCard = card();
        sectorCard.addView(sectionTitle("오늘의 주도섹터", "등락률 + 거래대금/수급 강도 기준"));
        sectorBox = new LinearLayout(this);
        sectorBox.setOrientation(LinearLayout.VERTICAL);
        sectorCard.addView(sectorBox);
        root.addView(sectorCard);

        // Tabs
        LinearLayout tabs = new LinearLayout(this);
        tabs.setOrientation(LinearLayout.HORIZONTAL);
        scalpBtn = btn("1. 단타");
        smartBtn = btn("2. 스마트머니");
        tradesBtn = btn("3. 오늘 매매");
        tabs.addView(scalpBtn, new LinearLayout.LayoutParams(0, dp(50), 1));
        tabs.addView(smartBtn, new LinearLayout.LayoutParams(0, dp(50), 1));
        tabs.addView(tradesBtn, new LinearLayout.LayoutParams(0, dp(50), 1));
        root.addView(tabs);
        View spacer = new View(this); root.addView(spacer, new LinearLayout.LayoutParams(1, dp(10)));

        contentBox = new LinearLayout(this);
        contentBox.setOrientation(LinearLayout.VERTICAL);
        root.addView(contentBox);

        scalpBtn.setOnClickListener(v -> { tab = 1; renderTab(); });
        smartBtn.setOnClickListener(v -> { tab = 2; renderTab(); });
        tradesBtn.setOnClickListener(v -> { tab = 3; renderTab(); });
        updateBudgetSummary();
        updateTabStyle();
    }

    private View sectionTitle(String a, String b) {
        LinearLayout box = new LinearLayout(this);
        box.setOrientation(LinearLayout.VERTICAL);
        box.addView(tv(a, 18, true, Color.rgb(24, 30, 43)));
        TextView sub = tv(b, 11, false, Color.rgb(108, 116, 133));
        sub.setPadding(0, dp(3), 0, dp(10));
        box.addView(sub);
        return box;
    }

    private void saveBudget() {
        String raw = budgetInput.getText().toString().replace(",", "").trim();
        try {
            long v = Long.parseLong(raw);
            if (v <= 0) throw new NumberFormatException();
            if (v < paper.heldCostWon()) {
                Toast.makeText(this, "오늘 자동매매 보유원가보다 낮게 설정할 수 없습니다.", Toast.LENGTH_LONG).show();
                return;
            }
            budgetPolicy.setLimitWon(v);
            budgetStore.saveLimitWon(v);
            updateBudgetSummary();
            Toast.makeText(this, "오늘 운용한도 " + won.format(v) + "원 저장", Toast.LENGTH_SHORT).show();
        } catch (Exception e) {
            Toast.makeText(this, "원 단위 숫자로 입력하세요.", Toast.LENGTH_SHORT).show();
        }
    }

    private void updateBudgetSummary() {
        budgetPolicy.syncHeldCost(paper.heldCostWon());
        budgetSummary.setText("한도 " + won.format(budgetPolicy.getLimitWon()) + "원  ·  모의보유 원가 " +
                won.format(budgetPolicy.getHeldCostWon()) + "원  ·  신규매수 가능 " +
                won.format(budgetPolicy.getRemainingWon()) + "원\n기존 실계좌 보유 보호 " +
                won.format(portfolio.protectedHeldCostWon()) + "원 · 매수/매도 대상 제외");
        if (paperSummary != null) {
            paperSummary.setText("가상 현금 " + won.format(paper.cashWon()) + "원  ·  보유평가 " +
                    won.format(paper.marketValueWon()) + "원  ·  총자산 " + won.format(paper.totalAssetWon()) +
                    "원\n평가손익 " + signedWon(paper.unrealizedPnlWon()) + "  ·  실현손익 " + signedWon(paper.realizedPnlWon()));
        }
    }

    private void refreshAll() {
        showMarketPlaceholders();
        showSectorPlaceholder();
        live.fetchMarketDashboard(new LiveDataProvider.Callback<List<MarketSnapshot>>() {
            @Override public void onSuccess(List<MarketSnapshot> v) { liveStatus.setText("● 실시간 연결"); renderMarkets(v); }
            @Override public void onError(String m) { liveStatus.setText("○ " + m + " · 가짜 시세 표시 안 함"); }
        });
        live.fetchLeadingSectors(new LiveDataProvider.Callback<List<SectorSnapshot>>() {
            @Override public void onSuccess(List<SectorSnapshot> v) { renderSectors(v); }
            @Override public void onError(String m) { showSectorPlaceholder(); }
        });
        live.fetchPositions(new LiveDataProvider.Callback<List<Position>>() {
            @Override public void onSuccess(List<Position> v) { portfolio.positions().clear(); portfolio.positions().addAll(v); updateBudgetSummary(); renderTab(); }
            @Override public void onError(String m) { updateBudgetSummary(); renderTab(); }
        });
    }

    private void showMarketPlaceholders() {
        marketGrid.removeAllViews();
        String[] names = {"코스피", "코스닥", "코스피 야간선물", "나스닥", "필라델피아 반도체", "나스닥 선물"};
        for (int i = 0; i < names.length; i += 2) {
            LinearLayout row = new LinearLayout(this);
            row.setOrientation(LinearLayout.HORIZONTAL);
            row.addView(marketTile(names[i], null), new LinearLayout.LayoutParams(0, dp(116), 1));
            if (i + 1 < names.length) {
                LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(0, dp(116), 1); lp.setMargins(dp(8), 0, 0, 0);
                row.addView(marketTile(names[i+1], null), lp);
            }
            LinearLayout.LayoutParams rlp = new LinearLayout.LayoutParams(-1, -2); rlp.setMargins(0, 0, 0, dp(8));
            marketGrid.addView(row, rlp);
        }
    }

    private View marketTile(String label, MarketSnapshot x) {
        LinearLayout c = new LinearLayout(this);
        c.setOrientation(LinearLayout.VERTICAL);
        c.setPadding(dp(12), dp(10), dp(12), dp(8));
        c.setBackground(bg(Color.rgb(247, 249, 253), 14));
        c.addView(tv(label, 13, true, Color.rgb(44, 52, 69)));
        String value = x == null || x.value == null ? "연결 대기" : String.format(Locale.KOREA, "%,.2f", x.value);
        c.addView(tv(value, 18, true, Color.rgb(21, 27, 39)));
        String change = x == null || x.changePct == null ? "실시간 값만 표시" : String.format(Locale.KOREA, "%+.2f%%", x.changePct);
        c.addView(tv(change, 11, false, Color.rgb(93, 101, 118)));
        SparklineView sp = new SparklineView(this);
        if (x != null) sp.setPoints(x.sparkline);
        c.addView(sp, new LinearLayout.LayoutParams(-1, 0, 1));
        return c;
    }

    private void renderMarkets(List<MarketSnapshot> xs) {
        marketGrid.removeAllViews();
        for (int i=0; i<xs.size(); i+=2) {
            LinearLayout row = new LinearLayout(this);
            row.addView(marketTile(xs.get(i).label, xs.get(i)), new LinearLayout.LayoutParams(0, dp(116), 1));
            if (i+1<xs.size()) { LinearLayout.LayoutParams lp=new LinearLayout.LayoutParams(0,dp(116),1); lp.setMargins(dp(8),0,0,0); row.addView(marketTile(xs.get(i+1).label,xs.get(i+1)),lp); }
            LinearLayout.LayoutParams rlp=new LinearLayout.LayoutParams(-1,-2); rlp.setMargins(0,0,0,dp(8)); marketGrid.addView(row,rlp);
        }
    }

    private void showSectorPlaceholder() {
        sectorBox.removeAllViews();
        TextView t = tv("실시간 섹터 수급 데이터 연결 후 자동 순위 표시", 13, false, Color.rgb(101, 109, 125));
        t.setPadding(0, dp(8), 0, dp(8));
        sectorBox.addView(t);
    }

    private void renderSectors(List<SectorSnapshot> xs) {
        sectorBox.removeAllViews();
        int rank=1;
        for (SectorSnapshot s: xs) {
            String line = rank + ". " + s.sector + "   " + (s.changePct==null?"-":String.format(Locale.KOREA,"%+.2f%%",s.changePct)) + "   대표 " + s.leader;
            TextView t=tv(line,13,rank<=3,Color.rgb(38,45,60)); t.setPadding(0,dp(5),0,dp(5)); sectorBox.addView(t); rank++;
        }
    }

    private void renderTab() {
        updateTabStyle();
        contentBox.removeAllViews();
        updateBudgetSummary();
        if (tab == 1) renderScalp(); else if (tab == 2) renderSmart(); else renderTrades();
    }

    private void updateTabStyle() {
        if (scalpBtn == null) return;
        Button[] bs={scalpBtn,smartBtn,tradesBtn};
        for(int i=0;i<bs.length;i++) {
            boolean on=(i+1)==tab;
            bs[i].setBackground(bg(on?Color.rgb(61,104,255):Color.rgb(229,233,242), 12));
            bs[i].setTextColor(on?Color.WHITE:Color.rgb(49,57,73));
        }
    }

    private void renderScalp() {
        contentBox.addView(sectionCardHeader("현재 모의매수 종목", "가상 100만원 계좌 · 실제 현재가로 평가 · 기존 실계좌 보유종목은 미포함"));
        if (paper.positions().isEmpty()) contentBox.addView(infoCard("현재 모의보유종목 없음", "실시간 후보에서 종목을 눌러 모의 매수하면 여기에 표시됩니다."));
        else for (Position p: paper.positions()) contentBox.addView(paperPositionCard(p));

        if (!portfolio.positions().isEmpty()) {
            contentBox.addView(sectionCardHeader("기존 실계좌 보유 보호", "이 종목들은 모의/자동매매가 절대 건드리지 않습니다."));
            for (Position p: portfolio.positions()) contentBox.addView(positionCard(p));
        }

        contentBox.addView(sectionCardHeader("오늘 단타 후보", "장 시작가 ~ 상승 VI 직전 · KRX ONLY · 실시간 값 없으면 매수 차단"));
        live.fetchScalpCandidates(new LiveDataProvider.Callback<List<StockCandidate>>() {
            @Override public void onSuccess(List<StockCandidate> xs) {
                markPaper(xs);
                if (backendSettings.autoPaperEnabled()) autoTrader.onScalpCandidates(xs);
                updateBudgetSummary();
                for (StockCandidate x: xs) contentBox.addView(candidateCard(x,false));
            }
            @Override public void onError(String m) { contentBox.addView(infoCard("실시간 후보 연결 대기", m + " · 모의매매도 실제 시세 없이는 실행하지 않음")); }
        });
    }

    private void renderSmart() {
        contentBox.addView(sectionCardHeader("스마트머니 + 저평가", "외국인/기관 누적수급 + PER/PBR 상대저평가"));
        live.fetchSmartCandidates(new LiveDataProvider.Callback<List<StockCandidate>>() {
            @Override public void onSuccess(List<StockCandidate> xs) { markPaper(xs); updateBudgetSummary(); for (StockCandidate x: xs) contentBox.addView(candidateCard(x,true)); }
            @Override public void onError(String m) { contentBox.addView(infoCard("실시간 후보 연결 대기", m)); }
        });
    }

    private void renderTrades() {
        LinearLayout summary=card();
        summary.addView(tv("오늘 모의매매 요약",18,true,Color.rgb(25,31,43)));
        summary.addView(tv("가상 현금 " + won.format(paper.cashWon()) + "원  ·  총자산 " + won.format(paper.totalAssetWon()) + "원",14,true,Color.rgb(50,58,74)));
        summary.addView(tv("실현손익  " + signedWon(paper.realizedPnlWon()) + "   ·   거래 " + paper.trades().size() + "건",15,true,Color.rgb(50,58,74)));
        contentBox.addView(summary);
        if (paper.trades().isEmpty()) contentBox.addView(infoCard("오늘 모의체결 없음", "실제 현재가를 사용해 모의매수/모의매도하면 여기에 기록됩니다. 실제 계좌 주문은 발생하지 않습니다."));
        else for (TradeRecord t: paper.trades()) contentBox.addView(tradeCard(t));
    }

    private View sectionCardHeader(String a,String b){ LinearLayout c=card(); c.addView(sectionTitle(a,b)); return c; }
    private View infoCard(String a,String b){ LinearLayout c=card(); c.addView(tv(a,15,true,Color.rgb(42,49,63))); c.addView(tv(b,12,false,Color.rgb(103,111,127))); return c; }

    private View positionCard(Position p) {
        LinearLayout c=card();
        c.addView(tv(p.name+"  "+p.code + (p.isProtected()?"  🔒 기존보유 보호":"  ● 자동매매"),17,true,Color.rgb(25,31,43)));
        c.addView(tv("평균 " + won.format(p.avgPrice)+"원  ·  현재 " + won.format(p.currentPrice)+"원  ·  "+p.qty+"주",13,false,Color.rgb(72,80,96)));
        c.addView(tv("평가손익 " + signedWon(p.pnlWon()) + "  ("+String.format(Locale.KOREA,"%+.2f%%",p.pnlPct())+")",14,true,p.pnlWon()>=0?Color.rgb(208,60,66):Color.rgb(46,91,205)));
        return c;
    }

    private View paperPositionCard(Position p) {
        LinearLayout c=card();
        c.addView(tv(p.name+"  "+p.code+"  ● PAPER",17,true,Color.rgb(25,31,43)));
        c.addView(tv("평균 " + won.format(p.avgPrice)+"원  ·  실제 현재가 " + won.format(p.currentPrice)+"원  ·  "+p.qty+"주",13,false,Color.rgb(72,80,96)));
        c.addView(tv("평가손익 " + signedWon(p.pnlWon()) + "  ("+String.format(Locale.KOREA,"%+.2f%%",p.pnlPct())+")",14,true,p.pnlWon()>=0?Color.rgb(208,60,66):Color.rgb(46,91,205)));
        c.setOnClickListener(v -> new AlertDialog.Builder(this)
                .setTitle(p.name + " 모의포지션")
                .setMessage("실제 현재가 " + won.format(p.currentPrice) + "원 기준으로 가상 전량매도합니다.\n실제 NH 주문은 전송하지 않습니다.")
                .setNegativeButton("취소", null)
                .setPositiveButton("모의 전량매도", (d,w) -> attemptSellPaper(p))
                .show());
        return c;
    }

    private void markPaper(List<StockCandidate> xs) {
        for (StockCandidate x : xs) if (x.price > 0) paper.mark(x.code, (long)x.price);
    }

    private View candidateCard(StockCandidate x, boolean smart) {
        LinearLayout c=card();
        LinearLayout top=new LinearLayout(this); top.setGravity(Gravity.CENTER_VERTICAL);
        top.addView(tv(x.name+"  "+x.code,17,true,Color.rgb(25,31,43)),new LinearLayout.LayoutParams(0,-2,1));
        top.addView(tv(String.format(Locale.KOREA,"%.1f점",x.score),15,true,Color.rgb(61,104,255)));
        c.addView(top);
        c.addView(tv(smart?x.subtitleSmart():x.subtitleScalp(),12,false,Color.rgb(74,82,98)));
        c.addView(tv(x.reasonText(),11,false,Color.rgb(104,112,127)));
        c.setOnClickListener(v -> showStockDetail(x, smart));
        return c;
    }

    private View tradeCard(TradeRecord t) {
        LinearLayout c=card();
        c.addView(tv(t.name+"  "+t.code+"  ·  "+t.side,16,true,Color.rgb(30,36,49)));
        c.addView(tv(t.time+"  ·  "+t.qty+"주 × "+won.format(t.price)+"원",12,false,Color.rgb(86,94,110)));
        if ("SELL".equalsIgnoreCase(t.side)) c.addView(tv("실현 " + signedWon(t.realizedPnlWon)+"  "+String.format(Locale.KOREA,"%+.2f%%",t.realizedPnlPct),14,true,t.realizedPnlWon>=0?Color.rgb(208,60,66):Color.rgb(46,91,205)));
        return c;
    }

    private String signedWon(long x) { return (x>=0?"+":"-") + won.format(Math.abs(x)) + "원"; }

    private void showStockDetail(StockCandidate x, boolean smart) {
        ScrollView sv=new ScrollView(this); LinearLayout box=new LinearLayout(this); box.setOrientation(LinearLayout.VERTICAL); box.setPadding(dp(18),dp(12),dp(18),dp(8)); sv.addView(box);
        box.addView(tv(x.name+"  "+x.code,20,true,Color.rgb(26,32,45)));
        box.addView(tv("현재가  "+won.format((long)x.price)+"원",18,true,Color.rgb(61,104,255)));
        box.addView(tv("상승 VI 참고가  "+won.format((long)x.viPre)+"원",14,true,Color.rgb(73,80,95)));
        box.addView(tv("PER  "+(x.per>0?String.format(Locale.KOREA,"%.2f",x.per):"실시간 연결 필요")+"   ·   PBR  "+(x.pbr>0?String.format(Locale.KOREA,"%.2f",x.pbr):"실시간 연결 필요"),13,false,Color.rgb(82,90,106)));
        SparklineView chart=new SparklineView(this); chart.setPoints(x.priceSeries); box.addView(chart,new LinearLayout.LayoutParams(-1,dp(180)));
        if (x.priceSeries.isEmpty()) box.addView(tv("분봉/틱 그래프: 실시간 시세 연결 대기",11,false,Color.rgb(108,116,132)));
        box.addView(tv("판정 근거",14,true,Color.rgb(44,51,66))); box.addView(tv(x.reasonText(),12,false,Color.rgb(88,96,112)));
        AlertDialog d=new AlertDialog.Builder(this).setView(sv).setNegativeButton("닫기",null)
                .setPositiveButton("모의 매수",null).create();
        d.setOnShowListener(v -> d.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener(v2 -> attemptBuy(x)));
        d.show();
    }

    private void attemptBuy(StockCandidate x) {
        if (x.price <= 0) { Toast.makeText(this,"실시간 현재가가 없어 모의매수 차단",Toast.LENGTH_LONG).show(); return; }
        if (portfolio.hasProtectedCode(x.code)) { Toast.makeText(this,"기존 실계좌 보유종목은 보호 대상이라 모의 자동매수에서도 제외",Toast.LENGTH_LONG).show(); return; }
        long price=(long)x.price;
        budgetPolicy.syncHeldCost(paper.heldCostWon());
        long remain=Math.min(budgetPolicy.getRemainingWon(), paper.cashWon());
        int qty=(int)Math.min(Integer.MAX_VALUE, remain/price);
        if (qty<1) { Toast.makeText(this,"모의 현금 또는 오늘 운용한도 잔여금 부족. 보유종목을 모의매도한 뒤 다시 매수하세요.",Toast.LENGTH_LONG).show(); return; }
        OrderGuard.Decision dec=orderGuard.checkBuy(x.code,price,qty);
        if (!dec.allowed) { Toast.makeText(this,dec.reason,Toast.LENGTH_LONG).show(); return; }
        try {
            paper.buy(nowText(), x.code, x.name, qty, price);
            budgetPolicy.syncHeldCost(paper.heldCostWon());
            updateBudgetSummary();
            Toast.makeText(this,"PAPER 매수 체결: " + x.name + " " + qty + "주 × " + won.format(price) + "원\n실제 주문 전송 0건",Toast.LENGTH_LONG).show();
            renderTab();
        } catch (Exception e) {
            Toast.makeText(this,"모의매수 실패: " + e.getMessage(),Toast.LENGTH_LONG).show();
        }
    }

    private void attemptSellPaper(Position p) {
        if (p == null || p.currentPrice <= 0) { Toast.makeText(this,"실시간 현재가가 없어 모의매도 차단",Toast.LENGTH_LONG).show(); return; }
        try {
            paper.sell(nowText(), p.code, p.qty, p.currentPrice);
            budgetPolicy.syncHeldCost(paper.heldCostWon());
            updateBudgetSummary();
            Toast.makeText(this,"PAPER 매도 체결: " + p.name + " · 실제 주문 전송 0건",Toast.LENGTH_LONG).show();
            renderTab();
        } catch (Exception e) {
            Toast.makeText(this,"모의매도 실패: " + e.getMessage(),Toast.LENGTH_LONG).show();
        }
    }


    private void showBackendSettings() {
        LinearLayout box = new LinearLayout(this);
        box.setOrientation(LinearLayout.VERTICAL);
        box.setPadding(dp(18), dp(8), dp(18), dp(4));

        EditText url = new EditText(this);
        url.setHint("예: https://your-server.example.com");
        url.setText(backendSettings.getUrl());
        box.addView(tv("실시간 백엔드 주소", 14, true, Color.rgb(40,47,61)));
        box.addView(url);

        CheckBox auto = new CheckBox(this);
        auto.setText("AI 자동 모의매매 사용");
        auto.setChecked(backendSettings.autoPaperEnabled());
        box.addView(auto);

        TextView note = tv("APP_KEY / APP_SECRET은 APK에 넣지 않습니다. 서버의 환경변수에만 저장합니다.", 11, false, Color.rgb(95,103,120));
        note.setPadding(0, dp(8), 0, 0);
        box.addView(note);

        new AlertDialog.Builder(this)
                .setTitle("실시간 연결 설정")
                .setView(box)
                .setNegativeButton("취소", null)
                .setPositiveButton("저장", (d,w) -> {
                    backendSettings.setUrl(url.getText().toString());
                    backendSettings.setAutoPaperEnabled(auto.isChecked());
                    live = new BackendLiveDataProvider(backendSettings);
                    refreshAll();
                })
                .show();
    }

    private String nowText() {
        return new java.text.SimpleDateFormat("HH:mm:ss", Locale.KOREA).format(new java.util.Date());
    }

}
