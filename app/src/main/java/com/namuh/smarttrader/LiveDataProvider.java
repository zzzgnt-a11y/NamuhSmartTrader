package com.namuh.smarttrader;

import java.util.List;

/**
 * 실시간 데이터 경계.
 * v0.2에서는 UI와 계약을 먼저 고정하고, 값이 없는 경우 절대 임의 데모값을 만들지 않는다.
 */
public interface LiveDataProvider {
    interface Callback<T> {
        void onSuccess(T value);
        void onError(String message);
    }

    void fetchMarketDashboard(Callback<List<MarketSnapshot>> callback);
    void fetchLeadingSectors(Callback<List<SectorSnapshot>> callback);
    void fetchScalpCandidates(Callback<List<StockCandidate>> callback);
    void fetchSmartCandidates(Callback<List<StockCandidate>> callback);
    void fetchPositions(Callback<List<Position>> callback);
    void fetchTodayTrades(Callback<List<TradeRecord>> callback);
}
