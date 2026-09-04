package com.namuh.smarttrader;

/**
 * PAPER/LIVE가 동일 전략/주문 경로를 사용하도록 하는 단일 게이트웨이.
 *
 * 중요: Android v0.1 APK 소스에서는 NHPLUG 인증/실시간 WebSocket을 아직 연결하지 않았다.
 * 실제 주문 전송 코드를 임의로 추정하지 않고, 공식 Android/REST 인증 사양 확인 후 구현한다.
 */
public class NamuhGateway {
    public static final String PAPER_BASE = "https://moapi.nhplug.com:8443";
    public static final String LIVE_BASE  = "https://api.nhplug.com:8443";

    private TradingMode mode = TradingMode.PAPER;

    public void setMode(TradingMode mode) { this.mode = mode; }
    public TradingMode getMode() { return mode; }
    public String baseUrl() { return mode == TradingMode.PAPER ? PAPER_BASE : LIVE_BASE; }

    public String buildOrderSummary(String side, String code, int qty, Long price) {
        return "mode=" + mode +
                ", market=KRX, SOR=N, side=" + side +
                ", code=" + code + ", qty=" + qty +
                ", price=" + (price == null ? "MARKET" : price);
    }

    public String submitDisabled(String side, String code, int qty, Long price) {
        // 안전상 모바일 v0.1에서는 실제 API 호출을 하지 않는다.
        return "[전송 차단] " + buildOrderSummary(side, code, qty, price);
    }
}
