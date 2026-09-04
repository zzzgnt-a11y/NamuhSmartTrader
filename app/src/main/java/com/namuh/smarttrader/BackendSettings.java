package com.namuh.smarttrader;

import android.content.Context;
import android.content.SharedPreferences;

public final class BackendSettings {
    private static final String PREF = "backend_settings";
    private final SharedPreferences sp;

    public BackendSettings(Context c) {
        sp = c.getSharedPreferences(PREF, Context.MODE_PRIVATE);
    }

    public String getUrl() {
        return sp.getString("url", "http://10.0.2.2:8787");
    }

    public void setUrl(String url) {
        if (url == null) return;
        url = url.trim();
        while (url.endsWith("/")) url = url.substring(0, url.length()-1);
        sp.edit().putString("url", url).apply();
    }

    public boolean autoPaperEnabled() {
        return sp.getBoolean("auto_paper", true);
    }

    public void setAutoPaperEnabled(boolean on) {
        sp.edit().putBoolean("auto_paper", on).apply();
    }
}
