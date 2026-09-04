package com.namuh.smarttrader;

import android.os.Handler;
import android.os.Looper;
import java.util.List;

/**
 * 실시간 공급원이 아직 연결되지 않았을 때 fail-closed 동작.
 * 사용자가 실시간 값으로 오인하지 않도록 데모 숫자를 반환하지 않는다.
 */
public class DisconnectedLiveDataProvider implements LiveDataProvider {
    private final Handler main = new Handler(Looper.getMainLooper());

    private <T> void fail(Callback<T> cb) {
        main.post(() -> cb.onError("실시간 데이터 공급원 연결 필요"));
    }

    @Override public void fetchMarketDashboard(Callback<List<MarketSnapshot>> cb) { fail(cb); }
    @Override public void fetchLeadingSectors(Callback<List<SectorSnapshot>> cb) { fail(cb); }
    @Override public void fetchScalpCandidates(Callback<List<StockCandidate>> cb) { fail(cb); }
    @Override public void fetchSmartCandidates(Callback<List<StockCandidate>> cb) { fail(cb); }
    @Override public void fetchPositions(Callback<List<Position>> cb) { fail(cb); }
    @Override public void fetchTodayTrades(Callback<List<TradeRecord>> cb) { fail(cb); }
}
