package com.namuh.smarttrader;

import android.os.Handler;
import android.os.Looper;
import org.json.*;
import java.io.*;
import java.net.*;
import java.nio.charset.StandardCharsets;
import java.util.*;

public final class BackendLiveDataProvider implements LiveDataProvider {
    private final BackendSettings settings;
    private final Handler main = new Handler(Looper.getMainLooper());

    public BackendLiveDataProvider(BackendSettings settings) {
        this.settings = settings;
    }

    private interface Parser<T> { T parse(JSONObject o) throws Exception; }

    private <T> void get(String path, Parser<T> parser, Callback<T> cb) {
        new Thread(() -> {
            HttpURLConnection c = null;
            try {
                URL u = new URL(settings.getUrl() + path);
                c = (HttpURLConnection)u.openConnection();
                c.setConnectTimeout(3000);
                c.setReadTimeout(5000);
                c.setRequestMethod("GET");
                c.setRequestProperty("Accept", "application/json");
                int code = c.getResponseCode();
                InputStream in = code >= 200 && code < 300 ? c.getInputStream() : c.getErrorStream();
                String body = readAll(in);
                if (code < 200 || code >= 300) throw new IOException("HTTP " + code + " " + body);
                T v = parser.parse(new JSONObject(body));
                main.post(() -> cb.onSuccess(v));
            } catch (Exception e) {
                String m = e.getMessage() == null ? e.getClass().getSimpleName() : e.getMessage();
                main.post(() -> cb.onError(m));
            } finally {
                if (c != null) c.disconnect();
            }
        }).start();
    }

    private static String readAll(InputStream in) throws Exception {
        if (in == null) return "";
        ByteArrayOutputStream b = new ByteArrayOutputStream();
        byte[] buf = new byte[4096];
        int n;
        while ((n = in.read(buf)) >= 0) b.write(buf, 0, n);
        return b.toString(StandardCharsets.UTF_8.name());
    }

    private static Double optDoubleObj(JSONObject o, String k) {
        if (!o.has(k) || o.isNull(k)) return null;
        return o.optDouble(k);
    }

    private static List<Double> doubles(JSONArray a) {
        List<Double> xs = new ArrayList<>();
        if (a == null) return xs;
        for (int i=0;i<a.length();i++) xs.add(a.optDouble(i));
        return xs;
    }

    private static List<MarketSnapshot> markets(JSONObject o) {
        List<MarketSnapshot> out = new ArrayList<>();
        JSONArray a = o.optJSONArray("items");
        if (a == null) return out;
        for (int i=0;i<a.length();i++) {
            JSONObject x = a.optJSONObject(i);
            if (x == null) continue;
            MarketSnapshot m = new MarketSnapshot(x.optString("label"), x.optString("symbol", ""));
            m.value = optDoubleObj(x, "value");
            m.changePct = optDoubleObj(x, "change_pct");
            m.sparkline.addAll(doubles(x.optJSONArray("sparkline")));
            out.add(m);
        }
        return out;
    }

    private static List<SectorSnapshot> sectors(JSONObject o) {
        List<SectorSnapshot> out = new ArrayList<>();
        JSONArray a = o.optJSONArray("items");
        if (a == null) return out;
        for (int i=0;i<a.length();i++) {
            JSONObject x = a.optJSONObject(i);
            if (x == null) continue;
            SectorSnapshot s = new SectorSnapshot(
                    x.optString("sector"),
                    optDoubleObj(x, "change_pct"),
                    optDoubleObj(x, "score"),
                    x.optString("leader"),
                    true
            );
            out.add(s);
        }
        return out;
    }

    private static StockCandidate candidate(JSONObject x) {
        StockCandidate c = new StockCandidate();
        c.code = x.optString("code");
        c.name = x.optString("name");
        c.price = x.optDouble("price");
        c.score = x.optDouble("score");
        c.executionStrength = x.optDouble("execution_strength");
        c.sectorScore = x.optDouble("sector_score");
        c.viPre = x.optDouble("vi_pre");
        c.per = x.optDouble("per");
        c.pbr = x.optDouble("pbr");
        c.foreignNet = x.optDouble("foreign_net");
        c.institutionNet = x.optDouble("institution_net");
        JSONArray rs = x.optJSONArray("reasons");
        if (rs != null) for (int j=0;j<rs.length();j++) c.reasons.add(rs.optString(j));
        c.priceSeries.addAll(doubles(x.optJSONArray("price_series")));
        return c;
    }

    private static List<StockCandidate> candidates(JSONObject o) {
        List<StockCandidate> out = new ArrayList<>();
        JSONArray a = o.optJSONArray("items");
        if (a == null) return out;
        for (int i=0;i<a.length();i++) {
            JSONObject x = a.optJSONObject(i);
            if (x != null) out.add(candidate(x));
        }
        return out;
    }

    private static List<Position> positions(JSONObject o) {
        List<Position> out = new ArrayList<>();
        JSONArray a = o.optJSONArray("items");
        if (a == null) return out;
        for (int i=0;i<a.length();i++) {
            JSONObject x = a.optJSONObject(i);
            if (x == null) continue;
            out.add(new Position(
                x.optString("code"), x.optString("name"),
                x.optInt("qty"), x.optLong("avg_price"),
                x.optLong("current_price"), false
            ));
        }
        return out;
    }

    private static List<TradeRecord> trades(JSONObject o) {
        List<TradeRecord> out = new ArrayList<>();
        JSONArray a = o.optJSONArray("items");
        if (a == null) return out;
        for (int i=0;i<a.length();i++) {
            JSONObject x = a.optJSONObject(i);
            if (x == null) continue;
            out.add(new TradeRecord(
                x.optString("time"), x.optString("code"), x.optString("name"),
                x.optString("side"), x.optInt("qty"), x.optLong("price"),
                x.optLong("realized_pnl_won"), x.optDouble("realized_pnl_pct")
            ));
        }
        return out;
    }

    @Override public void fetchMarketDashboard(Callback<List<MarketSnapshot>> cb) {
        get("/api/market", BackendLiveDataProvider::markets, cb);
    }
    @Override public void fetchLeadingSectors(Callback<List<SectorSnapshot>> cb) {
        get("/api/sectors", BackendLiveDataProvider::sectors, cb);
    }
    @Override public void fetchScalpCandidates(Callback<List<StockCandidate>> cb) {
        get("/api/candidates/scalp", BackendLiveDataProvider::candidates, cb);
    }
    @Override public void fetchSmartCandidates(Callback<List<StockCandidate>> cb) {
        get("/api/candidates/smart", BackendLiveDataProvider::candidates, cb);
    }
    @Override public void fetchPositions(Callback<List<Position>> cb) {
        get("/api/protected", BackendLiveDataProvider::positions, cb);
    }
    @Override public void fetchTodayTrades(Callback<List<TradeRecord>> cb) {
        get("/api/trades", BackendLiveDataProvider::trades, cb);
    }
}
